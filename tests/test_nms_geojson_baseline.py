"""Synthetic, offline tests for classification-wide candidate inspection."""
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.nms_geojson_baseline import (CandidateError, ORDER, assemble_candidate,
    inspect_bytes, read_bounded, signature_report)


def feature(identity, updated='2026-02-12T12:00:00Z', *, classification=None,
            translations=None, extra=None):
    record = {'id': identity, 'number': '01/001', 'text': 'RWY <é> & TEST',
              'issued': '2026-02-12T11:00:00Z', 'effectiveStart': '2026-02-12T12:00:00Z',
              'effectiveEnd': '2026-02-13T12:00:00Z', 'lastUpdated': updated,
              'location': 'MEM', 'icaoLocation': 'KMEM'}
    if classification is not None:
        record['classification'] = classification
    if extra:
        record.update(extra)
    return {'type': 'Feature', 'properties': {'coreNOTAMData': {'notam': record,
        'notamTranslation': translations if translations is not None else [
            {'type': 'LOCAL_FORMAT', 'simpleText': '!MEM é & <safe>'},
            {'type': 'ICAO', 'formattedText': 'ICAO TEXT'}]}}, 'unknown': {'kept': True}}


def body(features, **extra):
    value = {'status': 'Success', 'data': {'geojson': features}, **extra}
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def all_sets(overrides=None):
    overrides = overrides or {}
    return [inspect_bytes(body(overrides.get(c, [feature(c)])), c,
                          provenance={'classification': c}) for c in ORDER]


class GeoJsonBaselineTests(unittest.TestCase):
    def code(self, expected, call):
        with self.assertRaises(CandidateError) as caught:
            call()
        self.assertEqual(str(caught.exception), expected)

    def test_import_and_operations_make_no_network_calls(self):
        with patch.object(socket, 'socket', side_effect=AssertionError('network')), \
             patch.object(socket, 'getaddrinfo', side_effect=AssertionError('dns')):
            self.assertEqual(assemble_candidate(all_sets()).audit['selected_record_count'], 5)

    def test_requires_exact_five_classifications(self):
        self.code('INCOMPLETE_BASELINE', lambda: assemble_candidate(all_sets()[:-1]))
        self.code('INVALID_CLASSIFICATION', lambda: inspect_bytes(body([]), 'DOM'))

    def test_bounds_input_and_rejects_non_json_or_compression_without_guessing(self):
        self.code('INPUT_TOO_LARGE', lambda: inspect_bytes(body([]), 'FDC', max_bytes=2))
        for value in (b'PK\x03\x04x', b'\x1f\x8bx', b'<xml/>'):
            self.code('UNSUPPORTED_CONTENT', lambda value=value: inspect_bytes(value, 'FDC'))

    def test_utf8_only_json_and_malformed_json_are_fixed_failures(self):
        self.code('INVALID_JSON', lambda: inspect_bytes(b'{"x":"\xff"}', 'FDC'))
        self.code('INVALID_JSON', lambda: inspect_bytes(b'{', 'FDC'))

    def test_structural_limits_and_signature_only_report(self):
        nested = {'status':'Success','data':{'geojson':[]}}
        for _ in range(8): nested={'x':nested}
        self.code('INVALID_JSON', lambda: inspect_bytes(json.dumps(nested).encode(), 'FDC', max_depth=4))
        report=signature_report(b'PK\x03\x04private', 'FDC')
        self.assertEqual(report['signature'],'zip'); self.assertFalse(report['json_parseable'])
        self.assertNotIn('private', json.dumps(report))

    def test_requires_success_inline_geojson_and_no_errors(self):
        for value in ({}, {'status':'Failure','data':{'geojson':[]}},
                      {'status':'Success','errors':['x'],'data':{'geojson':[]}},
                      {'status':'Success','data':{'url':'/private'}}):
            self.code('INVALID_RESPONSE', lambda value=value: inspect_bytes(json.dumps(value).encode(), 'FDC'))

    def test_inspection_is_safe_and_retains_original_private_bytes(self):
        raw = body([feature('PRIVATE-ID', extra={'unexpectedSecretField':'value'})])
        item = inspect_bytes(raw, 'DOMESTIC', provenance={'saved_at':'offline'})
        self.assertEqual(item.original_bytes, raw)
        rendered = json.dumps(item.report)
        self.assertNotIn('PRIVATE-ID', rendered); self.assertNotIn('value', rendered)
        self.assertIn('unexpectedSecretField', item.report['unexpected_record_fields'])

    def test_inspection_counts_translations_cancellation_and_ranges(self):
        a = feature('a', '2026-02-11T00:00:00Z', extra={'cancelationDate':'2026-02-12T00:00:00Z'})
        b = feature('b', '2026-02-13T00:00:00Z', translations=[{'type':'ICAO','simpleText':'separate'}])
        report = inspect_bytes(body([a,b]), 'FDC').report
        self.assertEqual((report['local_format_count'],report['icao_count'],report['no_local_format_count']), (1,2,1))
        self.assertEqual(report['cancellation_field_count'], 1)
        self.assertEqual(report['min_last_updated'], '2026-02-11T00:00:00Z')

    def test_missing_ids_are_reported_but_candidate_rejects_them(self):
        bad = feature('x'); del bad['properties']['coreNOTAMData']['notam']['id']
        item = inspect_bytes(body([bad]), 'FDC')
        self.assertEqual(item.report['missing_or_invalid_id_count'], 1)
        self.code('INVALID_RECORD', lambda: assemble_candidate(all_sets({'FDC':[bad]})))

    def test_original_features_unicode_escaped_text_and_unknowns_survive(self):
        source = feature('same', extra={'opaque':['é','<&>']})
        candidate = assemble_candidate(all_sets({'DOMESTIC':[source]}))
        selected = next(x for x in candidate.payload['data']['geojson']
                        if x['properties']['coreNOTAMData']['notam']['id']=='same')
        self.assertEqual(selected, source)
        self.assertIn('é', json.dumps(candidate.payload, ensure_ascii=False))

    def test_local_format_is_only_explicit_type_and_icao_stays_separate(self):
        source = feature('display', translations=[
            {'type':'LOCAL_FORMAT','simpleText':'LOCAL'},
            {'type':'LOCAL_FORMAT','formattedText':'not-local-simple'},
            {'type':'ICAO','simpleText':'ICAO SIMPLE'},
            {'type':'UNKNOWN','simpleText':'UNKNOWN'}])
        candidate = assemble_candidate(all_sets({'DOMESTIC':[source]}))
        mapped = candidate.normalize_partition(airport='KMEM', location='KMEM', retrieved_utc='offline')
        texts = next(n for n in mapped['airports']['KMEM']['notices']
                     if n['id'] == 'display')['formatted_texts']
        self.assertEqual([(x['type'],x['field'],x['text']) for x in texts], [
            ('LOCAL_FORMAT','simpleText','LOCAL'), ('ICAO','simpleText','ICAO SIMPLE')])

    def test_exact_duplicates_are_deterministic(self):
        shared = feature('duplicate')
        result = assemble_candidate(all_sets({'INTERNATIONAL':[shared], 'MILITARY':[shared]}))
        self.assertEqual(result.audit['exact_duplicate_count'], 1)
        self.assertEqual(len(result.record_evidence['duplicate']), 2)
        self.assertEqual(sum(f['properties']['coreNOTAMData']['notam']['id']=='duplicate'
                             for f in result.payload['data']['geojson']), 1)

    def test_newer_wins_and_older_is_accounted(self):
        old=feature('versioned','2026-02-11T00:00:00Z'); new=feature('versioned','2026-02-12T00:00:00Z', extra={'text':'new'})
        result=assemble_candidate(all_sets({'INTERNATIONAL':[old], 'MILITARY':[new], 'FDC':[old]}))
        self.assertEqual(result.audit['newer_replacement_count'],1)
        self.assertEqual(result.audit['older_duplicate_count'],1)

    def test_same_id_time_different_content_is_conflict(self):
        a=feature('conflict'); b=feature('conflict', extra={'text':'different'})
        self.code('IDENTITY_CONFLICT', lambda: assemble_candidate(all_sets({'INTERNATIONAL':[a], 'MILITARY':[b]})))

    def test_explicit_cross_classification_is_rejected(self):
        wrong=feature('wrong', classification='FDC')
        self.code('CLASSIFICATION_CONFLICT', lambda: assemble_candidate(all_sets({'DOMESTIC':[wrong]})))

    def test_unmapped_payload_abbreviation_is_preserved_not_silently_changed(self):
        dom=feature('dom', classification='DOM')
        result=assemble_candidate(all_sets({'DOMESTIC':[dom]}))
        record=next(f for f in result.payload['data']['geojson'] if f['properties']['coreNOTAMData']['notam']['id']=='dom')
        self.assertEqual(record['properties']['coreNOTAMData']['notam']['classification'],'DOM')

    def test_aggregate_output_limit_is_enforced_before_candidate(self):
        sets=all_sets({'FDC':[feature('large', extra={'opaque':'x'*200})]})
        self.code('OUTPUT_TOO_LARGE', lambda: assemble_candidate(sets, max_output_bytes=100))
        self.assertEqual(assemble_candidate(sets, max_output_bytes=10_000).audit['selected_record_count'],5)

    def test_candidate_has_no_cutover_or_cursor_and_fixed_gate(self):
        result=assemble_candidate(all_sets())
        self.assertEqual(result.audit['diagnostic'],'BASELINE_CUTOVER_REQUIRED')
        self.assertFalse(result.audit['baseline_established']); self.assertIsNone(result.audit['watermark'])
        self.assertFalse(hasattr(result,'coverage_since'))

    def test_bounded_file_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'saved.json'; path.write_bytes(b'1234')
            self.assertEqual(read_bounded(path,4),b'1234')
            self.code('INPUT_TOO_LARGE', lambda: read_bounded(path,3))


if __name__ == '__main__':
    unittest.main()
