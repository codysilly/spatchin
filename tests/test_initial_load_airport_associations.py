"""Synthetic tests for bounded Initial Load airport association."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "notam"
sys.path.insert(0, str(SCRIPTS))
from associate_initial_load_airports import InspectionError, associate_bytes, associate_evidence
from c070_notam_partition import load_versioned_registry


ATTEMPT = "a" * 32


class SyntheticStorage:
    def validate_location(self, path):
        if not Path(path).is_absolute():
            raise OSError()

    def verify_private(self, path):
        if not Path(path).exists():
            raise OSError()


def event(identity, location, *, text="PRIVATE NOTICE", number="1"):
    return f"""<msg:hasMember><event:Event gml:id="event-{identity}">
      <gml:identifier>EVENT-{identity}</gml:identifier>
      <event:textNOTAM><event:NOTAM><event:type>N</event:type><event:number>{number}</event:number>
       <event:issued>2026-11-16T12:00:00.000Z</event:issued><event:location>{location}</event:location>
       <event:effectiveStart>202611161200</event:effectiveStart><event:text>{text}</event:text>
      </event:NOTAM></event:textNOTAM>
      <event:translation><event:NOTAMTranslation><event:type>LOCAL_FORMAT</event:type>
       <event:simpleText>PRIVATE LOCAL {identity}</event:simpleText>
      </event:NOTAMTranslation></event:translation>
      <event:extension><fnse:EventExtension><fnse:classification>DOM</fnse:classification>
       <fnse:lastUpdated>2026-11-16T12:54:00.000Z</fnse:lastUpdated>
      </fnse:EventExtension></event:extension>
    </event:Event></msg:hasMember>"""


def event_without_notam(identity):
    return f"""<msg:hasMember><event:Event gml:id="event-{identity}">
      <gml:identifier>EVENT-{identity}</gml:identifier>
    </event:Event></msg:hasMember>"""


def airport(identity, designator, event_identity, *, duplicate_relation=False):
    relation = f'<event:theEvent xlink:href="#event-{event_identity}"/>'
    if duplicate_relation:
        relation += f'<event:theEvent xlink:href="#EVENT-{event_identity}"/>'
    return f"""<msg:hasMember><aixm:AirportHeliport gml:id="airport-{identity}">
      <gml:identifier>AIRPORT-{identity}</gml:identifier><aixm:timeSlice>
       <aixm:AirportHeliportTimeSlice><aixm:designator>{designator}</aixm:designator>
        <aixm:extension>{relation}</aixm:extension>
       </aixm:AirportHeliportTimeSlice></aixm:timeSlice>
    </aixm:AirportHeliport></msg:hasMember>"""


def runway(event_identity):
    return f"""<msg:hasMember><aixm:Runway gml:id="runway-private">
      <gml:identifier>RUNWAY-PRIVATE</gml:identifier><aixm:timeSlice><aixm:RunwayTimeSlice>
       <aixm:associatedAirportHeliport xlink:href="#airport-private"/>
       <aixm:extension><event:theEvent xlink:href="#event-{event_identity}"/></aixm:extension>
      </aixm:RunwayTimeSlice></aixm:timeSlice>
    </aixm:Runway></msg:hasMember>"""


def member(body, message_id=None):
    message_id = message_id or "NMS_ID_" + hashlib.sha256(body.encode()).hexdigest()[:16]
    return (
        f'<wfs:member><msg:AIXMBasicMessage gml:id="{message_id}">'
        f"{body}</msg:AIXMBasicMessage></wfs:member>"
    )


def document(members):
    return (
        """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2"
 xmlns:aixm="http://www.aixm.aero/schema/5.1" xmlns:msg="http://www.aixm.aero/schema/5.1/message"
 xmlns:event="http://www.aixm.aero/schema/5.1/event"
 xmlns:fnse="http://www.aixm.aero/schema/5.1/extensions/FAA/FNSE"
 xmlns:xlink="http://www.w3.org/1999/xlink">
 <soap:Body><wfs:FeatureCollection>"""
        + "".join(members)
        + "</wfs:FeatureCollection></soap:Body></soap:Envelope>"
    ).encode()


def evidence(parent, body):
    root = Path(parent) / ATTEMPT
    root.mkdir()
    artifact = gzip.compress(body, mtime=0)
    (root / "initial-load.bin").write_bytes(artifact)
    digest = hashlib.sha256(artifact).hexdigest()
    receipt = {
        "attempt": ATTEMPT,
        "bytes": len(artifact),
        "sha256": digest,
        "schema": 1,
        "capture_started_utc": "2026-11-16T12:00:00Z",
        "capture_completed_utc": "2026-11-16T12:00:01Z",
        "initial_control_bytes": 100,
        "initial_control_sha256": "b" * 64,
        "content_continuation_used": True,
        "stage_receipts": [
            {"stage": "auth", "reserved_utc": "2026-11-16T11:59:59Z"},
            {"stage": "initial-aixm-soap", "reserved_utc": "2026-11-16T12:00:00Z"},
            {"stage": "content", "reserved_utc": "2026-11-16T12:00:00Z"},
        ],
        "baseline_established": False,
        "watermark": None,
        "decoded": False,
        "published": False,
    }
    (root / "receipt.json").write_text(json.dumps(receipt))
    return root, digest, len(artifact)


class AssociationTests(unittest.TestCase):
    def inspect(self, members, *, sink=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root, digest, size = evidence(temporary.name, document(members))
        return associate_evidence(
            root,
            digest,
            expected_bytes=size,
            registry=load_versioned_registry(),
            storage=SyntheticStorage(),
            record_sink=sink,
        )

    def test_exact_location_and_explicit_airport_relationships_associate(self):
        report = self.inspect(
            [
                member(event("mem", "MEM") + airport("mem", "KMEM", "mem")),
                member(event("ord", "KORD")),
            ]
        )
        self.assertEqual(report["total_notams_inspected"], 2)
        self.assertEqual(report["notams_associated_with_c070_airports"], 2)
        self.assertEqual(report["per_airport_notice_counts"], {"KMEM": 1, "KORD": 1})
        self.assertEqual(report["duplicate_association_evidence"], 1)
        self.assertFalse(report["runway_relationships_used"])

    def test_in_memory_production_decoder_seam_streams_records(self):
        records = []
        body = gzip.compress(
            document([member(event("mem", "MEM") + airport("mem", "KMEM", "mem"))]), mtime=0
        )
        report = associate_bytes(
            body, registry=load_versioned_registry(), record_sink=records.append
        )
        self.assertEqual(report["total_notams_inspected"], 1)
        self.assertEqual(records[0]["source_message_id"].startswith("NMS_ID_"), True)
        self.assertEqual(records[0]["accepted_airports"], ["KMEM"])

    def test_multiple_explicit_airports_are_preserved(self):
        records = []
        report = self.inspect(
            [
                member(
                    event("multi", "UNKNOWN")
                    + airport("mem", "KMEM", "multi")
                    + airport("ord", "KORD", "multi")
                )
            ],
            sink=records.append,
        )
        self.assertEqual(report["multiple_airport_notams"], 1)
        self.assertEqual(report["notams_associated_with_c070_airports"], 1)
        self.assertEqual(records[0]["accepted_airports"], ["KMEM", "KORD"])

    def test_conflict_is_flagged_and_not_assigned(self):
        records = []
        report = self.inspect(
            [member(event("conflict", "MEM") + airport("ord", "KORD", "conflict"))],
            sink=records.append,
        )
        self.assertEqual(report["conflicting_notams"], 1)
        self.assertEqual(report["unmatched_or_unresolved_notams"], 1)
        self.assertEqual(report["notams_associated_with_c070_airports"], 0)
        self.assertEqual(records[0]["status"], "conflicting")

    def test_unregistered_location_and_runway_relationship_do_not_guess(self):
        report = self.inspect([member(event("none", "ZZZZ") + runway("none"))])
        self.assertEqual(report["notams_associated_with_c070_airports"], 0)
        self.assertEqual(report["unmatched_or_unresolved_notams"], 1)
        self.assertEqual(
            report["source_fields_and_relationships"]["notam_location_unregistered"], 1
        )

    def test_sink_preserves_exact_source_values_but_report_is_private_safe(self):
        records = []
        secret = "PRIVATE-NOTICE-DO-NOT-REPORT"
        report = self.inspect(
            [member(event("secret", "MEM", text=secret, number="007"))], sink=records.append
        )
        self.assertEqual(records[0]["notam"]["text"], [secret])
        self.assertEqual(records[0]["notam"]["issued"], ["2026-11-16T12:00:00.000Z"])
        self.assertEqual(records[0]["representations"][0]["simpleText"], ["PRIVATE LOCAL secret"])
        self.assertEqual(records[0]["classifications"], ["DOM"])
        self.assertEqual(records[0]["source_last_updated"], ["2026-11-16T12:54:00.000Z"])
        self.assertEqual(records[0]["source_identifiers"], ["EVENT-secret"])
        self.assertTrue(records[0]["source_message_id"].startswith("NMS_ID_"))
        self.assertEqual(report["message_ids_preserved"], 1)
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("EVENT-secret", json.dumps(report))

    def test_duplicate_source_identifier_is_counted_without_disclosure(self):
        report = self.inspect(
            [
                member(event("same", "MEM"), "NMS_ID_FIRST"),
                member(event("same", "MEM"), "NMS_ID_SECOND"),
            ]
        )
        self.assertEqual(report["duplicate_source_identifiers"], 1)

    def test_two_events_one_notam_uses_notam_owner_and_message_identity(self):
        records = []
        report = self.inspect(
            [
                member(
                    event_without_notam("context")
                    + event("owner", "MEM")
                    + airport("mem", "KMEM", "owner"),
                    "NMS_ID_TWO_EVENTS",
                )
            ],
            sink=records.append,
        )
        self.assertEqual(report["total_notams_inspected"], 1)
        self.assertEqual(records[0]["source_message_id"], "NMS_ID_TWO_EVENTS")
        self.assertEqual(records[0]["source_identifiers"], ["EVENT-owner"])
        self.assertEqual(records[0]["accepted_airports"], ["KMEM"])

    def test_message_structure_and_identity_fail_closed(self):
        cases = {
            "missing-id": "<wfs:member><msg:AIXMBasicMessage>"
            + event("one", "MEM")
            + "</msg:AIXMBasicMessage></wfs:member>",
            "missing-notam": member(event_without_notam("one"), "NMS_ID_MISSING_NOTAM"),
            "multiple-notams": member(
                event("one", "MEM") + event("two", "MEM"), "NMS_ID_MULTIPLE_NOTAMS"
            ),
            "three-events": member(
                event("one", "MEM") + event_without_notam("two") + event_without_notam("three"),
                "NMS_ID_THREE_EVENTS",
            ),
        }
        for name, value in cases.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(InspectionError, "UNSUPPORTED_STRUCTURE"),
            ):
                self.inspect([value])

    def test_duplicate_message_ids_fail_closed(self):
        with self.assertRaisesRegex(InspectionError, "UNSUPPORTED_STRUCTURE"):
            self.inspect(
                [
                    member(event("one", "MEM"), "NMS_ID_COLLISION"),
                    member(event("two", "KORD"), "NMS_ID_COLLISION"),
                ]
            )


class PrivateSpecimenTests(unittest.TestCase):
    def test_opt_in_spa58_c070_aggregate(self):
        value = os.environ.get("SPATCHIN_IL_SPECIMEN_DIR")
        if not value:
            self.skipTest("private specimen not requested")
        report = associate_evidence(
            value,
            "963a696d0d905bac0597e714a643345b7a565cad0330fca174f5204b9f5e7e40",
            expected_bytes=43_073_137,
        )
        self.assertEqual(report["total_notams_inspected"], 72_675)
        self.assertEqual(report["notams_associated_with_c070_airports"], 8_298)
        self.assertEqual(report["c070_airports_represented"], 130)
        self.assertEqual(report["unmatched_or_unresolved_notams"], 64_377)
        self.assertEqual(report["conflicting_notams"], 0)
        self.assertEqual(report["multiple_airport_notams"], 0)
        self.assertEqual(report["duplicate_association_evidence"], 3_848)
        self.assertEqual(report["duplicate_source_identifiers"], 0)
        self.assertEqual(report["message_ids_preserved"], 72_675)
        self.assertFalse(report["runway_relationships_used"])
        self.assertTrue(report["evidence"]["unchanged_during_inspection"])


if __name__ == "__main__":
    unittest.main()
