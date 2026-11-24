#!/usr/bin/env python3
"""Fetch validated AWC METARs, retry transient failures, preserve last good snapshot."""
import json
import math
import os
import random
import sys
import tempfile
import time
import urllib.error
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
URL = "https://aviationweather.gov/api/data/metar?ids=" + ",".join(sorted(AIRPORTS)) + "&format=json"
DEST = Path("data/metars.json")
DELAYS = (15, 30, 60)  # seconds before retries 2, 3, and 4


def observation_time(item):
    value = item.get("obsTime", item.get("reportTime"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, timezone.utc).timestamp()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    raise ValueError("Missing observation time")


def requested_station(item):
    return (isinstance(item, dict) and isinstance(item.get("icaoId"), str)
            and item["icaoId"] in AIRPORTS)


def rejection_reason(item, *, enforce_freshness=True):
    """Name the first failed validation rule for an upstream METAR record."""
    if not requested_station(item):
        return "unrecognized_airport"
    if not isinstance(item.get("rawOb"), str) or not item["rawOb"].strip():
        return "missing_raw_observation"
    try:
        observed = observation_time(item)
    except (ValueError, TypeError, OverflowError, OSError):
        return "invalid_observation_time"
    speed = item.get("wspd")
    if speed is not None:
        try:
            if isinstance(speed, bool) or not math.isfinite(float(speed)):
                return "invalid_wind_speed"
            if float(speed) < 0:
                return "negative_wind_speed"
        except (ValueError, TypeError, OverflowError, OSError):
            return "invalid_wind_speed"
    now = time.time()
    if observed > now + 300:
        return "future_observation"
    if enforce_freshness and observed <= now - 7 * 86400:
        return "outside_7_day_window"
    return None


def valid(item, *, enforce_freshness=True):
    return rejection_reason(item, enforce_freshness=enforce_freshness) is None


def fetch(diagnostics=None):
    req = urllib.request.Request(URL, headers={
        "User-Agent": "SpatchinDashboard/0.9 (GitHub Actions)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=35) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise ValueError("AWC response was not a JSON array")
    selected = {}
    summary = {}
    for item in payload:
        if not requested_station(item):
            continue
        code = item["icaoId"]
        entry = summary.setdefault(code, {"candidates": 0, "rejected": {}})
        entry["candidates"] += 1
        reason = rejection_reason(item)
        if reason:
            entry["rejected"][reason] = entry["rejected"].get(reason, 0) + 1
            continue
        if code not in selected or observation_time(item) > observation_time(selected[code]):
            selected[code] = item
    if diagnostics is not None:
        diagnostics["_response_received"] = True
        diagnostics.update(summary)
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


def format_observed(item):
    if item is None:
        return "none"
    return datetime.fromtimestamp(observation_time(item), timezone.utc).isoformat().replace("+00:00", "Z")


def log_retention(previous, latest, diagnostics):
    """Explain preserved observations in per-run Actions logs; no new public file."""
    for code in sorted(AIRPORTS):
        saved = previous.get(code)
        incoming = latest.get(code)
        evidence = diagnostics.get(code, {})
        if incoming is None:
            reason = "rejected_upstream" if evidence.get("candidates", 0) else "missing_upstream"
        elif saved is not None and observation_time(incoming) < observation_time(saved):
            reason = "older_upstream"
        elif saved is not None and incoming == saved:
            reason = "unchanged_upstream"
        else:
            continue
        rejected = evidence.get("rejected", {})
        rejected_detail = ",".join(f"{key}:{rejected[key]}" for key in sorted(rejected)) or "none"
        action = "retained" if saved is not None else "unavailable"
        print(
            f"METAR {code} {action}: reason={reason}; "
            f"saved_obs={format_observed(saved)}; upstream_obs={format_observed(incoming)}; "
            f"candidates={evidence.get('candidates', 0)}; rejected={rejected_detail}"
        )


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
    diagnostics = {}
    for attempt in range(1, len(DELAYS) + 2):
        diagnostics = {}
        try:
            latest = fetch(diagnostics=diagnostics)
            print(f"AWC succeeded on attempt {attempt}; {len(latest)} valid airports")
            break
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            print(f"AWC attempt {attempt} failed: {exc}", file=sys.stderr, flush=True)
            if attempt <= len(DELAYS):
                delay = DELAYS[attempt - 1]
                print(f"Retrying in {delay} seconds", flush=True)
                time.sleep(delay)
    if latest is None:
        if diagnostics.get("_response_received"):
            log_retention(previous, {}, diagnostics)
        print("AWC unavailable after retries; keeping existing data/metars.json unchanged", file=sys.stderr)
        raise SystemExit(1)
    log_retention(previous, latest, diagnostics)
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
