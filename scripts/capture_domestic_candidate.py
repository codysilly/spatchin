"""Review or explicitly execute one private DOMESTIC NMS candidate capture.

Review is the default and performs no network, credential read, reservation, or
write. Execution requires a current account-wide history attestation and the
exact operation digest printed by review. No retry, publication, or scheduling.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from nms_http import HTTPAdapter
from nms_refresh import Store, collect_classification_candidate, encode
from nms_refresh_contract import RefreshError


OPERATION = {
    'schema': 1,
    'classification': 'DOMESTIC',
    'auth': {'method': 'POST', 'url': 'https://api-nms.aim.faa.gov/v1/auth/token'},
    'data': {'method': 'GET', 'url':
             'https://api-nms.aim.faa.gov/nmsapi/v1/notams?classification=DOMESTIC&allowRedirect=false',
             'nmsResponseFormat': 'GEOJSON'},
    'continuation': 'at most one documented same-host /nmsapi/v1/content token',
    'retry': False,
    'publication': False,
    'baseline': False,
}


def default_store_path():
    """Use the migrated Windows private ledger unless an operator overrides it."""
    local_app_data = os.environ.get('LOCALAPPDATA')
    return (str(Path(local_app_data) / 'Spatchin' / 'private-faa' / 'ledger')
            if local_app_data else None)


def operation_digest():
    return hashlib.sha256(encode(OPERATION)).hexdigest()


def review(store, now):
    return {'operation': OPERATION, 'operation_approval_digest': operation_digest(),
            'budget': store.budget_review(now), 'credentials_read': False,
            'provider_requests_made': False,
            'authorization_ready': False,
            'remaining_gate': 'CURRENT_ACCOUNT_WIDE_HISTORY_AND_OWNER_APPROVAL_REQUIRED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_store = default_store_path()
    parser.add_argument('--store', default=default_store, required=default_store is None,
                        help='private shared-ledger directory (defaults to the migrated Spatchin ledger)')
    parser.add_argument('--account', required=True, help='logical account ID already bound to the ledger')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--approve-operation')
    parser.add_argument('--external-history-attested', action='store_true')
    args = parser.parse_args()
    store = Store(args.store, account=args.account)
    now = datetime.now(timezone.utc)
    try:
        if not args.execute:
            if args.approve_operation or args.external_history_attested:
                raise RefreshError('INVALID_REQUEST')
            print(json.dumps(review(store, now), indent=2))
            return
        if (args.approve_operation != operation_digest()
                or not args.external_history_attested):
            raise RefreshError('INVALID_REQUEST')
        credentials = {'client_id': os.environ.get('FAA_NMS_CLIENT_ID'),
                       'client_secret': os.environ.get('FAA_NMS_CLIENT_SECRET')}
        result = collect_classification_candidate(store, classification='DOMESTIC',
            credentials=credentials, transport=HTTPAdapter(),
            clock=lambda:datetime.now(timezone.utc))
        print(json.dumps(result, indent=2))
    except RefreshError as error:
        print(str(error))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
