"""Offline C070 registry validation and exact GeoJSON airport partitioning.

No network, FAA authentication, capture, scheduling, or publication is present.
"""

import copy
import json
from pathlib import Path
import re

from normalize_notam_snapshot import normalize


DEFAULT_MAX_INPUT_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024 * 1024
VERSIONED_REGISTRY = (
    Path(__file__).resolve().parents[2] / "docs/reference/c070-airport-registry.json"
)


def _encoded_size(value):
    return len(
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def c070_codes(path=None):
    path = path or Path(__file__).resolve().parents[2] / "docs/reference/c070-airports.csv"
    codes = [
        line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if (
        len(codes) != 130
        or len(set(codes)) != 130
        or any(not re.fullmatch(r"[A-Z]{3}", code) for code in codes)
    ):
        raise ValueError("invalid C070 Sheet1 column A export")
    return tuple(codes)


def load_registry(value, *, codes=None):
    """Validate an explicit mapping; never infer ICAO from an IATA code."""
    codes = tuple(codes or c070_codes())
    records = (
        value.get("airports") if isinstance(value, dict) and set(value) == {"airports"} else value
    )
    if isinstance(records, dict):
        # A pre-indexed dictionary is only a convenience representation; it
        # receives the same complete validation as an input list.
        if any(key != item.get("iata") for key, item in records.items() if isinstance(item, dict)):
            raise ValueError("registry dictionary key does not match IATA code")
        records = list(records.values())
    if not isinstance(records, list) or len(records) != len(codes):
        raise ValueError("registry must contain exactly the C070 airports")
    result, icaos = {}, set()
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("invalid registry airport")
        iata, icao, name, coverage = (
            item.get(key) for key in ("iata", "icao", "name", "source_coverage")
        )
        if (
            not isinstance(iata, str)
            or not isinstance(icao, str)
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(coverage, dict)
            or set(item) != {"iata", "icao", "name", "source_coverage"}
        ):
            raise ValueError("registry airport fields are incomplete")
        if not re.fullmatch(r"[A-Z]{3}", iata) or not re.fullmatch(r"[A-Z0-9]{4}", icao):
            raise ValueError("registry airport identifier is invalid")
        if iata in result:
            raise ValueError("duplicate registry IATA code")
        if icao in icaos:
            raise ValueError("duplicate registry ICAO code")
        if not coverage:
            raise ValueError("registry source coverage metadata is required")
        result[iata] = copy.deepcopy(item)
        icaos.add(icao)
    if set(result) != set(codes):
        raise ValueError("registry does not match C070 Sheet1 column A")
    return result


def load_versioned_registry(path=VERSIONED_REGISTRY):
    """Load the reviewed, version-controlled C070 registry."""
    return load_registry(json.loads(Path(path).read_text(encoding="utf-8")))


def _feature_codes(feature):
    try:
        record = feature["properties"]["coreNOTAMData"]["notam"]
    except (KeyError, TypeError):
        return None
    values = [record.get("location"), record.get("icaoLocation")]
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{3,4}", value) for value in values
    ):
        return None
    return tuple(values)


def features_from_capture(payload):
    """Accept the saved DOMESTIC bare array or the documented response envelope."""
    if isinstance(payload, list):
        return payload
    if (
        isinstance(payload, dict)
        and payload.get("status") == "Success"
        and payload.get("errors") in (None, [])
        and isinstance(payload.get("data"), dict)
        and isinstance(payload["data"].get("geojson"), list)
    ):
        return payload["data"]["geojson"]
    raise ValueError("bare feature array or successful inline GeoJSON response required")


def partition(
    payload,
    registry,
    *,
    retrieved_utc,
    max_input_bytes=DEFAULT_MAX_INPUT_BYTES,
    max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES,
):
    """Keep a feature only when both source identifiers match one registry airport."""
    # Always validate, including dictionaries returned by a previous validation
    # call: callers cannot bypass C070 coverage or uniqueness checks.
    registry = load_registry(registry)
    if not isinstance(retrieved_utc, str) or not retrieved_utc.strip():
        raise ValueError("capture retrieval timestamp is required")
    if (
        not isinstance(max_input_bytes, int)
        or not isinstance(max_output_bytes, int)
        or min(max_input_bytes, max_output_bytes) < 1
    ):
        raise ValueError("invalid partition byte limit")
    if _encoded_size(payload) > max_input_bytes:
        raise ValueError("capture exceeds input byte limit")
    features = features_from_capture(payload)
    # The saved DOMESTIC evidence has used both location/icaoLocation ordering
    # conventions.  Both explicit identifiers must nevertheless form exactly
    # one reviewed registry pair; one-field and mixed-airport records stay out.
    by_pair = {frozenset((entry["iata"], entry["icao"])): entry for entry in registry.values()}
    selected = {entry["icao"]: [] for entry in registry.values()}
    excluded = {"missing_or_invalid_identifiers": 0, "cross_airport_or_unregistered": 0}
    for index, feature in enumerate(features):
        pair = _feature_codes(feature)
        entry = by_pair.get(frozenset(pair)) if pair and pair[0] != pair[1] else None
        if entry is None:
            excluded[
                "missing_or_invalid_identifiers"
                if pair is None
                else "cross_airport_or_unregistered"
            ] += 1
            continue
        selected[entry["icao"]].append(copy.deepcopy(feature))
    airports = {}
    for entry in registry.values():
        icao = entry["icao"]
        # Reuse the established normalizer so source text, original features,
        # IDs, dates and representations follow the same reader contract.
        mapped = normalize(
            {"status": "Success", "data": {"geojson": selected[icao]}},
            airport=icao,
            retrieved_utc=retrieved_utc,
            query_context={"location": icao},
        )
        airport = mapped["airports"][icao]
        airport["warning"] = (
            "Filtered from a classification-wide DOMESTIC GeoJSON capture; "
            "not an FAA airport-specific location query. Completeness unknown."
        )
        airport["source_coverage"] = copy.deepcopy(entry["source_coverage"])
        airports[icao] = airport
    result = {
        "retrieved_utc": retrieved_utc,
        "airports": airports,
        "partition": {
            "coverage": "UNKNOWN",
            "excluded_record_counts": excluded,
            "input_record_count": len(features),
            "view": "FILTERED_AIRPORT_PARTITION",
            "source": "classification-wide DOMESTIC GeoJSON capture",
            "normalizer_input": "filtered view; not an FAA airport-specific location query",
        },
    }
    if _encoded_size(result) > max_output_bytes:
        raise ValueError("partition exceeds output byte limit")
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, help="reviewed registry JSON, local path")
    parser.add_argument("--capture", required=True, help="private local GeoJSON capture path")
    parser.add_argument("--retrieved-utc", required=True)
    args = parser.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    raw = Path(args.capture).read_bytes()
    if len(raw) > DEFAULT_MAX_INPUT_BYTES:
        parser.error("capture exceeds input byte limit")
    capture = json.loads(raw)
    print(
        json.dumps(
            partition(capture, registry, retrieved_utc=args.retrieved_utc), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
