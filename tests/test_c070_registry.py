import copy
import csv
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'notam'))

from build_c070_registry import NASR_COLUMNS, OURAIRPORTS_COLUMNS, build, read_csv
from c070_notam_partition import c070_codes, load_registry, load_versioned_registry


class VersionedC070RegistryTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / 'docs/reference/c070-airport-registry.json').read_text())
        self.registry = load_versioned_registry()

    def test_all_130_sheet_codes_are_complete_unique_and_unknown_coverage(self):
        self.assertEqual(set(self.registry), set(c070_codes()))
        self.assertEqual(len(self.registry), 130)
        self.assertEqual(len({item['icao'] for item in self.registry.values()}), 130)
        for item in self.registry.values():
            self.assertTrue(item['name'])
            self.assertEqual(item['source_coverage'], {'metar': 'UNKNOWN', 'atis': 'UNKNOWN',
                                                       'runways': 'UNKNOWN', 'notams': 'UNKNOWN'})

    def test_committed_exception_is_explicit_and_does_not_change_nasr_mapping(self):
        report = json.loads((ROOT / 'docs/reference/c070-airport-registry-exceptions.json').read_text())
        self.assertEqual(report['exceptions'], [{'iata': 'IWA', 'kind': 'SECONDARY_CONFLICT_OR_MISSING',
                                                  'ourairports_match_count': 1,
                                                  'ourairports_icao_codes': ['UUBI'], 'nasr_icao': 'KIWA'}])
        self.assertEqual(self.registry['IWA']['icao'], 'KIWA')

    def test_builder_uses_named_columns_and_reports_secondary_conflicts(self):
        nasr = [{'ARPT_ID': code, 'ICAO_ID': 'X' + code, 'ARPT_NAME': code + ' name'} for code in c070_codes()]
        ours = [{'iata_code': code, 'icao_code': 'X' + code, 'gps_code': '', 'name': code} for code in c070_codes()]
        ours[0]['icao_code'] = 'DIFF'
        registry, exceptions = build(nasr, ours)
        self.assertEqual(len(registry), 130)
        self.assertEqual(exceptions[0]['iata'], c070_codes()[0])
        with self.assertRaises(ValueError): read_csv(ROOT / 'docs/reference/c070-airports.csv', NASR_COLUMNS)
        duplicate = copy.deepcopy(registry); duplicate[1]['icao'] = duplicate[0]['icao']
        with self.assertRaises(ValueError): load_registry(duplicate)


if __name__ == '__main__':
    unittest.main()
