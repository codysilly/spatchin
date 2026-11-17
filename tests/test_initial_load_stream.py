"""Offline synthetic and opt-in private-specimen tests for the IL inspector."""
from dataclasses import replace
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import inspect_initial_load_stream as inspector
from inspect_initial_load_stream import InspectionError, InspectionLimits, inspect_evidence


ATTEMPT = "a" * 32


class SyntheticStorage:
    def validate_location(self, path):
        if not Path(path).is_absolute():
            raise OSError()

    def verify_private(self, path):
        if not Path(path).exists():
            raise OSError()


def event(identity, *, classification="DOM", translations=True, effective_end="202611171200",
          extra=""):
    rendered = ""
    if translations:
        rendered = ("<event:translation><event:NOTAMTranslation>"
                    "<event:type>OTHER:ICAO</event:type><event:formattedText>PRIVATE TEXT</event:formattedText>"
                    "</event:NOTAMTranslation></event:translation>"
                    "<event:translation><event:NOTAMTranslation>"
                    "<event:type>LOCAL_FORMAT</event:type><event:simpleText>PRIVATE LOCAL</event:simpleText>"
                    "</event:NOTAMTranslation></event:translation>")
    return f'''<msg:hasMember><event:Event gml:id="event-{identity}">
      <gml:identifier>EVENT-{identity}</gml:identifier>
      <aixm:timeSlice><event:EventTimeSlice gml:id="slice-{identity}">
       <aixm:interpretation>BASELINE</aixm:interpretation>
       <event:textNOTAM><event:NOTAM><event:type>N</event:type><event:number>{identity}</event:number>
        <event:issued>2026-11-16T12:00:00.000Z</event:issued><event:location>MEM</event:location>
        <event:effectiveStart>202611161200</event:effectiveStart>
        <event:effectiveEnd>{effective_end}</event:effectiveEnd><event:text>PRIVATE NOTICE {identity}</event:text>
       </event:NOTAM></event:textNOTAM>{rendered}
       <event:extension><fnse:EventExtension><fnse:classification>{classification}</fnse:classification>
        <fnse:lastUpdated>2026-11-16T12:54:00.000Z</fnse:lastUpdated>
       </fnse:EventExtension></event:extension>{extra}
      </event:EventTimeSlice></aixm:timeSlice>
    </event:Event></msg:hasMember>'''


def airport(identity="shared", *, changed=False):
    name = "CHANGED PRIVATE NAME" if changed else "PRIVATE NAME"
    return f'''<msg:hasMember><aixm:AirportHeliport gml:id="airport-{identity}">
      <gml:identifier>AIRPORT-{identity}</gml:identifier>
      <aixm:timeSlice><aixm:AirportHeliportTimeSlice gml:id="airport-slice-{identity}">
       <aixm:interpretation>SNAPSHOT</aixm:interpretation><aixm:name>{name}</aixm:name>
      </aixm:AirportHeliportTimeSlice></aixm:timeSlice>
    </aixm:AirportHeliport></msg:hasMember>'''


def runway(identity, airport_identity="shared"):
    return f'''<msg:hasMember><aixm:Runway gml:id="runway-{identity}">
      <gml:identifier>RUNWAY-{identity}</gml:identifier>
      <aixm:associatedAirportHeliport xlink:href="#AIRPORT-{airport_identity}"/>
    </aixm:Runway></msg:hasMember>'''


def member(body):
    return f"<wfs:member><msg:AIXMBasicMessage>{body}</msg:AIXMBasicMessage></wfs:member>"


def document(members):
    return ('''<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2"
 xmlns:aixm="http://www.aixm.aero/schema/5.1" xmlns:msg="http://www.aixm.aero/schema/5.1/message"
 xmlns:event="http://www.aixm.aero/schema/5.1/event"
 xmlns:fnse="http://www.aixm.aero/schema/5.1/extensions/FAA/FNSE"
 xmlns:xlink="http://www.w3.org/1999/xlink"><soap:Body><wfs:FeatureCollection>'''
            + "".join(members) + "</wfs:FeatureCollection></soap:Body></soap:Envelope>").encode()


def gzip_bytes(body):
    return gzip.compress(body, mtime=0)


def evidence(parent, body, *, compressed=True):
    root = Path(parent) / ATTEMPT
    root.mkdir()
    artifact = gzip_bytes(body) if compressed else body
    (root / "initial-load.bin").write_bytes(artifact)
    digest = hashlib.sha256(artifact).hexdigest()
    receipt = {"attempt": ATTEMPT, "bytes": len(artifact), "sha256": digest,
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
               "baseline_established": False, "watermark": None,
               "decoded": False, "published": False}
    (root / "receipt.json").write_text(json.dumps(receipt))
    return root, digest, len(artifact)


class InspectorTests(unittest.TestCase):
    def assert_code(self, code, call):
        with self.assertRaises(InspectionError) as error:
            call()
        self.assertEqual(str(error.exception), code)

    def inspect(self, body, *, limits=InspectionLimits(), compressed=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root, digest, size = evidence(temporary.name, body, compressed=compressed)
        return inspect_evidence(root, digest, expected_bytes=size,
                                limits=limits, storage=SyntheticStorage())

    def test_import_has_no_network_store_process_or_file_io(self):
        script = '''import sys
def block(event,args):
 if event.startswith("socket.") or event in {"sqlite3.connect","subprocess.Popen"}:raise RuntimeError(event)
sys.addaudithook(block)
sys.path.insert(0,sys.argv[1])
import inspect_initial_load_stream
print("OFFLINE IMPORT")
'''
        result = subprocess.run([sys.executable, "-B", "-c", script, str(SCRIPTS)],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "OFFLINE IMPORT")

    def test_genuine_hierarchy_aggregates_without_private_values(self):
        body = document([
            member(event("one") + airport() + runway("one")),
            member(event("two", classification="MIL", effective_end="PERM")
                   + event("related", classification="FDC", translations=False)
                   + airport() + runway("two")),
            member(event("three", classification="INTL") + airport(changed=True)),
        ])
        report = self.inspect(body)
        self.assertEqual(report["records"]["wfs_members"], 3)
        self.assertEqual(report["records"]["aixm_basic_messages"], 3)
        self.assertEqual(report["records"]["events_per_member"], {1: 2, 2: 1})
        self.assertEqual(report["records"]["members_with_multiple_events"], 1)
        self.assertEqual(report["records"]["notams_per_member"], {1: 2, 2: 1})
        self.assertEqual(report["records"]["notam_field_cardinality"]["number"], {1: 4})
        self.assertEqual(report["records"]["notam_field_cardinality"]["effectiveEnd"], {1: 4})
        self.assertEqual(report["classifications"]["labels"],
                         {"DOM": 1, "MIL": 1, "FDC": 1, "INTL": 1})
        self.assertEqual(report["translations"]["kinds"],
                         {"OTHER:ICAO": 3, "LOCAL_FORMAT": 3})
        self.assertEqual(report["effective_time_shapes"]["effectiveEnd"],
                         {"compact-12": 3, "alpha-4-sentinel": 1})
        self.assertEqual(report["identities"]["repeated_occurrences"], 2)
        self.assertEqual(report["identities"]["repeated_exact"], 1)
        self.assertEqual(report["identities"]["repeated_changed"], 1)
        self.assertEqual(report["references"]["resolved"], 2)
        serialized = json.dumps(report)
        for private in ("PRIVATE", "EVENT-one", "AIRPORT-shared", str(Path.cwd())):
            self.assertNotIn(private, serialized)
        self.assertFalse(report["baseline_established"])
        self.assertIsNone(report["watermark"])
        self.assertEqual(report["diagnostic"], "BASELINE_CUTOVER_REQUIRED")

    def test_dtd_and_entity_declarations_are_rejected_across_chunks(self):
        base = document([member(event("one"))])
        for declaration in (b'<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///secret">]>',
                            b'<!ENTITY leak SYSTEM "https://example.invalid/private">'):
            self.assert_code("UNSAFE_XML", lambda d=declaration:
                             self.inspect(d + base))
        padding = b" " * (65536 - 3)
        self.assert_code("UNSAFE_XML", lambda:
                         self.inspect(padding + b"<!DOCTYPE x>" + base))
        utf16 = ('<?xml version="1.0" encoding="UTF-16"?>'
                 '<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///secret">]><x>&leak;</x>').encode('utf-16')
        self.assert_code("MALFORMED_XML", lambda: self.inspect(utf16))
        iso = document([member(event("one"))]).replace(b'encoding="UTF-8"',
                                                        b'encoding="ISO-8859-1"')
        self.assert_code("MALFORMED_XML", lambda: self.inspect(iso))
        accepted = self.inspect(b"\xef\xbb\xbf" + document([member(event("bom"))]))
        self.assertEqual(accepted["records"]["wfs_members"], 1)

    def test_schema_and_xlink_are_inert_and_never_resolved(self):
        body = document([member(event("one") + runway("one", "missing"))])
        body = body.replace(b"<wfs:FeatureCollection>",
            b'<wfs:FeatureCollection xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            b'xsi:schemaLocation="https://example.invalid/schema.xsd">')
        with patch("socket.socket", side_effect=AssertionError("network")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            report = self.inspect(body)
        self.assertEqual(report["references"]["unresolved"], 1)
        self.assertEqual(report["references"]["non_fragment"], 0)

    def test_malformed_gzip_xml_extra_members_and_trailing_data_fail_closed(self):
        body = document([member(event("one"))])
        self.assert_code("MALFORMED_XML", lambda: self.inspect(body[:-10]))
        self.assert_code("INVALID_GZIP", lambda: self.inspect(b"not gzip", compressed=False))
        joined = gzip_bytes(body) + gzip_bytes(body)
        self.assert_code("GZIP_MEMBER_COUNT", lambda: self.inspect(joined, compressed=False))
        trailing = gzip_bytes(body) + b"trailing"
        self.assert_code("GZIP_MEMBER_COUNT", lambda: self.inspect(trailing, compressed=False))
        damaged = bytearray(gzip_bytes(body)); damaged[-8] ^= 1
        self.assert_code("INVALID_GZIP", lambda: self.inspect(bytes(damaged), compressed=False))

    def test_compression_bomb_uses_fixed_output_windows_before_limit(self):
        bomb = b" " * (4 * 1024 * 1024)
        limits = replace(InspectionLimits(), decompressed_bytes=128 * 1024)
        real = inspector.zlib.decompressobj
        maxima = []
        class TrackingDecompressor:
            def __init__(self, inner): self.inner = inner
            def decompress(self, value, max_length=0):
                maxima.append(max_length)
                output = self.inner.decompress(value, max_length)
                self.max_returned = max(getattr(self, "max_returned", 0), len(output))
                return output
            def __getattr__(self, name): return getattr(self.inner, name)
        with patch.object(inspector.zlib, "decompressobj",
                          side_effect=lambda *args: TrackingDecompressor(real(*args))):
            self.assert_code("DECOMPRESSED_LIMIT", lambda: self.inspect(bomb, limits=limits))
        self.assertTrue(maxima)
        self.assertLessEqual(max(maxima), inspector.DECOMPRESS_OUTPUT_CHUNK)

    def test_oversized_individual_text_and_attribute_fail_incrementally(self):
        large_text = "X" * 4096
        body = document([member(event("one").replace("PRIVATE NOTICE one", large_text))])
        self.assert_code("XML_LIMIT", lambda: self.inspect(
            body, limits=replace(InspectionLimits(), scalar_chars=1024)))
        large_attribute = b' private="' + b"X" * 4096 + b'"'
        body = document([member(event("one"))]).replace(
            b'<event:Event gml:id="event-one">',
            b'<event:Event gml:id="event-one"' + large_attribute + b'>')
        self.assert_code("XML_LIMIT", lambda: self.inspect(
            body, limits=replace(InspectionLimits(), markup_token_bytes=1024)))

    def test_evidence_hash_receipt_permissions_and_change_detection(self):
        body = document([member(event("one"))])
        with tempfile.TemporaryDirectory() as temporary:
            root, digest, size = evidence(temporary, body)
            self.assert_code("EVIDENCE_HASH_MISMATCH", lambda:
                inspect_evidence(root, "0" * 64, expected_bytes=size, storage=SyntheticStorage()))
            receipt = json.loads((root / "receipt.json").read_text())
            receipt["watermark"] = "changed"
            (root / "receipt.json").write_text(json.dumps(receipt))
            self.assert_code("RECEIPT_INVALID", lambda:
                inspect_evidence(root, digest, expected_bytes=size, storage=SyntheticStorage()))
        with tempfile.TemporaryDirectory() as temporary:
            root, digest, size = evidence(temporary, body)
            original = inspector._stream_gzip
            def mutate(stream, parser, limits):
                result = original(stream, parser, limits)
                (root / "initial-load.bin").write_bytes((root / "initial-load.bin").read_bytes() + b"x")
                return result
            with patch.object(inspector, "_stream_gzip", side_effect=mutate):
                self.assert_code("EVIDENCE_CHANGED", lambda:
                    inspect_evidence(root, digest, expected_bytes=size, storage=SyntheticStorage()))

    def test_receipt_duplicate_keys_replacement_and_required_byte_count(self):
        body = document([member(event("one"))])
        with tempfile.TemporaryDirectory() as temporary:
            root, digest, size = evidence(temporary, body)
            raw = (root / "receipt.json").read_text()
            (root / "receipt.json").write_text(raw[:-1] + ',"schema":1}')
            self.assert_code("RECEIPT_INVALID", lambda: inspect_evidence(
                root, digest, expected_bytes=size, storage=SyntheticStorage()))
        with tempfile.TemporaryDirectory() as temporary:
            root, digest, size = evidence(temporary, body)
            original = inspector._stream_gzip
            def replace_receipt(stream, parser, limits):
                result = original(stream, parser, limits)
                receipt = root / "receipt.json"
                replacement = root / "replacement.tmp"
                replacement.write_bytes(receipt.read_bytes())
                replacement.replace(receipt)
                return result
            with patch.object(inspector, "_stream_gzip", side_effect=replace_receipt):
                self.assert_code("EVIDENCE_CHANGED", lambda: inspect_evidence(
                    root, digest, expected_bytes=size, storage=SyntheticStorage()))
            with self.assertRaises(TypeError):
                inspect_evidence(root, digest, storage=SyntheticStorage())

    def test_unknown_structural_names_are_privacy_bucketed(self):
        private_name = "PRIVATE_IDENTIFIER_123"
        unknown = (f'<msg:hasMember><aixm:{private_name} gml:id="private">'
                   f'<gml:identifier>PRIVATE-SOURCE-ID</gml:identifier>'
                   f'<aixm:{private_name}Ref xlink:href="#PRIVATE-SOURCE-ID"/>'
                   f'</aixm:{private_name}></msg:hasMember>')
        report = self.inspect(document([member(event("one") + unknown)]))
        rendered = json.dumps(report)
        self.assertNotIn(private_name, rendered)
        self.assertNotIn("PRIVATE-SOURCE-ID", rendered)
        self.assertEqual(report["records"]["feature_types"]["<other>"], 1)
        self.assertEqual(report["references"]["relation_elements"]["<other>"], 1)

    def test_explicit_resource_limits(self):
        body = document([member(event("one") + airport())])
        cases = [
            (replace(InspectionLimits(), compressed_bytes=10), "COMPRESSED_LIMIT"),
            (replace(InspectionLimits(), decompressed_bytes=10), "DECOMPRESSED_LIMIT"),
            (replace(InspectionLimits(), elements=5), "XML_LIMIT"),
            (replace(InspectionLimits(), depth=3), "XML_LIMIT"),
            (replace(InspectionLimits(), wfs_members=1), None),
            (replace(InspectionLimits(), features=1), "XML_LIMIT"),
            (replace(InspectionLimits(), attributes=1), "XML_LIMIT"),
            (replace(InspectionLimits(), text_chars=8), "XML_LIMIT"),
            (replace(InspectionLimits(), per_member_elements=3), "XML_LIMIT"),
            (replace(InspectionLimits(), per_member_features=1), "XML_LIMIT"),
            (replace(InspectionLimits(), per_member_text_chars=8), "XML_LIMIT"),
            (replace(InspectionLimits(), scalar_chars=4), "XML_LIMIT"),
        ]
        for limits, code in cases:
            if code:
                with self.subTest(code=code, limits=limits):
                    self.assert_code(code, lambda limits=limits: self.inspect(body, limits=limits))
        two = document([member(event("one")), member(event("two"))])
        self.assert_code("XML_LIMIT", lambda:
                         self.inspect(two, limits=replace(InspectionLimits(), wfs_members=1)))

    def test_completed_elements_are_detached_and_memory_is_bounded(self):
        def run(count):
            body = document([member(event(str(index), translations=False))
                             for index in range(count)])
            tracemalloc.start()
            report = self.inspect(body)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self.assertEqual(report["records"]["wfs_members"], count)
            return peak
        small = run(100)
        large = run(2500)
        self.assertLess(large, 32 * 1024 * 1024)
        self.assertLess(large - small, 20 * 1024 * 1024)

    def test_fixed_diagnostics_do_not_echo_input(self):
        secret = "PRIVATE-SECRET-NEVER-ECHO"
        with tempfile.TemporaryDirectory() as temporary:
            root, digest, size = evidence(temporary, secret.encode(), compressed=False)
            try:
                inspect_evidence(root, digest, expected_bytes=size, storage=SyntheticStorage())
            except InspectionError as error:
                self.assertIn(str(error), InspectionError.CODES)
                self.assertNotIn(secret, str(error))


class PrivateSpecimenTests(unittest.TestCase):
    def test_opt_in_spa56_specimen_aggregates(self):
        value = os.environ.get("SPATCHIN_IL_SPECIMEN_DIR")
        if not value:
            self.skipTest("private specimen not requested")
        report = inspect_evidence(
            value,
            "963a696d0d905bac0597e714a643345b7a565cad0330fca174f5204b9f5e7e40",
            expected_bytes=43_073_137,
        )
        self.assertEqual(report["container"]["decompressed_bytes"], 362_833_367)
        self.assertEqual(report["records"]["wfs_members"], 72_675)
        self.assertEqual(report["records"]["aixm_basic_messages"], 72_675)
        self.assertEqual(report["records"]["embedded_features"], 191_248)
        self.assertEqual(report["records"]["members_with_multiple_events"], 15)
        self.assertEqual(report["records"]["event_features_without_notam"], 15)
        self.assertEqual(sum(report["classifications"]["labels"].values()), 72_675)
        self.assertEqual(report["identities"]["identifier_occurrences"], 191_248)
        self.assertEqual(report["identities"]["repeated_occurrences"], 2_023)
        self.assertEqual(report["identities"]["repeated_same_member"], 0)
        self.assertEqual(report["references"]["resolved"], 134_117)
        self.assertTrue(report["evidence"]["unchanged_during_inspection"])
        self.assertEqual(report["diagnostic"], "BASELINE_CUTOVER_REQUIRED")


if __name__ == "__main__":
    unittest.main()
