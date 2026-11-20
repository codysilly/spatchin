"""Read the approved C070 IATA/ICAO mapping without network access.

The FAA NASR-backed registry is a station allowlist, not proof that a
particular weather product is available at every listed airport.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs/reference/c070-airport-registry.json"
CODES_PATH = ROOT / "docs/reference/c070-airports.csv"
EXPECTED_COUNT = 130


def load_c070_stations(registry_path=REGISTRY_PATH, codes_path=CODES_PATH):
    """Return {IATA: ICAO}; reject incomplete, duplicate, or changed registries."""
    codes = [line.strip() for line in Path(codes_path).read_text(encoding="utf-8-sig").splitlines()
             if line.strip()]
    if len(codes) != EXPECTED_COUNT or len(set(codes)) != EXPECTED_COUNT:
        raise ValueError("C070 airport list is missing airports or contains duplicates")
    if any(not re.fullmatch(r"[A-Z]{3}", code) for code in codes):
        raise ValueError("C070 airport list contains an invalid IATA code")

    document = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    entries = document.get("airports") if isinstance(document, dict) else None
    if not isinstance(entries, list) or len(entries) != EXPECTED_COUNT:
        raise ValueError("C070 registry must contain exactly 130 airports")

    stations = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("C070 registry contains an invalid airport record")
        iata, icao = item.get("iata"), item.get("icao")
        if not isinstance(iata, str) or not re.fullmatch(r"[A-Z]{3}", iata):
            raise ValueError("C070 registry contains an invalid IATA identifier")
        if not isinstance(icao, str) or not re.fullmatch(r"[A-Z0-9]{4}", icao):
            raise ValueError(f"C070 registry has no verified ICAO identifier for {iata}")
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError(f"C070 registry has no airport name for {iata}")
        if iata in stations:
            raise ValueError(f"Duplicate C070 registry airport: {iata}")
        stations[iata] = icao

    if set(stations) != set(codes) or len(set(stations.values())) != EXPECTED_COUNT:
        raise ValueError("C070 IATA/ICAO identifiers do not match the approved airport list")
    return stations
