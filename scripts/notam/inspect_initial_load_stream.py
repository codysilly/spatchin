"""Offline, bounded inspection of a preserved NMS Initial Load specimen.

This module has no network, credential, SQLite, collector, decoder, publication,
or public-data integration.  It verifies an existing protected capture and emits
only aggregate structural diagnostics.  Source text, identifiers, coordinates,
links, and internal hashes are never returned.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import zlib
from xml.parsers import expat

from capture_storage import platform_storage


SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
WFS = "http://www.opengis.net/wfs/2.0"
GML = "http://www.opengis.net/gml/3.2"
AIXM = "http://www.aixm.aero/schema/5.1"
MESSAGE = "http://www.aixm.aero/schema/5.1/message"
EVENT = "http://www.aixm.aero/schema/5.1/event"
FNSE = "http://www.aixm.aero/schema/5.1/extensions/FAA/FNSE"
FNS = "urn:us.gov.dot.faa.aim.fns"
XHTML = "http://www.w3.org/1999/xhtml"
XLINK = "http://www.w3.org/1999/xlink"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

KNOWN_NAMESPACES = frozenset((SOAP, WFS, GML, AIXM, MESSAGE, EVENT, FNSE, FNS, XHTML, XLINK, XSI))
KNOWN_CLASSIFICATIONS = frozenset(("INTL", "DOM", "MIL", "FDC"))
KNOWN_TRANSLATIONS = frozenset(("OTHER:ICAO", "LOCAL_FORMAT"))
KNOWN_EVENT_TYPES = frozenset(("N", "R", "C"))
KNOWN_INTERPRETATIONS = frozenset(("SNAPSHOT", "BASELINE", "TEMPDELTA", "PERMDELTA"))
KNOWN_FEATURE_NAMES = frozenset(
    (
        "Event",
        "AirportHeliport",
        "VerticalStructure",
        "ObstacleArea",
        "RunwayDirection",
        "Runway",
        "InstrumentApproachProcedure",
        "RunwayElement",
        "TaxiwayElement",
        "StandardInstrumentDeparture",
        "Navaid",
        "FinalLeg",
        "Unit",
        "Taxiway",
        "VisualGlideSlopeIndicator",
        "RunwayDirectionLightSystem",
        "ApronElement",
        "TaxiwayLightSystem",
        "MarkerBeacon",
        "Airspace",
        "Apron",
        "Route",
        "RouteSegment",
        "DepartureLeg",
        "VOR",
        "DesignatedPoint",
        "DME",
        "InformationService",
        "AirportSign",
        "RadioCommunicationChannel",
        "RadioFrequencyArea",
        "AirTrafficControlService",
        "PrimarySurveillanceRadar",
        "TACAN",
        "Glidepath",
        "RunwayProtectArea",
        "TaxiwayMarking",
        "Localizer",
        "WindDirectionIndicator",
        "RadarSystem",
        "RunwayVisualRange",
        "RunwayMarking",
        "Azimuth",
        "PilotControlledLighting",
        "AirportSuppliesService",
        "AeronauticalGroundLight",
        "RunwayCentrelinePoint",
        "ApronMarking",
        "ArrestingGear",
        "ApronLightSystem",
        "FireFightingService",
        "NavigationAreaRestriction",
        "ApproachLightingSystem",
        "TouchDownLiftOff",
        "StandardInstrumentArrival",
        "AircraftGroundService",
    )
)
KNOWN_RELATION_NAMES = frozenset(
    (
        "theEvent",
        "reference_ownerAirport",
        "obstacle",
        "runwayDirection",
        "usedRunway",
        "associatedAirportHeliport",
        "associatedRunway",
        "associatedApron",
        "theNavaidEquipment",
        "servedAirport",
        "associatedRunwayDirection",
        "associatedTaxiway",
        "radioCommunication",
        "clientAirport",
        "airportHeliport",
        "pointChoice_navaidSystem",
        "routeFormed",
        "pointChoice_fixDesignatedPoint",
        "lightedTaxiway",
        "aerodromeBeacon",
        "onRunway",
        "markedTaxiway",
        "associatedAirport",
        "theRadarEquipment",
        "procedure",
        "theVerticalStructure",
        "markedApron",
        "protectedRunwayDirection",
        "markedRunway",
        "activatedGroundLighting",
        "navaidBroadcast",
        "servedRunwayDirection",
        "lightedApron",
        "causeEvent",
    )
)
VALUE_QNAMES = frozenset(
    (
        (GML, "identifier"),
        (FNSE, "classification"),
        (AIXM, "interpretation"),
        (EVENT, "type"),
        (EVENT, "effectiveStart"),
        (EVENT, "effectiveEnd"),
        (EVENT, "issued"),
        (FNSE, "lastUpdated"),
        (GML, "beginPosition"),
        (GML, "endPosition"),
        (GML, "timePosition"),
    )
)
DECOMPRESS_OUTPUT_CHUNK = 64 * 1024


class InspectionError(Exception):
    """A fixed diagnostic that cannot echo private input."""

    CODES = frozenset(
        (
            "INVALID_REQUEST",
            "EVIDENCE_UNAVAILABLE",
            "PRIVATE_ACCESS_REQUIRED",
            "RECEIPT_INVALID",
            "EVIDENCE_HASH_MISMATCH",
            "EVIDENCE_CHANGED",
            "COMPRESSED_LIMIT",
            "INVALID_GZIP",
            "GZIP_MEMBER_COUNT",
            "DECOMPRESSED_LIMIT",
            "UNSAFE_XML",
            "MALFORMED_XML",
            "XML_LIMIT",
            "UNSUPPORTED_NAMESPACE",
            "UNSUPPORTED_STRUCTURE",
            "LOCAL_FAILURE",
        )
    )

    def __init__(self, code):
        super().__init__(code if code in self.CODES else "MALFORMED_XML")


@dataclass(frozen=True)
class InspectionLimits:
    compressed_bytes: int = 1024 * 1024 * 1024
    decompressed_bytes: int = 1024 * 1024 * 1024
    elements: int = 8_000_000
    depth: int = 64
    wfs_members: int = 100_000
    features: int = 300_000
    namespaces: int = 32
    qnames: int = 4096
    attributes: int = 4_000_000
    attribute_chars: int = 512 * 1024 * 1024
    text_chars: int = 1024 * 1024 * 1024
    references: int = 300_000
    identities: int = 300_000
    per_member_elements: int = 100_000
    per_member_features: int = 4096
    per_member_text_chars: int = 32 * 1024 * 1024
    scalar_chars: int = 16 * 1024 * 1024
    markup_token_bytes: int = 1024 * 1024

    def validate(self):
        values = vars(self)
        if any(type(value) is not int or value < 1 for value in values.values()):
            raise InspectionError("INVALID_REQUEST")


@dataclass
class _Feature:
    kind: tuple[str, str]
    member: int
    depth: int
    digest: object
    identity: bytes | None = None
    aliases: set[bytes] | None = None
    notams: int = 0


@dataclass
class _Translation:
    kinds: Counter
    simple: int = 0
    formatted: int = 0


@dataclass
class _Notam:
    fields: Counter


@dataclass
class _Frame:
    qname: tuple[str, str]
    text_chars: int
    text_digest: object
    retained: list[str] | None


NOTAM_FIELDS = frozenset(
    (
        (EVENT, "number"),
        (EVENT, "year"),
        (EVENT, "issued"),
        (EVENT, "location"),
        (EVENT, "effectiveStart"),
        (EVENT, "effectiveEnd"),
        (EVENT, "text"),
        (EVENT, "series"),
        (EVENT, "scope"),
        (EVENT, "traffic"),
        (EVENT, "purpose"),
        (EVENT, "selectionCode"),
        (EVENT, "coordinates"),
    )
)


def _split(tag):
    match = re.fullmatch(r"\{([^}]+)\}(.+)", tag if isinstance(tag, str) else "")
    if not match:
        raise InspectionError("UNSUPPORTED_NAMESPACE")
    return match.group(1), match.group(2)


def _split_expat(tag):
    try:
        namespace, local = tag.split("}", 1)
        if not namespace or not local:
            raise ValueError()
        return namespace, local
    except (AttributeError, ValueError):
        raise InspectionError("UNSUPPORTED_NAMESPACE") from None


def _safe_bucket(value, allowed):
    return value if value in allowed else "<other>"


def _safe_local(value, allowed):
    return value if value in allowed else "<other>"


def _identity(value):
    return hashlib.sha256(b"spatchin-il-identity\0" + value.encode("utf-8")).digest()


def _encode_part(value):
    value = value.encode("utf-8")
    return len(value).to_bytes(8, "big") + value


def _timestamp_shape(value):
    if not value:
        return "empty"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        return "iso-utc-seconds"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z", value):
        return "iso-utc-fractional"
    if re.fullmatch(r"\d{12}", value):
        return "compact-12"
    if re.fullmatch(r"\d{12}[A-Za-z]+", value):
        return "compact-12-suffix"
    if re.fullmatch(r"[A-Za-z]{4}", value):
        return "alpha-4-sentinel"
    if re.fullmatch(r"\d+[A-Za-z]+", value):
        return "compact-other-suffix"
    return "other"


def _stat_marker(stat):
    # Windows can update creation/change metadata representation when a handle is
    # reopened. Device, file identity, size, and last-write time are the stable
    # replacement/mutation evidence; the complete bytes are also hashed twice.
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _hash_stream(stream, limit):
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise InspectionError("COMPRESSED_LIMIT")
        digest.update(chunk)
    return total, digest.hexdigest()


class _AggregateParser:
    def __init__(self, limits):
        self.limits = limits
        self.parser = expat.ParserCreate(encoding="UTF-8", namespace_separator="}")
        self.parser.buffer_text = False
        self.parser.StartElementHandler = self._start
        self.parser.EndElementHandler = self._end
        self.parser.CharacterDataHandler = self._characters
        self.parser.StartDoctypeDeclHandler = self._unsafe_declaration
        self.parser.EntityDeclHandler = self._unsafe_declaration
        self.parser.ExternalEntityRefHandler = self._external_entity
        self.parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        self.stack = []
        self.elements = self.depth = self.max_depth = 0
        self.attributes = self.attribute_chars = self.text_chars = 0
        self.namespaces = Counter()
        self.qnames = Counter()
        self.root = None
        self.envelope_children = Counter()
        self.body_payloads = Counter()
        self.feature_collection_count = 0
        self.members = 0
        self.messages = 0
        self.features = Counter()
        self.member_feature_counts = Counter()
        self.member_event_counts = Counter()
        self.member_notam_counts = Counter()
        self.member_classification_counts = Counter()
        self.member_translation_counts = Counter()
        self.classifications = Counter()
        self.translation_kinds = Counter()
        self.translation_shapes = Counter()
        self.effective_times = defaultdict(Counter)
        self.interpretations = Counter()
        self.event_types = Counter()
        self.reference_relations = Counter()
        self.current_member = None
        self.member_elements = self.member_features = self.member_text = 0
        self.current_feature = None
        self.current_translation = None
        self.current_notam = None
        self.notam_field_cardinality = defaultdict(Counter)
        self.feature_identity_occurrences = 0
        self.identities = {}
        self.references = []
        self.repeated_occurrences = 0
        self.repeated_exact = 0
        self.repeated_changed = 0
        self.repeated_same_member = 0
        self.repeated_cross_member = 0
        self.repeated_types = Counter()
        self.repeated_type_conflicts = 0
        self.extra_event_members = 0
        self.event_features_with_notam = 0
        self.event_features_without_notam = 0
        self.reference_targets = defaultdict(set)

    def _limit(self, condition):
        if condition:
            raise InspectionError("XML_LIMIT")

    def feed(self, chunk):
        try:
            self.parser.Parse(chunk, False)
        except InspectionError:
            raise
        except expat.ExpatError:
            raise InspectionError("MALFORMED_XML") from None
        except Exception:
            raise InspectionError("MALFORMED_XML") from None

    def _unsafe_declaration(self, *_args):
        raise InspectionError("UNSAFE_XML")

    def _external_entity(self, *_args):
        raise InspectionError("UNSAFE_XML")

    def _feature_start(self, qname, attributes):
        feature = self.current_feature
        if feature is None:
            return
        feature.digest.update(b"S")
        feature.digest.update(_encode_part(qname[0]))
        feature.digest.update(_encode_part(qname[1]))
        for name, value in sorted(attributes.items()):
            feature.digest.update(_encode_part(name))
            feature.digest.update(_encode_part(value))

    def _feature_end(self, frame):
        feature = self.current_feature
        if feature is None:
            return
        feature.digest.update(b"E")
        feature.digest.update(_encode_part(frame.qname[0]))
        feature.digest.update(_encode_part(frame.qname[1]))
        feature.digest.update(frame.text_chars.to_bytes(8, "big"))
        feature.digest.update(frame.text_digest.digest())

    def _start(self, name, attributes):
        qname = _split_expat(name)
        namespace = qname[0]
        if namespace not in KNOWN_NAMESPACES:
            raise InspectionError("UNSUPPORTED_NAMESPACE")
        self.elements += 1
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        self.attributes += len(attributes)
        self.attribute_chars += sum(len(str(k)) + len(str(v)) for k, v in attributes.items())
        self.namespaces[namespace] += 1
        self.qnames[qname] += 1
        self._limit(
            self.elements > self.limits.elements
            or self.depth > self.limits.depth
            or self.attributes > self.limits.attributes
            or self.attribute_chars > self.limits.attribute_chars
            or len(self.namespaces) > self.limits.namespaces
            or len(self.qnames) > self.limits.qnames
        )
        parent_qname = self.stack[-1].qname if self.stack else None
        frame = _Frame(qname, 0, hashlib.sha256(), [] if qname in VALUE_QNAMES else None)
        self.stack.append(frame)
        if self.root is None:
            self.root = qname
        elif self.depth == 2:
            self.envelope_children[qname] += 1
        elif self.depth == 3 and parent_qname == (SOAP, "Body"):
            self.body_payloads[qname] += 1
        if qname == (WFS, "FeatureCollection"):
            self.feature_collection_count += 1
        if qname == (WFS, "member"):
            self.members += 1
            self._limit(self.members > self.limits.wfs_members or self.current_member is not None)
            self.current_member = self.members
            self.member_elements = self.member_features = self.member_text = 0
        if self.current_member is not None:
            self.member_elements += 1
            self._limit(self.member_elements > self.limits.per_member_elements)
        if qname == (MESSAGE, "AIXMBasicMessage"):
            self.messages += 1
        if parent_qname == (MESSAGE, "hasMember"):
            self.member_features += 1
            self._limit(
                self.current_member is None
                or self.member_features > self.limits.per_member_features
                or sum(self.features.values()) + 1 > self.limits.features
            )
            self.features[qname] += 1
            aliases = set()
            gml_id = attributes.get(GML + "}id")
            if gml_id:
                aliases.add(_identity(gml_id))
            self.current_feature = _Feature(
                qname, self.current_member, self.depth, hashlib.sha256(), aliases=aliases
            )
        self._feature_start(qname, attributes)
        if self.current_feature is not None:
            href = attributes.get(XLINK + "}href")
            if href is not None:
                self._limit(len(self.references) + 1 > self.limits.references)
                target = href[1:] if href.startswith("#") else href
                relation = _safe_local(qname[1], KNOWN_RELATION_NAMES)
                self.references.append(
                    (relation, self.current_feature.member, _identity(target), href.startswith("#"))
                )
                self.reference_relations[relation] += 1
        if qname == (EVENT, "NOTAMTranslation"):
            if self.current_translation is not None:
                raise InspectionError("UNSUPPORTED_STRUCTURE")
            self.current_translation = _Translation(Counter())
        if qname == (EVENT, "NOTAM"):
            if self.current_notam is not None:
                raise InspectionError("UNSUPPORTED_STRUCTURE")
            self.current_notam = _Notam(Counter())

    def _characters(self, value):
        if not self.stack or not value:
            return
        frame = self.stack[-1]
        count = len(value)
        frame.text_chars += count
        self.text_chars += count
        if self.current_member is not None:
            self.member_text += count
        self._limit(
            frame.text_chars > self.limits.scalar_chars
            or self.text_chars > self.limits.text_chars
            or self.member_text > self.limits.per_member_text_chars
        )
        encoded = value.encode("utf-8")
        frame.text_digest.update(encoded)
        if frame.retained is not None:
            frame.retained.append(value)

    def _end(self, name):
        qname = _split_expat(name)
        if not self.stack or self.stack[-1].qname != qname:
            raise InspectionError("UNSUPPORTED_STRUCTURE")
        frame = self.stack[-1]
        value = "".join(frame.retained).strip() if frame.retained is not None else ""
        self._feature_end(frame)
        if qname == (GML, "identifier") and self.current_feature is not None and value:
            self.current_feature.identity = _identity(value)
            self.current_feature.aliases.add(self.current_feature.identity)
        elif qname == (FNSE, "classification"):
            self.classifications[_safe_bucket(value, KNOWN_CLASSIFICATIONS)] += 1
            if self.current_member is not None:
                self.member_classification_counts[self.current_member] += 1
        elif qname == (AIXM, "interpretation"):
            self.interpretations[_safe_bucket(value, KNOWN_INTERPRETATIONS)] += 1
        elif qname == (EVENT, "type"):
            if self.current_translation is not None:
                self.current_translation.kinds[_safe_bucket(value, KNOWN_TRANSLATIONS)] += 1
            else:
                self.event_types[_safe_bucket(value, KNOWN_EVENT_TYPES)] += 1
        elif qname == (EVENT, "simpleText") and self.current_translation is not None:
            self.current_translation.simple += 1
        elif qname == (EVENT, "formattedText") and self.current_translation is not None:
            self.current_translation.formatted += 1
        elif qname in (
            (EVENT, "effectiveStart"),
            (EVENT, "effectiveEnd"),
            (EVENT, "issued"),
            (FNSE, "lastUpdated"),
            (GML, "beginPosition"),
            (GML, "endPosition"),
            (GML, "timePosition"),
        ):
            self.effective_times[qname[1]][_timestamp_shape(value)] += 1
        if self.current_notam is not None and qname in NOTAM_FIELDS:
            self.current_notam.fields[qname[1]] += 1
        if qname == (EVENT, "NOTAM") and self.current_member is not None:
            self.member_notam_counts[self.current_member] += 1
            if self.current_feature is not None:
                self.current_feature.notams += 1
            for field in (name for _, name in NOTAM_FIELDS):
                self.notam_field_cardinality[field][self.current_notam.fields[field]] += 1
            self.current_notam = None
        if qname == (EVENT, "NOTAMTranslation"):
            translation = self.current_translation
            if translation is None:
                raise InspectionError("UNSUPPORTED_STRUCTURE")
            for kind, count in translation.kinds.items():
                self.translation_kinds[kind] += count
            shape = (sum(translation.kinds.values()), translation.simple, translation.formatted)
            self.translation_shapes[shape] += 1
            if self.current_member is not None:
                self.member_translation_counts[self.current_member] += 1
            self.current_translation = None
        if (
            self.current_feature is not None
            and qname == self.current_feature.kind
            and self.depth == self.current_feature.depth
        ):
            self._finish_feature()
        if qname == (WFS, "member"):
            self.member_feature_counts[self.member_features] += 1
            events = self.member_event_counts[self.current_member]
            if events > 1:
                self.extra_event_members += 1
            self.current_member = None
            self.member_elements = self.member_features = self.member_text = 0
        self.stack.pop()
        self.depth -= 1

    def _finish_feature(self):
        feature = self.current_feature
        if feature.kind == (EVENT, "Event"):
            self.member_event_counts[feature.member] += 1
            if feature.notams:
                self.event_features_with_notam += 1
            else:
                self.event_features_without_notam += 1
        for alias in feature.aliases:
            self.reference_targets[alias].add(feature.member)
        identity = feature.identity
        if identity is not None:
            self.feature_identity_occurrences += 1
            self._limit(
                len(self.identities) + (identity not in self.identities) > self.limits.identities
            )
            digest = feature.digest.digest()
            prior = self.identities.get(identity)
            if prior is None:
                self.identities[identity] = {
                    "digests": {digest},
                    "members": {feature.member},
                    "kind": feature.kind,
                }
            else:
                self.repeated_occurrences += 1
                self.repeated_types[_safe_local(feature.kind[1], KNOWN_FEATURE_NAMES)] += 1
                self.repeated_type_conflicts += prior["kind"] != feature.kind
                self.repeated_exact += digest in prior["digests"]
                self.repeated_changed += digest not in prior["digests"]
                self.repeated_same_member += feature.member in prior["members"]
                self.repeated_cross_member += feature.member not in prior["members"]
                prior["digests"].add(digest)
                prior["members"].add(feature.member)
        self.current_feature = None

    def close(self):
        try:
            self.parser.Parse(b"", True)
        except InspectionError:
            raise
        except expat.ExpatError:
            raise InspectionError("MALFORMED_XML") from None
        if (
            self.stack
            or self.depth
            or self.current_member is not None
            or self.current_feature is not None
            or self.current_notam is not None
        ):
            raise InspectionError("MALFORMED_XML")
        if (
            self.root != (SOAP, "Envelope")
            or self.envelope_children != Counter({(SOAP, "Body"): 1})
            or self.body_payloads != Counter({(WFS, "FeatureCollection"): 1})
            or self.feature_collection_count != 1
            or self.members < 1
            or self.messages != self.members
        ):
            raise InspectionError("UNSUPPORTED_STRUCTURE")

    @staticmethod
    def _distribution(values, total):
        return dict(sorted(Counter(values.get(index, 0) for index in range(1, total + 1)).items()))

    def report(self):
        resolved = unresolved = internal = external = same = cross = 0
        for _, source_member, target, is_internal in self.references:
            internal += is_internal
            external += not is_internal
            members = self.reference_targets.get(target)
            if not members:
                unresolved += 1
            else:
                resolved += 1
                if source_member in members:
                    same += 1
                else:
                    cross += 1
        feature_counts = Counter()
        for qname, count in self.features.items():
            feature_counts[_safe_local(qname[1], KNOWN_FEATURE_NAMES)] += count
        return {
            "inspection_only": True,
            "format": "gzip-soap11-wfs20-aixm51",
            "xml": {
                "elements": self.elements,
                "max_depth": self.max_depth,
                "attributes": self.attributes,
                "text_characters": self.text_chars,
                "namespace_count": len(self.namespaces),
                "qname_count": len(self.qnames),
            },
            "records": {
                "wfs_members": self.members,
                "aixm_basic_messages": self.messages,
                "embedded_features": sum(self.features.values()),
                "feature_types": dict(feature_counts.most_common()),
                "features_per_member": dict(sorted(self.member_feature_counts.items())),
                "events_per_member": self._distribution(self.member_event_counts, self.members),
                "notams_per_member": self._distribution(self.member_notam_counts, self.members),
                "members_with_multiple_events": self.extra_event_members,
                "event_features_with_notam": self.event_features_with_notam,
                "event_features_without_notam": self.event_features_without_notam,
                "notam_field_cardinality": {
                    name: dict(sorted(counts.items()))
                    for name, counts in sorted(self.notam_field_cardinality.items())
                },
            },
            "identities": {
                "identifier_occurrences": self.feature_identity_occurrences,
                "distinct_identifiers": len(self.identities),
                "repeated_occurrences": self.repeated_occurrences,
                "repeated_exact": self.repeated_exact,
                "repeated_changed": self.repeated_changed,
                "repeated_same_member": self.repeated_same_member,
                "repeated_cross_member": self.repeated_cross_member,
                "repeated_feature_types": dict(self.repeated_types),
                "repeated_type_conflicts": self.repeated_type_conflicts,
            },
            "classifications": {
                "labels": dict(self.classifications),
                "per_member": self._distribution(self.member_classification_counts, self.members),
            },
            "translations": {
                "kinds": dict(self.translation_kinds),
                "shape_counts": {
                    "types=%d,simple=%d,formatted=%d" % key: value
                    for key, value in self.translation_shapes.items()
                },
                "per_member": self._distribution(self.member_translation_counts, self.members),
            },
            "effective_time_shapes": {
                name: dict(counts) for name, counts in self.effective_times.items()
            },
            "interpretations": dict(self.interpretations),
            "event_types": dict(self.event_types),
            "references": {
                "total": len(self.references),
                "internal_fragment": internal,
                "non_fragment": external,
                "resolved": resolved,
                "unresolved": unresolved,
                "same_member": same,
                "cross_member": cross,
                "relation_elements": dict(self.reference_relations),
            },
            "baseline_established": False,
            "watermark": None,
            "diagnostic": "BASELINE_CUTOVER_REQUIRED",
        }


class _SafetyScanner:
    def __init__(self, limits):
        self.limits = limits
        self.overlap = b""
        self.prefix = b""
        self.prefix_validated = False
        self.in_markup = False
        self.markup_bytes = 0
        self.quote = None

    def feed(self, chunk):
        if len(self.prefix) < 4096:
            self.prefix = (self.prefix + chunk)[:4096]
        if not self.prefix_validated:
            stripped = self.prefix.lstrip()
            partial_bom = len(stripped) < 3 and b"\xef\xbb\xbf".startswith(stripped)
            if stripped.startswith(b"\xef\xbb\xbf"):
                stripped = stripped[3:].lstrip()
            if (
                stripped.startswith((b"\xff\xfe", b"\xfe\xff"))
                or b"\x00" in self.prefix
                or (stripped and not stripped.startswith(b"<"))
            ):
                raise InspectionError("MALFORMED_XML")
            declaration_end = stripped.find(b"?>")
            declaration_pending = stripped.lower().startswith(b"<?xml") and declaration_end < 0
            if not (declaration_pending or partial_bom) or len(self.prefix) >= 4096:
                declaration = re.match(rb"\s*<\?xml\s+([^?]*)\?>", stripped, re.IGNORECASE)
                if declaration:
                    encoding = re.search(
                        rb"\bencoding\s*=\s*(['\"])([^'\"]+)\1", declaration.group(1), re.IGNORECASE
                    )
                    if encoding and encoding.group(2).upper().replace(b"_", b"-") not in (
                        b"UTF-8",
                        b"UTF8",
                    ):
                        raise InspectionError("MALFORMED_XML")
                self.prefix_validated = True
        scan = self.overlap + chunk
        if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", scan, re.IGNORECASE):
            raise InspectionError("UNSAFE_XML")
        self.overlap = scan[-64:]
        for byte in chunk:
            if not self.in_markup:
                if byte == 60:  # '<'
                    self.in_markup = True
                    self.markup_bytes = 1
                    self.quote = None
                continue
            self.markup_bytes += 1
            if self.markup_bytes > self.limits.markup_token_bytes:
                raise InspectionError("XML_LIMIT")
            if self.quote is not None:
                if byte == self.quote:
                    self.quote = None
            elif byte in (34, 39):
                self.quote = byte
            elif byte == 62:  # '>'
                self.in_markup = False
                self.markup_bytes = 0

    def finish(self):
        stripped = self.prefix.lstrip()
        if stripped.startswith(b"\xef\xbb\xbf"):
            stripped = stripped[3:].lstrip()
        if not self.prefix_validated or not stripped.startswith(b"<"):
            raise InspectionError("MALFORMED_XML")


def _stream_gzip(stream, parser, limits):
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    scanner = _SafetyScanner(limits)
    compressed = decompressed = 0

    def accept(output):
        nonlocal decompressed
        decompressed += len(output)
        if decompressed > limits.decompressed_bytes:
            raise InspectionError("DECOMPRESSED_LIMIT")
        scanner.feed(output)
        parser.feed(output)

    try:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            compressed += len(chunk)
            if compressed > limits.compressed_bytes:
                raise InspectionError("COMPRESSED_LIMIT")
            pending = chunk
            while pending:
                remaining = limits.decompressed_bytes - decompressed
                maximum = min(DECOMPRESS_OUTPUT_CHUNK, remaining + 1)
                output = decompressor.decompress(pending, maximum)
                pending = decompressor.unconsumed_tail
                if decompressor.unused_data:
                    raise InspectionError("GZIP_MEMBER_COUNT")
                if output:
                    accept(output)
                elif pending:
                    raise InspectionError("INVALID_GZIP")
        if not decompressor.eof:
            raise InspectionError("INVALID_GZIP")
        scanner.finish()
        parser.close()
        return compressed, decompressed
    except InspectionError:
        raise
    except zlib.error:
        raise InspectionError("INVALID_GZIP") from None


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError()
        value[key] = item
    return value


def _utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError()


def _load_receipt(path, attempt):
    try:
        with path.open("rb") as stream:
            before = _stat_marker(os.fstat(stream.fileno()))
            raw = stream.read(65537)
            after = _stat_marker(os.fstat(stream.fileno()))
        if len(raw) > 65536 or before != after or before != _stat_marker(path.stat()):
            raise ValueError()
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        stages = value.get("stage_receipts")
        continuation = value.get("content_continuation_used")
        expected_stages = ["auth", "initial-aixm-soap"] + (["content"] if continuation else [])
        if (
            not isinstance(value, dict)
            or value.get("schema") != 1
            or value.get("attempt") != attempt
            or type(value.get("bytes")) is not int
            or not re.fullmatch(r"[0-9a-f]{64}", value.get("sha256", ""))
            or type(value.get("initial_control_bytes")) is not int
            or value["initial_control_bytes"] < 1
            or not re.fullmatch(r"[0-9a-f]{64}", value.get("initial_control_sha256", ""))
            or type(continuation) is not bool
            or not isinstance(stages, list)
            or [item.get("stage") if isinstance(item, dict) else None for item in stages]
            != expected_stages
            or any(set(item) != {"stage", "reserved_utc"} for item in stages)
            or value.get("baseline_established") is not False
            or value.get("watermark") is not None
            or value.get("decoded") is not False
            or value.get("published") is not False
        ):
            raise ValueError()
        _utc(value["capture_started_utc"])
        _utc(value["capture_completed_utc"])
        for item in stages:
            _utc(item["reserved_utc"])
        return raw, value, before
    except Exception:
        raise InspectionError("RECEIPT_INVALID") from None


def inspect_evidence(
    evidence_dir, expected_sha256, *, expected_bytes, limits=InspectionLimits(), storage=None
):
    """Verify and inspect a protected evidence directory without modifying it."""
    limits.validate()
    root = Path(evidence_dir)
    if (
        not root.is_absolute()
        or not re.fullmatch(r"[0-9a-f]{32}", root.name)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "")
        or type(expected_bytes) is not int
        or expected_bytes < 1
    ):
        raise InspectionError("INVALID_REQUEST")
    artifact = root / "initial-load.bin"
    receipt_path = root / "receipt.json"
    try:
        storage = storage or platform_storage()
    except Exception:
        raise InspectionError("PRIVATE_ACCESS_REQUIRED") from None
    try:
        for path in (root, artifact, receipt_path):
            storage.validate_location(path)
            storage.verify_private(path)
    except InspectionError:
        raise
    except Exception:
        raise InspectionError("PRIVATE_ACCESS_REQUIRED") from None
    try:
        root_marker = _stat_marker(root.stat())
    except OSError:
        raise InspectionError("EVIDENCE_UNAVAILABLE") from None
    receipt_raw, receipt, receipt_marker = _load_receipt(receipt_path, root.name)
    if receipt["sha256"] != expected_sha256:
        raise InspectionError("EVIDENCE_HASH_MISMATCH")
    if receipt["bytes"] != expected_bytes:
        raise InspectionError("EVIDENCE_HASH_MISMATCH")
    try:
        with artifact.open("rb") as stream:
            before = _stat_marker(os.fstat(stream.fileno()))
            size, digest = _hash_stream(stream, limits.compressed_bytes)
            if size != receipt["bytes"] or digest != expected_sha256:
                raise InspectionError("EVIDENCE_HASH_MISMATCH")
            stream.seek(0)
            parser = _AggregateParser(limits)
            compressed, decompressed = _stream_gzip(stream, parser, limits)
            during = _stat_marker(os.fstat(stream.fileno()))
            stream.seek(0)
            final_size, final_digest = _hash_stream(stream, limits.compressed_bytes)
        after_path = _stat_marker(artifact.stat())
        for path in (root, artifact, receipt_path):
            storage.verify_private(path)
        final_receipt_raw, final_receipt, final_receipt_marker = _load_receipt(
            receipt_path, root.name
        )
        final_root_marker = _stat_marker(root.stat())
    except InspectionError:
        raise
    except OSError:
        raise InspectionError("EVIDENCE_UNAVAILABLE") from None
    except Exception:
        raise InspectionError("EVIDENCE_UNAVAILABLE") from None
    if (
        before != during
        or before != after_path
        or final_size != size
        or final_digest != digest
        or final_receipt_raw != receipt_raw
        or final_receipt != receipt
        or final_receipt_marker != receipt_marker
        or final_root_marker != root_marker
    ):
        raise InspectionError("EVIDENCE_CHANGED")
    report = parser.report()
    report["evidence"] = {
        "bytes": size,
        "sha256": digest,
        "receipt_consistent": True,
        "private_access_verified": True,
        "unchanged_during_inspection": True,
    }
    report["container"] = {
        "gzip_members": 1,
        "compressed_bytes": compressed,
        "decompressed_bytes": decompressed,
        "crc_and_size_validated": True,
        "trailing_bytes": 0,
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-bytes", required=True, type=int)
    args = parser.parse_args()
    try:
        report = inspect_evidence(
            args.evidence_dir, args.expected_sha256, expected_bytes=args.expected_bytes
        )
    except InspectionError as error:
        print(str(error))
        raise SystemExit(1) from None
    except Exception:
        print("LOCAL_FAILURE")
        raise SystemExit(1) from None
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
