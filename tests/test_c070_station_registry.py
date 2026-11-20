"""Offline tests for the owner-approved C070 station allowlist."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.c070_station_registry import (
    CODES_PATH, EXPECTED_COUNT, REGISTRY_PATH, load_c070_stations,
)


class C070StationRegistryTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.codes = [line.strip() for line in CODES_PATH.read_text(encoding="utf-8").splitlines()
                      if line.strip()]

    def load_modified(self, document=None, codes=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "registry.json"
            catalog = root / "codes.csv"
            manifest.write_text(json.dumps(self.document if document is None else document),
                                encoding="utf-8")
            catalog.write_text("\n".join(self.codes if codes is None else codes) + "\n",
                               encoding="utf-8")
            return load_c070_stations(manifest, catalog)

    def test_exact_c070_coverage_and_verified_identifiers(self):
        stations = load_c070_stations()
        self.assertEqual(len(stations), EXPECTED_COUNT)
        self.assertEqual(set(stations), set(self.codes))
        self.assertEqual(len(set(stations.values())), EXPECTED_COUNT)
        self.assertEqual(stations["MEM"], "KMEM")
        self.assertEqual(stations["IWA"], "KIWA")
        self.assertEqual(stations["ORD"], "KORD")

    def test_missing_or_extra_airport_rejected(self):
        missing = copy.deepcopy(self.document)
        missing["airports"].pop()
        with self.assertRaises(ValueError):
            self.load_modified(document=missing)
        with self.assertRaises(ValueError):
            self.load_modified(codes=self.codes[:-1])

    def test_mismatched_catalog_rejected(self):
        edited = list(self.codes)
        edited[-1] = edited[0]
        with self.assertRaises(ValueError):
            self.load_modified(codes=edited)

    def test_duplicate_station_mapping_rejected(self):
        duplicate = copy.deepcopy(self.document)
        duplicate["airports"][1]["icao"] = duplicate["airports"][0]["icao"]
        with self.assertRaises(ValueError):
            self.load_modified(document=duplicate)

    def test_unverified_station_and_blank_name_rejected(self):
        no_icao = copy.deepcopy(self.document)
        no_icao["airports"][0]["icao"] = None
        with self.assertRaises(ValueError):
            self.load_modified(document=no_icao)
        no_name = copy.deepcopy(self.document)
        no_name["airports"][0]["name"] = ""
        with self.assertRaises(ValueError):
            self.load_modified(document=no_name)


if __name__ == "__main__":
    unittest.main()
