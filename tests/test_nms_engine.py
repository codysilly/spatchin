"""Offline end-to-end production-state engine tests."""

from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "notam"
sys.path.insert(0, str(SCRIPTS))

from nms_baseline_candidate import CandidateError, REQUIRED_ACTIVATION_GATES
from nms_engine import collect_engine, execute_offline_cycle
from nms_refresh import Store
from tests.test_nms_baseline_candidate import envelope, feature, initial
from tests.test_initial_load_airport_associations import airport, document, event, member
from tests.test_nms_refresh import synthetic_store


class EngineTests(unittest.TestCase):
    def test_guarded_collector_accounts_baseline_and_delta_with_injected_transport(self):
        gates = {name: True for name in REQUIRED_ACTIVATION_GATES}
        initial_body = gzip.compress(
            document([member(event("mem", "MEM") + airport("mem", "KMEM", "mem"))]),
            mtime=0,
        )

        def baseline_transport(request, _limit):
            if request.stage == "auth":
                return 200, {}, b'{"access_token":"SYNTHETIC"}'
            if request.stage == "initial-aixm-soap":
                return 200, {}, b'{"status":"Success","data":{"url":"/v1/content/ONE"}}'
            self.assertEqual(request.stage, "content")
            return 200, {}, initial_body

        with tempfile.TemporaryDirectory() as temporary:
            store = synthetic_store(temporary)
            baseline_now = datetime(2026, 11, 16, 12, 55, tzinfo=timezone.utc)
            result = collect_engine(
                store,
                mode="baseline",
                credentials={"client_id": "SYNTHETIC", "client_secret": "SYNTHETIC"},
                transport=baseline_transport,
                clock=lambda: baseline_now,
                activation_gates=gates,
            )
            self.assertTrue(result["transport_invoked"])
            self.assertFalse(result["live_network_authorized"])

            def delta_transport(request, _limit):
                if request.stage == "auth":
                    return 200, {}, b'{"access_token":"SYNTHETIC"}'
                self.assertEqual(request.stage, "delta")
                return 200, {}, json.dumps(envelope([feature("NEW", "KORD")])).encode()

            delta_now = datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc)
            result = collect_engine(
                store,
                mode="delta",
                credentials={"client_id": "SYNTHETIC", "client_secret": "SYNTHETIC"},
                transport=delta_transport,
                clock=lambda: delta_now,
            )
            self.assertEqual(result["catalog_records"], 2)
            with store.review_connect() as db:
                state = store.load(db)
                statuses = db.execute("SELECT status FROM attempts ORDER BY reserved").fetchall()
            self.assertEqual(state["attempt_count"], 2)
            self.assertEqual(state["call_count"], 5)
            self.assertEqual(state["response_count"], 3)
            self.assertEqual(statuses, [("ACCEPTED",), ("ACCEPTED",)])

    def test_baseline_multiple_deltas_restart_and_failure_retention(self):
        gates = {name: True for name in REQUIRED_ACTIVATION_GATES}
        with tempfile.TemporaryDirectory() as temporary:
            store = synthetic_store(temporary)
            first = execute_offline_cycle(
                store,
                mode="baseline",
                now=datetime(2026, 11, 16, 12, 55, tzinfo=timezone.utc),
                initial_records=[initial(), initial("UNRESOLVED", status="unresolved")],
                capture_started_utc="2026-11-16T12:54:55.099701Z",
                activation_gates=gates,
            )
            self.assertFalse(first["transport_invoked"])
            self.assertEqual(first["airports"], 130)
            second = execute_offline_cycle(
                store,
                mode="delta",
                now=datetime(2026, 11, 16, 13, 0, tzinfo=timezone.utc),
                delta_payload=envelope([feature("NEW", "KORD")]),
            )
            self.assertEqual(second["catalog_records"], 2)
            snapshot_before = store.snapshot()
            with self.assertRaises(CandidateError) as error:
                execute_offline_cycle(
                    store,
                    mode="delta",
                    now=datetime(2026, 11, 16, 13, 4, tzinfo=timezone.utc),
                    delta_payload=envelope([feature(text="EQUAL VERSION CONFLICT")]),
                )
            self.assertEqual(str(error.exception), "CONFLICTING_UPDATE")
            self.assertEqual(store.snapshot(), snapshot_before)
            restarted = Store(
                (Path(temporary) / "synthetic-account").resolve(), account="SYNTHETIC-ACCOUNT"
            )
            third = execute_offline_cycle(
                restarted,
                mode="delta",
                now=datetime(2026, 11, 16, 13, 8, tzinfo=timezone.utc),
                delta_payload=envelope(
                    [feature("NEW", "KORD", text="UPDATED", updated="2026-11-16T13:07:00Z")]
                ),
            )
            self.assertEqual(third["catalog_records"], 2)
            snapshot = json.loads(restarted.snapshot())
            self.assertEqual(len(snapshot["airports"]), 130)
            self.assertEqual(snapshot["publication"]["status"], "PRIVATE_CANDIDATE_NOT_PUBLISHED")

    def test_publication_preflight_failure_preserves_prior_state(self):
        gates = {name: True for name in REQUIRED_ACTIVATION_GATES}
        with tempfile.TemporaryDirectory() as temporary:
            store = synthetic_store(temporary)
            before = store.snapshot()
            with self.assertRaises(CandidateError) as error:
                execute_offline_cycle(
                    store,
                    mode="baseline",
                    now=datetime(2026, 11, 16, 12, 55, tzinfo=timezone.utc),
                    initial_records=[initial()],
                    capture_started_utc="2026-11-16T12:54:55Z",
                    activation_gates=gates,
                    before_accept=lambda _body: (_ for _ in ()).throw(OSError("synthetic")),
                )
            self.assertEqual(str(error.exception), "LOCAL_FAILURE")
            self.assertEqual(store.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
