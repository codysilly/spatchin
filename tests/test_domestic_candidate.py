"""Offline supervised DOMESTIC candidate gate tests; networking is blocked."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'/'notam'
sys.path.insert(0, str(SCRIPTS))
from capture_domestic_candidate import (OPERATION, default_store_path, operation_digest,
                                        review)
from test_nms_refresh import NOW, synthetic_store


class DomesticCandidateGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = synthetic_store(self.temp.name)

    def test_review_is_read_only_without_credentials_or_network(self):
        before = {path.name:path.read_bytes() for path in self.store.root.iterdir()}
        with patch.dict('os.environ', {}, clear=True), \
             patch.object(socket, 'socket', side_effect=AssertionError('network')), \
             patch.object(socket, 'getaddrinfo', side_effect=AssertionError('dns')):
            result = review(self.store, NOW)
        self.assertFalse(result['credentials_read'])
        self.assertFalse(result['provider_requests_made'])
        self.assertFalse(result['authorization_ready'])
        self.assertEqual(before, {path.name:path.read_bytes() for path in self.store.root.iterdir()})

    def test_digest_binds_exact_domestic_operation(self):
        self.assertEqual(len(operation_digest()), 64)
        self.assertIn('classification=DOMESTIC&allowRedirect=false',
                      OPERATION['data']['url'])
        self.assertEqual(OPERATION['data']['nmsResponseFormat'], 'GEOJSON')
        self.assertFalse(OPERATION['retry']); self.assertFalse(OPERATION['publication'])

    def test_windows_default_store_is_the_migrated_private_ledger(self):
        with patch.dict('os.environ', {'LOCALAPPDATA': r'C:\Users\synthetic\AppData\Local'}, clear=True):
            self.assertEqual(default_store_path(),
                             r'C:\Users\synthetic\AppData\Local\Spatchin\private-faa\ledger')
        with patch.dict('os.environ', {}, clear=True):
            self.assertIsNone(default_store_path())

    def test_cli_wrong_approval_stops_before_credentials_or_network(self):
        child = subprocess.run([sys.executable, '-B', str(SCRIPTS/'capture_domestic_candidate.py'),
            '--store', str(self.store.root), '--account', 'SYNTHETIC-ACCOUNT',
            '--execute', '--external-history-attested', '--approve-operation', 'wrong'],
            capture_output=True, timeout=15, env={})
        self.assertEqual(child.returncode, 1)
        self.assertEqual(child.stdout.strip(), b'INVALID_REQUEST')
        self.assertFalse(child.stderr)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
