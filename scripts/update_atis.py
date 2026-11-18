#!/usr/bin/env python3
"""Collect unofficial atis.info D-ATIS; retain last good airport reports."""
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import urllib.request

AIRPORTS = ('KORD', 'KLAX', 'KJFK')
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
        return {}
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
        return previous
    except (OSError, ValueError, TypeError) as exc:
        print(f'Previous ATIS snapshot unreadable: {exc}', file=sys.stderr)
        return {}


def fetch(airport):
    request = urllib.request.Request(URL + airport, headers={
        'User-Agent': 'Spatchin/0.9 (independent aviation data prototype)',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        return select_reports(json.load(response), airport)


def newest(reports):
    return max(report_time(item) for item in reports)


def write_snapshot(airports):
    payload = {
        'retrieved_utc': dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
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
    previous = read_previous()
    merged = dict(previous)
    successes = []
    failures = {}
    for airport in AIRPORTS:
        try:
            incoming = fetch(airport)
            successes.append(airport)
            if airport not in merged or newest(incoming) >= newest(merged[airport]):
                merged[airport] = incoming
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            failures[airport] = str(exc)
            print(f'{airport}: {exc}; retaining previous report if present', file=sys.stderr)
    if not successes:
        print('All ATIS retrievals failed; keeping published snapshot unchanged', file=sys.stderr)
        raise SystemExit(1)
    if merged == previous:
        print('ATIS checked; no newer reports; published snapshot unchanged')
    else:
        write_snapshot(merged)
        print('Published ATIS reports for:', ', '.join(sorted(merged)))
    if failures:
        print('Unavailable on this check:', ', '.join(sorted(failures)), file=sys.stderr)


if __name__ == '__main__':
    main()
