"""Offline configuration checks: parse source only; never run updaters."""
import ast
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def tree(name):
    path = ROOT / 'scripts' / name
    source = path.read_bytes()
    compile(source, str(path), 'exec')  # Syntax check without execution.
    return ast.parse(source, filename=str(path))


def assigned(node, name):
    for item in ast.walk(node):
        if isinstance(item, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in item.targets
        ):
            return ast.literal_eval(item.value)
    raise AssertionError(f'Missing assignment: {name}')


class UpdaterAirportTests(unittest.TestCase):
    def test_metar_uses_c070_registry_and_awc_endpoint(self):
        # Inspect source without running a provider collector.
        module = tree('update_metar.py')
        imported = {node.module for node in ast.walk(module)
                    if isinstance(node, ast.ImportFrom)}
        self.assertIn('scripts.c070_station_registry', imported)
        source = (ROOT / 'scripts/update_metar.py').read_text(encoding='utf-8')
        self.assertIn('load_c070_stations().values()', source)
        self.assertIn('https://aviationweather.gov/api/data/metar?ids=', source)
        self.assertIn('&format=json', source)

    def test_atis_uses_bounded_c070_coverage_including_mem(self):
        module = tree('update_atis.py')
        imported = {node.module for node in ast.walk(module)
                    if isinstance(node, ast.ImportFrom)}
        self.assertIn('scripts.c070_station_registry', imported)
        self.assertEqual(assigned(module, 'CONFIGURED_IATA'),
                         ('ORD', 'LAX', 'JFK', 'MEM'))
        source = (ROOT / 'scripts/update_atis.py').read_text(encoding='utf-8')
        self.assertIn('AIRPORTS = tuple(_registry[code] for code in CONFIGURED_IATA)', source)
        self.assertEqual(assigned(module, 'URL'), 'https://atis.info/api/')

    def test_runways_use_c070_registry_and_guard_existing_four_airports(self):
        module = tree('update_runways.py')
        imported = {node.module for node in ast.walk(module)
                    if isinstance(node, ast.ImportFrom)}
        self.assertIn('scripts.c070_station_registry', imported)
        source = (ROOT / 'scripts/update_runways.py').read_text(encoding='utf-8')
        self.assertIn('load_c070_stations()', source)
        self.assertIn('AIRPORTS = frozenset(', source)
        self.assertEqual(assigned(module, 'LEGACY_COUNTS'),
                         {'ORD': 16, 'LAX': 8, 'JFK': 8, 'MEM': 8})


    def test_taf_uses_only_cloudflare_dispatch_after_cutover(self):
        workflow = (ROOT / '.github/workflows/taf-update.yml').read_text(encoding='utf-8')
        self.assertIn("on:\n  workflow_dispatch:\npermissions:", workflow)
        self.assertNotIn("\n  schedule:", workflow)
        self.assertIn('  group: spatchin-taf-update', workflow)
        self.assertIn('  cancel-in-progress: false', workflow)
        self.assertIn('    run: python scripts/update_taf.py', workflow)
        self.assertIn('  contents: write', workflow)


if __name__ == '__main__':
    unittest.main()
