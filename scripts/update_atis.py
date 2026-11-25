#!/usr/bin/env python3
"""Collect unofficial atis.info D-ATIS; retain last good airport reports."""
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import time
import urllib.error
import urllib.request

if __package__:
    from .c070_station_registry import load_c070_stations
else:
    try:
        from scripts.c070_station_registry import load_c070_stations
    except ModuleNotFoundError as exc:
        if exc.name != 'scripts':
            raise
        from c070_station_registry import load_c070_stations

# Candidate evidence only: third-party directory, checked 2026-11-25.
# https://weather.schaffrath.net/D-ATIS.html (not a provider guarantee).
DIRECTORY_ICAO = frozenset((
    'KABQ', 'KADW', 'KALB', 'KATL', 'KAUS', 'KBDL', 'KBNA', 'KBOI',
    'KBOS', 'KBUF', 'KBUR', 'KBWI', 'KCHS', 'KCLE', 'KCLT', 'KCMH',
    'KCVG', 'KDAL', 'KDCA', 'KDEN', 'KDFW', 'KDJT', 'KDTW', 'KELP',
    'KEWR', 'KFLL', 'KGSO', 'KHOU', 'KHPN', 'KIAD', 'KIAH', 'KIND',
    'KJFK', 'KJAX', 'KLAS', 'KLAX', 'KLGA', 'KLIT', 'KMCI', 'KMCO',
    'KMDW', 'KMEM', 'KMIA', 'KMKE', 'KMSP', 'KMSY', 'KOAK', 'KOKC',
    'KOMA', 'KONT', 'KORD', 'KPDX', 'KPHL', 'KPHX', 'KPIT', 'KPVD',
    'KRDU', 'KRNO', 'KSAN', 'KSAT', 'KSDF', 'KSEA', 'KSFO', 'KSJC',
    'KSLC', 'KSMF', 'KSNA', 'KSTL', 'KTEB', 'KTPA', 'KTUL', 'KVNY',
    'PANC', 'PHNL', 'TJSJ',
))
_registry = load_c070_stations()
CATALOG_AIRPORTS = tuple(sorted(_registry.values()))
AIRPORTS = tuple(code for code in CATALOG_AIRPORTS if code in DIRECTORY_ICAO)
# Draft acquisition bounds; production activation requires owner authorization.
MAX_REQUESTS = 62
RUN_BUDGET_SECONDS = 180
REQUEST_TIMEOUT_SECONDS = 20
if not {'KORD', 'KLAX', 'KJFK', 'KMEM'} <= set(AIRPORTS) or len(AIRPORTS) > MAX_REQUESTS:
    raise ValueError('ATIS candidate list exceeds reviewed scope')


def collection_order(hour=None):
    """Rotate the first station hourly to avoid fixed-order starvation."""
    if hour is None:
        hour = int(dt.datetime.now(dt.timezone.utc).timestamp()) // 3600
    start = hour % len(AIRPORTS)
    return AIRPORTS[start:] + AIRPORTS[:start]
OUTPUT = pathlib.Path('data/atis.json')
URL = 'https://atis.info/api/'
TYPES = frozenset(('combined', 'arr', 'dep'))


def report_time(item):
    """Read source update time as UTC; never use fetch time as report time."""
    value = item.get('updatedAt')
    if not isinstance(value, str):
        raise ValueError('Missing source update timestamp')
    stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Source update timestamp has no timezone')
    if stamp > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise ValueError('Future source update timestamp')
    return stamp.timestamp()


def select_reports(records, airport):
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        raise ValueError('Expected an array of ATIS reports')
    valid = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        if str(item.get('airport', '')).upper() != airport or item.get('type') not in TYPES:
            continue
        if not isinstance(item.get('datis'), str) or not item['datis'].strip():
            continue
        try:
            stamp = report_time(item)
        except (ValueError, TypeError, OverflowError):
            continue
        kind = item['type']
        if kind not in valid or stamp > valid[kind][0]:
            valid[kind] = (stamp, {key: item.get(key) for key in
                                   ('airport', 'type', 'code', 'datis', 'time', 'updatedAt')})
    if not valid:
        raise ValueError('No valid ATIS reports')
    return [valid[kind][1] for kind in ('combined', 'arr', 'dep') if kind in valid]


def read_previous():
    if not OUTPUT.exists():
        return {}, None, None, None
    try:
        payload = json.loads(OUTPUT.read_text(encoding='utf-8'))
        if not isinstance(payload, dict) or not isinstance(payload.get('airports'), dict):
            raise ValueError('Invalid previous snapshot')
        previous = {}
        for airport in AIRPORTS:
            try:
                previous[airport] = select_reports(payload['airports'][airport], airport)
            except (KeyError, ValueError, TypeError):
                continue
        return previous, payload.get('configured_airports'), payload.get('retrieved_utc'), payload.get('catalog_airports')
    except (OSError, ValueError, TypeError) as exc:
        print(f'Previous ATIS snapshot unreadable: {exc}', file=sys.stderr)
        return {}, None, None, None


def fetch(airport, *, timeout=REQUEST_TIMEOUT_SECONDS):
    request = urllib.request.Request(URL + airport, headers={
        'User-Agent': 'Spatchin/0.9 (independent aviation data prototype)',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return select_reports(json.load(response), airport)


def merge_reports(previous, incoming):
    """Keep the newest report for each independent ATIS type."""
    by_type = {item['type']: item for item in previous}
    for item in incoming:
        kind = item['type']
        if kind not in by_type or report_time(item) >= report_time(by_type[kind]):
            by_type[kind] = item
    return [by_type[kind] for kind in ('combined', 'arr', 'dep') if kind in by_type]


def write_snapshot(airports, *, retrieved_utc=None):
    payload = {
        'retrieved_utc': retrieved_utc or dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'configured_airports': list(AIRPORTS),
        'catalog_airports': list(CATALOG_AIRPORTS),
        'source': URL.rstrip('/'),
        'airports': airports,
        'notice': 'atis.info: Do not use for real world flight planning or navigation.',
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=f'.{OUTPUT.name}.', dir=OUTPUT.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(path, OUTPUT)
    except BaseException:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise


def main():
    previous, previous_coverage, previous_retrieved, previous_catalog = read_previous()
    merged = dict(previous)
    successes = []
    failures = {}
    attempted = 0
    deadline = time.monotonic() + RUN_BUDGET_SECONDS
    for airport in collection_order():
        remaining = deadline - time.monotonic()
        if attempted >= MAX_REQUESTS or remaining <= 0:
            print('ATIS collection budget exhausted; remaining stations not checked', file=sys.stderr)
            break
        attempted += 1
        try:
            incoming = fetch(airport, timeout=min(REQUEST_TIMEOUT_SECONDS, remaining))
            successes.append(airport)
            merged[airport] = merge_reports(merged.get(airport, []), incoming)
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            failures[airport] = str(exc)
            print(f'{airport}: {exc}; retaining previous report if present', file=sys.stderr)
            if isinstance(exc, urllib.error.HTTPError) and (exc.code in (429, 503)):
                print('ATIS provider throttled or unavailable; stopping this collection', file=sys.stderr)
                break
    print(f'ATIS station requests attempted: {attempted}/{len(AIRPORTS)}')
    if not successes:
        print('All ATIS retrievals failed; keeping published snapshot unchanged', file=sys.stderr)
        raise SystemExit(1)
    if merged == previous:
        if previous_coverage != list(AIRPORTS) or previous_catalog != list(CATALOG_AIRPORTS):
            # Metadata-only migration must not refresh the age of retained reports.
            write_snapshot(merged, retrieved_utc=previous_retrieved)
            print('Published ATIS coverage metadata; source reports unchanged')
        else:
            print('ATIS checked; no newer reports; published snapshot unchanged')
    else:
        write_snapshot(merged)
        print('Published ATIS reports for:', ', '.join(sorted(merged)))
    if failures:
        print('Unavailable on this check:', ', '.join(sorted(failures)), file=sys.stderr)


if __name__ == '__main__':
    main()
