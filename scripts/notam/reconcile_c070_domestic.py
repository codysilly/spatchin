"""Reconcile one saved DOMESTIC GeoJSON capture against the C070 registry.

This is intentionally local-file-only.  It neither contacts a provider nor writes
inside the checkout.  Its JSON outputs are private review artifacts, not a
publication action.  Empty airport collections always retain UNKNOWN coverage.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from c070_notam_partition import (
    DEFAULT_MAX_INPUT_BYTES,
    c070_codes,
    features_from_capture,
    load_registry,
)
from normalize_notam_snapshot import normalize


REQUIRED_NOTICE_FIELDS = (
    "id",
    "number",
    "text",
    "issued",
    "effectiveStart",
    "effectiveEnd",
    "lastUpdated",
)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024 * 1024
HISTORICAL_CAPTURE_FEATURE_COUNT = 21024
HISTORICAL_C070_MATCH_COUNT = 3084
PUBLICATION_FIELDS = frozenset(
    (
        "id",
        "number",
        "year",
        "text",
        "issued",
        "effectiveStart",
        "effectiveEnd",
        "lastUpdated",
        "retrieved_utc",
        "formatted_texts",
    )
)


def _json_size(value):
    return len(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _finite_json(value):
    """Reject values JSON would otherwise silently serialize as nonstandard."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("nonfinite JSON value")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("invalid JSON object key")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _utc_timestamp(value):
    if not _nonempty_string(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    except ValueError:
        return False


def _record(feature):
    try:
        value = feature["properties"]["coreNOTAMData"]["notam"]
    except (KeyError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _classify(record, by_code, by_pair):
    """Return (airport ICAO or None, mutually-exclusive exception category)."""
    if record is None:
        return None, "missing_or_invalid_identifiers"
    values = [record.get("location"), record.get("icaoLocation")]
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{3,4}", value) for value in values
    ):
        return None, "missing_or_invalid_identifiers"
    first, second = values
    # The provider has used either ordering.  Require the exact reviewed pair,
    # never a prefix-derived association.
    entry = by_pair.get(frozenset((first, second))) if first != second else None
    if entry is not None:
        return entry["icao"], None
    first_entry, second_entry = by_code.get(first), by_code.get(second)
    if first_entry is not None or second_entry is not None:
        return None, "conflicting_identifiers"
    return None, "outside_c070"


def _candidate_notice(notice):
    """Keep display fields and supplied representations, not raw feature evidence."""
    keep = (
        "id",
        "number",
        "text",
        "issued",
        "effectiveStart",
        "effectiveEnd",
        "lastUpdated",
        "source",
        "retrieved_utc",
        "formatted_texts",
        "warnings",
        "reported_relationships",
    )
    return {field: copy.deepcopy(notice[field]) for field in keep if field in notice}


def reconcile(payload, registry, *, retrieved_utc, max_input_bytes=DEFAULT_MAX_INPUT_BYTES):
    """Return private evidence, reader-compatible candidate, and safe audit summary."""
    if not _utc_timestamp(retrieved_utc):
        raise ValueError("UTC capture retrieval timestamp is required")
    _finite_json(payload)
    if _json_size(payload) > max_input_bytes:
        raise ValueError("capture exceeds input byte limit")
    registry = load_registry(registry)
    features = features_from_capture(payload)
    by_code = {
        code: entry for entry in registry.values() for code in (entry["iata"], entry["icao"])
    }
    by_pair = {frozenset((entry["iata"], entry["icao"])): entry for entry in registry.values()}
    assigned = {entry["icao"]: [] for entry in registry.values()}
    evidence = {entry["icao"]: [] for entry in registry.values()}
    excluded_evidence = []
    excluded = {
        "missing_or_invalid_identifiers": 0,
        "conflicting_identifiers": 0,
        "outside_c070": 0,
    }
    source_ids, missing_fields = {}, {field: 0 for field in REQUIRED_NOTICE_FIELDS}
    records_with_missing_fields = 0

    for index, feature in enumerate(features):
        record = _record(feature)
        airport, category = _classify(record, by_code, by_pair)
        if category:
            excluded[category] += 1
            excluded_evidence.append(
                {
                    "source_index": index,
                    "category": category,
                    "original_feature": copy.deepcopy(feature),
                }
            )
            continue
        assert record is not None
        assigned[airport].append(copy.deepcopy(feature))
        evidence[airport].append(
            {"source_index": index, "original_feature": copy.deepcopy(feature)}
        )
        absent = False
        for field in REQUIRED_NOTICE_FIELDS:
            if not _nonempty_string(record.get(field)):
                missing_fields[field] += 1
                absent = True
        if absent:
            records_with_missing_fields += 1
        if _nonempty_string(record.get("id")):
            source_ids.setdefault(record["id"], []).append(index)

    airports, candidate_evidence = {}, {}
    normalization_failures = []
    for entry in registry.values():
        icao = entry["icao"]
        try:
            normalized = normalize(
                {"status": "Success", "data": {"geojson": assigned[icao]}},
                airport=icao,
                retrieved_utc=retrieved_utc,
                query_context={"location": icao},
            )
            notices = [
                _candidate_notice(value) for value in normalized["airports"][icao]["notices"]
            ]
        except (TypeError, ValueError, KeyError):
            # This should not occur for a valid envelope, but must not silently
            # turn a bad source into an apparently clear airport.
            notices = []
            normalization_failures.append(icao)
        airports[icao] = {
            "notices": notices,
            "completeness": "UNKNOWN",
            "warning": (
                "Filtered from a classification-wide DOMESTIC GeoJSON capture; "
                "not an FAA airport-specific location query. Completeness unknown."
            ),
            "source_coverage": copy.deepcopy(entry["source_coverage"]),
        }
        candidate_evidence[icao] = evidence[icao]

    duplicate_groups = sum(1 for indexes in source_ids.values() if len(indexes) > 1)
    duplicate_records = sum(len(indexes) for indexes in source_ids.values() if len(indexes) > 1)
    per_airport = {entry["icao"]: len(assigned[entry["icao"]]) for entry in registry.values()}
    input_count = len(features)
    assigned_count = sum(per_airport.values())
    excluded_count = sum(excluded.values())
    if input_count != assigned_count + excluded_count:
        raise ValueError("input accounting mismatch")
    summary = {
        "schema_version": 1,
        "capture_classification": "DOMESTIC",
        "coverage": "UNKNOWN",
        "retrieved_utc": retrieved_utc,
        "input_record_count": input_count,
        "assigned_record_count": assigned_count,
        "excluded_record_count": excluded_count,
        "accounting_reconciled": True,
        "per_airport_counts": per_airport,
        "airports_with_matched_notices": sum(count > 0 for count in per_airport.values()),
        "airports_with_zero_matched_records": [
            icao for icao, count in per_airport.items() if not count
        ],
        "exception_counts": {
            **excluded,
            "duplicate_source_id_groups": duplicate_groups,
            "records_with_duplicate_source_ids": duplicate_records,
            "records_with_missing_required_fields": records_with_missing_fields,
            "normalization_failures": len(normalization_failures),
        },
        "missing_required_field_counts": missing_fields,
        "normalization_failure_airports": normalization_failures,
        "comparison_to_historical_c070_matches": assigned_count - HISTORICAL_C070_MATCH_COUNT,
        "historical_c070_candidate_match_count": HISTORICAL_C070_MATCH_COUNT,
        "historical_total_feature_count": HISTORICAL_CAPTURE_FEATURE_COUNT,
        "comparison_to_historical_total_features": input_count - HISTORICAL_CAPTURE_FEATURE_COUNT,
        "comparison_note": (
            "C070 matched records are compared with the historical 3,084 "
            "candidate matches. Raw input features are separately compared "
            "with the historical 21,024 total features; neither count is forced."
        ),
    }
    candidate = {
        "retrieved_utc": retrieved_utc,
        "airports": airports,
        "partition": {
            "coverage": "UNKNOWN",
            "view": "FILTERED_AIRPORT_PARTITION",
            "source": "classification-wide DOMESTIC GeoJSON capture",
            "normalizer_input": "filtered view; not an FAA airport-specific location query",
            "redistribution_notice": "NMS service response; do not characterize redistributed notices as FAA data.",
        },
        "reconciliation": {
            "state": "PRIVATE_REVIEW_ONLY",
            "publication_status": "NOT_PUBLICATION_READY",
            "source_label": "NMS service response",
            "automatic_updates": False,
        },
    }
    private_evidence = {
        "schema_version": 1,
        "retrieved_utc": retrieved_utc,
        "source_association": "classification-wide DOMESTIC GeoJSON capture",
        "assigned_source_evidence": candidate_evidence,
        "excluded_source_evidence": excluded_evidence,
        "duplicate_source_id_indexes": [
            indexes for indexes in source_ids.values() if len(indexes) > 1
        ],
        "original_capture": copy.deepcopy(payload),
    }
    return summary, candidate, private_evidence


def validate_private_candidate(candidate):
    """Validate the candidate's reader-compatible shape without approving publication.

    Public conversion is intentionally a separate reviewed step.  This validator
    permits private review fields, but makes sure their display projection fits
    the checked-in snapshot reader contract.
    """
    if (
        not isinstance(candidate, dict)
        or candidate.get("reconciliation", {}).get("publication_status") != "NOT_PUBLICATION_READY"
    ):
        raise ValueError("private candidate status is required")
    if "publication" in candidate:
        raise ValueError("private candidate must not claim publication metadata")
    if not _utc_timestamp(candidate.get("retrieved_utc")) or not isinstance(
        candidate.get("airports"), dict
    ):
        raise ValueError("invalid private candidate envelope")
    projected = {"retrieved_utc": candidate["retrieved_utc"], "airports": {}}
    for airport, collection in candidate["airports"].items():
        if (
            not re.fullmatch(r"[A-Z0-9]{3,4}", airport)
            or not isinstance(collection, dict)
            or not isinstance(collection.get("notices"), list)
        ):
            raise ValueError("invalid private candidate airport")
        notices = []
        for notice in collection["notices"]:
            if not isinstance(notice, dict):
                raise ValueError("invalid private candidate notice")
            display = {
                key: copy.deepcopy(value)
                for key, value in notice.items()
                if key in PUBLICATION_FIELDS
            }
            if any(
                value is not None and not isinstance(value, str)
                for key, value in display.items()
                if key != "formatted_texts"
            ):
                raise ValueError("invalid private candidate display field")
            if "formatted_texts" in display and (
                not isinstance(display["formatted_texts"], list)
                or any(
                    not isinstance(item, dict) or not isinstance(item.get("text"), str)
                    for item in display["formatted_texts"]
                )
            ):
                raise ValueError("invalid private candidate representation")
            notices.append(display)
        projected["airports"][airport] = {
            "notices": notices,
            "completeness": collection.get("completeness", "UNKNOWN"),
        }
    return projected


def validate_publication_conversion(candidate, publication):
    """Validate an explicit review-only conversion request; never write it publicly."""
    projected = validate_private_candidate(candidate)
    if not isinstance(publication, dict) or set(publication) != {
        "mode",
        "automatic_updates",
        "source_reference",
    }:
        raise ValueError("explicit publication conversion metadata is required")
    if (
        not isinstance(publication["mode"], str)
        or publication["automatic_updates"] is not False
        or not isinstance(publication["source_reference"], str)
    ):
        raise ValueError("invalid publication conversion metadata")
    projected["publication"] = copy.deepcopy(publication)
    return projected


def _read_json(path, limit):
    raw = Path(path).read_bytes()
    if len(raw) > limit:
        raise ValueError("capture exceeds input byte limit")

    def reject_constant(_value):
        raise ValueError("invalid JSON constant")

    value = json.loads(raw, parse_constant=reject_constant)
    _finite_json(value)
    return value


def _new_private_path(value):
    path = Path(value).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("outputs must be outside the repository")
    if path.exists():
        raise ValueError("outputs must be new files")
    return path


def _encoded_json(value):
    _finite_json(value)
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def _bounded_outputs(summary, report, candidate, evidence, max_output_bytes):
    if not isinstance(max_output_bytes, int) or max_output_bytes < 1:
        raise ValueError("invalid output byte limit")
    validate_private_candidate(candidate)
    values = (
        _encoded_json(summary),
        report.encode("utf-8"),
        _encoded_json(candidate),
        _encoded_json(evidence),
    )
    completion = _encoded_json(
        {
            "schema_version": 1,
            "state": "COMPLETE",
            "artifacts": [hashlib.sha256(body).hexdigest() for body in values],
        }
    )
    if any(len(value) > max_output_bytes for value in values + (completion,)):
        raise ValueError("reconciliation output exceeds byte limit")
    return values, completion


def _write_staged(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def _commit_bundle(outputs, bodies, completion, completion_body):
    """Stage each item and publish a completion marker only after all artifacts land."""
    staged = []
    try:
        for final, body in zip(outputs, bodies):
            handle = tempfile.NamedTemporaryFile(
                prefix=".spa19-", suffix=".tmp", dir=final.parent, delete=False
            )
            staged_path = Path(handle.name)
            try:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            staged.append((staged_path, final))
        for source, final in staged:
            os.replace(source, final)
        _write_staged(completion, completion_body)
    finally:
        for source, _final in staged:
            try:
                source.unlink()
            except FileNotFoundError:
                pass


def _report(summary):
    exceptions = summary["exception_counts"]
    return "\n".join(
        (
            "Spatchin C070 DOMESTIC offline reconciliation",
            "Coverage: UNKNOWN; locally filtered, not airport-specific responses.",
            f"Input records: {summary['input_record_count']}",
            f"Assigned: {summary['assigned_record_count']}; excluded: {summary['excluded_record_count']}",
            "Exceptions: " + ", ".join(f"{key}={value}" for key, value in exceptions.items()),
            f"Airports with notices: {summary['airports_with_matched_notices']}/130; "
            f"zero matched: {len(summary['airports_with_zero_matched_records'])}",
            f"Difference from historical 3,084 C070 candidate matches: {summary['comparison_to_historical_c070_matches']}",
            f"Difference from historical 21,024 total features: {summary['comparison_to_historical_total_features']}",
            "Every input record is accounted for. No lifecycle, cancellation, runway, or clear-status inference was made.",
            "",
        )
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, help="saved local JSON capture, never a URL")
    parser.add_argument("--retrieved-utc", required=True, help="original UTC retrieval timestamp")
    parser.add_argument("--summary", required=True, help="new private summary JSON path")
    parser.add_argument("--report", required=True, help="new private text report path")
    parser.add_argument(
        "--candidate", required=True, help="new private reader-compatible candidate path"
    )
    parser.add_argument("--evidence", required=True, help="new private full-evidence JSON path")
    parser.add_argument("--completion", required=True, help="new private completion marker path")
    parser.add_argument("--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES)
    parser.add_argument("--max-output-bytes", type=int, default=DEFAULT_MAX_OUTPUT_BYTES)
    args = parser.parse_args(argv)
    try:
        if args.max_input_bytes < 1:
            raise ValueError("invalid input byte limit")
        outputs = [
            _new_private_path(value)
            for value in (args.summary, args.report, args.candidate, args.evidence)
        ]
        completion = _new_private_path(args.completion)
        if len(set(outputs + [completion])) != len(outputs) + 1:
            raise ValueError("output paths must be distinct")
        payload = _read_json(args.capture, args.max_input_bytes)
        registry = json.loads(
            (ROOT / "docs/reference/c070-airport-registry.json").read_text(encoding="utf-8")
        )
        summary, candidate, evidence = reconcile(
            payload,
            registry,
            retrieved_utc=args.retrieved_utc,
            max_input_bytes=args.max_input_bytes,
        )
        report = _report(summary)
        bodies, completion_body = _bounded_outputs(
            summary, report, candidate, evidence, args.max_output_bytes
        )
        _commit_bundle(outputs, bodies, completion, completion_body)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        parser.error(
            "offline reconciliation failed; check local input, timestamp, and new private output paths"
        )
    print("Offline reconciliation artifacts written. Coverage remains UNKNOWN.")
    return 0


if __name__ == "__main__":
    main()
