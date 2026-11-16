import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from c070_notam_partition import c070_codes
from reconcile_c070_domestic import main, reconcile


class ReconcileDomesticTests(unittest.TestCase):
    def registry(self):
        return {'airports': [{'iata': code, 'icao': 'K' + code,
                              'name': code + ' airport',
                              'source_coverage': {'notams': 'UNKNOWN'}}
                             for code in c070_codes()]}

    def feature(self, iata='MEM', icao='KMEM', identifier='source-1', **changes):
        notice = {'id': identifier, 'number': '01/001', 'text': 'RAW\r\nLOCAL',
                  'issued': '2026-11-16T00:00:00Z',
                  'effectiveStart': '2026-11-16T00:00:00Z',
                  'effectiveEnd': 'PERM', 'lastUpdated': '2026-11-16T00:00:00Z',
                  'location': iata, 'icaoLocation': icao}
        notice.update(changes)
        return {'properties': {'coreNOTAMData': {'notam': notice,
                'notamTranslation': [{'type': 'LOCAL_FORMAT', 'formattedText': '!MEM exact'}]}}}

    def test_all_airports_and_exact_source_fields_are_preserved(self):
        payload = [self.feature(), self.feature(identifier='source-2', text='exact\r\ntext')]
        summary, candidate, evidence = reconcile(payload, self.registry(), retrieved_utc='2026-11-16T12:00:00Z')
        self.assertEqual(len(summary['per_airport_counts']), 130)
        self.assertEqual(summary['per_airport_counts']['KMEM'], 2)
        self.assertEqual(summary['assigned_record_count'], 2)
        self.assertTrue(summary['accounting_reconciled'])
        notice = candidate['airports']['KMEM']['notices'][1]
        self.assertEqual(notice['id'], 'source-2')
        self.assertEqual(notice['text'], 'exact\r\ntext')
        self.assertEqual(notice['issued'], '2026-11-16T00:00:00Z')
        self.assertEqual(notice['formatted_texts'][0]['text'], '!MEM exact')
        self.assertNotIn('original_feature', notice)
        self.assertEqual(evidence['assigned_source_evidence']['KMEM'][0]['original_feature'], payload[0])

    def test_accounting_duplicates_conflicts_outside_and_missing_are_explicit(self):
        payload = [self.feature(identifier='same'), self.feature(identifier='same'),
                   self.feature('MEM', 'KORD'), self.feature('ZZZ', 'KZZZ'),
                   self.feature(icao=None), self.feature(identifier=None)]
        summary, candidate, _ = reconcile(payload, self.registry(), retrieved_utc='2026-11-16T12:00:00Z')
        self.assertEqual(summary['input_record_count'], 6)
        self.assertEqual(summary['assigned_record_count'], 3)
        self.assertEqual(summary['excluded_record_count'], 3)
        self.assertEqual(summary['exception_counts']['conflicting_identifiers'], 1)
        self.assertEqual(summary['exception_counts']['outside_c070'], 1)
        self.assertEqual(summary['exception_counts']['missing_or_invalid_identifiers'], 1)
        self.assertEqual(summary['exception_counts']['duplicate_source_id_groups'], 1)
        self.assertEqual(summary['exception_counts']['records_with_duplicate_source_ids'], 2)
        self.assertEqual(summary['missing_required_field_counts']['id'], 1)
        self.assertEqual(candidate['airports']['KATL']['completeness'], 'UNKNOWN')
        self.assertEqual(candidate['airports']['KATL']['notices'], [])

    def test_envelope_and_output_are_deterministic_and_unknown(self):
        payload = {'status': 'Success', 'data': {'geojson': [self.feature()]}}
        first = reconcile(payload, self.registry(), retrieved_utc='2026-11-16T12:00:00Z')[:2]
        second = reconcile(copy.deepcopy(payload), self.registry(), retrieved_utc='2026-11-16T12:00:00Z')[:2]
        self.assertEqual(first, second)
        self.assertEqual(first[1]['partition']['coverage'], 'UNKNOWN')
        self.assertIn('not an FAA airport-specific', first[1]['airports']['KMEM']['warning'])

    def test_invalid_and_oversized_inputs_fail_without_writes_or_network(self):
        with self.assertRaisesRegex(ValueError, 'input byte limit'):
            reconcile([self.feature()], self.registry(), retrieved_utc='2026-11-16T12:00:00Z', max_input_bytes=1)
        with self.assertRaisesRegex(ValueError, 'UTC capture'):
            reconcile([self.feature()], self.registry(), retrieved_utc='not-a-timestamp')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'capture.json'
            source.write_text(json.dumps([self.feature()]), encoding='utf-8')
            output = Path(directory) / 'summary.json'
            args = ['--capture', str(source), '--retrieved-utc', '2026-11-16T12:00:00Z',
                    '--summary', str(output), '--report', str(Path(directory) / 'report.txt'),
                    '--candidate', str(Path(directory) / 'candidate.json'),
                    '--evidence', str(Path(directory) / 'evidence.json'), '--max-input-bytes', '1']
            with patch('socket.socket', side_effect=AssertionError('network forbidden')):
                with self.assertRaises(SystemExit):
                    main(args)
            self.assertFalse(output.exists())

    def test_cli_refuses_repository_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'capture.json'
            source.write_text(json.dumps([self.feature()]), encoding='utf-8')
            public_snapshot = (ROOT / 'data' / 'notams.json').read_bytes()
            args = ['--capture', str(source), '--retrieved-utc', '2026-11-16T12:00:00Z',
                    '--summary', str(ROOT / 'private-summary.json'), '--report', str(Path(directory) / 'report.txt'),
                    '--candidate', str(Path(directory) / 'candidate.json'), '--evidence', str(Path(directory) / 'evidence.json')]
            with self.assertRaises(SystemExit):
                main(args)
            self.assertEqual((ROOT / 'data' / 'notams.json').read_bytes(), public_snapshot)


if __name__ == '__main__':
    unittest.main()
