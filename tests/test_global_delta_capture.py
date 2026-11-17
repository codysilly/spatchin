"""Socket-blocked tests for the supervised global delta evidence capture."""
import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))

from capture_global_delta import (STORAGE_REQUIRED_BYTES, execute, operation, operation_digest,
                                  proposed_since, review)
from nms_refresh_contract import RefreshError
from test_nms_refresh import CREDENTIALS, NOW, TOKEN, encode, feature, synthetic_store


def envelope(features):
    return {'status': 'Success', 'data': {'geojson': features}}


class Transport:
    def __init__(self, body=None, failure=None):
        self.body = body if body is not None else encode(envelope([feature()]))
        self.failure = failure
        self.requests = []

    def __call__(self, request, limit):
        self.requests.append(request)
        if self.failure == request.stage:
            raise TimeoutError()
        if request.stage == 'auth':
            return 200, {}, encode({'access_token': TOKEN})
        return 200, {}, self.body


class GlobalDeltaCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = synthetic_store(self.temp.name)
        parent = self.store.root / 'initial-load-evidence'
        self.store.storage.create_attempt(parent)
        attempt = 'synthetic-initial-attempt'
        evidence = parent / attempt
        self.store.storage.create_attempt(evidence)
        receipt = {'schema': 1, 'attempt': attempt,
                   'capture_started_utc': NOW.isoformat(),
                   'capture_completed_utc': (NOW + timedelta(seconds=10)).isoformat(),
                   'baseline_established': False, 'watermark': None}
        self.store.storage.private_write(evidence / 'receipt.json', encode(receipt))
        self.since = (NOW.replace(microsecond=0) - timedelta(seconds=1)).isoformat()

    def code(self, expected, call):
        with self.assertRaises(RefreshError) as got:
            call()
        self.assertEqual(str(got.exception), expected)

    def test_default_review_is_read_only_and_reports_exact_global_request(self):
        before = {str(path.relative_to(self.store.root)): path.read_bytes()
                  for path in self.store.root.rglob('*') if path.is_file()}
        with patch.object(socket, 'socket', side_effect=AssertionError), \
                patch.object(socket, 'getaddrinfo', side_effect=AssertionError):
            result = review(self.store, NOW + timedelta(minutes=1))
        after = {str(path.relative_to(self.store.root)): path.read_bytes()
                 for path in self.store.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(proposed_since(self.store), self.since)
        self.assertEqual(result['intended_request'], {
            'method': 'GET', 'path': '/nmsapi/v1/notams',
            'lastUpdatedDate_utc': '2026-01-02T11:59:59Z',
            'nmsResponseFormat': 'GEOJSON'})
        self.assertFalse(result['operation']['delta']['airport_filters'])
        self.assertFalse(result['operation']['delta']['classification_filters'])
        self.assertFalse(result['credentials_read'])
        self.assertFalse(result['provider_requests_made'])
        self.assertEqual(len(result['operation_approval_digest']), 64)

    def test_expired_initial_window_is_reported_without_write(self):
        result = review(self.store, NOW + timedelta(hours=25))
        self.assertFalse(result['within_documented_24_hour_lookback'])
        self.assertIn('DELTA_GAP', result['blockers'])
        self.assertEqual(result['timestamp_diagnostic'], 'DELTA_GAP')
        self.assertFalse(result['locally_eligible'])

    def test_future_valid_and_whole_second_timestamp_preflight_match_execution(self):
        future = (NOW + timedelta(seconds=1)).isoformat()
        result = review(self.store, NOW, future)
        self.assertEqual(result['timestamp_diagnostic'], 'CLOCK_ROLLBACK')
        self.assertIn('CLOCK_ROLLBACK', result['blockers'])
        self.assertFalse(result['locally_eligible'])
        transport = Transport()
        self.code('CLOCK_ROLLBACK', lambda: execute(
            self.store, since=future, credentials=CREDENTIALS,
            transport=transport, clock=lambda: NOW))
        self.assertEqual(transport.requests, [])

        precise = (NOW - timedelta(minutes=1, microseconds=123456)).isoformat()
        valid = review(self.store, NOW, precise)
        self.assertIsNone(valid['timestamp_diagnostic'])
        self.assertTrue(valid['within_documented_24_hour_lookback'])
        self.assertEqual(valid['intended_request']['lastUpdatedDate_utc'],
                         '2026-01-02T11:58:59Z')

    def test_capture_preserves_validated_raw_bytes_and_receipt_without_state_change(self):
        cancellation_type = feature()
        record = cancellation_type['properties']['coreNOTAMData']['notam']
        record['type'] = 'NOTAMC'
        date_only = feature('SYNTHETIC-DATE-ONLY')
        date_record = date_only['properties']['coreNOTAMData']['notam']
        date_record['cancelationDate'] = '2026-01-02T12:00:00Z'
        date_record['status'] = 'PROVIDER-SUPPLIED-UNINTERPRETED'
        body = encode(envelope([cancellation_type, date_only, date_only]))
        transport = Transport(body)
        result = execute(self.store, since=self.since, credentials=CREDENTIALS,
                         transport=transport, clock=lambda: NOW)
        self.assertEqual([item.stage for item in transport.requests], ['auth', 'delta'])
        self.assertEqual(operation(self.since)['delta']['query']['lastUpdatedDate'],
                         '2026-01-02T11:59:59Z')
        evidence = self.store.root / 'delta-probe-evidence' / result['attempt']
        self.assertEqual((evidence / 'response.geojson').read_bytes(), body)
        receipt = json.loads((evidence / 'receipt.json').read_bytes())
        self.assertEqual(receipt['sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(receipt['diagnostic_counts']['duplicate_source_ids'], 1)
        self.assertEqual(
            receipt['diagnostic_counts']['records_with_cancelation_date_field'], 2)
        self.assertEqual(
            receipt['diagnostic_counts']['records_with_provider_cancellation_type'], 1)
        self.assertEqual(
            receipt['diagnostic_counts']['records_with_other_provider_lifecycle_fields'], 2)
        with self.store.review_connect() as db:
            state = self.store.load(db)
            self.assertFalse(state['baseline'])
            self.assertIsNone(state['watermark'])
            self.assertEqual(state['catalog'], {})
            self.assertEqual(db.execute('SELECT status FROM attempts').fetchone()[0],
                             'CAPTURED_DELTA_PROBE')

    def test_malformed_response_is_not_valid_evidence_and_no_retry_occurs(self):
        transport = Transport(b'{')
        self.code('INVALID_RESPONSE', lambda: execute(
            self.store, since=self.since, credentials=CREDENTIALS,
            transport=transport, clock=lambda: NOW))
        self.assertEqual([item.stage for item in transport.requests], ['auth', 'delta'])
        with self.store.review_connect() as db:
            self.assertEqual(db.execute('SELECT status FROM attempts').fetchone()[0],
                             'FAILED_ACCOUNTED')

    def test_transport_failure_has_no_retry_and_is_accounted(self):
        transport = Transport(failure='delta')
        self.code('TRANSPORT_FAILED', lambda: execute(
            self.store, since=self.since, credentials=CREDENTIALS,
            transport=transport, clock=lambda: NOW))
        self.assertEqual([item.stage for item in transport.requests], ['auth', 'delta'])

    def test_three_minute_account_gate_blocks_before_credentials_or_transport(self):
        first = Transport()
        execute(self.store, since=self.since, credentials=CREDENTIALS,
                transport=first, clock=lambda: NOW)
        second = Transport()
        self.code('BUDGET_WAIT', lambda: execute(
            self.store, since=self.since, credentials=CREDENTIALS,
            transport=second, clock=lambda: NOW + timedelta(minutes=2)))
        self.assertEqual(second.requests, [])
        report = self.store.delta_budget_review(NOW + timedelta(minutes=2))
        self.assertIn('ACCOUNT_WIDE_THREE_MINUTE_WAIT', report['blockers'])

    def test_imported_uncertainty_is_explicit_but_not_a_permanent_local_block(self):
        old = (NOW - timedelta(hours=1)).isoformat()
        with self.store.connect() as db, self.store.transaction(db):
            state = self.store.load(db)
            db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)',
                       ('uncertain', 'other-data', old, old,
                        'IMPORTED_UNCERTAIN', 'HISTORY_UNCERTAIN'))
            state['attempt_count'] += 1
            self.store.save(db, state)
        result = review(self.store, NOW)
        budget = result['budget']
        self.assertTrue(budget['local_three_minute_interval_elapsed'])
        self.assertFalse(budget['pending_or_recovery_attempt_present'])
        self.assertTrue(budget['historical_uncertainty_present'])
        self.assertEqual(budget['historical_uncertainty_count'], 1)
        self.assertEqual(budget['ambiguous_attempts'][0]['status'],
                         'IMPORTED_UNCERTAIN')
        self.assertNotIn('RECOVERY_REQUIRED', budget['blockers'])
        self.assertIn('EXTERNAL_ACCOUNT_ACTIVITY_ATTESTATION_REQUIRED',
                      result['blockers'])

    def test_storage_preflight_and_execution_fail_closed_before_reservation(self):
        usage = namedtuple('usage', 'total used free')(
            STORAGE_REQUIRED_BYTES, STORAGE_REQUIRED_BYTES, 0)
        with patch('capture_global_delta.shutil.disk_usage', return_value=usage):
            result = review(self.store, NOW)
            self.assertFalse(result['storage_ready'])
            self.assertEqual(result['storage_required_bytes'], STORAGE_REQUIRED_BYTES)
            self.assertIn('INSUFFICIENT_PRIVATE_STORAGE', result['blockers'])
            transport = Transport()
            self.code('HISTORY_OR_STORAGE_UNAVAILABLE', lambda: execute(
                self.store, since=self.since, credentials=CREDENTIALS,
                transport=transport, clock=lambda: NOW))
        self.assertEqual(transport.requests, [])
        with self.store.review_connect() as db:
            self.assertEqual(self.store.load(db)['attempt_count'], 0)

        with patch('capture_global_delta.shutil.disk_usage', side_effect=OSError):
            result = review(self.store, NOW)
            self.assertFalse(result['storage_ready'])
            self.assertIsNone(result['storage_free_bytes'])
            self.assertEqual(result['storage_diagnostic'],
                             'PRIVATE_STORAGE_CAPACITY_UNAVAILABLE')
            self.assertIn('PRIVATE_STORAGE_CAPACITY_UNAVAILABLE', result['blockers'])

    def test_equal_timestamp_conflicts_and_stale_revisions_remain_fail_closed(self):
        from nms_baseline_candidate import CandidateError, reconcile_delta
        candidate = {'schema': 1, 'baseline_established': False, 'watermark': None,
                     'catalog': {}, 'unresolved_records': []}
        # This guard is covered more fully by test_nms_baseline_candidate; the
        # capture itself deliberately does not reconcile or publish evidence.
        with self.assertRaises(CandidateError):
            reconcile_delta(candidate, envelope([]),
                            requested_since_utc=self.since,
                            received_utc=(NOW + timedelta(hours=25)).isoformat())

    def test_digest_is_bound_to_lower_bound(self):
        self.assertNotEqual(operation_digest(self.since),
                            operation_digest((NOW - timedelta(seconds=2)).isoformat()))

    def test_wrong_digest_cli_stops_before_credentials_or_network(self):
        child = subprocess.run([
            sys.executable, '-B', str(SCRIPTS / 'capture_global_delta.py'),
            '--store', str(self.store.root), '--account', 'SYNTHETIC-ACCOUNT',
            '--since', self.since, '--execute', '--external-history-attested',
            '--approve-operation', 'wrong'], capture_output=True, timeout=15, env={})
        self.assertEqual((child.returncode, child.stdout.strip(), child.stderr),
                         (1, b'INVALID_REQUEST', b''))


if __name__ == '__main__':
    unittest.main()
