#!/usr/bin/env python3
"""Stage a C070 diagram edition privately from a supplied XML catalog.

Explicit execution only. Never publishes or activates an edition.
No automatic retry, redirects, or FAA API credentials.
"""
import argparse
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

if __package__:
    from .index_airport_diagrams import BASE, MAX_XML_BYTES, build_manifest
    from .c070_station_registry import load_c070_stations
else:
    from index_airport_diagrams import BASE, MAX_XML_BYTES, build_manifest
    from c070_station_registry import load_c070_stations

MAX_PDF_BYTES = 16 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_pdf(url):
    # Exact FAA source only; no redirect to another endpoint.
    if not re.fullmatch(r"https://aeronav\.faa\.gov/d-tpp/[0-9]{4}/[A-Za-z0-9_-]+\.[Pp][Dd][Ff]", url):
        raise ValueError("Unapproved PDF URL")
    request = urllib.request.Request(url, headers={
        "User-Agent": "SpatchinDashboard/0.9",
        "Accept": "application/pdf",
    })
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=35) as response:
        if response.status != 200:
            raise ValueError("Unexpected PDF status")
        return response.read(MAX_PDF_BYTES + 1)


def validate_pdf(raw):
    # A structural sanity check, not proof of chart identity or validity.
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_PDF_BYTES:
        raise ValueError("Invalid PDF size")
    if not re.match(rb"%PDF-[0-9]\.[0-9]", raw) or not raw.rstrip().endswith(b"%%EOF"):
        raise ValueError("Invalid PDF header or trailer")
    return hashlib.sha256(raw).hexdigest()


def write_new(path, raw):
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def stage(raw_xml, stations, cycle, directory, *, max_requests, fetch):
    """One fresh staging directory per attempt; no automatic recovery or retry."""
    manifest = build_manifest(raw_xml, stations, cycle)
    jobs = []
    for iata, airport in manifest["airports"].items():
        if airport["status"] == "ambiguous":
            raise ValueError(f"Ambiguous chart identity for {iata}")
        if airport["status"] == "indexed":
            record = next(r for r in airport["records"] if r["action"] != "D")
            jobs.append((iata, record["source_url"]))
    if not jobs or len(jobs) > max_requests or max_requests > len(stations):
        raise ValueError("PDF request count outside explicit budget")
    if len({url for _, url in jobs}) != len(jobs):
        raise ValueError("Duplicate PDF source across airports")
    directory = Path(directory).resolve()
    # Keep raw files away from the GitHub Pages source tree.
    if directory == ROOT or ROOT in directory.parents:
        raise ValueError("Staging directory must be outside repository")
    directory.mkdir(parents=True, exist_ok=False)
    write_new(directory / "catalog.xml", raw_xml)
    for iata, url in jobs:
        # Reserve the attempt before network I/O. Any failure stops the run.
        with (directory / "attempts.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps({"iata": iata, "url": url}) + "\n")
            ledger.flush()
            os.fsync(ledger.fileno())
        raw = fetch(url)
        digest = validate_pdf(raw)
        filename = iata + ".pdf"
        write_new(directory / filename, raw)
        manifest["airports"][iata]["download"] = {
            "file": filename, "sha256": digest, "bytes": len(raw),
        }
    manifest["state"] = "staged_unvalidated"
    manifest["downloaded_count"] = len(jobs)
    # This is evidence of staging only; never an active edition pointer.
    write_new(directory / "candidate.json",
              (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", required=True, type=Path)
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--max-requests", required=True, type=int)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    with args.xml.open("rb") as handle:
        raw = handle.read(MAX_XML_BYTES + 1)
    stations = load_c070_stations()
    if not args.execute:
        print(json.dumps(build_manifest(raw, stations, args.cycle), indent=2))
        return
    result = stage(raw, stations, args.cycle, args.directory,
                   max_requests=args.max_requests, fetch=fetch_pdf)
    print(f"Staged {result['downloaded_count']} unvalidated diagrams")


if __name__ == "__main__":
    main()
