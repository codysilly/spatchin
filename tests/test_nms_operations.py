"""Production entry points with an injected provider and a local Git/Pages simulation."""

from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.test_nms_refresh import (
    CREDENTIALS,
    NOW,
    Transport,
    encode,
    envelope,
    feature,
    synthetic_store,
)
from tests.test_nms_baseline_candidate import initial
from nms_baseline_candidate import REQUIRED_ACTIVATION_GATES
from nms_engine import execute_offline_cycle
from nms_operations import EMPTY, Operations
from nms_pages_delivery import PagesDelivery, PublicationError, sha256
from nms_refresh_contract import RefreshError, instant


PUBLIC_BEFORE = b'{"retrieved_utc":"2025-12-31T12:00:00Z","airports":{}}\n'
SYNTHETIC_LEGACY = {
    "bytes": len(PUBLIC_BEFORE),
    "sha256": sha256(PUBLIC_BEFORE),
    "retrieved_utc": "2025-12-31T12:00:00Z",
}
RELEASE = "2" * 40
LOCAL_TEXT = "SYNTHETIC RWY 18L lighting report\r\nSECOND ORIGINAL LINE\rTHIRD"


def notice(*args, local=True, **kwargs):
    record = feature(*args, **kwargs)
    record["properties"]["coreNOTAMData"]["notamTranslation"] = (
        [{"type": "LOCAL_FORMAT", "simpleText": LOCAL_TEXT}] if local else []
    )
    return record


class LocalPages(PagesDelivery):
    def __init__(self, parent):
        self.fail_public = False
        self.fail_push = False
        self.race = False
        self.last_good = PUBLIC_BEFORE
        self.pushes = 0
        remote = parent / "remote"
        remote.mkdir()
        super().__init__(parent, remote=remote, read_public=self.deployed, wait=lambda _: None)
        self.git("init", "-b", "main")
        (remote / "data").mkdir()
        (remote / "data/notams.json").write_bytes(PUBLIC_BEFORE)
        (remote / "data/metars.json").write_bytes(b"weather before")
        self.git("add", "data")
        self.git("commit", "-m", "Synthetic baseline")
        self.git("config", "receive.denyCurrentBranch", "updateInstead")

    def git(self, *args):
        return super()._git(self.remote, *args)

    def deployed(self):
        if not self.fail_public:
            self.last_good = self.git("show", "HEAD:data/notams.json")
        return self.last_good

    def _git(self, cwd, *args, body=None):
        if args[0] == "push" and "--dry-run" not in args:
            if self.fail_push:
                raise PublicationError("GIT_DELIVERY_FAILED")
            if self.race:
                self.race = False
                (self.remote / "data/metars.json").write_bytes(b"weather from concurrent commit")
                self.git("add", "data/metars.json")
                self.git("commit", "-m", "Concurrent weather update")
            result = super()._git(cwd, *args, body=body)
            self.pushes += 1
            return result
        return super()._git(cwd, *args, body=body)

    def publish(self, *args, **kwargs):
        return super().publish(*args, **kwargs, wait_checks=1)


class Scenario:
    def __init__(self, parent):
        self.now = NOW
        self.store = synthetic_store(parent)
        self.delivery = LocalPages(Path(parent))
        self.operations = Operations(self.store, clock=lambda: self.now, delivery=self.delivery)
        execute_offline_cycle(
            self.store,
            mode="baseline",
            now=self.now,
            initial_records=[initial("BASELINE")],
            capture_started_utc="2026-01-02T11:59:00Z",
            activation_gates=dict.fromkeys(REQUIRED_ACTIVATION_GATES, True),
        )
        self.now += timedelta(minutes=3)
        self.watermark = self.operations.status()["watermark"]
        self.reopen()

    def reopen(self):
        self.operations = Operations(self.store, clock=lambda: self.now, delivery=self.delivery)

    def collect(self, transport, approval=None, credentials=CREDENTIALS):
        if approval is None:
            approval = self.operations.review_delta(self.watermark)["approval_sha256"]
        return self.operations.catch_up(
            self.watermark, approval, attest=True, credentials=credentials, transport=transport
        )

    def transport(self, *records):
        return Transport(self.store, envelope(list(records)), lambda: self.now)

    def first_publish(self):
        self.collect(self.transport(notice("NEW"), notice("NO-LOCAL", local=False)))
        review = self.operations.review_publication()
        return self.operations.publish_initial(review["approval_sha256"])

    def cycle(self, policy, transport):
        return self.operations.recurring(
            policy,
            policy["approval_sha256"],
            attest=True,
            credentials=CREDENTIALS,
            transport=transport,
        )


def offline_delivery_fixture():
    """Feed the browser suite the actual output bytes from an offline scheduled cycle."""
    with tempfile.TemporaryDirectory() as parent, patch("nms_operations.LEGACY", SYNTHETIC_LEGACY):
        scenario = Scenario(parent)
        scenario.first_publish()
        policy = scenario.operations.standing(6, 12, RELEASE)
        scenario.now += timedelta(hours=6)
        scenario.cycle(policy, scenario.transport())
        return scenario.delivery.deployed()


class OperationsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.scenario = Scenario(temporary.name)
        legacy = patch("nms_operations.LEGACY", SYNTHETIC_LEGACY)
        legacy.start()
        self.addCleanup(legacy.stop)

    def test_read_only_guard_and_continuity(self):
        s = self.scenario
        approval = s.operations.review_delta(s.watermark)["approval_sha256"]
        self.assertFalse(s.operations.root.exists())
        self.assertEqual(s.operations.state(), EMPTY)
        t = s.transport(notice("NEW"))
        with self.assertRaisesRegex(PublicationError, "APPROVAL_MISMATCH"):
            s.collect(t, "0" * 64)
        with self.assertRaisesRegex(RefreshError, "INVALID_CREDENTIALS"):
            s.collect(t, approval, credentials={})
        self.assertEqual(t.requests, [])
        s.now = NOW - timedelta(hours=1)
        with self.assertRaisesRegex(RefreshError, "CLOCK_ROLLBACK"):
            s.collect(t, approval)
        s.now = NOW + timedelta(hours=24)
        with self.assertRaisesRegex(RefreshError, "DELTA_GAP"):
            s.collect(t, approval)
        self.assertEqual(t.requests, [])
        self.assertEqual(s.operations.status()["accounted_attempts"], 0)

    def test_window_is_rechecked_after_auth_and_raw_start_controls_overlap(self):
        s = self.scenario
        t = s.transport(notice("NEW"))
        t.slow_auth = lambda: setattr(s, "now", s.now + timedelta(seconds=37))
        result = s.collect(t)
        self.assertEqual(result["watermark"], (s.now - timedelta(seconds=1)).isoformat())
        self.assertEqual([item.stage for item in t.requests], ["auth", "delta"])
        with self.assertRaisesRegex(RefreshError, "BUDGET_WAIT"):
            s.collect(s.transport())
        self.assertEqual(s.operations.status()["accounted_calls"], 2)

    def test_continuity_expires_during_auth_without_sending_a_delta(self):
        s = self.scenario
        s.now = instant(s.watermark) + timedelta(hours=24, seconds=-2)
        transport = s.transport()
        transport.slow_auth = lambda: setattr(s, "now", s.now + timedelta(seconds=3))
        with self.assertRaisesRegex(RefreshError, "DELTA_GAP"):
            s.collect(transport)
        self.assertEqual([item.stage for item in transport.requests], ["auth"])
        self.assertEqual(s.operations.status()["watermark"], s.watermark)

    def test_failed_request_does_not_advance_and_interrupted_reservation_requires_attestation(self):
        s = self.scenario
        failed = s.transport()
        failed.fail_stage = "delta"
        with self.assertRaisesRegex(RefreshError, "^TRANSPORT_FAILED$"):
            s.collect(failed)
        self.assertEqual(s.operations.status()["watermark"], s.watermark)
        self.assertEqual(len(failed.requests), 2)
        s.now += timedelta(minutes=3)
        crashed = s.transport(notice("NEW"))
        crashed.crash_stage = "delta"
        with self.assertRaises(SystemExit):
            s.collect(crashed)
        s.reopen()
        self.assertIn("RECOVERY_REQUIRED", s.operations.status()["blockers"])
        review = s.operations.review_reset()
        with self.assertRaisesRegex(PublicationError, "ATTESTATION"):
            s.operations.reset_interruption(review["approval_sha256"], attest=False)
        s.operations.reset_interruption(review["approval_sha256"], attest=True)
        self.assertEqual(s.operations.status()["watermark"], s.watermark)
        self.assertIn("BUDGET_WAIT", s.operations.status()["blockers"])
        with s.store.review_connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM attempts WHERE error='INTERRUPTED_UNCERTAIN'"
                ).fetchone(),
                (1,),
            )

    def test_concurrent_operator_process_cannot_enter(self):
        s = self.scenario
        script = (
            "from datetime import datetime; from nms_operations import Operations; "
            "from nms_refresh import Store; import sys; "
            "ops=Operations(Store(sys.argv[1],account='SYNTHETIC-ACCOUNT'),clock=datetime.now); "
            "with ops.lock(): pass"
        ).replace("; with", "\nwith")
        env = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "scripts/notam"),
        }
        import sys

        with s.operations.lock():
            result = subprocess.run(
                [sys.executable, "-B", "-c", script, str(s.store.root)],
                env=env,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"OPERATOR_BUSY", result.stderr)

    def test_malformed_and_conflicting_response_preserve_last_accepted(self):
        s = self.scenario
        t = s.transport()

        def malformed(request, limit):
            if request.stage == "delta":
                return 200, {}, b'{"status":"Success","status":"Success","data":{"geojson":[]}}'
            return t(request, limit)

        with self.assertRaisesRegex(RefreshError, "INVALID_RESPONSE"):
            s.collect(malformed)
        self.assertEqual(s.operations.status()["watermark"], s.watermark)
        s.now += timedelta(minutes=3)
        s.collect(s.transport(notice("NEW")))
        accepted = s.operations.status()["watermark"]
        s.now += timedelta(minutes=3)
        s.watermark = accepted
        with self.assertRaisesRegex(RefreshError, "CONFLICT"):
            s.collect(s.transport(notice("NEW", text="SYNTHETIC CONFLICT")))
        self.assertEqual(s.operations.status()["watermark"], accepted)
        self.assertEqual(s.operations.status()["ledger_recovery"], "CONFLICT")

    def test_initial_snapshot_conflict_and_approval_bind_exact_bytes(self):
        s = self.scenario
        s.collect(s.transport(notice("NEW")))
        review = s.operations.review_publication()
        self.assertEqual(review["airports"], 130)
        staged = s.operations.stage_review(review["manifest"]["sha256"])
        body = Path(staged["path"]).read_bytes()
        self.assertEqual(sha256(body), review["manifest"]["sha256"])
        self.assertEqual(
            json.loads(body)["airports"]["KMEM"]["notices"][-1]["formatted_texts"][0]["text"],
            LOCAL_TEXT,
        )
        with self.assertRaisesRegex(PublicationError, "APPROVAL_MISMATCH"):
            s.operations.publish_initial("0" * 64)
        with self.assertRaisesRegex(PublicationError, "OLDER_OR_CONFLICTING"):
            different = body.replace(b"lighting", b"lighting-conflict")
            manifest = {**review["manifest"], "bytes": len(different), "sha256": sha256(different)}
            s.operations._stage(different, manifest)
        self.assertEqual(Path(staged["path"]).read_bytes(), body)
        self.assertEqual(s.delivery.pushes, 0)

    def test_github_race_and_failed_deployment_recover_without_reacquisition(self):
        s = self.scenario
        first = s.first_publish()
        s.operations.publish_initial(s.operations.review_publication()["approval_sha256"])
        self.assertEqual(s.delivery.pushes, 1)
        policy = s.operations.standing(6, 12, RELEASE)
        s.now += timedelta(hours=6)
        s.delivery.race = True
        t = s.transport()
        with self.assertRaisesRegex(PublicationError, "GIT_DELIVERY_FAILED"):
            s.cycle(policy, t)
        self.assertEqual(
            s.operations.status()["publication"]["verified"]["sha256"], first["sha256"]
        )
        s.reopen()
        with self.assertRaisesRegex(PublicationError, "RECOVERY_REQUIRED"):
            s.cycle(policy, t)
        s.delivery.fail_public = True
        with self.assertRaisesRegex(PublicationError, "PUBLIC_DEPLOYMENT_UNVERIFIED"):
            s.operations.recover_publication(policy["approval_sha256"])
        self.assertEqual(s.delivery.pushes, 2)
        self.assertEqual(
            s.delivery.git("show", "HEAD:data/metars.json"), b"weather from concurrent commit"
        )
        s.delivery.fail_public = False
        result = s.operations.recover_publication(policy["approval_sha256"])
        self.assertEqual(result["sha256"], sha256(s.delivery.deployed()))
        self.assertEqual(s.delivery.pushes, 2)
        self.assertEqual([r.stage for r in t.requests], ["auth", "delta"])
        self.assertEqual(s.cycle(policy, t)["status"], "CADENCE_WAIT")
        self.assertEqual(json.loads(s.delivery.deployed())["publication"]["stale_after_hours"], 12)


if __name__ == "__main__":
    unittest.main()
