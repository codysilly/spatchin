#!/usr/bin/env python3
"""Collect a small, verified AWC TAF set; retain last good published reports."""
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AIRPORTS = {"KORD", "KLAX", "KJFK", "KMEM"}
URL = "https://aviationweather.gov/api/data/taf?ids=KORD,KLAX,KJFK,KMEM&format=json"
DEST = Path("data/tafs.json")


def epoch(value):
    """AWC epoch seconds or UTC date string; AWC's zone-free dates mean UTC."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError("Non-finite timestamp")
        return float(value)
    if isinstance(value, str) and value.strip():
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    raise ValueError("Missing or invalid timestamp")


def valid(item, *, now=None, enforce_freshness=True):
    if not isinstance(item, dict) or item.get("icaoId") not in AIRPORTS:
        return False
    if not isinstance(item.get("rawTAF"), str) or not item["rawTAF"].strip():
        return False
    try:
        issued = epoch(item.get("issueTime"))
        start = epoch(item.get("validTimeFrom"))
        end = epoch(item.get("validTimeTo"))
        now = time.time() if now is None else now
        if issued > now + 300 or start > end:
            return False
        if end - start < 3600 or end - start > 72 * 3600:
            return False
        if issued > end:
            return False
        if enforce_freshness and issued < now - 7 * 86400:
            return False
        return True
    except (ValueError, TypeError, OverflowError, OSError):
        return False


def compact(item):
    return {key: item[key] for key in
            ("icaoId", "rawTAF", "issueTime", "validTimeFrom", "validTimeTo")}


def select(records):
    if not isinstance(records, list):
        raise ValueError("AWC TAF response was not a JSON array")
    selected = {}
    for item in records:
        if not valid(item):
            continue
        code = item["icaoId"]
        if code not in selected or epoch(item["issueTime"]) >= epoch(selected[code]["issueTime"]):
            selected[code] = compact(item)
    if not selected:
        raise ValueError("AWC response contained no valid requested TAFs")
    return selected


def fetch():
    request = urllib.request.Request(URL, headers={
        "User-Agent": "SpatchinDashboard/0.9 (GitHub Actions)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=35) as response:
        return select(json.load(response))


def read_previous():
    if not DEST.exists():
        return {}
    try:
        data = json.loads(DEST.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("tafs"), list):
            raise ValueError("Previous snapshot has an invalid shape")
        return {item["icaoId"]: compact(item) for item in data["tafs"]
                if valid(item, enforce_freshness=False)}
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"Previous TAF snapshot unreadable: {exc}", file=sys.stderr)
        return {}


def write_snapshot(items):
    DEST.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{DEST.name}.", dir=DEST.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({
                "updated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "source": URL,
                "tafs": [items[code] for code in sorted(items)],
            }, handle, indent=2, ensure_ascii=False)
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
    try:
        incoming = fetch()
    except (ValueError, TypeError, OSError, OverflowError) as exc:
        print(f"AWC TAF retrieval failed: {exc}; existing snapshot unchanged", file=sys.stderr)
        raise SystemExit(1)
    merged = dict(previous)
    for code, item in incoming.items():
        if code not in merged or epoch(item["issueTime"]) >= epoch(merged[code]["issueTime"]):
            merged[code] = item
    if merged == previous:
        print("No new TAF issue; existing snapshot unchanged")
        return
    write_snapshot(merged)
    missing = sorted(AIRPORTS - incoming.keys())
    print(f"Published {len(merged)} TAFs; {len(incoming)} valid reports from AWC")
    if missing:
        print("No new usable TAF this check for: " + ", ".join(missing))


if __name__ == "__main__":
    main()
