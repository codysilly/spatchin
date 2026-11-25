"""Offline ATIS collector tests. HTTP responses are synthetic; no provider access."""
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'update_atis.py'


def load_module():
    spec = importlib.util.spec_from_file_location('update_atis_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(airport, *, age=5, kind='combined', code='A', text='SYNTHETIC ATIS TEXT'):
    timestamp = datetime.now(timezone.utc) - timedelta(minutes=age)
    return {'airport': airport, 'type': kind, 'code': code, 'time': timestamp.strftime('%H%M'),
            'updatedAt': timestamp.isoformat().replace('+00:00', 'Z'), 'datis': text}


class Response:
    def __init__(self, data):
        self.raw = io.BytesIO(json.dumps(data).encode('utf-8'))

    def __enter__(self):
        return self.raw

    def __exit__(self, *_):
        return False


class UpdateAtisTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.module.OUTPUT = Path(self.directory.name) / 'data' / 'atis.json'
        self.stations = ['KJFK', 'KLAX', 'KMEM', 'KORD']

    def prior(self, airport_reports, *, coverage=True):
        path = self.module.OUTPUT
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'retrieved_utc': '2026-01-01T00:00:00Z', 'airports': airport_reports}
        if coverage:
            payload['configured_airports'] = sorted(self.stations)
            payload['catalog_airports'] = list(self.module.CATALOG_AIRPORTS)
        path.write_text(json.dumps(payload), encoding='utf-8')
        return path.read_bytes()

    def collect(self, payloads, *, stations=None):
        calls = []
        records = []
        for value in payloads.values():
            if isinstance(value, Exception):
                continue
            records.extend(value if isinstance(value, list) else [value])
        def urlopen(request, timeout=20):
            endpoint = request.full_url.rsplit('/', 1)[-1]
            calls.append(endpoint)
            return Response((self.stations if stations is None else stations)
                            if endpoint == 'stations' else records)
        with mock.patch.object(self.module.urllib.request, 'urlopen', side_effect=urlopen):
            self.module.main()
        self.assertEqual(calls, ['stations', 'all'])

    def snapshot(self):
        return json.loads(self.module.OUTPUT.read_text(encoding='utf-8'))

    def test_success_publishes_dashboard_compatible_snapshot(self):
        payloads = {code: [report(code)] for code in self.stations}
        self.collect(payloads)
        snapshot = self.snapshot()
        self.assertEqual(set(snapshot['airports']), set(self.stations))
        self.assertTrue(snapshot['retrieved_utc'].endswith('Z'))
        self.assertEqual(snapshot['source'], 'https://atis.info/api')
        self.assertEqual(snapshot['airports']['KORD'][0]['type'], 'combined')
        self.assertEqual(snapshot['configured_airports'], sorted(self.stations))
        self.assertEqual(len(snapshot['catalog_airports']), 130)
        self.assertEqual(len(set(snapshot['catalog_airports']) - set(snapshot['configured_airports'])), 126)

    def test_failed_airport_keeps_previous_while_others_update(self):
        old = report('KORD', age=30, code='X')
        self.prior({'KORD': [old]})
        self.collect({'KORD': URLError('synthetic outage'),
                      'KLAX': [report('KLAX', age=2)],
                      'KJFK': [report('KJFK', age=3)], 'KMEM': [report('KMEM')]})
        snapshot = self.snapshot()
        self.assertEqual(snapshot['airports']['KORD'], [old])
        self.assertEqual(set(snapshot['airports']), {'KORD', 'KLAX', 'KJFK', 'KMEM'})

    def test_all_failures_keep_snapshot_and_signal_failure(self):
        before = self.prior({'KORD': [report('KORD')]})
        with redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as raised:
                self.collect({code: URLError('synthetic outage') for code in self.stations})
        self.assertEqual(raised.exception.code, 1)
        self.assertIn('ATIS bulk collection failed', stderr.getvalue())
        self.assertEqual(self.module.OUTPUT.read_bytes(), before)

    def test_bad_response_does_not_block_valid_airport(self):
        self.prior({'KORD': [report('KORD', age=20)]})
        self.collect({'KORD': {'nonsense': 'wrong shape'}, 'KLAX': [report('KLAX')],
                      'KJFK': [{'airport': 'KJFK', 'type': 'combined', 'datis': 'missing time'}]})
        self.assertEqual(set(self.snapshot()['airports']), {'KORD', 'KLAX'})

    def test_old_source_does_not_replace_newer_previous(self):
        previous = report('KORD', age=3, code='A')
        old = report('KORD', age=20, code='Z')
        self.prior({'KORD': [previous]})
        self.collect({'KORD': [old], 'KLAX': [report('KLAX')],
                      'KJFK': [report('KJFK')]})
        self.assertEqual(self.snapshot()['airports']['KORD'], [previous])

    def test_repeated_unchanged_reports_do_not_rewrite_file(self):
        records = {code: [report(code)] for code in self.stations}
        before = self.prior(records)
        self.collect(records)
        self.assertEqual(self.module.OUTPUT.read_bytes(), before)

    def test_split_arrival_update_keeps_previous_departure(self):
        arrival_old = report('KORD', age=30, kind='arr', code='A')
        departure = report('KORD', age=10, kind='dep', code='B')
        arrival_new = report('KORD', age=2, kind='arr', code='C')
        self.prior({'KORD': [arrival_old, departure]})
        self.collect({'KORD': [arrival_new], 'KLAX': [report('KLAX')],
                      'KJFK': [report('KJFK')]})
        reports = self.snapshot()['airports']['KORD']
        self.assertEqual([(r['type'], r['code']) for r in reports],
                         [('arr', 'C'), ('dep', 'B')])

    def test_split_departure_update_keeps_arrival_and_source_timestamps(self):
        arrival = report('KORD', age=10, kind='arr', code='A')
        departure_old = report('KORD', age=30, kind='dep', code='B')
        departure_new = report('KORD', age=2, kind='dep', code='C')
        self.prior({'KORD': [arrival, departure_old]})
        self.collect({'KORD': [departure_new], 'KLAX': [report('KLAX')],
                      'KJFK': [report('KJFK')]})
        reports = self.snapshot()['airports']['KORD']
        self.assertEqual([(r['type'], r['code']) for r in reports],
                         [('arr', 'A'), ('dep', 'C')])
        self.assertEqual(reports[0]['updatedAt'], arrival['updatedAt'])
        self.assertEqual(reports[1]['updatedAt'], departure_new['updatedAt'])

    def test_older_report_one_type_does_not_replace_newer_one(self):
        arrival_new = report('KORD', age=2, kind='arr', code='C')
        departure_old = report('KORD', age=15, kind='dep', code='B')
        self.prior({'KORD': [arrival_new, departure_old]})
        self.collect({'KORD': [report('KORD', age=30, kind='arr', code='A'),
                               report('KORD', age=1, kind='dep', code='D')],
                      'KLAX': [report('KLAX')], 'KJFK': [report('KJFK')]})
        reports = self.snapshot()['airports']['KORD']
        self.assertEqual([(r['type'], r['code']) for r in reports],
                         [('arr', 'C'), ('dep', 'D')])

    def test_combined_and_split_reports_remain_distinct(self):
        previous = report('KORD', age=15, kind='combined', code='A')
        arrival = report('KORD', age=3, kind='arr', code='B')
        departure = report('KORD', age=6, kind='dep', code='C')
        self.prior({'KORD': [previous]})
        self.collect({'KORD': [arrival, departure], 'KLAX': [report('KLAX')],
                      'KJFK': [report('KJFK')]})
        self.assertEqual([r['type'] for r in self.snapshot()['airports']['KORD']],
                         ['combined', 'arr', 'dep'])

    def test_mem_failure_is_configured_without_report(self):
        self.collect({code: [report(code)] for code in self.stations if code != 'KMEM'})
        snapshot = self.snapshot()
        self.assertIn('KMEM', snapshot['configured_airports'])
        self.assertNotIn('KMEM', snapshot['airports'])
        self.assertNotIn('KABE', snapshot['configured_airports'])
        self.assertIn('KABE', snapshot['catalog_airports'])

    def test_legacy_metadata_migration_does_not_refresh_retrieval_time(self):
        records = {code: [report(code)] for code in self.stations}
        self.prior(records, coverage=False)
        self.collect(records)
        snapshot = self.snapshot()
        self.assertEqual(snapshot['configured_airports'], sorted(self.stations))
        self.assertEqual(snapshot['retrieved_utc'], '2026-01-01T00:00:00Z')
        self.assertEqual(snapshot['airports'], records)

    def test_coverage_change_with_unchanged_reports(self):
        records = {code: [report(code)] for code in self.stations if code != 'KMEM'}
        self.prior(records, coverage=False)
        self.collect(records)
        snapshot = self.snapshot()
        self.assertIn('KMEM', snapshot['configured_airports'])
        self.assertNotIn('KMEM', snapshot['airports'])
        self.assertEqual(snapshot['retrieved_utc'], '2026-01-01T00:00:00Z')

    def test_full_c070_bulk_two_requests_and_non_catalog_filter(self):
        self.stations = list(self.module.CATALOG_AIRPORTS)
        payloads = {code: [report(code)] for code in self.stations}
        payloads['ZZZZ'] = [report('ZZZZ')]
        self.collect(payloads, stations=self.stations + ['ZZZZ'])
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot['airports']), 130)
        self.assertEqual(snapshot['configured_airports'], sorted(self.stations))
        self.assertNotIn('ZZZZ', snapshot['airports'])
        self.assertEqual(snapshot['coverage_source'], 'https://atis.info/api/stations')

    def test_rate_limit_or_unavailable_never_retries_or_falls_back(self):
        before = self.prior({'KORD': [report('KORD')]})
        for status in (429, 503):
            with mock.patch.object(self.module.urllib.request, 'urlopen', side_effect=[
                HTTPError('https://atis.info/api/stations', status, 'limited', {}, None)
            ]) as fetch:
                with self.assertRaises(SystemExit):
                    self.module.main()
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(self.module.OUTPUT.read_bytes(), before)

    def test_bulk_failure_preserves_snapshot_after_station_success(self):
        before = self.prior({'KORD': [report('KORD')]})
        with mock.patch.object(self.module.urllib.request, 'urlopen', side_effect=[
            Response(self.stations), URLError('synthetic outage')
        ]) as fetch:
            with self.assertRaises(SystemExit):
                self.module.main()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(self.module.OUTPUT.read_bytes(), before)

    def test_malformed_station_list_fails_before_bulk(self):
        before = self.prior({'KORD': [report('KORD')]})
        for invalid in ([], {}, ['bad'], [None]):
            with mock.patch.object(self.module.urllib.request, 'urlopen', return_value=Response(invalid)) as fetch:
                with self.assertRaises(SystemExit):
                    self.module.main()
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(self.module.OUTPUT.read_bytes(), before)

    def test_station_list_bulk_disagreement_keeps_snapshot(self):
        before = self.prior({'KORD': [report('KORD')]})
        with mock.patch.object(self.module.urllib.request, 'urlopen', side_effect=[
            Response(['KORD']), Response([report('KMEM')])
        ]) as fetch:
            with self.assertRaises(SystemExit):
                self.module.main()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(self.module.OUTPUT.read_bytes(), before)

    def test_delisted_station_keeps_historical_report(self):
        old = report('KMEM', age=10)
        self.prior({'KMEM': [old]})
        self.collect({'KORD': [report('KORD')]}, stations=['KORD'])
        snapshot = self.snapshot()
        self.assertNotIn('KMEM', snapshot['configured_airports'])
        self.assertEqual(snapshot['airports']['KMEM'], [old])

    def test_oversized_bulk_response_keeps_snapshot(self):
        before = self.prior({'KORD': [report('KORD')]})
        with mock.patch.object(self.module, 'MAX_RESPONSE_BYTES', 128), \
             mock.patch.object(self.module.urllib.request, 'urlopen', side_effect=[
                 Response(self.stations), Response([report('KORD', text='X'*200)])
             ]) as fetch:
            with self.assertRaises(SystemExit):
                self.module.main()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(self.module.OUTPUT.read_bytes(), before)

    def test_future_report_and_invalid_records_are_rejected(self):
        incoming = [report('KORD', age=-40), report('KLAX'), {'airport': 'KORD',
                    'type': 'combined', 'datis': ''}]
        with self.assertRaises(ValueError):
            self.module.select_reports(incoming, 'KORD')

    def test_split_reports_and_newest_type_selection(self):
        older = report('KJFK', age=12, kind='arr', code='B')
        newer = report('KJFK', age=4, kind='arr', code='C')
        departure = report('KJFK', age=8, kind='dep', code='D')
        selection = self.module.select_reports([older, newer, departure], 'KJFK')
        self.assertEqual([x['code'] for x in selection], ['C', 'D'])


if __name__ == '__main__':
    unittest.main()
