import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts' / 'notam'))
from c070_notam_partition import c070_codes, load_registry, partition


class C070RegistryTests(unittest.TestCase):
    def registry(self):
        return [{'iata': code, 'icao': 'K' + code, 'name': code + ' test airport',
                 'source_coverage': {'DOMESTIC': 'UNKNOWN'}} for code in c070_codes()]

    def feature(self, iata='MEM', icao='KMEM'):
        return {'properties': {'coreNOTAMData': {'notam': {'id': 'id', 'number': '01/1', 'text': 'raw',
            'issued': 'i', 'effectiveStart': 's', 'effectiveEnd': 'e', 'lastUpdated': 'u',
            'location': iata, 'icaoLocation': icao},
            'notamTranslation': [{'type': 'LOCAL_FORMAT', 'simpleText': 'local'}]}}}

    def test_sheet_export_and_registry_are_exact(self):
        codes = c070_codes()
        self.assertEqual(len(codes), 130)
        registry = load_registry(self.registry())
        self.assertEqual(set(registry), set(codes))
        bad = self.registry()[:-1]
        with self.assertRaises(ValueError): load_registry(bad)

    def test_duplicate_or_invalid_registry_mappings_are_rejected_for_list_and_dictionary_inputs(self):
        duplicate_iata = self.registry(); duplicate_iata[1]['iata'] = duplicate_iata[0]['iata']
        duplicate_icao = self.registry(); duplicate_icao[1]['icao'] = duplicate_icao[0]['icao']
        invalid = self.registry(); invalid[0]['source_coverage'] = {}
        for candidate in (duplicate_iata, duplicate_icao, invalid):
            with self.subTest(candidate=candidate[0]):
                with self.assertRaises(ValueError): partition([], candidate, retrieved_utc='offline')
        indexed = load_registry(self.registry())
        indexed['ABQ']['icao'] = indexed['ABE']['icao']
        with self.assertRaises(ValueError): partition([], indexed, retrieved_utc='offline')

    def test_partition_requires_exact_verified_pair_and_preserves_source_fields(self):
        registry = self.registry()
        payload = [self.feature(), self.feature('ORD', 'KORD'), self.feature('MEM', 'KORD'), self.feature('MEM', 'MEM!')]
        result = partition(payload, registry, retrieved_utc='offline capture time')
        self.assertEqual(len(result['airports']['KMEM']['notices']), 1)
        notice = result['airports']['KMEM']['notices'][0]
        self.assertEqual(notice['text'], 'raw'); self.assertEqual(notice['id'], 'id')
        self.assertEqual(notice['original_feature'], payload[0])
        self.assertEqual(notice['formatted_texts'][0]['text'], 'local')
        self.assertNotIn('query_context', notice)
        self.assertIn('classification-wide DOMESTIC', result['airports']['KMEM']['warning'])
        self.assertNotIn('Query-scoped', result['airports']['KMEM']['warning'])
        self.assertEqual(result['partition']['source'], 'classification-wide DOMESTIC GeoJSON capture')
        self.assertIn('not an FAA airport-specific', result['partition']['normalizer_input'])
        self.assertEqual(result['partition']['coverage'], 'UNKNOWN')
        self.assertEqual(result['partition']['excluded_record_counts'], {'missing_or_invalid_identifiers': 1, 'cross_airport_or_unregistered': 1})
        self.assertEqual(result['airports']['KATL']['notices'], [])

    def test_no_prefix_inference_or_cross_contamination(self):
        registry = self.registry()
        registry[0]['icao'] = 'XABE'
        payload = [self.feature('ABE', 'KABE'), self.feature('ABE', 'XABE')]
        result = partition(payload, registry, retrieved_utc='offline')
        self.assertEqual(len(result['airports']['XABE']['notices']), 1)
        self.assertEqual(result['partition']['excluded_record_counts']['cross_airport_or_unregistered'], 1)

    def test_documented_envelope_is_supported_but_ambiguous_identifiers_are_not(self):
        registry = self.registry()
        source = self.feature(); del source['properties']['coreNOTAMData']['notam']['icaoLocation']
        reversed_source = self.feature('KMEM', 'MEM')
        payload = {'status': 'Success', 'data': {'geojson': [source, reversed_source]}}
        result = partition(payload, registry, retrieved_utc='offline')
        self.assertEqual(len(result['airports']['KMEM']['notices']), 1)
        self.assertEqual(result['partition']['excluded_record_counts']['missing_or_invalid_identifiers'], 1)

    def test_bounded_input_and_output_refuse_without_returning_capture(self):
        payload = [self.feature()]
        with self.assertRaisesRegex(ValueError, 'input byte limit'):
            partition(payload, self.registry(), retrieved_utc='offline', max_input_bytes=1)
        with self.assertRaisesRegex(ValueError, 'output byte limit'):
            partition(payload, self.registry(), retrieved_utc='offline', max_output_bytes=1)


if __name__ == '__main__': unittest.main()
