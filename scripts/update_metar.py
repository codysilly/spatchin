#!/usr/bin/env python3
"""Fetch validated AWC METARs, retry transient failures, preserve last good snapshot."""
import json
import os
import random
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AIRPORTS = {"KORD", "KLAX", "KJFK", "KMEM"}
URL = "https://aviationweather.gov/api/data/metar?ids=KORD,KLAX,KJFK,KMEM&format=json"
DEST = Path("data/metars.json")
DELAYS = (15, 30, 60)  # seconds before retries 2, 3, and 4


def observation_time(item):
    value = item.get("obsTime", item.get("reportTime"))
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).timestamp()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    raise ValueError("Missing observation time")


def valid(item, *, enforce_freshness=True):
    if not isinstance(item, dict) or item.get("icaoId") not in AIRPORTS:
        return False
    if not item.get("rawOb"):
        return False
    try:
        observed = observation_time(item)
        speed = item.get("wspd")
        if speed is not None and float(speed) < 0:
            return False
        if observed > time.time() + 300:
            return False
        return not enforce_freshness or observed > time.time() - 7 * 86400
    except (ValueError, TypeError, OverflowError, OSError):
        return False


def fetch():
    req = urllib.request.Request(URL, headers={
        "User-Agent": "SpatchinDashboard/0.9 (GitHub Actions)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=35) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise ValueError("AWC response was not a JSON array")
    selected = {}
    for item in payload:
        if valid(item):
            code = item["icaoId"]
            if code not in selected or observation_time(item) > observation_time(selected[code]):
                selected[code] = item
    if not selected:
        raise ValueError("AWC response contained no valid requested METARs")
    return selected


def read_previous():
    previous = {}
    if DEST.exists():
        try:
            old = json.loads(DEST.read_text(encoding="utf-8"))
            if not isinstance(old, dict) or not isinstance(old.get("metars"), list):
                raise ValueError("Previous snapshot has an invalid shape")
            previous = {
                m["icaoId"]: m for m in old["metars"]
                if valid(m, enforce_freshness=False)
            }
        except (ValueError, KeyError, TypeError) as exc:
            print(f"Previous snapshot could not be parsed: {exc}", file=sys.stderr)
    return previous


def write_snapshot(snapshot):
    """Atomically replace the snapshot so readers never see partial JSON."""
    DEST.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{DEST.name}.", dir=DEST.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, DEST)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main():
    previous = read_previous()
    latest = None
    for attempt in range(1, len(DELAYS) + 2):
        try:
            latest = fetch()
            print(f"AWC succeeded on attempt {attempt}; {len(latest)} valid airports")
            break
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            print(f"AWC attempt {attempt} failed: {exc}", file=sys.stderr, flush=True)
            if attempt <= len(DELAYS):
                delay = DELAYS[attempt - 1]
                print(f"Retrying in {delay} seconds", flush=True)
                time.sleep(delay)
    if latest is None:
        print("AWC unavailable after retries; keeping existing data/metars.json unchanged", file=sys.stderr)
        raise SystemExit(1)
    merged = dict(previous)
    for code, item in latest.items():
        if code not in merged or observation_time(item) >= observation_time(merged[code]):
            merged[code] = item
    observations = [merged[code] for code in sorted(merged)]
    previous_observations = [previous[code] for code in sorted(previous)]
    if observations == previous_observations:
        print("No newer METAR observations; data/metars.json left unchanged")
        return
    snapshot = {
        "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": URL,
        "metars": observations,
    }
    write_snapshot(snapshot)
    print(f"Published {len(merged)} validated observations; older valid reports retained if missing upstream")


if __name__ == "__main__":
    main()
