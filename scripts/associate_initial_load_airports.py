"""Bounded offline C070 airport association for a preserved NMS Initial Load.

The utility performs no networking, acquisition, decoding activation, lifecycle
interpretation, runway matching, publication, or evidence mutation.  It accepts
only exact airport identifiers present in the reviewed C070 registry and reports
aggregate counts.  Callers may supply a record sink to retain the exact extracted
NOTAM scalars, source identifiers, timestamps, and translation representations in
private storage; the command-line report never emits those values.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
from xml.parsers import expat

from c070_notam_partition import load_registry, load_versioned_registry
from capture_storage import platform_storage
from inspect_initial_load_stream import (
    AIXM, EVENT, FNSE, GML, KNOWN_NAMESPACES, MESSAGE, SOAP, WFS, XLINK,
    InspectionError, InspectionLimits,
    _hash_stream, _load_receipt, _stat_marker, _stream_gzip,
)


NOTAM_SCALARS = frozenset((
    "number", "year", "issued", "location", "effectiveStart", "effectiveEnd",
    "text", "series", "scope", "traffic", "purpose", "selectionCode",
    "coordinates", "type",
))
TRANSLATION_SCALARS = frozenset(("type", "simpleText", "formattedText"))


@dataclass
class _Frame:
    qname: tuple[str, str]
    retained: list[str] | None = None
    chars: int = 0


@dataclass
class _Feature:
    kind: tuple[str, str]
    depth: int
    aliases: set[str] = field(default_factory=set)
    gml_ids: set[str] = field(default_factory=set)
    identifiers: set[str] = field(default_factory=set)
    event_refs: set[str] = field(default_factory=set)
    designators: list[str] = field(default_factory=list)
    notices: list[dict] = field(default_factory=list)
    translations: list[dict] = field(default_factory=list)
    classifications: list[str] = field(default_factory=list)
    last_updated: list[str] = field(default_factory=list)


def _target(value):
    return value[1:] if value.startswith("#") else value


def _split(name):
    try:
        namespace, local = name.split("}", 1)
        if not namespace or not local:
            raise ValueError()
        return namespace, local
    except (AttributeError, ValueError):
        raise InspectionError("UNSUPPORTED_NAMESPACE") from None


class _AssociationParser:
    def __init__(self, registry, limits, record_sink=None):
        self.registry = registry
        self.limits = limits
        self.record_sink = record_sink
        self.code_index = {}
        self.icao_index = {}
        for entry in registry.values():
            self.icao_index[entry["icao"]] = entry
            for code in (entry["iata"], entry["icao"]):
                if code in self.code_index:
                    raise InspectionError("INVALID_REQUEST")
                self.code_index[code] = entry
        self.parser = expat.ParserCreate(encoding="UTF-8", namespace_separator="}")
        self.parser.buffer_text = False
        self.parser.StartElementHandler = self._start
        self.parser.EndElementHandler = self._end
        self.parser.CharacterDataHandler = self._characters
        self.parser.StartDoctypeDeclHandler = self._unsafe
        self.parser.EntityDeclHandler = self._unsafe
        self.parser.ExternalEntityRefHandler = self._external
        self.parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        self.stack = []
        self.depth = self.elements = self.attributes = self.attribute_chars = 0
        self.text_chars = 0
        self.members = self.features = 0
        self.root = None
        self.namespaces = Counter()
        self.qnames = Counter()
        self.envelope_children = Counter()
        self.body_payloads = Counter()
        self.feature_collections = 0
        self.current_member = None
        self.member_elements = self.member_features = 0
        self.member_text = 0
        self.current_feature = None
        self.current_notice = None
        self.current_translation = None
        self.report_counts = Counter()
        self.airport_counts = Counter()
        self.source_counts = Counter()
        self.seen_notice_ids = set()

    def _limit(self, condition):
        if condition:
            raise InspectionError("XML_LIMIT")

    def _unsafe(self, *_args):
        raise InspectionError("UNSAFE_XML")

    def _external(self, *_args):
        raise InspectionError("UNSAFE_XML")

    def feed(self, chunk):
        try:
            self.parser.Parse(chunk, False)
        except InspectionError:
            raise
        except expat.ExpatError:
            raise InspectionError("MALFORMED_XML") from None
        except Exception:
            raise InspectionError("MALFORMED_XML") from None

    def _start(self, name, attributes):
        qname = _split(name)
        if qname[0] not in KNOWN_NAMESPACES:
            raise InspectionError("UNSUPPORTED_NAMESPACE")
        parent = self.stack[-1].qname if self.stack else None
        self.depth += 1
        self.elements += 1
        self.attributes += len(attributes)
        self.attribute_chars += sum(len(str(key)) + len(str(value))
                                    for key, value in attributes.items())
        self.namespaces[qname[0]] += 1
        self.qnames[qname] += 1
        self._limit(self.depth > self.limits.depth or self.elements > self.limits.elements
                    or self.attributes > self.limits.attributes
                    or self.attribute_chars > self.limits.attribute_chars
                    or len(self.namespaces) > self.limits.namespaces
                    or len(self.qnames) > self.limits.qnames)
        retain = False
        if qname[0] == EVENT:
            retain = ((self.current_notice is not None and qname[1] in NOTAM_SCALARS)
                      or (self.current_translation is not None
                          and qname[1] in TRANSLATION_SCALARS))
        if self.current_feature is not None and qname in ((GML, "identifier"),
                                                           (AIXM, "designator"),
                                                           (FNSE, "classification"),
                                                           (FNSE, "lastUpdated")):
            retain = True
        self.stack.append(_Frame(qname, [] if retain else None))
        if self.root is None:
            self.root = qname
        elif self.depth == 2:
            self.envelope_children[qname] += 1
        elif self.depth == 3 and parent == (SOAP, "Body"):
            self.body_payloads[qname] += 1
        if qname == (WFS, "FeatureCollection"):
            self.feature_collections += 1
        if qname == (WFS, "member"):
            self.members += 1
            self._limit(self.current_member is not None
                        or self.members > self.limits.wfs_members)
            self.current_member = []
            self.member_elements = self.member_features = self.member_text = 0
        if self.current_member is not None:
            self.member_elements += 1
            self._limit(self.member_elements > self.limits.per_member_elements)
        if parent == (MESSAGE, "hasMember"):
            self.features += 1
            self.member_features += 1
            self._limit(self.current_member is None or self.current_feature is not None
                        or self.features > self.limits.features
                        or self.member_features > self.limits.per_member_features)
            aliases = set()
            gml_id = attributes.get(GML + "}id")
            if isinstance(gml_id, str) and gml_id:
                aliases.add(gml_id)
            self.current_feature = _Feature(qname, self.depth, aliases=aliases,
                                            gml_ids=set(aliases))
        if self.current_feature is not None and qname == (EVENT, "theEvent"):
            href = attributes.get(XLINK + "}href")
            if isinstance(href, str) and href:
                self.current_feature.event_refs.add(_target(href))
                self.source_counts["all_feature_event_relationships_seen"] += 1
                if self.current_feature.kind == (AIXM, "AirportHeliport"):
                    self.source_counts["airport_event_relationships_seen"] += 1
        if qname == (EVENT, "NOTAM"):
            if self.current_notice is not None:
                raise InspectionError("UNSUPPORTED_STRUCTURE")
            self.current_notice = {"fields": {}, "translations": []}
        if qname == (EVENT, "NOTAMTranslation"):
            if self.current_translation is not None:
                raise InspectionError("UNSUPPORTED_STRUCTURE")
            self.current_translation = {}

    def _characters(self, value):
        if not value or not self.stack:
            return
        frame = self.stack[-1]
        frame.chars += len(value)
        self.text_chars += len(value)
        if self.current_member is not None:
            self.member_text += len(value)
        self._limit(frame.chars > self.limits.scalar_chars
                    or self.text_chars > self.limits.text_chars
                    or self.member_text > self.limits.per_member_text_chars)
        if frame.retained is not None:
            frame.retained.append(value)

    def _end(self, name):
        qname = _split(name)
        if not self.stack or self.stack[-1].qname != qname:
            raise InspectionError("UNSUPPORTED_STRUCTURE")
        frame = self.stack[-1]
        value = "".join(frame.retained) if frame.retained is not None else None
        if value is not None and self.current_feature is not None:
            if qname == (GML, "identifier") and value.strip():
                self.current_feature.aliases.add(value.strip())
                self.current_feature.identifiers.add(value.strip())
            elif (qname == (AIXM, "designator")
                  and self.current_feature.kind == (AIXM, "AirportHeliport")
                  and value.strip()):
                self.current_feature.designators.append(value.strip())
            elif qname == (FNSE, "classification") and value.strip():
                self.current_feature.classifications.append(value)
            elif qname == (FNSE, "lastUpdated") and value.strip():
                self.current_feature.last_updated.append(value)
        if value is not None and qname[0] == EVENT:
            if self.current_translation is not None and qname[1] in TRANSLATION_SCALARS:
                self.current_translation.setdefault(qname[1], []).append(value)
            elif self.current_notice is not None and qname[1] in NOTAM_SCALARS:
                self.current_notice["fields"].setdefault(qname[1], []).append(value)
        if qname == (EVENT, "NOTAMTranslation"):
            if self.current_feature is None or self.current_translation is None:
                raise InspectionError("UNSUPPORTED_STRUCTURE")
            self.current_feature.translations.append(self.current_translation)
            self.current_translation = None
        if qname == (EVENT, "NOTAM"):
            if self.current_feature is None or self.current_notice is None:
                raise InspectionError("UNSUPPORTED_STRUCTURE")
            self.current_feature.notices.append(self.current_notice)
            self.current_notice = None
        if (self.current_feature is not None and qname == self.current_feature.kind
                and self.depth == self.current_feature.depth):
            self.current_member.append(self.current_feature)
            self.current_feature = None
        if qname == (WFS, "member"):
            self._finish_member()
            self.current_member = None
            self.member_elements = self.member_features = self.member_text = 0
        self.stack.pop()
        self.depth -= 1

    def _match_codes(self, values, field):
        matches = set()
        for raw in values:
            self.source_counts[field + "_values"] += 1
            normalized = raw.strip().upper()
            entry = self.code_index.get(normalized)
            if entry is None:
                self.source_counts[field + "_unregistered"] += 1
            else:
                self.source_counts[field + "_c070_matches"] += 1
                matches.add(entry["icao"])
        return matches

    def _finish_member(self):
        events = [feature for feature in self.current_member if feature.kind == (EVENT, "Event")]
        airports = [feature for feature in self.current_member
                    if feature.kind == (AIXM, "AirportHeliport")]
        event_aliases = {alias for event in events for alias in event.aliases}
        for airport in airports:
            unresolved = airport.event_refs - event_aliases
            self.source_counts["resolved_airport_event_relationships"] += len(
                airport.event_refs & event_aliases)
            self.source_counts["unresolved_airport_event_relationships"] += len(unresolved)
        for event in events:
            for notice in event.notices:
                notice["translations"].extend(event.translations)
            linked = [airport for airport in airports if airport.event_refs & event.aliases]
            direct = self._match_codes(
                [value for airport in linked for value in airport.designators],
                "airport_designator")
            for notice in event.notices:
                self._finish_notice(event, notice, direct)

    def _finish_notice(self, event, notice, direct):
        self.report_counts["total_notams"] += 1
        locations = notice["fields"].get("location", [])
        location = self._match_codes(locations, "notam_location")
        duplicate_evidence = len(location & direct)
        self.report_counts["duplicate_association_evidence"] += duplicate_evidence
        conflict = bool(location and direct and location.isdisjoint(direct))
        if conflict:
            accepted = set()
            self.report_counts["conflicting_notams"] += 1
        else:
            accepted = location | direct
        if len(accepted) > 1:
            self.report_counts["multiple_airport_notams"] += 1
        if accepted:
            self.report_counts["associated_notams"] += 1
            for icao in accepted:
                self.airport_counts[icao] += 1
        else:
            self.report_counts["unresolved_notams"] += 1
        identifiers = sorted(event.aliases)
        if identifiers:
            digest = hashlib.sha256("\0".join(identifiers).encode("utf-8")).digest()
            if digest in self.seen_notice_ids:
                self.report_counts["duplicate_source_identifiers"] += 1
            else:
                self._limit(len(self.seen_notice_ids) + 1 > self.limits.identities)
                self.seen_notice_ids.add(digest)
        else:
            self.report_counts["notams_without_event_identifier"] += 1
        if self.record_sink is not None:
            evidence = {}
            for icao in sorted(location | direct):
                kinds = []
                if icao in location:
                    kinds.append("event:NOTAM/event:location")
                if icao in direct:
                    kinds.append("AirportHeliport.designator+event:theEvent")
                entry = self.icao_index[icao]
                evidence[icao] = {"iata": entry["iata"], "source_fields": kinds}
            self.record_sink({
                "source_event_aliases": identifiers,
                "source_gml_ids": sorted(event.gml_ids),
                "source_identifiers": sorted(event.identifiers),
                "notam": notice["fields"],
                "representations": notice["translations"],
                "classifications": list(event.classifications),
                "source_last_updated": list(event.last_updated),
                "association_evidence": evidence,
                "accepted_airports": sorted(accepted),
                "status": "conflicting" if conflict else ("associated" if accepted else "unresolved"),
            })

    def close(self):
        try:
            self.parser.Parse(b"", True)
        except InspectionError:
            raise
        except expat.ExpatError:
            raise InspectionError("MALFORMED_XML") from None
        if (self.stack or self.depth or self.current_member is not None
                or self.current_feature is not None or self.current_notice is not None
                or self.current_translation is not None):
            raise InspectionError("MALFORMED_XML")
        if (self.root != (SOAP, "Envelope")
                or self.envelope_children != Counter({(SOAP, "Body"): 1})
                or self.body_payloads != Counter({(WFS, "FeatureCollection"): 1})
                or self.feature_collections != 1 or self.members < 1
                or self.report_counts["total_notams"] < 1):
            raise InspectionError("UNSUPPORTED_STRUCTURE")

    def report(self):
        return {
            "inspection_only": True,
            "association_basis": [
                "exact reviewed C070 match of event:NOTAM/event:location",
                "exact reviewed C070 AirportHeliport designator linked by event:theEvent",
            ],
            "runway_relationships_used": False,
            "total_notams_inspected": self.report_counts["total_notams"],
            "notams_associated_with_c070_airports": self.report_counts["associated_notams"],
            "c070_airports_represented": len(self.airport_counts),
            "unmatched_or_unresolved_notams": self.report_counts["unresolved_notams"],
            "conflicting_notams": self.report_counts["conflicting_notams"],
            "multiple_airport_notams": self.report_counts["multiple_airport_notams"],
            "duplicate_association_evidence": self.report_counts["duplicate_association_evidence"],
            "duplicate_source_identifiers": self.report_counts["duplicate_source_identifiers"],
            "per_airport_notice_counts": dict(sorted(self.airport_counts.items())),
            "source_fields_and_relationships": dict(sorted(self.source_counts.items())),
            "baseline_established": False,
            "watermark": None,
            "diagnostic": "BASELINE_CUTOVER_REQUIRED",
        }


def associate_evidence(evidence_dir, expected_sha256, *, expected_bytes,
                       registry=None, limits=InspectionLimits(), storage=None,
                       record_sink=None):
    """Verify and stream one protected artifact, returning privacy-safe aggregates."""
    limits.validate()
    registry = load_versioned_registry() if registry is None else load_registry(registry)
    root = Path(evidence_dir)
    if (not root.is_absolute() or not re.fullmatch(r"[0-9a-f]{32}", root.name)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "")
            or type(expected_bytes) is not int or expected_bytes < 1):
        raise InspectionError("INVALID_REQUEST")
    artifact = root / "initial-load.bin"
    receipt_path = root / "receipt.json"
    try:
        storage = storage or platform_storage()
        for path in (root, artifact, receipt_path):
            storage.validate_location(path)
            storage.verify_private(path)
        root_marker = _stat_marker(root.stat())
        receipt_raw, receipt, receipt_marker = _load_receipt(receipt_path, root.name)
        if receipt["sha256"] != expected_sha256 or receipt["bytes"] != expected_bytes:
            raise InspectionError("EVIDENCE_HASH_MISMATCH")
        with artifact.open("rb") as stream:
            before = _stat_marker(os.fstat(stream.fileno()))
            size, digest = _hash_stream(stream, limits.compressed_bytes)
            if size != expected_bytes or digest != expected_sha256:
                raise InspectionError("EVIDENCE_HASH_MISMATCH")
            stream.seek(0)
            parser = _AssociationParser(registry, limits, record_sink=record_sink)
            compressed, decompressed = _stream_gzip(stream, parser, limits)
            during = _stat_marker(os.fstat(stream.fileno()))
            stream.seek(0)
            final_size, final_digest = _hash_stream(stream, limits.compressed_bytes)
        after = _stat_marker(artifact.stat())
        for path in (root, artifact, receipt_path):
            storage.verify_private(path)
        final_raw, final_receipt, final_marker = _load_receipt(receipt_path, root.name)
        if (before != during or before != after or final_size != size or final_digest != digest
                or final_raw != receipt_raw or final_receipt != receipt
                or final_marker != receipt_marker or _stat_marker(root.stat()) != root_marker):
            raise InspectionError("EVIDENCE_CHANGED")
    except InspectionError:
        raise
    except Exception:
        raise InspectionError("EVIDENCE_UNAVAILABLE") from None
    report = parser.report()
    report["evidence"] = {"bytes": size, "sha256_verified": True,
                          "private_access_verified": True,
                          "unchanged_during_inspection": True}
    report["container"] = {"gzip_members": 1, "compressed_bytes": compressed,
                           "decompressed_bytes": decompressed,
                           "crc_and_size_validated": True, "trailing_bytes": 0}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-bytes", required=True, type=int)
    args = parser.parse_args()
    try:
        report = associate_evidence(args.evidence_dir, args.expected_sha256,
                                    expected_bytes=args.expected_bytes)
    except InspectionError as error:
        print(str(error))
        raise SystemExit(1) from None
    except Exception:
        print("LOCAL_FAILURE")
        raise SystemExit(1) from None
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
