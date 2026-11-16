"""Supervised opaque FAA Initial Load capture; review is the default.

This is intentionally not the collector: it never calls a decoder, changes a
baseline/cursor/catalog/outbox, or opens a public path.  Execution is a separate
owner-approved operation and is not performed by tests or review mode.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

from capture_domestic_candidate import default_store_path
from nms_http import HTTPAdapter
from nms_refresh import Store, encode
from nms_refresh_contract import RefreshError, Request, auth_request, content_request, initial_request, stamp

MAX_CONTROL_BYTES = 1024 * 1024
MAX_CONTENT_BYTES = 1024 * 1024 * 1024
TIMEOUT_SECONDS = 300
OPERATION = {
    'schema': 1, 'purpose': 'opaque-initial-load-evidence-only',
    'auth': {'method': 'POST', 'url': 'https://api-nms.aim.faa.gov/v1/auth/token'},
    'initial_load': {'method': 'GET', 'url': 'https://api-nms.aim.faa.gov/nmsapi/v1/notams/il?allowRedirect=false'},
    'continuation': 'at most one same-host authenticated /nmsapi/v1/content/{token}',
    'network_calls': {'oauth_post': 1, 'initial_load_get': 1, 'content_get_max': 1},
    'redirects': False, 'retries': False, 'decode': False, 'publication': False,
    'baseline': False, 'watermark': None, 'content_max_bytes': MAX_CONTENT_BYTES,
    'timeout_seconds_per_call': TIMEOUT_SECONDS,
}

def operation_digest(): return hashlib.sha256(encode(OPERATION)).hexdigest()

def review(store, now):
    """Read the existing shared ledger only; no credentials, reservations or I/O."""
    budget = store.budget_review(now)
    evidence_root = store.root/'initial-load-evidence'
    usage = shutil.disk_usage(store.root)
    return {'operation': OPERATION, 'operation_approval_digest': operation_digest(),
            'budget': budget, 'credentials_read': False, 'provider_requests_made': False,
            'reservation_created': False, 'evidence_root_exists': evidence_root.exists(),
            'storage_free_bytes': usage.free, 'storage_required_bytes': MAX_CONTENT_BYTES,
            'storage_ready': usage.free >= MAX_CONTENT_BYTES,
            'remaining_gate': 'CURRENT_ACCOUNT_WIDE_HISTORY_EXTERNAL_ACTIVITY_OWNER_APPROVAL_AND_STORAGE_REQUIRED'}

def _token(body):
    try:
        token = json.loads(body)['access_token']
        if not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token): raise ValueError()
        return token
    except Exception: raise RefreshError('AUTH_FAILED') from None

def _content_path(body, started, now):
    try:
        value = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not (isinstance(value, dict) and value.get('status') == 'Success' and value.get('errors') in (None, [])
                and isinstance(value.get('data'), dict) and isinstance(value['data'].get('url'), str)):
            raise ValueError()
        return content_request(value['data']['url'], started, now)
    except RefreshError: raise
    except Exception: raise RefreshError('INVALID_RESPONSE') from None

def _direct_initial(body):
    """Only explicitly recognizable non-JSON initial bodies can bypass control JSON."""
    return body.startswith((b'\x1f\x8b', b'PK\x03\x04', b'BZh', b'\xfd7zXZ\x00', b'<?xml'))

def execute(store, *, credentials, transport, clock):
    """Perform the exact capped 1 POST + 1 IL GET + optional 1 content GET."""
    if not callable(transport): raise RefreshError('INVALID_REQUEST')
    attempt = None
    with store.connect() as db:
        try:
            # Recheck immediately before admission. A prior dry-run is never a
            # reservation, and insufficient disk must not consume one.
            store.storage.verify_private(store.root)
            if shutil.disk_usage(store.root).free < MAX_CONTENT_BYTES:
                raise RefreshError('HISTORY_OR_STORAGE_UNAVAILABLE')
            attempt, _ = store.reserve(db, 'bulk', clock())
            evidence_parent = store.root/'initial-load-evidence'
            if not evidence_parent.exists(): store.storage.create_attempt(evidence_parent)
            store.storage.verify_private(evidence_parent)
            evidence = evidence_parent/attempt
            store.storage.create_attempt(evidence)
            stages = []
            def call(request, token=None, limit=MAX_CONTROL_BYTES):
                at = clock(); store.call_reserved(db, attempt, request.stage, at)
                stages.append({'stage': request.stage, 'reserved_utc': stamp(at)})
                headers = dict(request.headers)
                if token is not None: headers['Authorization'] = 'Bearer '+token
                request = Request(request.stage, request.url, headers, request.body, request.method)
                try: status, _, body = transport(request, limit)
                except Exception: raise RefreshError('TRANSPORT_FAILED') from None
                if not isinstance(body, bytes) or len(body) > limit: raise RefreshError('RESPONSE_TOO_LARGE')
                if status != 200: raise RefreshError('AUTH_FAILED' if request.stage == 'auth' else 'HTTP_FAILED')
                if request.stage != 'auth': store.received(db, attempt, request.stage, body, clock())
                return body
            token = _token(call(auth_request(credentials), limit=65536))
            started = stamp(clock()); control = call(initial_request(), token)
            next_request = _content_path(control, started, clock()) if control[:1] in (b'{', b'[') else None
            if next_request is None and not _direct_initial(control):
                raise RefreshError('INVALID_RESPONSE')
            artifact = evidence/('content.partial' if next_request else 'initial-load.bin')
            if next_request:
                store.storage.private_write(artifact, b'')
                total = 0; digest = hashlib.sha256()
                with artifact.open('ab') as stream:
                    def sink(chunk):
                        nonlocal total
                        total += len(chunk)
                        if total > MAX_CONTENT_BYTES: raise OSError()
                        stream.write(chunk); digest.update(chunk)
                    at = clock(); store.call_reserved(db, attempt, next_request.stage, at)
                    stages.append({'stage': next_request.stage, 'reserved_utc': stamp(at)})
                    try: status, detail = transport.stream(Request(next_request.stage, next_request.url,
                        {'Authorization': 'Bearer '+token}), MAX_CONTENT_BYTES, sink)
                    except Exception: raise RefreshError('TRANSPORT_FAILED') from None
                    stream.flush(); os.fsync(stream.fileno())
                if status != 200: raise RefreshError('HTTP_FAILED')
                if detail != {'bytes': total, 'sha256': digest.hexdigest()}: raise RefreshError('INVALID_RESPONSE')
                completed = evidence/'initial-load.bin'; store.storage.replace(artifact, completed); artifact = completed
            else:
                store.storage.private_write(artifact, control)
            store.storage.verify_private(artifact)
            artifact_bytes = total if next_request else len(control)
            artifact_sha256 = digest.hexdigest() if next_request else hashlib.sha256(control).hexdigest()
            manifest = {'schema': 1, 'attempt': attempt, 'capture_started_utc': started, 'capture_completed_utc': stamp(clock()),
                'initial_control_bytes': len(control), 'initial_control_sha256': hashlib.sha256(control).hexdigest(),
                'bytes': artifact_bytes, 'sha256': artifact_sha256, 'content_continuation_used': bool(next_request),
                'stage_receipts': stages,
                'baseline_established': False, 'watermark': None, 'decoded': False, 'published': False}
            receipt = encode(manifest); store.storage.private_write(evidence/'receipt.json', receipt)
            store.received(db, attempt, 'initial-load-receipt', receipt, clock())
            with store.transaction(db):
                state = store.load(db)
                if state['active'] != attempt: raise RefreshError('RECOVERY_REQUIRED')
                state['active'] = None; store.save(db, state)
                db.execute('UPDATE attempts SET status=? WHERE id=?', ('CAPTURED_INITIAL_LOAD', attempt))
            return {'attempt': attempt, 'status': 'CAPTURED_INITIAL_LOAD', **manifest}
        except Exception as error:
            code = str(error) if isinstance(error, RefreshError) else 'LOCAL_FAILURE'
            if attempt is not None:
                try: store.failed(db, attempt, code, clock())
                except Exception: raise RefreshError('PERSISTENCE_UNCERTAIN') from None
            raise RefreshError(code) from None

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = default_store_path(); parser.add_argument('--store', default=default, required=default is None)
    parser.add_argument('--account', required=True); parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approve-operation'); parser.add_argument('--external-history-attested', action='store_true')
    args = parser.parse_args(); store = Store(args.store, account=args.account)
    try:
        if not args.execute:
            if args.approve_operation or args.external_history_attested: raise RefreshError('INVALID_REQUEST')
            print(json.dumps(review(store, datetime.now(timezone.utc)), indent=2)); return
        if args.approve_operation != operation_digest() or not args.external_history_attested: raise RefreshError('INVALID_REQUEST')
        credentials = {'client_id': os.environ.get('FAA_NMS_CLIENT_ID'), 'client_secret': os.environ.get('FAA_NMS_CLIENT_SECRET')}
        print(json.dumps(execute(store, credentials=credentials, transport=HTTPAdapter(timeout=TIMEOUT_SECONDS, max_bytes=MAX_CONTENT_BYTES), clock=lambda:datetime.now(timezone.utc)), indent=2))
    except RefreshError as error: print(str(error)); raise SystemExit(1) from None

if __name__ == '__main__': main()
