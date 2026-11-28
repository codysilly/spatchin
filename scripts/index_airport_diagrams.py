#!/usr/bin/env python3
"""Build a C070 diagram candidate manifest from a local FAA d-TPP XML file.

No network requests or publication. A candidate is not an accepted edition.
FAA schema: https://aeronav.faa.gov/d-tpp/Metafile_XML_Definitions.pdf
"""
import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__:
    from .c070_station_registry import load_c070_stations
else:
    from c070_station_registry import load_c070_stations

BASE = "https://aeronav.faa.gov/d-tpp/"
MAX_XML_BYTES = 64 * 1024 * 1024


def effective(value):
    return datetime.strptime(value, "%H%MZ %m/%d/%y").replace(tzinfo=timezone.utc)


def utc(value):
    return value.isoformat().replace("+00:00", "Z")


def build_manifest(raw, stations, expected_cycle):
    if not raw or len(raw) > MAX_XML_BYTES:
        raise ValueError("Invalid XML size")
    # Reject declarations that can expand entities; require UTF-8 input.
    xml = raw.decode("utf-8-sig")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", xml, re.I):
        raise ValueError("DTD and entities are not permitted")
    root = ET.fromstring(xml)
    if root.tag != "digital_tpp":
        raise ValueError("Invalid d-TPP root")
    cycle = root.get("cycle", "")
    if not re.fullmatch(r"[0-9]{2}(0[1-9]|1[0-3])", cycle) or cycle != expected_cycle:
        raise ValueError("Unexpected d-TPP cycle")
    start = effective(root.get("from_edate", ""))
    end = effective(root.get("to_edate", ""))
    if end - start != timedelta(days=28):
        raise ValueError("Invalid effective interval")
    if not stations or len(set(stations.values())) != len(stations):
        raise ValueError("Invalid station mapping")

    by_icao = {icao: iata for iata, icao in stations.items()}
    records = {iata: [] for iata in stations}
    seen = set()
    apd_count = 0
    for airport in root.findall("./state_code/city_name/airport_name"):
        icao = airport.get("icao_ident", "").strip()
        faa = airport.get("apt_ident", "").strip()
        iata = by_icao.get(icao)
        # Do not equate FAA identifiers with IATA identifiers.
        if iata:
            seen.add(iata)
        for record in airport.findall("record"):
            if (record.findtext("chart_code") or "").strip() != "APD":
                continue
            apd_count += 1
            if not iata:
                continue
            action = (record.findtext("useraction") or "").strip()
            if action not in ("", "A", "C", "D"):
                raise ValueError(f"Unknown chart action for {icao}")
            name = (record.findtext("pdf_name") or "").strip()
            if action != "D" and not re.fullmatch(r"[A-Za-z0-9_-]+\.PDF", name, re.I):
                raise ValueError(f"Unsafe or missing PDF filename for {icao}")
            records[iata].append({
                "faa": faa, "action": action, "pdf_name": name,
                "source_url": None if action == "D" else BASE + cycle + "/" + name,
            })
    if not apd_count or not seen:
        raise ValueError("No APD or matching airport records in catalog")

    airports = {}
    for iata, icao in sorted(stations.items()):
        entries = records[iata]
        active = [r for r in entries if r["action"] != "D"]
        if len(active) > 1:
            status = "ambiguous"
        elif len(active) == 1:
            status = "indexed"
        elif entries:
            status = "deleted"
        elif iata in seen:
            status = "no_apd_in_index"
        else:
            status = "airport_not_in_index"
        airports[iata] = {"icao": icao, "status": status, "records": entries}
    return {
        "schema_version": 1, "state": "candidate_unvalidated",
        "cycle": cycle, "effective_from_utc": utc(start),
        "effective_to_utc": utc(end),
        "xml_sha256": hashlib.sha256(raw).hexdigest(),
        "airport_count": len(stations),
        "indexed_count": sum(a["status"] == "indexed" for a in airports.values()),
        "airports": airports,
    }


def edition_state(manifest, now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("An aware timestamp is required")
    start = datetime.fromisoformat(manifest["effective_from_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(manifest["effective_to_utc"].replace("Z", "+00:00"))
    return "future" if now < start else "expired" if now >= end else "effective"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--cycle", required=True)
    args = parser.parse_args()
    with args.xml.open("rb") as handle:
        raw = handle.read(MAX_XML_BYTES + 1)
    manifest = build_manifest(raw, load_c070_stations(), args.cycle)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
