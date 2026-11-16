import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from c070_notam_partition import c070_codes
import reconcile_c070_domestic as reconciler
from reconcile_c070_domestic import (main, reconcile, validate_private_candidate,
                                     validate_publication_conversion)


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
        self.assertEqual(summary['comparison_to_historical_c070_matches'], 2 - 3084)
        self.assertEqual(summary['comparison_to_historical_total_features'], 2 - 21024)
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

    def test_private_candidate_validates_with_reader_and_separate_conversion_contract(self):
        _summary, candidate, _evidence = reconcile([self.feature()], self.registry(), retrieved_utc='2026-11-16T12:00:00Z')
        projection = validate_private_candidate(candidate)
        self.assertNotIn('publication', candidate)
        self.assertNotIn('source', projection['airports']['KMEM']['notices'][0])
        conversion = validate_publication_conversion(candidate, {
            'mode': 'fixed snapshot', 'automatic_updates': False,
            'source_reference': 'https://notams.aim.faa.gov/notamSearch/'})
        self.assertEqual(conversion['publication']['automatic_updates'], False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'candidate.json'
            path.write_text(json.dumps(projection), encoding='utf-8')
            script = "const fs=require('fs');require('./notam-snapshots.js').validate(JSON.parse(fs.readFileSync(process.argv[1],'utf8')));"
            result = subprocess.run(['node', '-e', script, str(path)], cwd=ROOT,
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

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
                    '--evidence', str(Path(directory) / 'evidence.json'),
                    '--completion', str(Path(directory) / 'complete.json'), '--max-input-bytes', '1']
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
                    '--candidate', str(Path(directory) / 'candidate.json'), '--evidence', str(Path(directory) / 'evidence.json'),
                    '--completion', str(Path(directory) / 'complete.json')]
            with self.assertRaises(SystemExit):
                main(args)
            self.assertEqual((ROOT / 'data' / 'notams.json').read_bytes(), public_snapshot)

    def test_cli_writes_plain_text_and_completion_only_after_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'capture.json'
            source.write_text(json.dumps([self.feature()]), encoding='utf-8')
            outputs = {name: Path(directory) / name for name in ('summary.json', 'report.txt', 'candidate.json', 'evidence.json', 'complete.json')}
            args = ['--capture', str(source), '--retrieved-utc', '2026-11-16T12:00:00Z',
                    '--summary', str(outputs['summary.json']), '--report', str(outputs['report.txt']),
                    '--candidate', str(outputs['candidate.json']), '--evidence', str(outputs['evidence.json']),
                    '--completion', str(outputs['complete.json'])]
            self.assertEqual(main(args), 0)
            report = outputs['report.txt'].read_text(encoding='utf-8')
            self.assertTrue(report.startswith('Spatchin C070'))
            self.assertIn('\nAssigned:', report)
            self.assertFalse(report.startswith('"'))
            completion = json.loads(outputs['complete.json'].read_text(encoding='utf-8'))
            self.assertEqual(completion['state'], 'COMPLETE')

    def test_nonfinite_and_oversized_outputs_fail_before_completion_marker(self):
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            reconcile([self.feature(unexpected=float('inf'))], self.registry(), retrieved_utc='2026-11-16T12:00:00Z')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'capture.json'
            source.write_text(json.dumps([self.feature()]), encoding='utf-8')
            outputs = {name: Path(directory) / name for name in ('summary.json', 'report.txt', 'candidate.json', 'evidence.json', 'complete.json')}
            args = ['--capture', str(source), '--retrieved-utc', '2026-11-16T12:00:00Z',
                    '--summary', str(outputs['summary.json']), '--report', str(outputs['report.txt']),
                    '--candidate', str(outputs['candidate.json']), '--evidence', str(outputs['evidence.json']),
                    '--completion', str(outputs['complete.json']), '--max-output-bytes', '1']
            with self.assertRaises(SystemExit): main(args)
            self.assertFalse(any(path.exists() for path in outputs.values()))

    def test_commit_failure_never_creates_completion_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'capture.json'
            source.write_text(json.dumps([self.feature()]), encoding='utf-8')
            outputs = {name: Path(directory) / name for name in ('summary.json', 'report.txt', 'candidate.json', 'evidence.json', 'complete.json')}
            args = ['--capture', str(source), '--retrieved-utc', '2026-11-16T12:00:00Z',
                    '--summary', str(outputs['summary.json']), '--report', str(outputs['report.txt']),
                    '--candidate', str(outputs['candidate.json']), '--evidence', str(outputs['evidence.json']),
                    '--completion', str(outputs['complete.json'])]
            actual_replace = reconciler.os.replace
            calls = [0]
            def fail_second_replace(source_path, destination_path):
                calls[0] += 1
                if calls[0] == 2:
                    raise OSError('synthetic failure')
                return actual_replace(source_path, destination_path)
            with patch.object(reconciler.os, 'replace', side_effect=fail_second_replace):
                with self.assertRaises(SystemExit): main(args)
            self.assertTrue(outputs['summary.json'].exists())
            self.assertFalse(outputs['complete.json'].exists())


if __name__ == '__main__':
    unittest.main()
