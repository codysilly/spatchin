"""Explicit local history import. Default is a read-only review; never contacts NMS."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone, timedelta

from capture_storage import platform_storage
from nms_refresh import Store, SCHEMA, encode
from nms_refresh_contract import instant, stamp


class HistoryImportError(Exception):
    CODES = set('''IMPORT_INVALID_MANIFEST IMPORT_MISSING_FIELD IMPORT_UNKNOWN_FIELD
    IMPORT_IDENTITY_UNVERIFIED IMPORT_HISTORY_INCOMPLETE IMPORT_INVALID_TIME
    IMPORT_CONTRADICTION IMPORT_UNBOUNDED_UNCERTAINTY IMPORT_EVIDENCE_MISMATCH
    IMPORT_INVALID_SNAPSHOT IMPORT_TARGET_EXISTS IMPORT_INVALID_TARGET
    IMPORT_APPROVAL_MISMATCH IMPORT_STORAGE_FAILURE IMPORT_INTERRUPTED
    IMPORT_FINALIZATION_UNCERTAIN IMPORT_RECOVERY_NOT_ELIGIBLE
    IMPORT_RECOVERY_SCOPE_MISMATCH'''.split())

    def __init__(self, code):
        super().__init__(code if code in self.CODES else 'IMPORT_STORAGE_FAILURE')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_object(value, required, optional=()):
    if not isinstance(value, dict):
        raise HistoryImportError('IMPORT_INVALID_MANIFEST')
    if not set(required) <= set(value):
        raise HistoryImportError('IMPORT_MISSING_FIELD')
    if set(value)-set(required)-set(optional):
        raise HistoryImportError('IMPORT_UNKNOWN_FIELD')


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Exception:
        raise HistoryImportError('IMPORT_INVALID_MANIFEST') from None


def read_bounded(path, maximum):
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(maximum+1)
        if len(data) > maximum:
            raise ValueError()
        return data
    except Exception:
        raise HistoryImportError('IMPORT_EVIDENCE_MISMATCH') from None


def utc(value):
    try:
        return instant(value)
    except Exception:
        raise HistoryImportError('IMPORT_INVALID_TIME') from None


def validate_snapshot(data):
    try:
        value = strict_json(data)
        utc(value['retrieved_utc'])
        if (not isinstance(value['airports'], dict) or 'KMEM' not in value['airports']
                or value.get('synthetic') is True or ('synthetic' in value and type(value['synthetic']) is not bool)):
            raise ValueError()
        for code, entry in value['airports'].items():
            if not re.fullmatch(r'[A-Z0-9]{3,4}', code) or not isinstance(entry['notices'], list):
                raise ValueError()
            for key in ['warning','completeness']:
                if key in entry and not isinstance(entry[key], str):
                    raise ValueError()
            for notice in entry['notices']:
                if not isinstance(notice, dict):
                    raise ValueError()
                for key in ['text','id','number','source','effectiveStart','effectiveEnd','retrieved_utc','scope']:
                    if notice.get(key) is not None and not isinstance(notice[key], str):
                        raise ValueError()
                if 'warnings' in notice and (not isinstance(notice['warnings'], list) or any(not isinstance(w,str) for w in notice['warnings'])):
                    raise ValueError()
                if 'formatted_texts' in notice:
                    if not isinstance(notice['formatted_texts'], list):raise ValueError()
                    for text in notice['formatted_texts']:
                        if not isinstance(text['text'], str) or any(key in text and not isinstance(text[key],str) for key in ['type','field']):
                            raise ValueError()
        return value
    except Exception:
        raise HistoryImportError('IMPORT_INVALID_SNAPSHOT') from None


def _review(manifest_path, target, *, clock, existing_target=False):
    """No writes: validate explicit history, byte hashes, identity and destination."""
    target = Path(target)
    if not existing_target and (target.exists() or target.is_symlink()):
        raise HistoryImportError('IMPORT_TARGET_EXISTS')
    if not target.is_absolute() or not target.parent.is_dir() or any((p/'.git').exists() for p in [target,*target.parents]):
        raise HistoryImportError('IMPORT_INVALID_TARGET')
    try:
        platform_storage().validate_location(target)
    except Exception:
        raise HistoryImportError('IMPORT_INVALID_TARGET') from None
    raw = read_bounded(manifest_path, 1024*1024)
    manifest = strict_json(raw)
    checked_object(manifest, ['schema_version','account','history','attempts','uncertainties','prior_snapshot'])
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
        raise HistoryImportError('IMPORT_INVALID_MANIFEST')
    account = manifest['account']
    checked_object(account, ['logical_id','identity_reference','identity_confirmed','all_clients_quiesced'])
    if (not isinstance(account['logical_id'], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',account['logical_id'])
            or not isinstance(account['identity_reference'],str) or not account['identity_reference'].strip()
            or account['identity_confirmed'] is not True or account['all_clients_quiesced'] is not True):
        raise HistoryImportError('IMPORT_IDENTITY_UNVERIFIED')
    history = manifest['history']
    checked_object(history, ['inventory_complete','complete_through_utc','declaration_reference'])
    if history['inventory_complete'] is not True or not isinstance(history['declaration_reference'],str) or not history['declaration_reference'].strip():
        raise HistoryImportError('IMPORT_HISTORY_INCOMPLETE')
    through = utc(history['complete_through_utc'])
    if through > clock():
        raise HistoryImportError('IMPORT_INVALID_TIME')
    attempts, uncertainties = manifest['attempts'], manifest['uncertainties']
    if not isinstance(attempts,list) or not isinstance(uncertainties,list):
        raise HistoryImportError('IMPORT_INVALID_MANIFEST')
    ids=set(); evidence=[]; calls=0; untimed=0; rows=[]; uncertain_ids=set()
    stages={'auth','initial-aixm-soap','initial-classification-geojson','content','delta','other-data'}
    for index, attempt in enumerate(attempts):
        checked_object(attempt, ['id','kind','reserved_utc','last_io_utc','last_io_is_upper_bound','outcome','receipt','calls','known_call_count'])
        if (not isinstance(attempt['id'],str) or not attempt['id'] or attempt['id'] in ids
                or attempt['kind'] not in ('bulk','delta','other-data')
                or attempt['outcome'] not in ('succeeded','failed','uncertain')):
            raise HistoryImportError('IMPORT_CONTRADICTION')
        ids.add(attempt['id'])
        start, end = utc(attempt['reserved_utc']), utc(attempt['last_io_utc'])
        if start > end or end > through:
            raise HistoryImportError('IMPORT_CONTRADICTION')
        uncertain = attempt['outcome']=='uncertain'
        if type(attempt['last_io_is_upper_bound']) is not bool or (uncertain and not attempt['last_io_is_upper_bound']):
            raise HistoryImportError('IMPORT_UNBOUNDED_UNCERTAINTY')
        if attempt['last_io_is_upper_bound'] and not uncertain:
            raise HistoryImportError('IMPORT_CONTRADICTION')
        if uncertain:
            uncertain_ids.add(attempt['id'])
        receipt=attempt['receipt']; checked_object(receipt,['path','sha256'])
        if not Path(receipt['path']).is_absolute() or not re.fullmatch(r'[a-f0-9]{64}',receipt['sha256']):
            raise HistoryImportError('IMPORT_EVIDENCE_MISMATCH')
        receipt_bytes=read_bounded(receipt['path'],4*1024*1024)
        if digest(receipt_bytes)!=receipt['sha256']:
            raise HistoryImportError('IMPORT_EVIDENCE_MISMATCH')
        evidence.append({'index':index,'sha256':receipt['sha256']})
        if not isinstance(attempt['calls'],list) or type(attempt['known_call_count']) is not int:
            raise HistoryImportError('IMPORT_INVALID_MANIFEST')
        if attempt['known_call_count']!=len(attempt['calls']):
            raise HistoryImportError('IMPORT_CONTRADICTION')
        # This repository's SPA-26 receipt has defined pre-I/O auth/GET counters.
        # Other receipt formats remain hash-backed evidence for operator review;
        # their field names are not guessed into accounting semantics.
        try:
            receipt_value=strict_json(receipt_bytes)
        except HistoryImportError:
            receipt_value={}
        if isinstance(receipt_value,dict) and receipt_value.get('ledger')=='SPA-26':
            for field,number in [('auth_attempts',sum(c.get('stage')=='auth' for c in attempt['calls'] if isinstance(c,dict))),
                                 ('data_attempts',sum(c.get('stage')!='auth' for c in attempt['calls'] if isinstance(c,dict)))]:
                if type(receipt_value.get(field)) is not int or receipt_value[field]!=number:
                    raise HistoryImportError('IMPORT_CONTRADICTION')
        last=start
        for call in attempt['calls']:
            checked_object(call,['stage','at_utc','certainty'])
            if call['at_utc'] is None:
                if not uncertain or call['certainty']!='unknown-time' or call['stage'] not in stages:
                    raise HistoryImportError('IMPORT_UNBOUNDED_UNCERTAINTY')
                untimed+=1;calls+=1
                continue  # Retain a counted, explicitly unknown time; never fill one in.
            when=utc(call['at_utc'])
            if call['stage'] not in stages or call['certainty'] not in ('observed','reserved') or when<last or when>end:
                raise HistoryImportError('IMPORT_CONTRADICTION')
            last=when;calls+=1
        rows.append({'index':index,'kind':attempt['kind'],'reserved_utc':attempt['reserved_utc'],
                     'last_io_utc':attempt['last_io_utc'],'last_io_is_upper_bound':attempt['last_io_is_upper_bound'],
                     'outcome':attempt['outcome'],'known_calls':len(attempt['calls']),'receipt_sha256':receipt['sha256']})
    references=set()
    for item in uncertainties:
        checked_object(item,['attempt_id','code'])
        if (item['attempt_id'] not in uncertain_ids or item['attempt_id'] in references
                or item['code'] not in ('OUTCOME_UNKNOWN','TIMING_UNCERTAIN','ADDITIONAL_CALLS_UNKNOWN')):
            raise HistoryImportError('IMPORT_CONTRADICTION')
        references.add(item['attempt_id'])
    if references!=uncertain_ids:
        raise HistoryImportError('IMPORT_UNBOUNDED_UNCERTAINTY')
    prior=manifest['prior_snapshot']; checked_object(prior,['path','bytes','sha256','approved_for_display','origin_attempt_id'])
    if (not Path(prior['path']).is_absolute() or type(prior['bytes']) is not int
            or not 0<prior['bytes']<=64*1024*1024 or prior['approved_for_display'] is not True):
        raise HistoryImportError('IMPORT_INVALID_SNAPSHOT')
    snapshot=read_bounded(prior['path'],64*1024*1024)
    if len(snapshot)!=prior['bytes'] or digest(snapshot)!=prior['sha256']:
        raise HistoryImportError('IMPORT_EVIDENCE_MISMATCH')
    parsed=validate_snapshot(snapshot)
    if utc(parsed['retrieved_utc']) > clock():
        raise HistoryImportError('IMPORT_INVALID_SNAPSHOT')
    origin=next((a for a in attempts if a['id']==prior['origin_attempt_id']),None)
    if (origin is None or origin['outcome']=='failed' or utc(parsed['retrieved_utc'])<utc(origin['reserved_utc'])
            or utc(parsed['retrieved_utc'])>through or not any(c['stage']!='auth' for c in origin['calls'])):
        raise HistoryImportError('IMPORT_CONTRADICTION')
    approval=digest(encode({'manifest_sha256':digest(raw),'target':str(target.resolve()),
                            'snapshot_sha256':digest(snapshot),'receipts':evidence}))
    report={'approval_digest':approval,'manifest_sha256':digest(raw),'logical_account':account['logical_id'],
            'account_reference_sha256':digest(account['identity_reference'].encode()),
            'attempt_count':len(attempts),'known_call_count':calls,'uncertain_attempt_count':len(uncertain_ids),
            'known_calls_without_timestamps':untimed,
            'history_verified':not bool(uncertain_ids),'activation_hold':bool(uncertain_ids),
            'history_complete_through_utc':history['complete_through_utc'],'attempts':rows,
            'prior_snapshot_bytes':len(snapshot),'prior_snapshot_sha256':digest(snapshot),
            'minimum_primary_not_before_utc':max(utc(a['last_io_utc'])+timedelta(minutes=3) for a in attempts).isoformat(),
            'minimum_bulk_not_before_utc':max([utc(a['last_io_utc'])+timedelta(minutes=3) for a in attempts]+
                [utc(a['last_io_utc'])+timedelta(hours=24) for a in attempts if a['kind']=='bulk']).isoformat(),
            'baseline':False,'watermark':None,'writes_performed':False,'provider_requests_authorized':False}
    return report, manifest, raw, snapshot


def review(manifest_path, target, *, clock=lambda:datetime.now(timezone.utc), _existing_target=False):
    try:
        return _review(manifest_path,target,clock=clock,existing_target=_existing_target)
    except HistoryImportError:
        raise
    except Exception:
        raise HistoryImportError('IMPORT_INVALID_MANIFEST') from None


def import_history(manifest_path, target, *, approve, clock=lambda:datetime.now(timezone.utc), storage=None, checkpoint=None):
    """Fresh target only. No resume/reset; interruptions leave a blocked audit artifact."""
    report, manifest, raw, snapshot = review(manifest_path,target,clock=clock)
    if approve != report['approval_digest']:
        raise HistoryImportError('IMPORT_APPROVAL_MISMATCH')
    storage=storage or platform_storage();target=Path(target);db=None;created=False;finalizing=False
    def point(name):
        if checkpoint is not None:
            checkpoint(name)  # Test-only fault seam; no default hook or network.
    try:
        storage.create_attempt(target);created=True
        marker={'schema':1,'state':'PENDING','approval_digest':approve}
        storage.private_write(target/'import-status.json',encode(marker))
        storage.private_write(target/'import-manifest.private.json',raw)
        point('pending')
        for name in ['account.sqlite3','account.sqlite3-journal']:
            storage.private_write(target/name,b'')
        db=sqlite3.connect((target/'account.sqlite3').as_uri()+'?mode=rw',uri=True,isolation_level=None)
        if db.execute('PRAGMA journal_mode=PERSIST').fetchone()[0]!='persist':raise ValueError()
        db.execute('PRAGMA synchronous=EXTRA')
        db.executescript(SCHEMA)
        held=report['activation_hold']
        state={'schema':1,'account':manifest['account']['logical_id'],'history_verified':False,
               'history_complete_through':manifest['history']['complete_through_utc'],
               'scope':'all-classifications','airport':'KMEM','baseline':False,'watermark':None,
               'active':None,'recovery':'IMPORT_IN_PROGRESS','catalog':{},
               'published_b64':base64.b64encode(snapshot).decode(),'attempt_count':report['attempt_count'],
               'call_count':report['known_call_count'],'response_count':0,'import_digest':approve}
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO state VALUES (1,?)',(encode(state).decode(),))
        for attempt in manifest['attempts']:
            status='IMPORTED_UNCERTAIN' if attempt['outcome']=='uncertain' else 'IMPORTED_'+attempt['outcome'].upper()
            db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)',(attempt['id'],attempt['kind'],
                attempt['reserved_utc'],attempt['last_io_utc'],status,'IMPORTED_UNCERTAINTY' if held else None))
            for index,call in enumerate(attempt['calls']):
                db.execute('INSERT INTO calls VALUES (?,?,?)',(attempt['id'],'imported-'+str(index)+'-'+call['stage'],
                           call['at_utc'] if call['at_utc'] is not None else 'UNVERIFIED_TIME'))
        db.execute('COMMIT');point('history-written')
        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError()
        if db.execute('SELECT count(*) FROM attempts').fetchone()[0]!=report['attempt_count']:raise ValueError()
        if db.execute('SELECT count(*) FROM calls').fetchone()[0]!=report['known_call_count']:raise ValueError()
        state.update(history_verified=not held,recovery='IMPORTED_UNCERTAINTY' if held else None)
        db.execute('BEGIN IMMEDIATE');db.execute('UPDATE state SET document=? WHERE singleton=1',(encode(state).decode(),));db.execute('COMMIT')
        db.close();db=None
        for path in target.iterdir():storage.verify_private(path)
        # Re-read source hashes immediately before finalization; never edit evidence.
        second,_,_,_=review(manifest_path,target,clock=clock,_existing_target=True)
        if second['approval_digest']!=approve:
            raise HistoryImportError('IMPORT_EVIDENCE_MISMATCH')
        point('validated')
        marker['state']='HELD_UNCERTAINTY' if held else 'READY'
        storage.private_write(target/'import-status.next',encode(marker))
        finalizing=True
        storage.replace(target/'import-status.next',target/'import-status.json')
        if (target/'import-status.json').read_bytes()!=encode(marker):raise ValueError()
        point('finalized')
        if not held:
            store=Store(target,account=manifest['account']['logical_id'],storage=storage)
            if store.snapshot()!=snapshot:raise ValueError()
        return {**report,'writes_performed':True,'status':'IMPORTED_HELD' if held else 'IMPORTED_READY_NO_BASELINE'}
    except FileExistsError:
        raise HistoryImportError('IMPORT_TARGET_EXISTS') from None
    except HistoryImportError:
        raise
    except Exception:
        raise HistoryImportError('IMPORT_FINALIZATION_UNCERTAIN' if finalizing else
                                 'IMPORT_INTERRUPTED' if created else 'IMPORT_STORAGE_FAILURE') from None
    finally:
        if db is not None:
            if db.in_transaction:db.rollback()
            db.close()


def review_uncertainty_release(target, declaration_path, *, clock=lambda:datetime.now(timezone.utc), storage=None):
    """Read-only review of the one bounded historical timing hold."""
    target=Path(target);storage=storage or platform_storage();now=clock()
    try:
        for path in (target,target/'import-status.json',target/'import-manifest.private.json',
                     target/'account.sqlite3',target/'account.sqlite3-journal'):
            storage.validate_location(path);storage.verify_private(path)
        marker=strict_json(read_bounded(target/'import-status.json',8192))
        if (marker.get('schema')!=1 or marker.get('state')!='HELD_UNCERTAINTY'
                or not isinstance(marker.get('approval_digest'),str)):
            raise HistoryImportError('IMPORT_RECOVERY_SCOPE_MISMATCH')
        imported,manifest,_,_=review(target/'import-manifest.private.json',target,
                                     clock=clock,_existing_target=True)
        if marker['approval_digest']!=imported['approval_digest'] or not imported['activation_hold']:
            raise HistoryImportError('IMPORT_RECOVERY_SCOPE_MISMATCH')
        if (len(manifest['uncertainties'])!=1
                or manifest['uncertainties'][0].get('code')!='TIMING_UNCERTAIN'):
            raise HistoryImportError('IMPORT_RECOVERY_SCOPE_MISMATCH')
        uncertain_id=manifest['uncertainties'][0]['attempt_id']
        uncertain=[item for item in manifest['attempts'] if item['id']==uncertain_id]
        if len(uncertain)!=1:
            raise HistoryImportError('IMPORT_RECOVERY_SCOPE_MISMATCH')
        attempt=uncertain[0]
        if (attempt['outcome']!='uncertain' or attempt['last_io_is_upper_bound'] is not True
                or attempt['known_call_count']<1 or any(call['at_utc'] is not None
                or call['certainty']!='unknown-time' for call in attempt['calls'])):
            raise HistoryImportError('IMPORT_RECOVERY_SCOPE_MISMATCH')
        declaration_raw=read_bounded(declaration_path,64*1024)
        declaration=strict_json(declaration_raw)
        checked_object(declaration,['schema_version','account','inventory_complete',
            'all_external_clients_stopped','confirmed_through_utc','statement',
            'bound_import_approval_digest'])
        confirmed=utc(declaration['confirmed_through_utc'])
        if (declaration['schema_version']!=1 or declaration['account']!=manifest['account']['logical_id']
                or declaration['inventory_complete'] is not True
                or declaration['all_external_clients_stopped'] is not True
                or not isinstance(declaration['statement'],str) or not declaration['statement'].strip()
                or declaration['bound_import_approval_digest']!=marker['approval_digest']
                or confirmed>now or now-confirmed>timedelta(minutes=5)):
            raise HistoryImportError('IMPORT_RECOVERY_NOT_ELIGIBLE')
        upper=utc(attempt['last_io_utc'])
        existing=utc(imported['minimum_bulk_not_before_utc'])
        release_not_before=max(upper+timedelta(hours=24),existing)
        db=sqlite3.connect((target/'account.sqlite3').as_uri()+'?mode=ro',uri=True)
        try:
            state=json.loads(db.execute('SELECT document FROM state WHERE singleton=1').fetchone()[0])
            row=db.execute('SELECT status,error,last_io FROM attempts WHERE id=?',(uncertain_id,)).fetchone()
            if (state.get('import_digest')!=marker['approval_digest'] or state.get('active') is not None
                    or state.get('recovery')!='IMPORTED_UNCERTAINTY' or state.get('history_verified') is not False
                    or row!=('IMPORTED_UNCERTAIN','IMPORTED_UNCERTAINTY',attempt['last_io_utc'])
                    or db.execute('SELECT count(*) FROM attempts').fetchone()[0]!=len(manifest['attempts'])):
                raise HistoryImportError('IMPORT_RECOVERY_SCOPE_MISMATCH')
        finally:db.close()
        binding={'schema':1,'target':str(target.resolve()),'account':manifest['account']['logical_id'],
            'account_reference_sha256':imported['account_reference_sha256'],
            'import_approval_digest':marker['approval_digest'],
            'manifest_sha256':imported['manifest_sha256'],
            'prior_snapshot_sha256':imported['prior_snapshot_sha256'],
            'receipt_sha256':attempt['receipt']['sha256'],'uncertain_attempt_id':uncertain_id,
            'uncertainty_code':'TIMING_UNCERTAIN','unknown_call_count':attempt['known_call_count'],
            'upper_bound_utc':attempt['last_io_utc'],'release_not_before_utc':release_not_before.isoformat(),
            'inventory_confirmed_through_utc':declaration['confirmed_through_utc'],
            'declaration_sha256':digest(declaration_raw)}
        approval=digest(encode(binding))
        return {'status':'HISTORICAL_RELEASE_REVIEW','release_approval_digest':approval,
            'release_eligible':now>=release_not_before,'release_not_before_utc':release_not_before.isoformat(),
            'reviewed_utc':stamp(now),'account':manifest['account']['logical_id'],
            'attempt_id':uncertain_id,'known_call_count':attempt['known_call_count'],
            'unknown_individual_timestamps':True,'upper_bound_utc':attempt['last_io_utc'],
            'uncertainty_retained_after_release':True,'inventory_confirmed':True,
            'external_clients_stopped':True,'writes_performed':False,'binding':binding}
    except HistoryImportError:raise
    except Exception:raise HistoryImportError('IMPORT_RECOVERY_SCOPE_MISMATCH') from None


def release_uncertainty(target, declaration_path, *, approve, clock=lambda:datetime.now(timezone.utc), storage=None):
    """Release only a reviewed, elapsed TIMING_UNCERTAIN import hold."""
    storage=storage or platform_storage();target=Path(target)
    report=review_uncertainty_release(target,declaration_path,clock=clock,storage=storage)
    if not report['release_eligible']:
        raise HistoryImportError('IMPORT_RECOVERY_NOT_ELIGIBLE')
    if approve!=report['release_approval_digest']:
        raise HistoryImportError('IMPORT_APPROVAL_MISMATCH')
    raw=read_bounded(declaration_path,64*1024);db=None;finalizing=False
    try:
        storage.private_write(target/'uncertainty-release-declaration.private.json',raw)
        db=sqlite3.connect((target/'account.sqlite3').as_uri()+'?mode=rw',uri=True,isolation_level=None)
        if db.execute('PRAGMA journal_mode=PERSIST').fetchone()[0]!='persist':raise ValueError()
        db.execute('PRAGMA synchronous=EXTRA');db.execute('BEGIN IMMEDIATE')
        state=json.loads(db.execute('SELECT document FROM state WHERE singleton=1').fetchone()[0])
        if state.get('recovery')!='IMPORTED_UNCERTAINTY' or state.get('active') is not None:raise ValueError()
        state.update(history_verified=True,recovery=None,
            history_complete_through=report['binding']['inventory_confirmed_through_utc'],
            historical_uncertainty={
            'status':'RELEASED_BOUNDED_TIMING_UNCERTAINTY','attempt_id':report['attempt_id'],
            'unknown_individual_timestamps':True,'known_call_count':report['known_call_count'],
            'upper_bound_utc':report['upper_bound_utc'],'release_not_before_utc':report['release_not_before_utc'],
            'inventory_confirmed_through_utc':report['binding']['inventory_confirmed_through_utc'],
            'release_approval_digest':approve,'released_utc':report['reviewed_utc'],
            'uncertainty_retained':True})
        db.execute('UPDATE state SET document=? WHERE singleton=1',(encode(state).decode(),));db.execute('COMMIT')
        marker={'schema':1,'state':'READY','approval_digest':state['import_digest'],
                'historical_release_approval_digest':approve}
        storage.private_write(target/'import-status.next',encode(marker));finalizing=True
        storage.replace(target/'import-status.next',target/'import-status.json')
        return {**report,'status':'RELEASED_READY_NO_BASELINE','writes_performed':True}
    except FileExistsError:raise HistoryImportError('IMPORT_RECOVERY_SCOPE_MISMATCH') from None
    except HistoryImportError:raise
    except Exception:raise HistoryImportError('IMPORT_FINALIZATION_UNCERTAIN' if finalizing else 'IMPORT_INTERRUPTED') from None
    finally:
        if db is not None:
            if db.in_transaction:db.rollback()
            db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest');parser.add_argument('--target',required=True)
    parser.add_argument('--write',action='store_true');parser.add_argument('--approve')
    parser.add_argument('--release-declaration');parser.add_argument('--release-historical-hold',action='store_true')
    parser.add_argument('--approve-release')
    args=parser.parse_args()
    try:
        if args.release_declaration:
            if args.manifest or args.write or args.approve:raise HistoryImportError('IMPORT_INVALID_MANIFEST')
            report=review_uncertainty_release(args.target,args.release_declaration)
            print(json.dumps(report,indent=2),flush=True)
            if args.release_historical_hold:
                result=release_uncertainty(args.target,args.release_declaration,approve=args.approve_release)
                print(json.dumps({'status':result['status'],'release_approval_digest':result['release_approval_digest']}))
            elif args.approve_release:raise HistoryImportError('IMPORT_INVALID_MANIFEST')
            return
        if not args.manifest or args.release_historical_hold or args.approve_release:
            raise HistoryImportError('IMPORT_INVALID_MANIFEST')
        report,_,_,_=review(args.manifest,args.target)
        print(json.dumps(report,indent=2),flush=True)  # Review precedes the first write.
        if args.write:
            result=import_history(args.manifest,args.target,approve=args.approve)
            print(json.dumps({'status':result['status'],'activation_hold':result['activation_hold']}))
        elif args.approve:
            raise HistoryImportError('IMPORT_INVALID_MANIFEST')
    except HistoryImportError as error:
        print(str(error));raise SystemExit(1) from None
    except Exception:
        print('IMPORT_INVALID_MANIFEST');raise SystemExit(1) from None


if __name__=='__main__':main()
