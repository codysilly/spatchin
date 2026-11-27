#!/usr/bin/env python3
"""Publish verified FAA NASR runway inventories and nominal magnetic headings."""
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
    from .nasr_runway_inventory import generate_inventory
else:
    try:
        from scripts.c070_station_registry import load_c070_stations
        from scripts.nasr_runway_inventory import generate_inventory
    except ModuleNotFoundError as exc:
        if exc.name != 'scripts':
            raise
        from c070_station_registry import load_c070_stations
        from nasr_runway_inventory import generate_inventory

AIRPORTS = frozenset(load_c070_stations())  # Verified IATA IDs, not K+IATA guesses.
LEGACY_COUNTS = {'ORD': 16, 'LAX': 8, 'JFK': 8, 'MEM': 8}
END_ID = re.compile(r'(?:0[1-9]|[12][0-9]|3[0-6])[LRC]?\Z')
# FAA AMR data dictionary: H-number identifiers are helipads.
HELIPAD_ID = re.compile(r'H[1-9][0-9]*\Z')
# ORD A30-10X: alternate ILS for physical runway 10R, not another runway.
# https://airnav.com/airport/ORD
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
    required = {
        'APT_BASE.csv': {'SITE_NO', 'ARPT_ID', 'ICAO_ID'},
        'APT_RWY_END.csv': {'SITE_NO', 'ARPT_ID', 'RWY_END_ID', 'TRUE_ALIGNMENT', 'RWY_ID'},
    }.get(filename)
    if not required or not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError('FAA runway-end schema not recognized; refusing to publish')
    return list(reader)


def generate(archive, url, cycle):
    # Legacy true-alignment contract retained for historical offline regressions only.
    # FAA location identifiers are not reliable facility joins on their own.
    # Map verified C070 ICAOs to unique NASR SITE_NO values in APT_BASE,
    # then read only the runway ends belonging to those exact facilities.
    icao_to_code = {icao: code for code, icao in load_c070_stations().items()}
    bases = get_table(archive, 'APT_BASE.csv')
    if not bases:
        raise ValueError('FAA airport base table is empty')
    by_code = {code: [] for code in AIRPORTS}
    for row in bases:
        code = icao_to_code.get((row.get('ICAO_ID') or '').strip().upper())
        if code is not None:
            by_code[code].append((
                (row.get('SITE_NO') or '').strip(),
                (row.get('ARPT_ID') or '').strip().upper(),
            ))

    invalid = {}
    rejected_samples = {}
    excluded = {code: [] for code in AIRPORTS}

    def record_rejection(code, category, runway_end='', runway_pair='', raw_heading=''):
        # FAA runway identifiers are public, but keep production failure logs bounded.
        samples = rejected_samples.setdefault(code, [])
        if len(samples) < 3:
            samples.append({
                'category': category,
                'runway_end': runway_end[:8],
                'runway_pair': runway_pair[:16],
                'true_alignment': 'missing' if not raw_heading else 'present',
            })

    site_candidates = {}
    for code, identities in by_code.items():
        if not identities:
            invalid[code] = 'not_in_nasr_airport_base'
        elif len(identities) != 1 or not all(identities[0]):
            invalid[code] = 'ambiguous_nasr_airport_identity'
        else:
            site, airport_id = identities[0]
            site_candidates.setdefault(site, []).append((code, airport_id))

    by_site = {}
    for site, matches in site_candidates.items():
        if len(matches) == 1:
            by_site[site] = matches[0]
        else:
            for code, _ in matches:
                invalid[code] = 'ambiguous_nasr_site_number'

    rows = get_table(archive, 'APT_RWY_END.csv')
    if not rows:
        raise ValueError('FAA runway-end table is empty')
    found = {code: [] for code in AIRPORTS}
    seen = {code: set() for code in AIRPORTS}
    for row in rows:
        identity = by_site.get((row.get('SITE_NO') or '').strip())
        if identity is None:
            continue
        code, airport_id = identity
        if (row.get('ARPT_ID') or '').strip().upper() != airport_id:
            invalid.setdefault(code, 'nasr_airport_identity_mismatch')
            continue
        rid = (row.get('RWY_END_ID') or '').strip().upper()
        pair = (row.get('RWY_ID') or '').strip().upper()
        raw = (row.get('TRUE_ALIGNMENT') or '').strip()
        # Only exclude documented, single-record non-runway identifiers.
        # Unknown or paired identifiers remain subject to fail-closed validation.
        auxiliary_reason = None
        if pair == rid and not raw:
            if HELIPAD_ID.fullmatch(rid):
                auxiliary_reason = 'helipad'
            elif code == 'ORD' and rid == '10X':
                auxiliary_reason = 'alternate_ils_for_10R'
        if auxiliary_reason and rid not in seen[code]:
            seen[code].add(rid)
            excluded[code].append({'id': rid, 'reason': auxiliary_reason})
            continue
        rejection = None
        if not END_ID.fullmatch(rid):
            rejection = 'invalid_runway_end_id'
        elif rid in seen[code]:
            rejection = 'duplicate_runway_end_id'
        elif not pair:
            rejection = 'missing_runway_pair'
        if rejection:
            invalid.setdefault(code, 'invalid_or_duplicate_runway_end')
            record_rejection(code, rejection, rid, pair, raw)
            continue
        seen[code].add(rid)
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
            available = {e['id'] for e in ends}
            for end in ends:
                pair_ends = end['pair'].split('/')
                if len(pair_ends) != 2 or end['id'] not in pair_ends or not set(pair_ends).issubset(available):
                    reason = 'incomplete_runway_pair'
                    break
        if reason:
            coverage[code] = {'status': 'unavailable', 'reason': reason}
            if excluded[code]:
                coverage[code]['excluded_non_runway_records'] = sorted(excluded[code], key=lambda item: item['id'])
            continue
        ends.sort(key=lambda e: (int(e['id'][:2]), e['id']))
        airports[code] = ends
        coverage[code] = {
            'status': 'available',
            'runway_ends': len(ends),
            'missing_true_alignments': sum(e['true_heading'] is None for e in ends),
        }
        if excluded[code]:
            coverage[code]['excluded_non_runway_records'] = sorted(excluded[code], key=lambda item: item['id'])

    # Preserve the four already verified airports; refuse an update that loses them.
    for code in LEGACY_COUNTS:
        if code not in airports:
            details = rejected_samples.get(code, [])
            diagnostic = f'; rejected_examples={json.dumps(details, sort_keys=True)}' if details else ''
            raise ValueError(f'{code}: {coverage[code]["reason"]}{diagnostic}; refusing to replace existing data')
    return {
        'source': 'FAA NASR 28-Day Subscription — APT_BASE.csv / APT_RWY_END.csv',
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
                data = generate_inventory(archive, url, cycle, load_c070_stations())
            for code, count in LEGACY_COUNTS.items():
                if len(data['airports'][code]) != count:
                    raise ValueError(f'{code}: legacy inventory count changed; review before publication')
            publish(data)
            available = len(data['airports'])
            total_ends = sum(len(items) for items in data['airports'].values())
            print(f'FAA NASR cycle {cycle}: {available}/{len(AIRPORTS)} C070 airports have verified runway inventories; {total_ends} physical runway ends')
            unavailable = [code for code, item in data['airport_coverage'].items()
                           if item['status'] != 'available']
            if unavailable:
                print('Runway data unavailable for: ' + ', '.join(unavailable))
            for code, item in data['airport_coverage'].items():
                if item.get('excluded_non_runway_records'):
                    print(f'{code}: excluded non-runway records: {json.dumps(item["excluded_non_runway_records"], sort_keys=True)}')
            return
        except (OSError, ValueError, TypeError, zipfile.BadZipFile) as exc:
            failures.append(f'{cycle}: {exc}')
    sys.exit('No valid FAA runway archive available. Existing data untouched. ' + ' | '.join(failures))


if __name__ == '__main__':
    main()
