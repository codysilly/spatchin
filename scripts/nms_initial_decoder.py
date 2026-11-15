"""Bounded offline inspection of NMS initial-load SOAP/AIXM content.

The supplied NMS documents identify AIXM 5.1 in a SOAP envelope, but do not
identify compression, archive layout, a complete XML field map, or baseline
cutover evidence.  This module therefore inspects only raw XML evidence.  It
never guesses a container or converts opaque AIXM records into reader records.
"""
from dataclasses import dataclass, field
import re
from xml.etree import ElementTree as ET

from nms_refresh_contract import DecodedInitial, RefreshError, instant

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_ELEMENTS = 250_000
MAX_DEPTH = 64
MAX_TEXT_CHARS = 64 * 1024 * 1024
MAX_ATTRIBUTES = 1_000_000
MAX_ATTRIBUTE_CHARS = 64 * 1024 * 1024
MAX_SERIALIZED_MEMBER_BYTES = 64 * 1024 * 1024

SOAP_NAMESPACES = {
    "http://schemas.xmlsoap.org/soap/envelope/",
    "http://www.w3.org/2003/05/soap-envelope",
}
AIXM_NAMESPACES = {
    "http://www.aixm.aero/schema/5.1",
    "http://www.aixm.aero/schema/5.1/message",
}
GML_NAMESPACES = {"http://www.opengis.net/gml/3.2"}


class InitialDecodeError(Exception):
    """Fixed safe diagnostic; never includes source bytes or parser details."""
    CODES = {
        "INITIAL_UNSUPPORTED_FORMAT", "INITIAL_INPUT_TOO_LARGE",
        "INITIAL_UNSAFE_XML", "INITIAL_MALFORMED_XML",
        "INITIAL_XML_LIMIT", "INITIAL_UNSUPPORTED_NAMESPACE",
        "INITIAL_UNSUPPORTED_STRUCTURE", "INITIAL_MAPPING_REQUIRED",
    }

    def __init__(self, code):
        super().__init__(code if code in self.CODES else "INITIAL_MALFORMED_XML")


@dataclass(frozen=True)
class InspectedInitial:
    format: str
    soap_namespace: str
    message_namespace: str
    record_count: int
    record_xml: tuple[str, ...] = field(repr=False)
    # XML parsing normalizes entity references and line endings. Original response
    # bytes remain in the collector response ledger and are not replaced by these
    # inspectable serializations.


def _split(tag):
    match = re.fullmatch(r"\{([^}]+)\}(.+)", tag if isinstance(tag, str) else "")
    if not match:
        raise InitialDecodeError("INITIAL_UNSUPPORTED_NAMESPACE")
    return match.group(1), match.group(2)


def _validated_utf8(body):
    """Accept only UTF-8 XML so the safety scan and parser see identical text."""
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InitialDecodeError("INITIAL_UNSUPPORTED_FORMAT") from None
    if "\x00" in text:
        raise InitialDecodeError("INITIAL_UNSUPPORTED_FORMAT")
    declaration = re.match(r"\s*<\?xml\s+([^?]*)\?>", text, re.IGNORECASE)
    if declaration:
        encoding = re.search(r"\bencoding\s*=\s*(['\"])([^'\"]+)\1",
                             declaration.group(1), re.IGNORECASE)
        if encoding and encoding.group(2).upper().replace("_", "-") not in {"UTF-8", "UTF8"}:
            raise InitialDecodeError("INITIAL_UNSUPPORTED_FORMAT")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
        raise InitialDecodeError("INITIAL_UNSAFE_XML")
    if not text.lstrip().startswith("<"):
        raise InitialDecodeError("INITIAL_UNSUPPORTED_FORMAT")
    return text


def _bounded_tree(body):
    if not isinstance(body, bytes):
        raise InitialDecodeError("INITIAL_UNSUPPORTED_FORMAT")
    if not body or len(body) > MAX_INPUT_BYTES:
        raise InitialDecodeError("INITIAL_INPUT_TOO_LARGE")
    prefix = body[:4096].lstrip()
    if prefix.startswith((b"PK\x03\x04", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")):
        raise InitialDecodeError("INITIAL_UNSUPPORTED_FORMAT")
    text = _validated_utf8(body)
    try:
        parser = ET.XMLPullParser(events=("start", "end"))
        count = depth = text_chars = attributes = attribute_chars = 0
        root = None
        for offset in range(0, len(text), 65536):
            parser.feed(text[offset:offset + 65536])
            for event, element in parser.read_events():
                if event == "start":
                    count += 1
                    depth += 1
                    attributes += len(element.attrib)
                    attribute_chars += sum(len(str(name)) + len(str(value))
                                           for name, value in element.attrib.items())
                    if (count > MAX_ELEMENTS or depth > MAX_DEPTH
                            or attributes > MAX_ATTRIBUTES
                            or attribute_chars > MAX_ATTRIBUTE_CHARS):
                        raise InitialDecodeError("INITIAL_XML_LIMIT")
                else:
                    text_chars += len(element.text or "") + len(element.tail or "")
                    if text_chars > MAX_TEXT_CHARS:
                        raise InitialDecodeError("INITIAL_XML_LIMIT")
                    depth -= 1
                    if depth == 0:
                        root = element
        parser.close()
        if root is None:
            raise InitialDecodeError("INITIAL_MALFORMED_XML")
        return root
    except InitialDecodeError:
        raise
    except ET.ParseError:
        raise InitialDecodeError("INITIAL_MALFORMED_XML") from None
    except Exception:
        raise InitialDecodeError("INITIAL_MALFORMED_XML") from None


class _BoundedUnicodeWriter:
    def __init__(self, aggregate):
        self.aggregate = aggregate
        self.chunks = []

    def write(self, value):
        size = len(value.encode("utf-8"))
        if self.aggregate[0] + size > MAX_SERIALIZED_MEMBER_BYTES:
            raise InitialDecodeError("INITIAL_XML_LIMIT")
        self.aggregate[0] += size
        self.chunks.append(value)

    def value(self):
        return "".join(self.chunks)


def _serialize_member(element, aggregate):
    writer = _BoundedUnicodeWriter(aggregate)
    ET.ElementTree(element).write(writer, encoding="unicode",
                                  short_empty_elements=True)
    return writer.value()


def inspect_initial(body, stage):
    """Inspect evidenced raw SOAP/AIXM XML without declaring reader semantics."""
    if stage != "initial-aixm-soap":
        raise InitialDecodeError("INITIAL_UNSUPPORTED_FORMAT")
    root = _bounded_tree(body)
    soap_ns, root_name = _split(root.tag)
    if soap_ns not in SOAP_NAMESPACES or root_name != "Envelope":
        raise InitialDecodeError("INITIAL_UNSUPPORTED_NAMESPACE")
    child_names = [_split(child.tag) for child in root]
    headers = [child for child in root if _split(child.tag) == (soap_ns, "Header")]
    bodies = [child for child in root if _split(child.tag) == (soap_ns, "Body")]
    if (len(headers) > 1 or len(bodies) != 1
            or any(name not in {(soap_ns, "Header"), (soap_ns, "Body")}
                   for name in child_names)
            or (headers and child_names.index((soap_ns, "Header"))
                > child_names.index((soap_ns, "Body")))):
        raise InitialDecodeError("INITIAL_UNSUPPORTED_STRUCTURE")
    payloads = list(bodies[0])
    if len(payloads) != 1:
        raise InitialDecodeError("INITIAL_UNSUPPORTED_STRUCTURE")
    message = payloads[0]
    message_ns, message_name = _split(message.tag)
    if message_ns not in AIXM_NAMESPACES or message_name != "AIXMBasicMessage":
        raise InitialDecodeError("INITIAL_UNSUPPORTED_NAMESPACE")
    members = []
    serialized_bytes = [0]
    for child in message:
        namespace, local = _split(child.tag)
        if (namespace, local) == (message_ns, "hasMember"):
            if len(child) != 1:
                raise InitialDecodeError("INITIAL_UNSUPPORTED_STRUCTURE")
            feature_ns, _ = _split(child[0].tag)
            if feature_ns not in AIXM_NAMESPACES:
                raise InitialDecodeError("INITIAL_UNSUPPORTED_NAMESPACE")
            members.append(_serialize_member(child[0], serialized_bytes))
        elif namespace in GML_NAMESPACES and local in {"boundedBy", "metaDataProperty"}:
            continue
        else:
            raise InitialDecodeError("INITIAL_UNSUPPORTED_STRUCTURE")
    return InspectedInitial("raw-soap-aixm-5.1", soap_ns, message_ns,
                            len(members), tuple(members))


def decode_initial(body, stage):
    """Production collector seam: inspect evidence, then require missing mapping."""
    inspect_initial(body, stage)
    raise RefreshError("BASELINE_CUTOVER_REQUIRED")


def assemble_synthetic(inspected, *, payload, coverage_since):
    """Explicit test seam; never derives records or continuity from XML fields."""
    if not isinstance(inspected, InspectedInitial) or not isinstance(payload, dict):
        raise InitialDecodeError("INITIAL_MAPPING_REQUIRED")
    instant(coverage_since)
    return DecodedInitial(payload, coverage_since)
