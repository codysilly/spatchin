#!/usr/bin/env python3
"""Publish FAA NASR runway ends for C070 airports, without inferred bearings."""
import csv
import io
import json
import math
import os
import re
import sys
import tempfile
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if __package__:
    from .c070_station_registry import load_c070_stations
else:
    try:
        from scripts.c070_station_registry import load_c070_stations
    except ModuleNotFoundError as exc:
        if exc.name != 'scripts':
            raise
        from c070_station_registry import load_c070_stations

AIRPORTS = frozenset(load_c070_stations())  # Verified IATA IDs, not K+IATA guesses.
LEGACY_COUNTS = {'ORD': 16, 'LAX': 8, 'JFK': 8, 'MEM': 8}
END_ID = re.compile(r'(?:0[1-9]|[12][0-9]|3[0-6])[LRC]?\Z')
BASE = date(2026, 10, 1)  # Known FAA NASR effective cycle
OUT = Path('data/runways.json')


def cycle_dates(today):
    elapsed = (today - BASE).days // 28
    for n in (elapsed, elapsed - 1):
        yield BASE + timedelta(days=28 * n)


def fetch_archive(cycle):
    url = f'https://nfdc.faa.gov/webContent/28DaySub/extra/{cycle:%d_%b_%Y}_APT_CSV.zip'
    request = urllib.request.Request(url, headers={
        'User-Agent': 'SpatchinDashboard/0.9 (GitHub Actions)',
        'Accept': 'application/zip',
    })
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read()
    return zipfile.ZipFile(io.BytesIO(raw)), url


def get_table(archive, filename):
    matches = [n for n in archive.namelist()
               if n.upper().endswith(filename.upper()) and not n.endswith('/')]
    if len(matches) != 1:
        raise ValueError(f'Expected one {filename}, found {matches}')
    with archive.open(matches[0]) as stream:
        data = stream.read().decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(data))
    required = {'ARPT_ID', 'RWY_END_ID', 'TRUE_ALIGNMENT', 'RWY_ID'}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError('FAA runway-end schema not recognized; refusing to publish')
    return list(reader)


def generate(archive, url, cycle):
    rows = get_table(archive, 'APT_RWY_END.csv')
    if not rows:
        raise ValueError('FAA runway-end table is empty')
    found = {code: [] for code in AIRPORTS}
    seen = {code: set() for code in AIRPORTS}
    invalid = {}
    for row in rows:
        code = (row.get('ARPT_ID') or '').strip().upper()
        if code not in found:
            continue
        rid = (row.get('RWY_END_ID') or '').strip().upper()
        pair = (row.get('RWY_ID') or '').strip().upper()
        if not END_ID.fullmatch(rid) or rid in seen[code] or not pair:
            invalid.setdefault(code, 'invalid_or_duplicate_runway_end')
            continue
        seen[code].add(rid)
        raw = (row.get('TRUE_ALIGNMENT') or '').strip()
        degrees = None
        if raw:
            try:
                degrees = float(raw)
            except ValueError:
                invalid.setdefault(code, 'invalid_true_alignment')
                continue
            if not math.isfinite(degrees) or not 0 <= degrees <= 360:
                invalid.setdefault(code, 'invalid_true_alignment')
                continue
            degrees %= 360
        found[code].append({'id': rid, 'true_heading': degrees, 'pair': pair})

    airports, coverage = {}, {}
    for code in sorted(AIRPORTS):
        ends = found[code]
        reason = invalid.get(code)
        if not ends and not reason:
            reason = 'not_in_nasr_runway_end_table'
        elif len(ends) < 2 or len(ends) % 2:
            reason = reason or 'incomplete_runway_end_inventory'
        if code in LEGACY_COUNTS and len(ends) != LEGACY_COUNTS[code]:
            reason = reason or 'legacy_runway_end_count_mismatch'
        if not reason:
            by_id = {end['id']: end for end in ends}
            for end in ends:
                pair_ends = end['pair'].split('/')
                if (len(pair_ends) != 2 or len(set(pair_ends)) != 2
                        or end['id'] not in pair_ends or not set(pair_ends).issubset(by_id)):
                    reason = 'incomplete_runway_pair'
                    break
            if not reason:
                for end in ends:
                    pair_ends = set(end['pair'].split('/'))
                    if any(set(by_id[mate]['pair'].split('/')) != pair_ends for mate in pair_ends):
                        reason = 'inconsistent_runway_pair'
                        break
        if reason:
            coverage[code] = {'status': 'unavailable', 'reason': reason}
            continue
        ends.sort(key=lambda e: (int(e['id'][:2]), e['id']))
        airports[code] = ends
        coverage[code] = {
            'status': 'available',
            'runway_ends': len(ends),
            'missing_true_alignments': sum(e['true_heading'] is None for e in ends),
        }

    # Preserve the four already verified airports; refuse an update that loses them.
    for code in LEGACY_COUNTS:
        if code not in airports:
            raise ValueError(f'{code}: {coverage[code]["reason"]}; refusing to replace existing data')
    return {
        'source': 'FAA NASR 28-Day Subscription — APT_RWY_END.csv',
        'source_url': url,
        'effective_date': cycle.isoformat(),
        'heading_reference': 'TRUE',
        'airports': airports,
        'airport_coverage': coverage,
    }


def publish(data):
    # Time is metadata only; identical validated source data does not need a commit.
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding='utf-8'))
            if {k: v for k, v in previous.items() if k != 'generated_utc'} == data:
                print('No NASR runway changes; snapshot unchanged')
                return False
        except (OSError, ValueError, TypeError):
            pass
    data = {'generated_utc': datetime.now(timezone.utc).isoformat(), **data}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.runways.', dir=OUT.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, OUT)
    except BaseException:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise
    return True


def main():
    failures = []
    for cycle in cycle_dates(datetime.now(timezone.utc).date()):
        try:
            archive, url = fetch_archive(cycle)
            with archive:
                data = generate(archive, url, cycle)
            publish(data)
            available = len(data['airports'])
            missing_headings = sum(item['missing_true_alignments'] for item in
                                   data['airport_coverage'].values() if item['status'] == 'available')
            print(f'FAA NASR cycle {cycle}: {available}/{len(AIRPORTS)} C070 airports have verified runway inventories; {missing_headings} ends lack true alignments')
            unavailable = [code for code, item in data['airport_coverage'].items()
                           if item['status'] != 'available']
            if unavailable:
                print('Runway data unavailable for: ' + ', '.join(unavailable))
            return
        except (OSError, ValueError, TypeError, zipfile.BadZipFile) as exc:
            failures.append(f'{cycle}: {exc}')
    sys.exit('No valid FAA runway archive available. Existing data untouched. ' + ' | '.join(failures))


if __name__ == '__main__':
    main()
