#!/usr/bin/env python3
"""Collect unofficial atis.info D-ATIS; retain last good airport reports."""
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
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

# Provider API documentation supplied by owner, 2026-11-25.
# https://atis.info/api — /stations and /all, one request each.
CATALOG_AIRPORTS = tuple(sorted(load_c070_stations().values()))
MAX_REQUESTS = 2
REQUEST_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
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
        for airport in CATALOG_AIRPORTS:
            try:
                previous[airport] = select_reports(payload['airports'][airport], airport)
            except (KeyError, ValueError, TypeError):
                continue
        return previous, payload.get('configured_airports'), payload.get('retrieved_utc'), payload.get('catalog_airports')
    except (OSError, ValueError, TypeError) as exc:
        print(f'Previous ATIS snapshot unreadable: {exc}', file=sys.stderr)
        return {}, None, None, None


def fetch_json(endpoint):
    if endpoint not in ('stations', 'all'):
        raise ValueError('Unexpected ATIS endpoint')
    request = urllib.request.Request(URL + endpoint, headers={
        'User-Agent': 'Spatchin/0.9 (independent aviation data prototype)',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError('ATIS response exceeds size limit')
    return json.loads(raw)


def configured_stations(payload):
    """Validate provider-listed identifiers; restrict coverage to C070."""
    if not isinstance(payload, list) or not payload or any(
        not isinstance(code, str) or len(code) != 4 or
        not code.isascii() or not code.isalnum() or code != code.upper()
        for code in payload
    ):
        raise ValueError('Invalid ATIS station list')
    return sorted(set(payload).intersection(CATALOG_AIRPORTS))


def bulk_reports(payload, configured):
    """Validate the documented array of reports; ignore non-C070 data."""
    if not isinstance(payload, list) or not payload:
        raise ValueError('Invalid or empty ATIS bulk response')
    grouped = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError('Unexpected ATIS bulk report shape')
        airport = item.get('airport')
        if not isinstance(airport, str):
            continue
        airport = airport.upper()
        if airport in CATALOG_AIRPORTS:
            grouped.setdefault(airport, []).append(item)
    incoming = {}
    for airport, records in grouped.items():
        try:
            valid = select_reports(records, airport)
        except (ValueError, TypeError, OverflowError):
            continue
        if airport not in configured:
            raise ValueError('ATIS station list and bulk response disagree')
        incoming[airport] = valid
    if not incoming:
        raise ValueError('No valid C070 ATIS reports in bulk response')
    return incoming


def merge_reports(previous, incoming):
    """Keep the newest report for each independent ATIS type."""
    by_type = {item['type']: item for item in previous}
    for item in incoming:
        kind = item['type']
        if kind not in by_type or report_time(item) >= report_time(by_type[kind]):
            by_type[kind] = item
    return [by_type[kind] for kind in ('combined', 'arr', 'dep') if kind in by_type]


def write_snapshot(airports, configured, *, retrieved_utc=None):
    payload = {
        'retrieved_utc': retrieved_utc or dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'configured_airports': configured,
        'coverage_source': URL + 'stations',
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
    try:
        configured = configured_stations(fetch_json('stations'))
        incoming = bulk_reports(fetch_json('all'), configured)
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        print(f'ATIS bulk collection failed; keeping published snapshot unchanged: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
    merged = dict(previous)
    for airport, records in incoming.items():
        merged[airport] = merge_reports(merged.get(airport, []), records)
    if merged == previous:
        if previous_coverage != configured or previous_catalog != list(CATALOG_AIRPORTS):
            # Metadata-only migration must not refresh the age of retained reports.
            write_snapshot(merged, configured, retrieved_utc=previous_retrieved)
            print('Published ATIS coverage metadata; source reports unchanged')
        else:
            print('ATIS checked; no newer reports; published snapshot unchanged')
    else:
        write_snapshot(merged, configured)
        print('Published ATIS reports for:', ', '.join(sorted(merged)))
    print(f'ATIS coverage: {len(configured)}/{len(CATALOG_AIRPORTS)} C070 stations listed; '
          f'{len(incoming)} returned usable reports')


if __name__ == '__main__':
    main()
