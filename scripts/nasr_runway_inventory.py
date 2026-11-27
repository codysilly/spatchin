"""Build C070 fixed-wing runway inventories from FAA NASR CSV tables."""
import csv
import io
import re
from collections import defaultdict

END = re.compile(r'(?:0[1-9]|[12][0-9]|3[0-6])[LRC]?\Z')
PAD = re.compile(r'H(?:[1-9][0-9]*|[A-Z])\Z')
AUXILIARY = {('ORD', '10X'), ('DTW', '04X/22X'), ('SNA', '20X')}
SOURCE = 'FAA NASR 28-Day Subscription — APT_BASE.csv / APT_RWY.csv / APT_RWY_END.csv'


def table(archive, name, fields, cycle):
    matches = [n for n in archive.namelist() if n.rsplit('/', 1)[-1] == name]
    if len(matches) != 1:
        raise ValueError(f'Expected one {name}')
    with archive.open(matches[0]) as stream:
        reader = csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig'))
        if not set(fields) | {'EFF_DATE'} <= set(reader.fieldnames or []):
            raise ValueError(f'Invalid {name} schema')
        rows = list(reader)
    if not rows or any(row['EFF_DATE'] != cycle.strftime('%Y/%m/%d') for row in rows):
        raise ValueError(f'Empty or wrong-cycle {name}')
    return rows


def variation(row):
    value, direction, year = row['MAG_VARN'], row['MAG_HEMIS'], row['MAG_VARN_YEAR']
    if not (value.isdigit() and 0 <= int(value) <= 180 and direction in ('E', 'W')
            and year.isdigit() and 1900 <= int(year) <= 2100):
        return None, None
    return int(value) * (-1 if direction == 'W' else 1), int(year)


def generate_inventory(archive, url, cycle, stations):
    bases = table(archive, 'APT_BASE.csv', ('SITE_NO', 'ARPT_ID', 'ICAO_ID', 'MAG_VARN',
                  'MAG_HEMIS', 'MAG_VARN_YEAR'), cycle)
    pairs = table(archive, 'APT_RWY.csv', ('SITE_NO', 'ARPT_ID', 'RWY_ID', 'RWY_LEN',
                  'SURFACE_TYPE_CODE'), cycle)
    ends = table(archive, 'APT_RWY_END.csv', ('SITE_NO', 'ARPT_ID', 'RWY_ID', 'RWY_END_ID',
                 'ILS_TYPE'), cycle)
    icao_to_code = {icao: code for code, icao in stations.items()}
    identities = defaultdict(list)
    for row in bases:
        if row['ICAO_ID'] in icao_to_code:
            identities[icao_to_code[row['ICAO_ID']]].append(row)
    sites = {}
    for code in sorted(stations):
        matches = identities[code]
        if len(matches) != 1:
            raise ValueError(f'{code}: missing or ambiguous facility')
        row = matches[0]
        if not row['SITE_NO'] or not row['ARPT_ID'] or row['SITE_NO'] in sites:
            raise ValueError(f'{code}: invalid or duplicate facility identity')
        sites[row['SITE_NO']] = code

    def group(rows):
        result = defaultdict(list)
        for row in rows:
            code = sites.get(row['SITE_NO'])
            if code is not None:
                if row['ARPT_ID'] != identities[code][0]['ARPT_ID']:
                    raise ValueError(f'{code}: inconsistent facility identifier')
                result[code].append(row)
        return result

    pair_rows, end_rows = group(pairs), group(ends)
    airports, coverage, metadata = {}, {}, {}
    for code in sorted(stations):
        by_pair = defaultdict(list)
        for row in end_rows[code]:
            by_pair[row['RWY_ID']].append(row)
        seen_pairs, seen_ends, inventory, excluded = set(), set(), [], []
        for row in pair_rows[code]:
            pair = row['RWY_ID']
            if pair in seen_pairs:
                raise ValueError(f'{code}: duplicate runway record {pair}')
            seen_pairs.add(pair)
            names = pair.split('/')
            records = by_pair.pop(pair, [])
            if sorted(r['RWY_END_ID'] for r in records) != sorted(names):
                raise ValueError(f'{code}: incomplete or conflicting ends for {pair}')
            length = row['RWY_LEN']
            surface = row['SURFACE_TYPE_CODE']
            if len(names) == 2 and len(set(names)) == 2 and all(END.fullmatch(n) for n in names):
                if not length.isdigit() or int(length) <= 0:
                    raise ValueError(f'{code}: invalid physical runway length {pair}')
                for name in names:
                    if name in seen_ends:
                        raise ValueError(f'{code}: duplicate physical end {name}')
                    seen_ends.add(name)
                    inventory.append({'id': name, 'magnetic_heading': int(name[:2]) * 10 % 360,
                                      'pair': pair})
            elif PAD.fullmatch(pair) and length.isdigit() and int(length) > 0 and surface and not records[0]['ILS_TYPE']:
                excluded.append({'id': pair, 'reason': 'helipad'})
            elif (code, pair) in AUXILIARY and length == '0' and not surface and all(r['ILS_TYPE'] for r in records):
                excluded.append({'id': pair, 'reason': 'alternate_approach_system'})
            else:
                raise ValueError(f'{code}: unclassified runway record {pair}')
        if by_pair or not inventory:
            raise ValueError(f'{code}: orphan runway ends or empty inventory')
        airports[code] = sorted(inventory, key=lambda item: item['id'])
        coverage[code] = {'status': 'available', 'runway_ends': len(inventory)}
        if excluded:
            coverage[code]['excluded_non_runway_records'] = sorted(excluded, key=lambda item: item['id'])
        degrees, year = variation(identities[code][0])
        metadata[code] = {'heading_method': 'runway-designation-magnetic',
                          'magnetic_variation_deg': degrees, 'magnetic_variation_year': year}
    return {'source': SOURCE, 'source_url': url, 'effective_date': cycle.isoformat(),
            'heading_reference': 'MAGNETIC', 'airports': airports, 'airport_coverage': coverage,
            'airport_metadata': metadata}
