"""Synthetic, offline tests for classification-wide candidate inspection."""
import gzip
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "notam"))
from nms_geojson_baseline import (CandidateError, ORDER, assemble_candidate,
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

    def test_bounds_input_and_rejects_unsupported_compression_without_guessing(self):
        self.code('INPUT_TOO_LARGE', lambda: inspect_bytes(body([]), 'FDC', max_bytes=2))
        for value in (b'PK\x03\x04x', b'<xml/>'):
            self.code('UNSUPPORTED_CONTENT', lambda value=value: inspect_bytes(value, 'FDC'))

    def test_gzip_bare_array_preserves_source_bytes_and_dom_classification(self):
        source = feature('DOM-PRIVATE-ID', classification='DOM')
        raw = gzip.compress(json.dumps([source], ensure_ascii=False).encode())
        item = inspect_bytes(raw, 'DOMESTIC', provenance={'retrieved_utc':'offline'})
        self.assertEqual(item.original_bytes, raw)
        self.assertEqual(item.provenance, {'retrieved_utc':'offline'})
        self.assertEqual(item.report['signature'], 'gzip')
        self.assertEqual(item.report['compression'], 'gzip')
        self.assertEqual(item.report['source_shape'], 'bare_geojson_array')
        self.assertEqual(item.report['record_count'], 1)
        self.assertFalse(item.report['baseline_established'])
        self.assertIsNone(item.report['watermark'])
        self.assertEqual(item.report['coverage'], 'UNKNOWN')
        record = item.payload['data']['geojson'][0]['properties']['coreNOTAMData']['notam']
        self.assertEqual((record['id'], record['classification']), ('DOM-PRIVATE-ID', 'DOM'))

    def test_uncompressed_success_envelope_remains_supported(self):
        raw = body([feature('legacy-envelope', classification='DOM')])
        item = inspect_bytes(raw, 'DOMESTIC')
        self.assertEqual((item.report['signature'], item.report['compression'],
                          item.report['source_shape']),
                         ('json', 'none', 'success_geojson_envelope'))
        self.assertEqual(item.report['decoded_sha256'], item.report['original_input_sha256'])

    def test_truncated_gzip_and_expansion_limit_fail_safely(self):
        raw = gzip.compress(json.dumps([feature('gzip')]).encode())
        self.code('INVALID_GZIP', lambda: inspect_bytes(raw[:-4], 'DOMESTIC'))
        self.code('DECOMPRESSED_TOO_LARGE', lambda: inspect_bytes(
            raw, 'DOMESTIC', max_decompressed_bytes=8))

    def test_utf8_only_json_and_malformed_json_are_fixed_failures(self):
        self.code('INVALID_JSON', lambda: inspect_bytes(b'{"x":"\xff"}', 'FDC'))
        self.code('INVALID_JSON', lambda: inspect_bytes(b'{', 'FDC'))

    def test_nonstandard_json_numbers_are_rejected_but_normal_numbers_work(self):
        for token in (b'NaN', b'Infinity', b'-Infinity'):
            raw = b'{"status":"Success","data":{"geojson":[],"number":' + token + b'}}'
            self.code('INVALID_JSON', lambda raw=raw: inspect_bytes(raw, 'FDC'))
        item = inspect_bytes(b'{"status":"Success","data":{"geojson":[],"number":1.25}}', 'FDC')
        self.assertTrue(item.report['json_parseable'])
        self.code('INVALID_JSON', lambda: inspect_bytes(
            b'{"status":"Success","data":{"geojson":[],"number":1e999}}', 'FDC'))

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

    def test_malformed_translation_types_have_fixed_non_leaking_failure(self):
        for malformed in ([], {}, None, 7):
            source = feature('PRIVATE-ID', translations=[{'type': malformed, 'simpleText': 'SECRET'}])
            self.code('INVALID_RECORD', lambda source=source:
                      inspect_bytes(body([source]), 'FDC'))
        report = inspect_bytes(body([feature('ok', translations=[
            {'type': 'LOCAL_FORMAT', 'simpleText': 'local'},
            {'type': 'ICAO', 'simpleText': 'icao'}])]), 'FDC').report
        self.assertEqual((report['local_format_count'], report['icao_count']), (1, 1))

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

    def test_partition_uses_only_explicit_consistent_airport_evidence(self):
        mem = feature('mem')
        mem_alias = feature('mem-alias', extra={'location':'KMEM', 'icaoLocation':'MEM'})
        ord_notice = feature('ord', extra={'location':'ORD', 'icaoLocation':'KORD'})
        jfk_notice = feature('jfk', extra={'location':'JFK', 'icaoLocation':'KJFK'})
        missing = feature('missing'); missing_record = missing['properties']['coreNOTAMData']['notam']
        del missing_record['location']; del missing_record['icaoLocation']
        conflict = feature('conflict-location', extra={'location':'MEM', 'icaoLocation':'KORD'})
        one_identifier = feature('one-identifier'); del one_identifier['properties']['coreNOTAMData']['notam']['icaoLocation']
        invalid = feature('invalid-location', extra={'location':'MEM!', 'icaoLocation':'KMEM'})
        duplicate = feature('duplicate-mem')
        overrides = {classification: [] for classification in ORDER}
        overrides.update({'DOMESTIC': [mem, mem_alias, ord_notice, jfk_notice, missing,
            conflict, one_identifier, invalid, duplicate], 'FDC': [duplicate]})
        candidate = assemble_candidate(all_sets(overrides))
        mapped = candidate.normalize_partition(airport='KMEM', location='MEM', retrieved_utc='offline')
        self.assertEqual([notice['id'] for notice in mapped['airports']['KMEM']['notices']],
                         ['duplicate-mem', 'mem', 'mem-alias', 'one-identifier'])
        self.assertEqual(mapped['airports']['KMEM']['completeness'], 'UNKNOWN')
        self.assertEqual(mapped['partition']['view'], 'FILTERED_AIRPORT_PARTITION')
        self.assertIn('not the unchanged provider response', mapped['partition']['normalizer_input'])
        self.assertEqual(mapped['partition']['excluded_record_counts'], {
            'missing_airport_evidence': 1, 'invalid_airport_evidence': 1,
            'conflicting_airport_evidence': 1, 'different_airport': 2})
        self.assertGreater(len(candidate.payload['data']['geojson']), 3)
        self.assertEqual(len(candidate.record_evidence['duplicate-mem']), 2)

    def test_partition_can_be_empty_without_claiming_coverage(self):
        overrides = {classification: [] for classification in ORDER}
        overrides['DOMESTIC'] = [feature('ord-only', extra={
            'location':'ORD', 'icaoLocation':'KORD'})]
        candidate = assemble_candidate(all_sets(overrides))
        mapped = candidate.normalize_partition(airport='KJFK', location='JFK', retrieved_utc='offline')
        self.assertEqual(mapped['airports']['KJFK']['notices'], [])
        self.assertEqual(mapped['partition']['coverage'], 'UNKNOWN')

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
