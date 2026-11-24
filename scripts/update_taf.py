#!/usr/bin/env python3
"""Collect AWC TAFs for verified C070 stations; retain last good published reports."""
import json
import math
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .c070_station_registry import load_c070_stations
else:
    try:
        from scripts.c070_station_registry import load_c070_stations
    except ModuleNotFoundError as exc:
        if exc.name != "scripts":
            raise
        from c070_station_registry import load_c070_stations

AIRPORTS = frozenset(load_c070_stations().values())
URL = "https://aviationweather.gov/api/data/taf?ids=" + ",".join(sorted(AIRPORTS)) + "&format=json"
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
    if (not isinstance(item, dict) or not isinstance(item.get("icaoId"), str)
            or item["icaoId"] not in AIRPORTS):
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
    """Preserve AWC decoded forecast periods beside the verbatim raw TAF.

    Older snapshots do not include fcsts; a newer collector run can fill those
    records without needing a new TAF issue or any extra provider request.
    """
    selected = {key: item[key] for key in
                ("icaoId", "rawTAF", "issueTime", "validTimeFrom", "validTimeTo")}
    periods = item.get("fcsts")
    if isinstance(periods, list):
        saved = []
        for period in periods[:64]:
            if not isinstance(period, dict):
                continue
            try:
                start, end = epoch(period.get("timeFrom")), epoch(period.get("timeTo"))
                if start >= end or end < epoch(item["validTimeFrom"]) or start > epoch(item["validTimeTo"]):
                    continue
            except (ValueError, TypeError, OverflowError, OSError):
                continue
            fields = ("timeFrom", "timeTo", "timeBec", "fcstChange",
                      "probability", "wdir", "wspd", "wgst")
            saved.append({key: period[key] for key in fields if key in period})
        selected["fcsts"] = saved
    return selected


def select(records):
    if not isinstance(records, list):
        raise ValueError("AWC TAF response was not a JSON array")
    selected = {}
    for item in records:
        if not valid(item):
            continue
        code = item["icaoId"]
        candidate = compact(item)
        earlier = selected.get(code)
        if earlier is None or epoch(candidate["issueTime"]) > epoch(earlier["issueTime"]):
            selected[code] = candidate
        elif (epoch(candidate["issueTime"]) == epoch(earlier["issueTime"])
              and len(candidate.get("fcsts", [])) >= len(earlier.get("fcsts", []))):
            selected[code] = candidate
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
        older = merged.get(code)
        if older is None or epoch(item["issueTime"]) > epoch(older["issueTime"]):
            merged[code] = item
        elif epoch(item["issueTime"]) == epoch(older["issueTime"]):
            # Do not erase decoded periods on a temporary provider omission.
            if len(item.get("fcsts", [])) >= len(older.get("fcsts", [])):
                merged[code] = item
    missing = sorted(AIRPORTS - incoming.keys())
    print(f"AWC returned {len(incoming)} valid station reports of {len(AIRPORTS)} configured")
    if missing:
        print("No usable TAF this check for: " + ", ".join(missing))
    if merged == previous:
        print("No new TAF issue; existing snapshot unchanged")
        return
    write_snapshot(merged)
    print(f"Published {len(merged)} TAFs; {len(incoming)} valid reports from AWC")


if __name__ == "__main__":
    main()
