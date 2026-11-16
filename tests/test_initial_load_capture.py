"""Synthetic, socket/DNS-blocked checks for the supervised opaque IL capture."""
import json, socket, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from capture_initial_load import OPERATION, execute, operation_digest, review
from nms_refresh_contract import RefreshError
from test_nms_refresh import NOW, CREDENTIALS, TOKEN, synthetic_store

class Transport:
    def __init__(self, mode='ok'): self.mode=mode; self.requests=[]
    def __call__(self, request, limit):
        self.requests.append(request.stage)
        if request.stage == 'auth': return 200, {}, json.dumps({'access_token': TOKEN}).encode()
        return 200, {}, json.dumps({'status':'Success','data':{'url':'/v1/content/SYNTHETIC'}}).encode()
    def stream(self, request, limit, sink):
        self.requests.append(request.stage)
        if self.mode == 'redirect': return 307, {}
        if self.mode == 'partial': sink(b'partial'); raise TimeoutError()
        body = b'SYNTHETIC-AIXM-SOAP-COMPRESSED-BYTES'; sink(body)
        return 200, {'bytes':len(body), 'sha256':__import__('hashlib').sha256(body).hexdigest()}

class InitialLoadCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=synthetic_store(self.temp.name)
    def code(self, code, call):
        with self.assertRaises(RefreshError) as got: call()
        self.assertEqual(str(got.exception),code)
    def test_review_is_read_only_and_has_distinct_digest(self):
        before={p.name:p.read_bytes() for p in self.store.root.iterdir()}
        with patch.object(socket,'socket',side_effect=AssertionError), patch.object(socket,'getaddrinfo',side_effect=AssertionError):
            result=review(self.store,NOW)
        self.assertFalse(result['credentials_read']); self.assertFalse(result['provider_requests_made'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.store.root.iterdir()})
        self.assertEqual(OPERATION['initial_load']['url'],'https://api-nms.aim.faa.gov/nmsapi/v1/notams/il?allowRedirect=false')
        self.assertEqual(len(operation_digest()),64)
    def test_capture_is_opaque_three_stage_and_preserves_bytes(self):
        transport=Transport(); result=execute(self.store,credentials=CREDENTIALS,transport=transport,clock=lambda:NOW)
        self.assertEqual(transport.requests,['auth','initial-aixm-soap','content']); self.assertFalse(result['baseline_established'])
        evidence=self.store.root/'initial-load-evidence'/result['attempt']
        self.assertEqual((evidence/'initial-load.bin').read_bytes(),b'SYNTHETIC-AIXM-SOAP-COMPRESSED-BYTES')
        receipt=json.loads((evidence/'receipt.json').read_bytes()); self.assertEqual(receipt['sha256'],result['sha256'])
        with self.store.connect() as db:
            self.assertEqual(self.store.load(db)['watermark'],None)
            self.assertEqual(db.execute('SELECT count(*) FROM calls').fetchone()[0],3)
    def test_partial_and_redirect_are_accounted_without_retry(self):
        for mode, expected in [('partial','TRANSPORT_FAILED'),('redirect','HTTP_FAILED')]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                self.store=synthetic_store(root); transport=Transport(mode)
                self.code(expected,lambda:execute(self.store,credentials=CREDENTIALS,transport=transport,clock=lambda:NOW))
                self.assertEqual(transport.requests,['auth','initial-aixm-soap','content'])
                with self.store.connect() as db:
                    self.assertEqual(db.execute('SELECT status FROM attempts').fetchone()[0],'FAILED_ACCOUNTED')
    def test_existing_active_ledger_stops_before_transport(self):
        with self.store.connect() as db: self.store.reserve(db,'bulk',NOW)
        self.code('RECOVERY_REQUIRED',lambda:execute(self.store,credentials=CREDENTIALS,transport=lambda *_:self.fail('network'),clock=lambda:NOW))

if __name__ == '__main__': unittest.main()
