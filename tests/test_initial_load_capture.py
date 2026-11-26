"""Synthetic, socket/DNS-blocked checks for the supervised opaque IL capture."""
import json, socket, sys, tempfile, unittest, subprocess
from collections import namedtuple
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'/'notam'
sys.path.insert(0, str(SCRIPTS))
from capture_initial_load import OPERATION, execute, operation_digest, review
from nms_refresh_contract import RefreshError
from test_nms_refresh import NOW, CREDENTIALS, TOKEN, synthetic_store

class Transport:
    def __init__(self, mode='ok', control=None): self.mode=mode; self.requests=[]; self.control=control
    def __call__(self, request, limit):
        self.requests.append(request.stage)
        if request.stage == 'auth': return 200, {}, json.dumps({'access_token': TOKEN}).encode()
        return 200, {}, self.control if self.control is not None else json.dumps({'status':'Success','data':{'url':'/v1/content/SYNTHETIC'}}).encode()
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
        self.assertEqual(receipt['capture_started_utc'],NOW.isoformat())
        self.assertEqual([item['stage'] for item in receipt['stage_receipts']],['auth','initial-aixm-soap','content'])
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

    def test_malformed_error_or_unrecognized_control_is_accounted_without_content(self):
        for body in [b'{', b'{"status":"Failure"}', b'not-a-recognized-initial-binary']:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as root:
                self.store=synthetic_store(root); transport=Transport(control=body)
                self.code('INVALID_RESPONSE',lambda:execute(self.store,credentials=CREDENTIALS,transport=transport,clock=lambda:NOW))
                self.assertEqual(transport.requests,['auth','initial-aixm-soap'])

    def test_execution_rechecks_disk_before_reservation(self):
        usage=namedtuple('usage','total used free')(10,9,MAX:=1)
        with patch('capture_initial_load.shutil.disk_usage',return_value=usage):
            self.code('HISTORY_OR_STORAGE_UNAVAILABLE',lambda:execute(self.store,credentials=CREDENTIALS,transport=lambda *_:self.fail('network'),clock=lambda:NOW))
        with self.store.connect() as db:self.assertEqual(self.store.load(db)['attempt_count'],0)

    def test_expired_content_path_stops_before_content_get(self):
        transport=Transport(); times=[NOW,NOW,NOW,NOW+timedelta(minutes=5)]; index=[0]
        def clock():
            value=times[min(index[0],len(times)-1)]; index[0]+=1; return value
        self.code('CONTENT_EXPIRED',lambda:execute(self.store,credentials=CREDENTIALS,transport=transport,clock=clock))
        self.assertEqual(transport.requests,['auth','initial-aixm-soap'])

    def test_wrong_digest_cli_cannot_reach_credentials_or_network(self):
        child=subprocess.run([sys.executable,'-B',str(SCRIPTS/'capture_initial_load.py'),'--store',str(self.store.root),
            '--account','SYNTHETIC-ACCOUNT','--execute','--external-history-attested','--approve-operation','wrong'],capture_output=True,timeout=15,env={})
        self.assertEqual((child.returncode,child.stdout.strip(),child.stderr),(1,b'INVALID_REQUEST',b''))

if __name__ == '__main__': unittest.main()
