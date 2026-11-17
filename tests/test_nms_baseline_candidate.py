"""Offline SPA-55 candidate, reconciliation, cutover, and Store tests."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from nms_baseline_candidate import (
    CandidateError, CompatibilityProbe, InitialCandidateSink, accept_private_candidate,
    build_initial_candidate, compatibility_matrix, continuity_report,
    dashboard_projection, reconcile_delta,
)
from tests.test_nms_refresh import synthetic_store


NOW = datetime(2026, 11, 16, 13, tzinfo=timezone.utc)


def initial(identifier="ID-1", airport="KMEM", *, status="associated",
            text="ORIGINAL NOTICE", updated="2026-11-16T12:54:00Z"):
    return {
        "source_event_aliases": ["gml-" + identifier, identifier],
        "source_gml_ids": ["gml-" + identifier],
        "source_identifiers": [identifier],
        "notam": {"number": ["001"], "text": [text], "type": ["N"],
                  "issued": ["2026-11-16T12:00:00Z"],
                  "effectiveStart": ["2026-11-16T12:00:00Z"],
                  "effectiveEnd": ["PERM"], "location": [airport[1:]]},
        "representations": [{"type": ["LOCAL_FORMAT"], "simpleText": [text]}],
        "classifications": ["DOM"], "source_last_updated": [updated],
        "association_evidence": {airport: {"source_fields": ["event:location"]}},
        "accepted_airports": [airport] if status == "associated" else [],
        "status": status,
    }


def feature(identifier="ID-1", airport="KMEM", *, text="ORIGINAL NOTICE",
            updated="2026-11-16T12:54:00Z", kind="N", classification="DOM"):
    local = airport[1:] if airport.startswith("K") else airport
    return {"type": "Feature", "geometry": None,
            "properties": {"coreNOTAMData": {
                "notam": {"id": identifier, "number": "001", "text": text,
                          "issued": "2026-11-16T12:00:00Z",
                          "effectiveStart": "2026-11-16T12:00:00Z",
                          "effectiveEnd": "PERM", "lastUpdated": updated,
                          "location": local, "icaoLocation": airport,
                          "classification": classification, "type": kind},
                "notamTranslation": [{"type": "LOCAL_FORMAT", "simpleText": text}]}}}


def envelope(features):
    return {"status": "Success", "data": {"geojson": features}}


class CandidateTests(unittest.TestCase):
    def candidate(self, records=None):
        return build_initial_candidate(records or [initial()],
            capture_started_utc="2026-11-16T12:54:55.099701Z")

    def assert_code(self, code, call):
        with self.assertRaises(CandidateError) as error:
            call()
        self.assertEqual(str(error.exception), code)

    def test_initial_adapter_preserves_fields_and_unresolved_records(self):
        unresolved = initial("NO-AIRPORT", status="unresolved")
        candidate = self.candidate([initial(), unresolved])
        current = candidate["catalog"]["ID-1"]["current"]
        self.assertEqual(current["notam"]["text"], ["ORIGINAL NOTICE"])
        self.assertEqual(current["classifications"], ["DOM"])
        self.assertEqual(current["last_updated"], ["2026-11-16T12:54:00Z"])
        self.assertEqual(current["airport_associations"], ["KMEM"])
        self.assertEqual(len(candidate["unresolved_records"]), 1)
        self.assertFalse(candidate["baseline_established"])
        self.assertIsNone(candidate["watermark"])

    def test_streaming_sink_is_bounded_and_has_no_network_dependency(self):
        sink = InitialCandidateSink(capture_started_utc="2026-11-16T12:54:55Z",
                                    max_records=1)
        with patch("socket.socket", side_effect=AssertionError("network")), \
             patch("socket.getaddrinfo", side_effect=AssertionError("dns")):
            sink(initial())
            candidate = sink.finish()
        self.assertEqual(candidate["audit"]["input_records"], 1)
        self.assert_code("RECORD_LIMIT", lambda: sink(initial("SECOND")))

    def test_delta_replay_update_cancellation_and_missing_are_explicit(self):
        candidate = self.candidate([initial(), initial("MISSING", "KORD")])
        replayed = reconcile_delta(candidate, envelope([feature()]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:00:00Z")
        self.assertEqual(replayed["delta_candidate"]["audit"]["replayed"], 1)
        self.assertEqual(replayed["delta_candidate"]["audit"]["missing_prior_records_preserved"], 1)
        changed = feature(text="UPDATED ORIGINAL", updated="2026-11-16T13:01:00Z", kind="C")
        changed["properties"]["coreNOTAMData"]["notam"]["cancelationDate"] = "2026-11-16T13:02:00Z"
        result = reconcile_delta(candidate, envelope([changed]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:02:00Z")
        self.assertEqual(result["delta_candidate"]["audit"]["updated"], 1)
        self.assertEqual(result["delta_candidate"]["audit"]["cancellation_signals_preserved"], 1)
        self.assertIn("MISSING", result["catalog"])
        self.assertEqual(result["catalog"]["ID-1"]["current"]["notam"]["type"], "C")
        self.assertFalse(result["baseline_established"])
        self.assertIsNone(result["watermark"])

    def test_conflicting_same_or_older_and_cross_airport_updates_refuse_atomically(self):
        for change in (
            feature(text="CONFLICT"),
            feature(text="OLDER", updated="2026-11-16T12:53:59Z"),
            feature(airport="KORD", text="CROSS", updated="2026-11-16T13:01:00Z"),
        ):
            candidate = self.candidate()
            before = copy.deepcopy(candidate)
            self.assert_code("CONFLICTING_UPDATE", lambda change=change: reconcile_delta(
                candidate, envelope([change]), requested_since_utc="2026-11-16T12:54:00Z",
                received_utc="2026-11-16T13:02:00Z"))
            self.assertEqual(candidate, before)

    def test_same_timestamp_cross_format_replay_requires_all_shared_evidence(self):
        cases = []
        cross_airport = feature(airport="KORD")
        cases.append(cross_airport)
        cases.append(feature(classification="INTL"))
        cases.append(feature(kind="C"))
        cancellation = feature()
        cancellation["properties"]["coreNOTAMData"]["notam"]["cancelationDate"] = (
            "2026-11-16T12:54:00Z")
        cases.append(cancellation)
        missing = feature()
        del missing["properties"]["coreNOTAMData"]["notam"]["classification"]
        cases.append(missing)

        for conflicting in cases:
            with self.subTest(record=conflicting):
                candidate = self.candidate()
                before = copy.deepcopy(candidate)
                self.assert_code("CONFLICTING_UPDATE", lambda: reconcile_delta(
                    candidate, envelope([conflicting]),
                    requested_since_utc="2026-11-16T12:54:00Z",
                    received_utc="2026-11-16T13:02:00Z"))
                self.assertEqual(candidate, before)

    def test_no_match_is_retained_unresolved_and_absence_never_deletes(self):
        result = reconcile_delta(self.candidate(), envelope([feature("NEW", "KORD")]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:02:00Z")
        self.assertIn("ID-1", result["catalog"])
        self.assertEqual(result["unresolved_records"][-1]["source_identity"], "NEW")
        self.assertEqual(result["delta_candidate"]["audit"]["unresolved"], 1)

    def test_delta_lookback_and_cutover_gates_fail_closed(self):
        candidate = self.candidate()
        self.assert_code("DELTA_GAP", lambda: reconcile_delta(candidate, envelope([]),
            requested_since_utc="2026-11-15T12:59:59Z",
            received_utc="2026-11-16T13:00:00Z"))
        report = continuity_report(candidate, now_utc="2026-11-17T13:00:00Z",
            ledger_budget={"ledger_time_eligible": True}, external_activity_attested=True)
        self.assertEqual(report["diagnostic"], "DELTA_GAP")
        near = continuity_report(candidate, now_utc="2026-11-16T13:00:00Z",
            ledger_budget={"ledger_time_eligible": True}, external_activity_attested=True)
        self.assertEqual(near["diagnostic"], "BASELINE_CUTOVER_REQUIRED")
        self.assertFalse(near["baseline_established"])

    def test_existing_store_accepts_private_candidate_without_snapshot_or_cursor_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = synthetic_store(temporary)
            before = store.snapshot()
            result = accept_private_candidate(store, self.candidate())
            self.assertEqual(result["status"], "PRIVATE_ONLY_NOT_ACTIVATED")
            self.assertEqual(store.snapshot(), before)
            with store.review_connect() as db:
                state = store.load(db)
            self.assertFalse(state["baseline"])
            self.assertIsNone(state["watermark"])
            self.assertEqual(state["offline_candidate_status"], "PRIVATE_ONLY_NOT_ACTIVATED")
            stored = json.loads(__import__("base64").b64decode(state["offline_candidate_b64"]))
            self.assertEqual(stored["catalog"]["ID-1"]["identity"], "ID-1")

    def test_store_preflight_failure_rolls_back_candidate_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = synthetic_store(temporary)
            def fail(_body):
                raise OSError("SYNTHETIC failure")
            self.assert_code("LOCAL_FAILURE", lambda: accept_private_candidate(
                store, self.candidate(), before_accept=fail))
            with store.review_connect() as db:
                state = store.load(db)
            self.assertNotIn("offline_candidate_b64", state)

    def test_dashboard_contract_is_private_unknown_and_runway_neutral(self):
        projection = dashboard_projection(self.candidate(), ["KMEM"],
                                          generated_utc="2026-11-16T13:00:00Z")
        self.assertEqual(projection["airports"]["KMEM"]["notices"][0]["text"],
                         "ORIGINAL NOTICE")
        self.assertEqual(projection["airports"]["KMEM"]["completeness"], "UNKNOWN")
        self.assertFalse(projection["publication"]["automatic_updates"])
        self.assertEqual(projection["publication"]["runway_matching_behavior"], "UNCHANGED")
        self.assertNotIn("CLOSED", json.dumps(projection))

    def test_compatibility_probe_requires_exact_identity_and_reports_field_equality(self):
        probe = CompatibilityProbe()
        probe(initial())
        report = probe.compare(envelope([feature(), feature("OTHER", text="OTHER NOTICE")]))
        self.assertEqual(report["delta_records"], 2)
        self.assertEqual(report["exact_identity_matches"], 1)
        self.assertEqual(report["field_equal"]["text"], 1)
        self.assertEqual(report["classification_equal"], 1)
        self.assertEqual(report["representations_equal"], 0)
        statuses = {row["status"] for row in compatibility_matrix()}
        self.assertIn("SEMANTICS_UNPROVEN", statuses)


if __name__ == "__main__":
    unittest.main()
