"""Offline FAA NASR runway inventory tests; no provider calls."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

from scripts import update_runways

ALL_CODES = sorted(update_runways.AIRPORTS)
LEGACY_PAIRS = {
    'ORD': ['04L/22R', '04R/22L', '09L/27R', '09R/27L', '09C/27C',
            '10L/28R', '10C/28C', '10R/28L'],
    'LAX': ['06L/24R', '06R/24L', '07L/25R', '07R/25L'],
    'JFK': ['04L/22R', '04R/22L', '13L/31R', '13R/31L'],
    'MEM': ['09/27', '18C/36C', '18L/36R', '18R/36L'],
}


def make_rows(codes=ALL_CODES):
    rows = []
    for code in codes:
        for pair in LEGACY_PAIRS.get(code, ['09/27']):
            for rid in pair.split('/'):
                rows.append({'ARPT_ID': code, 'RWY_END_ID': rid, 'RWY_ID': pair,
                             'TRUE_ALIGNMENT': '090' if rid.startswith(('09', '10')) else '270'})
    return rows


def archive(rows, columns=('ARPT_ID', 'RWY_END_ID', 'RWY_ID', 'TRUE_ALIGNMENT')):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    zipbytes = io.BytesIO()
    with zipfile.ZipFile(zipbytes, 'w') as output:
        output.writestr('APT_RWY_END.csv', buffer.getvalue())
    zipbytes.seek(0)
    return zipfile.ZipFile(zipbytes)


class NasrC070RunwayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out_patch = mock.patch.object(update_runways, 'OUT', Path(self.temp.name) / 'data' / 'runways.json')
        self.out_patch.start()
        self.addCleanup(self.out_patch.stop)
        self.network = mock.patch.object(update_runways.urllib.request, 'urlopen',
                                         side_effect=AssertionError('No network permitted during tests'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def run_generate(self, rows, **kwargs):
        with archive(rows, **kwargs) as file:
            return update_runways.generate(file, 'https://nfdc.faa.gov/test-synthetic.zip', date(2026, 10, 29))

    def test_all_130_registered_airports_have_runway_inventories(self):
        self.assertEqual(len(ALL_CODES), 130)
        result = self.run_generate(make_rows())
        self.assertEqual(set(result['airports']), set(ALL_CODES))
        self.assertEqual(len(result['airport_coverage']), 130)
        self.assertEqual(len(result['airports']['ORD']), 16)
        self.assertEqual(len(result['airports']['LAX']), 8)
        self.assertEqual(len(result['airports']['JFK']), 8)
        self.assertEqual(len(result['airports']['MEM']), 8)
        self.assertEqual(result['heading_reference'], 'TRUE')
        self.assertEqual(result['effective_date'], '2026-10-29')

    def test_missing_true_alignment_keeps_end_without_inventing_bearing(self):
        rows = make_rows()
        target = next(row for row in rows if row['ARPT_ID'] == 'ORD')
        target['TRUE_ALIGNMENT'] = ''
        result = self.run_generate(rows)
        self.assertEqual(result['airport_coverage']['ORD']['missing_true_alignments'], 1)
        end = next(end for end in result['airports']['ORD'] if end['id'] == target['RWY_END_ID'])
        self.assertIsNone(end['true_heading'])
        self.assertEqual({x['id'] for x in result['airports']['ORD']},
                         {r['RWY_END_ID'] for r in rows if r['ARPT_ID'] == 'ORD'})

    def test_malformed_secondary_airport_is_reported_and_not_silently_partial(self):
        code = next(code for code in ALL_CODES if code not in LEGACY_PAIRS)
        rows = make_rows()
        bad = next(row for row in rows if row['ARPT_ID'] == code)
        bad['TRUE_ALIGNMENT'] = 'Infinity'
        result = self.run_generate(rows)
        self.assertNotIn(code, result['airports'])
        self.assertEqual(result['airport_coverage'][code]['reason'], 'invalid_true_alignment')
        self.assertEqual(len(result['airports']), 129)
        self.assertIn('ORD', result['airports'])

    def test_missing_airport_has_explicit_unknown_coverage(self):
        code = next(code for code in ALL_CODES if code not in LEGACY_PAIRS)
        result = self.run_generate([r for r in make_rows() if r['ARPT_ID'] != code])
        self.assertNotIn(code, result['airports'])
        self.assertEqual(result['airport_coverage'][code]['status'], 'unavailable')
        self.assertEqual(result['airport_coverage'][code]['reason'], 'not_in_nasr_runway_end_table')

    def test_missing_reciprocal_or_duplicate_end_rejects_whole_airport(self):
        code = next(code for code in ALL_CODES if code not in LEGACY_PAIRS)
        source = make_rows()
        extra = {**next(row for row in source if row['ARPT_ID'] == code)}
        result = self.run_generate(source + [extra])
        self.assertEqual(result['airport_coverage'][code]['reason'], 'invalid_or_duplicate_runway_end')
        result = self.run_generate([r for r in source if not (r['ARPT_ID'] == code and r['RWY_END_ID'] == '27')])
        self.assertEqual(result['airport_coverage'][code]['reason'], 'incomplete_runway_end_inventory')

    def test_legacy_airport_regression_prevents_publication(self):
        source = make_rows()
        with self.assertRaisesRegex(ValueError, 'ORD'):
            self.run_generate([r for r in source if not (r['ARPT_ID'] == 'ORD' and r['RWY_END_ID'] == '04L')])

    def test_unrecognized_schema_and_empty_table_refused(self):
        with self.assertRaisesRegex(ValueError, 'schema'):
            self.run_generate(make_rows(), columns=('ARPT_ID', 'RWY_END_ID'))
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.run_generate([])

    def test_atomic_write_and_identical_snapshot_preserved(self):
        result = self.run_generate(make_rows())
        self.assertTrue(update_runways.publish(result))
        before = update_runways.OUT.read_bytes()
        self.assertEqual(json.loads(before)['airports']['MEM'][0]['id'], '09')
        self.assertFalse(update_runways.publish(result))
        self.assertEqual(update_runways.OUT.read_bytes(), before)
        self.assertTrue(update_runways.publish({**result, 'effective_date': '2026-11-26'}))
        self.assertNotEqual(update_runways.OUT.read_bytes(), before)

    def test_cycle_date_logic_uses_two_existing_archive_requests(self):
        self.assertEqual(list(update_runways.cycle_dates(date(2026, 11, 24))),
                         [date(2026, 10, 29), date(2026, 10, 1)])


if __name__ == '__main__':
    unittest.main()
