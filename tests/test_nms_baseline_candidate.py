"""Offline SPA-55 candidate, reconciliation, cutover, and Store tests."""

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "notam"
sys.path.insert(0, str(SCRIPTS))
from nms_baseline_candidate import (
    CandidateError,
    CompatibilityProbe,
    InitialCandidateSink,
    accept_private_candidate,
    accept_production_candidate,
    build_initial_candidate,
    compatibility_matrix,
    continuity_report,
    dashboard_projection,
    promote_baseline,
    publication_snapshot,
    reconcile_delta,
    REQUIRED_ACTIVATION_GATES,
)
from tests.test_nms_refresh import synthetic_store


NOW = datetime(2026, 11, 16, 13, tzinfo=timezone.utc)


def initial(
    identifier="ID-1",
    airport="KMEM",
    *,
    status="associated",
    text="ORIGINAL NOTICE",
    updated="2026-11-16T12:54:00Z",
):
    return {
        "source_message_id": identifier,
        "source_event_aliases": ["gml-" + identifier, identifier],
        "source_gml_ids": ["gml-" + identifier],
        "source_identifiers": [identifier],
        "notam": {
            "number": ["001"],
            "text": [text],
            "type": ["N"],
            "issued": ["2026-11-16T12:00:00Z"],
            "effectiveStart": ["2026-11-16T12:00:00Z"],
            "effectiveEnd": ["PERM"],
            "location": [airport[1:]],
        },
        "representations": [{"type": ["LOCAL_FORMAT"], "simpleText": [text]}],
        "classifications": ["DOM"],
        "source_last_updated": [updated],
        "association_evidence": {airport: {"source_fields": ["event:location"]}},
        "accepted_airports": [airport] if status == "associated" else [],
        "status": status,
    }


def feature(
    identifier="ID-1",
    airport="KMEM",
    *,
    text="ORIGINAL NOTICE",
    updated="2026-11-16T12:54:00Z",
    kind="N",
    classification="DOM",
):
    local = airport[1:] if airport.startswith("K") else airport
    return {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "coreNOTAMData": {
                "notam": {
                    "id": identifier,
                    "number": "001",
                    "text": text,
                    "issued": "2026-11-16T12:00:00Z",
                    "effectiveStart": "2026-11-16T12:00:00Z",
                    "effectiveEnd": "PERM",
                    "lastUpdated": updated,
                    "location": local,
                    "icaoLocation": airport,
                    "classification": classification,
                    "type": kind,
                },
                "notamTranslation": [{"type": "LOCAL_FORMAT", "simpleText": text}],
            }
        },
    }


def envelope(features):
    return {"status": "Success", "data": {"geojson": features}}


class CandidateTests(unittest.TestCase):
    def candidate(self, records=None):
        return build_initial_candidate(
            records or [initial()], capture_started_utc="2026-11-16T12:54:55.099701Z"
        )

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
        self.assertEqual(current["source_message_id"], "ID-1")
        self.assertEqual(current["source_identifiers"], ["ID-1"])
        self.assertEqual(current["airport_associations"], ["KMEM"])
        self.assertEqual(len(candidate["unresolved_records"]), 1)
        self.assertFalse(candidate["baseline_established"])
        self.assertIsNone(candidate["watermark"])

    def test_streaming_sink_is_bounded_and_has_no_network_dependency(self):
        sink = InitialCandidateSink(capture_started_utc="2026-11-16T12:54:55Z", max_records=1)
        with (
            patch("socket.socket", side_effect=AssertionError("network")),
            patch("socket.getaddrinfo", side_effect=AssertionError("dns")),
        ):
            sink(initial())
            candidate = sink.finish()
        self.assertEqual(candidate["audit"]["input_records"], 1)
        self.assert_code("RECORD_LIMIT", lambda: sink(initial("SECOND")))

    def test_message_identity_is_required_and_collisions_fail_closed(self):
        missing = initial()
        del missing["source_message_id"]
        self.assert_code("INVALID_RECORD", lambda: self.candidate([missing]))
        self.assert_code(
            "IDENTITY_CONFLICT",
            lambda: self.candidate([initial("ID-1"), initial("ID-1", text="DIFFERENT")]),
        )
        self.assert_code(
            "IDENTITY_CONFLICT",
            lambda: self.candidate(
                [initial("ID-1", status="unresolved"), initial("ID-1", status="unresolved")]
            ),
        )

    def test_message_identity_not_event_identity_drives_join_replay_and_update(self):
        message_id = "NMS_ID_MESSAGE_123"
        event_id = "EVENT-UUID-456"
        source = initial("IGNORED-FIXTURE-ID")
        source.update(
            {
                "source_message_id": message_id,
                "source_event_aliases": ["event-gml-456", event_id],
                "source_gml_ids": ["event-gml-456"],
                "source_identifiers": [event_id],
            }
        )

        candidate = self.candidate([source])
        self.assertEqual(set(candidate["catalog"]), {message_id})
        self.assertNotIn(event_id, candidate["catalog"])
        current = candidate["catalog"][message_id]["current"]
        self.assertEqual(current["source_message_id"], message_id)
        self.assertEqual(current["source_identifiers"], [event_id])

        replayed = reconcile_delta(
            candidate,
            envelope([feature(message_id)]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:00:00Z",
        )
        self.assertEqual(replayed["delta_candidate"]["audit"]["replayed"], 1)
        changed = feature(message_id, text="UPDATED BY MESSAGE ID", updated="2026-11-16T13:01:00Z")
        updated = reconcile_delta(
            replayed,
            envelope([changed]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:02:00Z",
        )
        self.assertEqual(updated["delta_candidate"]["audit"]["updated"], 1)
        self.assertEqual(updated["catalog"][message_id]["current"]["source_identity"], message_id)

        event_only = reconcile_delta(
            candidate,
            envelope([feature(event_id, text="EVENT ID IS NOT THE MESSAGE ID")]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:00:00Z",
        )
        self.assertEqual(event_only["delta_candidate"]["audit"]["inserted"], 1)
        self.assertIn(event_id, event_only["catalog"])

        probe = CompatibilityProbe()
        probe(source)
        message_report = probe.compare(envelope([feature(message_id)]))
        event_report = probe.compare(
            envelope([feature(event_id, text="EVENT ID IS NOT THE MESSAGE ID")])
        )
        self.assertEqual(message_report["exact_identity_matches"], 1)
        self.assertEqual(event_report["exact_identity_matches"], 0)
        self.assertEqual(event_report["unique_logical_field_matches"], 0)

    def test_delta_replay_update_cancellation_and_missing_are_explicit(self):
        candidate = self.candidate([initial(), initial("MISSING", "KORD")])
        replayed = reconcile_delta(
            candidate,
            envelope([feature()]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:00:00Z",
        )
        self.assertEqual(replayed["delta_candidate"]["audit"]["replayed"], 1)
        self.assertEqual(replayed["delta_candidate"]["audit"]["missing_prior_records_preserved"], 1)
        changed = feature(text="UPDATED ORIGINAL", updated="2026-11-16T13:01:00Z", kind="C")
        changed["properties"]["coreNOTAMData"]["notam"]["cancelationDate"] = "2026-11-16T13:02:00Z"
        result = reconcile_delta(
            candidate,
            envelope([changed]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:02:00Z",
        )
        self.assertEqual(result["delta_candidate"]["audit"]["updated"], 1)
        self.assertEqual(result["delta_candidate"]["audit"]["cancellation_signals_preserved"], 1)
        self.assertIn("MISSING", result["catalog"])
        self.assertEqual(result["catalog"]["ID-1"]["current"]["notam"]["type"], "C")
        self.assertFalse(result["baseline_established"])
        self.assertIsNone(result["watermark"])

    def test_conflicting_equal_and_cross_airport_updates_refuse_atomically(self):
        for change in (
            feature(text="CONFLICT"),
            feature(airport="KORD", text="CROSS", updated="2026-11-16T13:01:00Z"),
        ):
            candidate = self.candidate()
            before = copy.deepcopy(candidate)
            self.assert_code(
                "CONFLICTING_UPDATE",
                lambda change=change: reconcile_delta(
                    candidate,
                    envelope([change]),
                    requested_since_utc="2026-11-16T12:54:00Z",
                    received_utc="2026-11-16T13:02:00Z",
                ),
            )
            self.assertEqual(candidate, before)

    def test_stale_revision_is_ignored_without_overwriting_current(self):
        candidate = self.candidate()
        result = reconcile_delta(
            candidate,
            envelope([feature(text="OLDER", updated="2026-11-16T12:53:59Z")]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:02:00Z",
        )
        self.assertEqual(result["delta_candidate"]["audit"]["stale_ignored"], 1)
        self.assertEqual(result["catalog"]["ID-1"]["current"]["notam"]["text"], ["ORIGINAL NOTICE"])

    def test_same_timestamp_cross_format_replay_requires_all_shared_evidence(self):
        cases = []
        cross_airport = feature(airport="KORD")
        cases.append(cross_airport)
        cases.append(feature(classification="INTL"))
        cases.append(feature(kind="C"))
        cancellation = feature()
        cancellation["properties"]["coreNOTAMData"]["notam"]["cancelationDate"] = (
            "2026-11-16T12:54:00Z"
        )
        cases.append(cancellation)
        missing = feature()
        del missing["properties"]["coreNOTAMData"]["notam"]["classification"]
        cases.append(missing)

        for conflicting in cases:
            with self.subTest(record=conflicting):
                candidate = self.candidate()
                before = copy.deepcopy(candidate)
                self.assert_code(
                    "CONFLICTING_UPDATE",
                    lambda: reconcile_delta(
                        candidate,
                        envelope([conflicting]),
                        requested_since_utc="2026-11-16T12:54:00Z",
                        received_utc="2026-11-16T13:02:00Z",
                    ),
                )
                self.assertEqual(candidate, before)

    def test_new_associated_notice_is_inserted_and_absence_never_deletes(self):
        result = reconcile_delta(
            self.candidate(),
            envelope([feature("NEW", "KORD")]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:02:00Z",
        )
        self.assertIn("ID-1", result["catalog"])
        self.assertIn("NEW", result["catalog"])
        self.assertEqual(result["delta_candidate"]["audit"]["inserted"], 1)

    def test_new_unassociated_notice_is_retained_unresolved(self):
        result = reconcile_delta(
            self.candidate(),
            envelope([feature("NEW", "KZZZ")]),
            requested_since_utc="2026-11-16T12:54:00Z",
            received_utc="2026-11-16T13:02:00Z",
        )
        self.assertEqual(result["unresolved_records"][-1]["source_identity"], "NEW")
        self.assertEqual(result["delta_candidate"]["audit"]["unresolved"], 1)

    def test_delta_lookback_and_cutover_gates_fail_closed(self):
        candidate = self.candidate()
        self.assert_code(
            "DELTA_GAP",
            lambda: reconcile_delta(
                candidate,
                envelope([]),
                requested_since_utc="2026-11-15T12:59:59Z",
                received_utc="2026-11-16T13:00:00Z",
            ),
        )
        report = continuity_report(
            candidate,
            now_utc="2026-11-17T13:00:00Z",
            ledger_budget={"ledger_time_eligible": True},
            external_activity_attested=True,
        )
        self.assertEqual(report["diagnostic"], "DELTA_GAP")
        near = continuity_report(
            candidate,
            now_utc="2026-11-16T13:00:00Z",
            ledger_budget={"ledger_time_eligible": True},
            external_activity_attested=True,
        )
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

            self.assert_code(
                "LOCAL_FAILURE",
                lambda: accept_private_candidate(store, self.candidate(), before_accept=fail),
            )
            with store.review_connect() as db:
                state = store.load(db)
            self.assertNotIn("offline_candidate_b64", state)

    def test_dashboard_contract_is_private_unknown_and_runway_neutral(self):
        projection = dashboard_projection(
            self.candidate(), ["KMEM"], generated_utc="2026-11-16T13:00:00Z"
        )
        self.assertEqual(projection["airports"]["KMEM"]["notices"][0]["text"], "ORIGINAL NOTICE")
        self.assertEqual(projection["airports"]["KMEM"]["completeness"], "UNKNOWN")
        self.assertFalse(projection["publication"]["automatic_updates"])
        self.assertEqual(projection["publication"]["runway_matching_behavior"], "UNCHANGED")
        self.assertNotIn("CLOSED", json.dumps(projection))

    def test_gated_baseline_delta_and_130_airport_publication_contract(self):
        gates = {name: True for name in REQUIRED_ACTIVATION_GATES}
        active = promote_baseline(
            self.candidate(), gates=gates, accepted_utc="2026-11-16T12:55:00Z"
        )
        self.assertTrue(active["baseline_established"])
        self.assertEqual(active["watermark"], "2026-11-16T12:54:54+00:00")
        updated = reconcile_delta(
            active,
            envelope([feature("NEW", "KORD")]),
            requested_since_utc=active["watermark"],
            received_utc="2026-11-16T13:00:00Z",
            request_started_utc="2026-11-16T12:58:07.900000Z",
        )
        self.assertEqual(updated["watermark"], "2026-11-16T12:58:06+00:00")
        snapshot = publication_snapshot(updated, generated_utc="2026-11-16T13:00:00Z")
        self.assertEqual(len(snapshot["airports"]), 130)
        self.assertIn("KMEM", snapshot["airports"])
        self.assertIn("KORD", snapshot["airports"])
        self.assertEqual(
            snapshot["airports"]["KMEM"]["notices"][0]["representations"][0]["type"],
            ["LOCAL_FORMAT"],
        )

    def test_activation_requires_every_gate_and_accepts_atomically(self):
        gates = {name: True for name in REQUIRED_ACTIVATION_GATES}
        missing = dict(gates)
        missing.pop("account_history_validated")
        self.assert_code(
            "VALIDATION_REQUIRED",
            lambda: promote_baseline(
                self.candidate(), gates=missing, accepted_utc="2026-11-16T12:55:00Z"
            ),
        )
        active = promote_baseline(
            self.candidate(), gates=gates, accepted_utc="2026-11-16T12:55:00Z"
        )
        with tempfile.TemporaryDirectory() as temporary:
            store = synthetic_store(temporary)
            result = accept_production_candidate(
                store, active, generated_utc="2026-11-16T12:55:00Z"
            )
            self.assertEqual(result["airports"], 130)
            with store.review_connect() as db:
                state = store.load(db)
            self.assertTrue(state["baseline"])
            self.assertEqual(state["watermark"], active["watermark"])
            self.assertIn("ID-1", state["catalog"])
            self.assertEqual(len(json.loads(store.snapshot())["airports"]), 130)

    def test_compatibility_probe_requires_exact_identity_and_reports_field_equality(self):
        probe = CompatibilityProbe()
        probe(initial())
        report = probe.compare(envelope([feature(), feature("OTHER", text="OTHER NOTICE")]))
        self.assertEqual(report["delta_records"], 2)
        self.assertEqual(report["exact_identity_matches"], 1)
        self.assertEqual(report["field_equal"]["text"], 1)
        self.assertEqual(report["classification_equal"], 1)
        self.assertEqual(report["representations_equal"], 0)
        self.assertEqual(compatibility_matrix()[0]["initial"], "AIXMBasicMessage/@gml:id")
        statuses = {row["status"] for row in compatibility_matrix()}
        self.assertIn("SEMANTICS_UNPROVEN", statuses)


if __name__ == "__main__":
    unittest.main()
