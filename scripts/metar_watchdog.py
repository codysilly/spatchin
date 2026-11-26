#!/usr/bin/env python3
"""Offline METAR freshness gate and optional independent incident heartbeat.

No AWC/provider requests. evaluate runs after a successful collector and
updates a tiny git-tracked, saturating alert state. notify runs only after a
successful push, and uses a repository secret for Better Stack's heartbeat.
"""
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SNAPSHOT = Path("data/metars.json")
STATE = Path(".github/metar-watchdog-state.json")
SITE_URL = "https://www.spatchin.com/data/metars.json"
HEARTBEAT_ENV = "SPATCHIN_METAR_HEARTBEAT_URL"
STALE_MINUTES = 90
SITE_LAG_MINUTES = 20
SITE_GRACE_MINUTES = 5
MIN_OBSERVATIONS = 4


def utc_time(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is not None:
            return timestamp.astimezone(timezone.utc)
    raise ValueError("Invalid UTC timestamp")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def count_stale(snapshot, now):
    observations = snapshot.get("metars")
    if not isinstance(observations, list) or len(observations) < MIN_OBSERVATIONS:
        raise ValueError("METAR snapshot has insufficient observations")
    stale = 0
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError("Invalid METAR entry")
        observed = utc_time(item.get("obsTime", item.get("reportTime")))
        if observed > now + timedelta(minutes=5):
            raise ValueError("METAR observation timestamp is in the future")
        stale += (now - observed).total_seconds() > STALE_MINUTES * 60
    return stale, len(observations)


def update_streak(snapshot, prior, now):
    stale, total = count_stale(snapshot, now)
    widespread = stale >= 2 and 2 * stale >= total
    old = prior.get("consecutive_widespread_stale", 0)
    if not isinstance(old, int) or isinstance(old, bool) or old not in (0, 1, 2):
        raise ValueError("Invalid prior watchdog state")
    next_streak = min(2, old + 1) if widespread else 0
    return {"consecutive_widespread_stale": next_streak}, stale, total


def evaluate(snapshot_path=SNAPSHOT, state_path=STATE, *, now=None):
    now = now or datetime.now(timezone.utc)
    snapshot = read_json(snapshot_path)
    state_path = Path(state_path)
    prior = read_json(state_path) if state_path.exists() else {"consecutive_widespread_stale": 0}
    state, stale, total = update_streak(snapshot, prior, now)
    if state != prior:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"METAR watchdog: {stale}/{total} observations older than {STALE_MINUTES} min; "
          f"widespread_stale_streak={state['consecutive_widespread_stale']}; "
          f"incident={state['consecutive_widespread_stale'] == 2}")
    return state


def public_lag(snapshot, *, now, fetcher=urllib.request.urlopen):
    """Return True if the site demonstrably lags; None means not verifiable."""
    try:
        repo_updated = utc_time(snapshot["updated_utc"])
        request = urllib.request.Request(
            SITE_URL + "?metar_watchdog=" + str(int(now.timestamp() // 60)),
            headers={"User-Agent": "SpatchinMETARWatchdog/0.9", "Cache-Control": "no-cache", "Accept": "application/json"},
        )
        with fetcher(request, timeout=8) as response:
            published = json.load(response)
        site_updated = utc_time(published["updated_utc"])
        if site_updated > now + timedelta(minutes=5) or repo_updated > now + timedelta(minutes=5):
            return None
        diff = (repo_updated - site_updated).total_seconds()
        repo_age = (now - repo_updated).total_seconds()
        print(f"METAR site: repository={repo_updated.isoformat()} publication={site_updated.isoformat()} "
              f"lag={int(diff // 60)}min")
        return diff > SITE_LAG_MINUTES * 60 and repo_age >= SITE_GRACE_MINUTES * 60
    except (OSError, ValueError, KeyError, TypeError, OverflowError, urllib.error.URLError) as exc:
        print(f"METAR site: unverified ({type(exc).__name__})")
        return None


def validate_heartbeat_url(value):
    """Reject accidental requests to anything other than Better Stack heartbeat URLs."""
    parsed = urllib.parse.urlsplit(value.strip())
    if (parsed.scheme != "https" or parsed.hostname not in
            ("incidents.betterstack.com", "uptime.betterstack.com") or
            parsed.username is not None or parsed.password is not None or
            parsed.port is not None or parsed.query or parsed.fragment or
            not parsed.path.startswith("/api/v1/heartbeat/") or
            len(parsed.path.split("/")) != 5 or not parsed.path.split("/")[-1]):
        raise ValueError("Invalid Better Stack heartbeat URL")
    return value.strip().rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_heartbeat(secret_url, *, fail, sender=None):
    base = validate_heartbeat_url(secret_url)
    request = urllib.request.Request(base + ("/fail" if fail else ""),
                                     headers={"User-Agent": "SpatchinMETARWatchdog/0.9"})
    sender = sender or urllib.request.build_opener(NoRedirect()).open
    try:
        with sender(request, timeout=8) as response:
            if not 200 <= response.status < 300:
                raise ValueError("Heartbeat service did not acknowledge delivery")
    except (OSError, ValueError, urllib.error.URLError):
        print("METAR watchdog: heartbeat delivery unverified (endpoint/secret never logged)", file=sys.stderr)
        return False
    print("METAR watchdog: Better Stack failure signal delivered" if fail else
          "METAR watchdog: Better Stack success heartbeat delivered")
    return True


def notify(snapshot_path=SNAPSHOT, state_path=STATE, *, now=None, fetcher=urllib.request.urlopen, sender=None):
    secret_url = os.environ.get(HEARTBEAT_ENV)
    if not secret_url:
        print(f"METAR watchdog: {HEARTBEAT_ENV} not configured; external alerting inactive")
        return False
    try:
        state = read_json(state_path) if Path(state_path).exists() else {"consecutive_widespread_stale": 0}
        snapshot = read_json(snapshot_path)
        stale_incident = state["consecutive_widespread_stale"] == 2
        lag = public_lag(snapshot, now=now or datetime.now(timezone.utc), fetcher=fetcher)
        if lag:
            print("METAR watchdog: public snapshot lags repository beyond the alert threshold")
        return send_heartbeat(secret_url, fail=stale_incident or lag is True, sender=sender)
    except (OSError, ValueError, TypeError, KeyError):
        print("METAR watchdog: validation failed; heartbeat withheld", file=sys.stderr)
        return False


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("evaluate", "notify"):
        raise SystemExit("Usage: metar_watchdog.py evaluate|notify")
    if sys.argv[1] == "evaluate":
        evaluate()
    else:
        notify()


if __name__ == "__main__":
    main()
