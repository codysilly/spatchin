"""Synthetic offline evidence only; no production format or continuity claim."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "notam"
sys.path.insert(0, str(SCRIPTS))
import nms_initial_decoder as decoder
from nms_initial_decoder import (InitialDecodeError, assemble_synthetic,
                                 decode_initial, inspect_initial)
from nms_refresh_contract import RefreshError

SOAP11 = "http://schemas.xmlsoap.org/soap/envelope/"
SOAP12 = "http://www.w3.org/2003/05/soap-envelope"
AIXM_MESSAGE = "http://www.aixm.aero/schema/5.1/message"
AIXM = "http://www.aixm.aero/schema/5.1"


def soap(records, *, soap=SOAP11, message=AIXM_MESSAGE):
    members = "".join(f'<aixm:hasMember><aixm5:Event gml:id="{identifier}">'
                      f'<aixm5:unknown>{text}</aixm5:unknown>'
                      '</aixm5:Event></aixm:hasMember>' for identifier, text in records)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\r\n'
            f'<soap:Envelope xmlns:soap="{soap}" xmlns:aixm="{message}" '
            f'xmlns:aixm5="{AIXM}" xmlns:gml="http://www.opengis.net/gml/3.2">'
            f'<soap:Header/><soap:Body><aixm:AIXMBasicMessage>{members}'
            f'</aixm:AIXMBasicMessage></soap:Body></soap:Envelope>').encode()


def soap_text(records, *, encoding="UTF-8"):
    return soap(records).decode().replace('encoding="UTF-8"',
                                           f'encoding="{encoding}"')


class InitialDecoderTests(unittest.TestCase):
    def assert_code(self, code, call):
        with self.assertRaises(InitialDecodeError) as error:
            call()
        self.assertEqual(str(error.exception), code)

    def test_import_performs_no_network_or_store_access(self):
        script = '''import sys
def block(event,args):
 if event.startswith("socket."):raise RuntimeError("Network blocked")
 if event in {"sqlite3.connect","subprocess.Popen"}:raise RuntimeError("Store/process blocked")
sys.addaudithook(block)
sys.path.insert(0,sys.argv[1])
import nms_initial_decoder
print("OFFLINE IMPORT")
'''
        result = subprocess.run([sys.executable, "-c", script, str(SCRIPTS)],
                                check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "OFFLINE IMPORT")

    def test_evidenced_soap_versions_aixm_namespace_order_duplicates_and_entities(self):
        for namespace in (SOAP11, SOAP12):
            body = soap([("same", " first &amp; &lt;literal&gt;\r\nline "),
                         ("same", "🙂 second")], soap=namespace)
            result = inspect_initial(body, "initial-aixm-soap")
            self.assertEqual(result.format, "raw-soap-aixm-5.1")
            self.assertEqual(result.soap_namespace, namespace)
            self.assertEqual(result.record_count, 2)
            self.assertEqual(len(result.record_xml), 2)
            self.assertIn(" first &amp; &lt;literal&gt;\nline ", result.record_xml[0])
            self.assertIn("🙂 second", result.record_xml[1])
            self.assertIn('id="same"', result.record_xml[0])
            self.assertIn('id="same"', result.record_xml[1])

    def test_utf8_policy_covers_bom_declaration_and_encoded_dtd_attacks(self):
        ordinary = soap_text([("unicode", "🙂 &amp; &lt;safe&gt;")])
        result = inspect_initial(b"\xef\xbb\xbf" + ordinary.encode("utf-8"),
                                 "initial-aixm-soap")
        self.assertIn("🙂 &amp; &lt;safe&gt;", result.record_xml[0])
        for body in (ordinary.encode("utf-16"),
                     soap_text([], encoding="ISO-8859-1").encode("ascii")):
            self.assert_code("INITIAL_UNSUPPORTED_FORMAT",
                             lambda body=body: inspect_initial(body, "initial-aixm-soap"))
        utf16_attack = ('<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///secret">]>'
                        + soap_text([("one", "&leak;")]).split("?>", 1)[1]).encode("utf-16")
        self.assert_code("INITIAL_UNSUPPORTED_FORMAT",
                         lambda: inspect_initial(utf16_attack, "initial-aixm-soap"))

    def test_no_local_format_or_operational_field_mapping_is_invented(self):
        result = inspect_initial(soap([("one", "ICAO-like condition only")]),
                                 "initial-aixm-soap")
        self.assertFalse(hasattr(result, "payload"))
        self.assertNotIn("LOCAL_FORMAT", result.record_xml[0])
        payload = {"status": "Success", "data": {"geojson": [{
            "properties": {"coreNOTAMData": {"notam": {"id": "SYNTHETIC"},
                            "notamTranslation": []}}}]}}
        assembled = assemble_synthetic(result, payload=payload,
                                       coverage_since="2026-01-02T11:59:00Z")
        self.assertIs(assembled.payload, payload)
        self.assertEqual(assembled.coverage_since, "2026-01-02T11:59:00Z")

    def test_production_seam_requires_mapping_and_cutover_after_safe_inspection(self):
        with self.assertRaises(RefreshError) as error:
            decode_initial(soap([("one", "opaque")]), "initial-aixm-soap")
        self.assertEqual(str(error.exception), "BASELINE_CUTOVER_REQUIRED")

    def test_rejects_unjustified_compression_stage_namespaces_and_structures(self):
        for body in (b"PK\x03\x04secret", b"\x1f\x8bsecret", b"BZhsecret",
                     b"not xml", b"<broken>"):
            expected = "INITIAL_MALFORMED_XML" if body == b"<broken>" else "INITIAL_UNSUPPORTED_FORMAT"
            self.assert_code(expected, lambda body=body: inspect_initial(body, "initial-aixm-soap"))
        self.assert_code("INITIAL_UNSUPPORTED_FORMAT",
                         lambda: inspect_initial(soap([]), "delta"))
        wrong = soap([], message="urn:synthetic:wrong")
        self.assert_code("INITIAL_UNSUPPORTED_NAMESPACE",
                         lambda: inspect_initial(wrong, "initial-aixm-soap"))
        two = soap([]).replace(b"</soap:Body>", b"<aixm:AIXMBasicMessage/></soap:Body>")
        self.assert_code("INITIAL_UNSUPPORTED_STRUCTURE",
                         lambda: inspect_initial(two, "initial-aixm-soap"))
        extra = soap([]).replace(b"<soap:Body>", b"<aixm:unexpected/><soap:Body>")
        self.assert_code("INITIAL_UNSUPPORTED_STRUCTURE",
                         lambda: inspect_initial(extra, "initial-aixm-soap"))

    def test_rejects_dtd_entities_and_enforces_actual_xml_limits(self):
        attack = (b'<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///secret">]>'
                  + soap([("one", "&leak;")]).split(b"?>", 1)[1])
        self.assert_code("INITIAL_UNSAFE_XML",
                         lambda: inspect_initial(attack, "initial-aixm-soap"))
        with patch.object(decoder, "MAX_INPUT_BYTES", 10):
            self.assert_code("INITIAL_INPUT_TOO_LARGE",
                             lambda: inspect_initial(soap([]), "initial-aixm-soap"))
        with patch.object(decoder, "MAX_ELEMENTS", 3):
            self.assert_code("INITIAL_XML_LIMIT",
                             lambda: inspect_initial(soap([]), "initial-aixm-soap"))
        with patch.object(decoder, "MAX_DEPTH", 2):
            self.assert_code("INITIAL_XML_LIMIT",
                             lambda: inspect_initial(soap([]), "initial-aixm-soap"))
        with patch.object(decoder, "MAX_TEXT_CHARS", 3):
            self.assert_code("INITIAL_XML_LIMIT",
                             lambda: inspect_initial(soap([("one", "long text")]), "initial-aixm-soap"))
        with patch.object(decoder, "MAX_ATTRIBUTES", 0):
            self.assert_code("INITIAL_XML_LIMIT",
                             lambda: inspect_initial(soap([("one", "text")]), "initial-aixm-soap"))
        with patch.object(decoder, "MAX_ATTRIBUTE_CHARS", 2):
            self.assert_code("INITIAL_XML_LIMIT",
                             lambda: inspect_initial(soap([("one", "text")]), "initial-aixm-soap"))

    def test_aggregate_member_serialization_counts_repeated_namespaces(self):
        one = inspect_initial(soap([("one", "🙂 &amp; &lt;literal&gt;")]),
                              "initial-aixm-soap")
        one_size = len(one.record_xml[0].encode("utf-8"))
        self.assertIn("xmlns:", one.record_xml[0])
        with patch.object(decoder, "MAX_SERIALIZED_MEMBER_BYTES", one_size):
            accepted = inspect_initial(soap([("one", "🙂 &amp; &lt;literal&gt;")]),
                                       "initial-aixm-soap")
            self.assertEqual(accepted.record_xml, one.record_xml)
        with patch.object(decoder, "MAX_SERIALIZED_MEMBER_BYTES", one_size * 2 - 1):
            self.assert_code("INITIAL_XML_LIMIT", lambda: inspect_initial(
                soap([("one", "🙂 &amp; &lt;literal&gt;"),
                      ("two", "🙂 &amp; &lt;literal&gt;")]), "initial-aixm-soap"))

    def test_diagnostics_never_echo_body_or_parser_exception(self):
        secret = "SYNTHETIC-SECRET-NEVER-ECHO"
        cases = [secret.encode(), f"<{secret}>".encode(),
                 b"<!DOCTYPE x><x>SYNTHETIC-SECRET-NEVER-ECHO</x>"]
        for body in cases:
            try:
                inspect_initial(body, "initial-aixm-soap")
            except InitialDecodeError as error:
                self.assertNotIn(secret, str(error))
                self.assertIn(str(error), InitialDecodeError.CODES)


if __name__ == "__main__":
    unittest.main()
