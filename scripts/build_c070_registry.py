"""Build the C070 registry from saved FAA NASR and OurAirports CSV files.

Offline only.  The caller supplies downloaded public source files; this tool does
not fetch them and never reads NOTAM captures or credentials.
"""
import argparse
import csv
import json
from pathlib import Path

from c070_notam_partition import c070_codes, load_registry


NASR_COLUMNS = frozenset(('ARPT_ID', 'ICAO_ID', 'ARPT_NAME'))
OURAIRPORTS_COLUMNS = frozenset(('iata_code', 'icao_code', 'gps_code', 'name'))


def read_csv(path, required):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError('documented source columns missing')
        return list(reader)


def build(nasr_rows, ourairports_rows, *, codes=None):
    codes = tuple(codes or c070_codes())
    nasr = {}
    for row in nasr_rows:
        code = row.get('ARPT_ID')
        if code in codes:
            nasr.setdefault(code, []).append(row)
    secondary = {}
    for row in ourairports_rows:
        code = row.get('iata_code')
        if code in codes:
            secondary.setdefault(code, []).append(row)
    airports, exceptions = [], []
    for code in codes:
        rows = nasr.get(code, [])
        if len(rows) != 1 or not rows[0].get('ICAO_ID') or not rows[0].get('ARPT_NAME'):
            exceptions.append({'iata': code, 'kind': 'NASR_UNVERIFIABLE', 'nasr_match_count': len(rows)})
            continue
        row = rows[0]
        registry_icao = row['ICAO_ID'].strip()
        matches = secondary.get(code, [])
        cross_refs = {((item.get('icao_code') or item.get('gps_code') or '').strip()) for item in matches}
        cross_refs.discard('')
        if len(matches) != 1 or cross_refs != {registry_icao}:
            exceptions.append({'iata': code, 'kind': 'SECONDARY_CONFLICT_OR_MISSING',
                               'ourairports_match_count': len(matches),
                               'ourairports_icao_codes': sorted(cross_refs),
                               'nasr_icao': registry_icao})
        airports.append({'iata': code, 'icao': registry_icao, 'name': row['ARPT_NAME'].strip(),
                         'source_coverage': {'metar': 'UNKNOWN', 'atis': 'UNKNOWN',
                                             'runways': 'UNKNOWN', 'notams': 'UNKNOWN'}})
    # A secondary conflict is reported, not used to alter a NASR-backed mapping.
    load_registry(airports, codes=codes)
    return airports, exceptions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nasr-apt-base', required=True)
    parser.add_argument('--ourairports', required=True)
    parser.add_argument('--registry-out', required=True)
    parser.add_argument('--exceptions-out', required=True)
    args = parser.parse_args()
    airports, exceptions = build(read_csv(args.nasr_apt_base, NASR_COLUMNS),
                                 read_csv(args.ourairports, OURAIRPORTS_COLUMNS))
    Path(args.registry_out).write_text(json.dumps({'airports': airports}, indent=2) + '\n', encoding='utf-8')
    Path(args.exceptions_out).write_text(json.dumps({'exceptions': exceptions}, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
