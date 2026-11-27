"""Native private storage, the CLI, and the authoritative acceptance transaction."""

import base64
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.test_nms_refresh import CREDENTIALS, SCRIPTS, TOKEN, synthetic_store
from tests.test_initial_load_airport_associations import document, event, member
from tests.test_nms_baseline_candidate import envelope, feature

from capture_global_delta import execute as capture_delta
from capture_initial_load import execute as capture_initial
from nms_refresh import encode
from nms_refresh_contract import stamp
from promote_nms_baseline import PromotionError, accept_production_candidate, review_or_promote


class PromotionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = synthetic_store(temp.name)
        self.now = datetime.now(timezone.utc)
        self.started = self.now.replace(microsecond=100000) - timedelta(minutes=12)
        self.delta_started = self.started + timedelta(minutes=6)
        self.lower = self.started.replace(microsecond=0) - timedelta(seconds=1)
        compressed = gzip.compress(
            document([member(event("MEM", "MEM"), message_id="SYNTHETIC-INITIAL")]), mtime=0
        )

        def transport(request, _limit):
            if request.stage == "auth":
                return 200, {}, encode({"access_token": TOKEN})
            if request.stage == "initial-aixm-soap":
                return 200, {}, b'{"status":"Success","data":{"url":"/v1/content/SYNTHETIC"}}'
            self.assertEqual(request.stage, "delta")
            return 200, {}, encode(envelope([feature("SYNTHETIC-DELTA", "KORD")]))

        def stream(request, _limit, sink):
            self.assertEqual(request.stage, "content")
            sink(compressed)
            return 200, {"bytes": len(compressed), "sha256": hashlib.sha256(compressed).hexdigest()}

        transport.stream = stream
        free = SimpleNamespace(free=max(shutil.disk_usage(self.store.root).free, 2**31))
        with patch("shutil.disk_usage", return_value=free):
            self.initial = capture_initial(
                self.store, credentials=CREDENTIALS, transport=transport, clock=lambda: self.started
            )["attempt"]
            self.delta = capture_delta(
                self.store,
                since=stamp(self.lower),
                credentials=CREDENTIALS,
                transport=transport,
                clock=lambda: self.delta_started,
            )["attempt"]
        self.initial_path = self.store.root / "initial-load-evidence" / self.initial
        self.delta_path = self.store.root / "delta-probe-evidence" / self.delta

    def run_promotion(self, report=None):
        options = {}
        if report is not None:
            options.update(
                approval=report["approval_sha256"],
                reviewed_utc=report["reviewed_utc"],
                external_history_attested=True,
            )
        return review_or_promote(
            self.store, self.initial, self.delta, clock=lambda: self.now, **options
        )

    def files(self):
        return {
            path.relative_to(self.store.root): path.read_bytes()
            for path in self.store.root.rglob("*")
            if path.is_file()
        }

    def accounting(self):
        with self.store.review_connect() as db:
            return (
                db.execute("SELECT * FROM attempts ORDER BY id").fetchall(),
                db.execute("SELECT * FROM calls ORDER BY attempt,stage").fetchall(),
                db.execute("SELECT * FROM responses ORDER BY attempt,stage").fetchall(),
            )

    def update_state(self, **changes):
        with self.store.connect() as db, self.store.transaction(db):
            state = self.store.load(db)
            state.update(changes)
            self.store.save(db, state)

    def test_cli_review_and_promotion_across_processes(self):
        accounting = self.accounting()
        before = self.files()
        command = [
            sys.executable,
            "-B",
            str(SCRIPTS / "promote_nms_baseline.py"),
            "--store",
            str(self.store.root),
            "--account",
            self.store.account,
            "--initial-attempt",
            self.initial,
            "--delta-attempt",
            self.delta,
        ]
        child = subprocess.run(command, capture_output=True, text=True, check=True)
        report = json.loads(child.stdout)
        self.assertEqual(report["status"], "REVIEW_ONLY")
        self.assertEqual(report["catalog_records"], 2)
        self.assertEqual(report["coverage"], "UNKNOWN")
        self.assertEqual(report["delta_audit"]["inserted"], 1)
        self.assertEqual(self.files(), before)
        promotion = command + [
            "--promote",
            "--reviewed-utc",
            report["reviewed_utc"],
            "--approve-promotion",
            report["approval_sha256"],
        ]
        denied = subprocess.run(promotion, capture_output=True, text=True)
        self.assertEqual(denied.returncode, 2)
        self.assertEqual(self.files(), before)

        child = subprocess.run(
            promotion + ["--external-history-attested"], capture_output=True, text=True, check=True
        )
        result = json.loads(child.stdout)
        cursor = stamp(self.delta_started.replace(microsecond=0) - timedelta(seconds=1))
        self.assertEqual(result["status"], "ACCEPTED_PRIVATE_NOT_PUBLISHED")
        self.assertEqual(result["watermark"], cursor)
        self.assertEqual(result["airports"], 130)
        self.assertEqual(self.accounting(), accounting)
        for name, body in before.items():
            if len(name.parts) > 1:
                self.assertEqual((self.store.root / name).read_bytes(), body)
        with self.store.review_connect() as db:
            state = self.store.load(db)
        accepted = json.loads(base64.b64decode(state["production_candidate_b64"]))
        self.assertEqual(accepted["promotion_approval_sha256"], report["approval_sha256"])
        self.assertEqual(accepted["watermark"], cursor)
        self.assertEqual(state["catalog"], accepted["catalog"])
        self.assertTrue(state["baseline"])
        snapshot = json.loads(self.store.snapshot())
        self.assertEqual(snapshot["retrieved_utc"], stamp(self.delta_started))
        self.assertEqual(
            snapshot["airports"]["KMEM"]["notices"][0]["retrieved_utc"], stamp(self.started)
        )
        self.assertFalse(snapshot["publication"]["automatic_updates"])
        repeated = subprocess.run(
            promotion + ["--external-history-attested"], capture_output=True, text=True
        )
        self.assertEqual(repeated.returncode, 1)
        self.assertEqual(repeated.stderr.strip(), "BASELINE_ALREADY_ACCEPTED")

    def test_changed_files_receipts_and_digest_are_rejected(self):
        report = self.run_promotion()
        with self.assertRaisesRegex(PromotionError, "^APPROVAL_MISMATCH$"):
            self.run_promotion({**report, "approval_sha256": "0" * 64})
        for path in (
            self.initial_path / "initial-load.bin",
            self.initial_path / "receipt.json",
            self.delta_path / "response.geojson",
            self.delta_path / "receipt.json",
        ):
            with self.subTest(name=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                before = self.files()
                with self.assertRaisesRegex(PromotionError, "^EVIDENCE_INVALID$"):
                    self.run_promotion(report)
                self.assertEqual(self.files(), before)
                path.write_bytes(original)

    def test_age_and_overlap_gates(self):
        report = self.run_promotion()
        self.now = self.lower + timedelta(hours=24, microseconds=1)
        with self.assertRaisesRegex(PromotionError, "^STALE_APPROVAL$"):
            self.run_promotion(report)
        self.now = self.delta_started + timedelta(minutes=5)
        path = self.delta_path / "receipt.json"
        value = json.loads(path.read_bytes())
        value["requested_since_utc"] = stamp(self.lower + timedelta(seconds=2))
        changed = encode(value)
        path.write_bytes(changed)
        with self.store.connect() as db, self.store.transaction(db):
            db.execute(
                "UPDATE responses SET body=? WHERE attempt=? AND stage='delta-probe-receipt'",
                (changed, self.delta),
            )
        with self.assertRaisesRegex(PromotionError, "^DELTA_GAP$"):
            self.run_promotion()

    def test_active_pending_and_recovery_states_are_rejected(self):
        report = self.run_promotion()
        for changes in ({"active": self.delta}, {"recovery": "DELTA_GAP"}):
            self.update_state(**changes)
            with self.assertRaisesRegex(PromotionError, "^RECOVERY_REQUIRED$"):
                self.run_promotion(report)
            self.update_state(active=None, recovery=None)
        with self.store.connect() as db, self.store.transaction(db):
            db.execute("UPDATE attempts SET status='IO_RESERVED' WHERE id=?", (self.delta,))
        with self.assertRaisesRegex(PromotionError, "^RECOVERY_REQUIRED$"):
            self.run_promotion(report)

    def test_ledger_changes_with_same_counts_invalidate_approval(self):
        report = self.run_promotion()
        accounting = self.accounting()
        self.update_state(history_complete_through=stamp(self.started - timedelta(hours=1)))
        self.assertEqual(self.accounting(), accounting)
        with self.assertRaisesRegex(PromotionError, "^APPROVAL_MISMATCH$"):
            self.run_promotion(report)

    def test_ledger_race_rolls_back_acceptance(self):
        report = self.run_promotion()
        accounting = self.accounting()
        before = self.store.snapshot()

        def race(*args, **kwargs):
            self.update_state(history_complete_through=stamp(self.started - timedelta(hours=1)))
            return accept_production_candidate(*args, **kwargs)

        with patch("promote_nms_baseline.accept_production_candidate", side_effect=race):
            with self.assertRaisesRegex(PromotionError, "^LEDGER_CHANGED$"):
                self.run_promotion(report)
        self.assertEqual(self.accounting(), accounting)
        self.assertEqual(self.store.snapshot(), before)
        with self.store.review_connect() as db:
            self.assertFalse(self.store.load(db)["baseline"])

    def test_evidence_race_rejected_inside_transaction(self):
        report = self.run_promotion()
        before = self.store.snapshot()

        def race(*args, **kwargs):
            (self.delta_path / "response.geojson").write_bytes(b"changed")
            return accept_production_candidate(*args, **kwargs)

        with patch("promote_nms_baseline.accept_production_candidate", side_effect=race):
            with self.assertRaisesRegex(PromotionError, "^EVIDENCE_INVALID$"):
                self.run_promotion(report)
        self.assertEqual(self.store.snapshot(), before)
