"""Prepare or explicitly capture one global FAA NMS GeoJSON delta as private evidence.

Review is the default. It is read-only and does not inspect credentials, reserve an
allowance, or contact the provider. Execution requires the printed operation digest,
an account-wide external-activity attestation, and separate owner authorization.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import shutil

from capture_domestic_candidate import default_store_path
from nms_http import HTTPAdapter
from nms_refresh import Store, encode, payload_features, source_record
from nms_refresh_contract import RefreshError, Request, auth_request, delta_request, instant, stamp

MAX_RESPONSE_BYTES = 256 * 1024 * 1024
# One response can coexist in SQLite, its durable journal/accounting path and the
# private evidence file. Keep a small receipt/filesystem margin as well.
STORAGE_REQUIRED_BYTES = MAX_RESPONSE_BYTES * 3 + 1024 * 1024
TIMEOUT_SECONDS = 300
INTERVAL = "one account-wide data/delta pull per elapsed three minutes"


def _wire_lower_bound(since):
    return instant(since).replace(microsecond=0)


def _storage_capacity(root):
    try:
        free = shutil.disk_usage(root).free
        return free, free >= STORAGE_REQUIRED_BYTES, None
    except Exception:
        return None, False, "PRIVATE_STORAGE_CAPACITY_UNAVAILABLE"


def operation(since):
    lower = _wire_lower_bound(since).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": 1,
        "purpose": "global-geojson-delta-evidence-only",
        "auth": {"method": "POST", "url": "https://api-nms.aim.faa.gov/v1/auth/token"},
        "delta": {
            "method": "GET",
            "path": "/nmsapi/v1/notams",
            "query": {"lastUpdatedDate": lower},
            "header": {"nmsResponseFormat": "GEOJSON"},
            "airport_filters": False,
            "classification_filters": False,
        },
        "account_interval": INTERVAL,
        "network_calls": {"oauth_post": 1, "delta_get": 1},
        "redirects": False,
        "retries": False,
        "publication": False,
        "baseline": False,
        "watermark": None,
        "response_max_bytes": MAX_RESPONSE_BYTES,
        "timeout_seconds_per_call": TIMEOUT_SECONDS,
    }


def operation_digest(since):
    return hashlib.sha256(encode(operation(since))).hexdigest()


def latest_initial_evidence(store):
    """Read bounded receipts only; never expose a protected local path."""
    root = store.root / "initial-load-evidence"
    receipts = []
    if root.is_dir():
        for path in root.glob("*/receipt.json"):
            try:
                store.storage.verify_private(path)
                raw = path.read_bytes()
                if len(raw) > 65536:
                    continue
                value = json.loads(raw)
                started = instant(value["capture_started_utc"])
                completed = instant(value["capture_completed_utc"])
                if (
                    value.get("schema") == 1
                    and value.get("attempt") == path.parent.name
                    and completed >= started
                    and value.get("baseline_established") is False
                    and value.get("watermark") is None
                ):
                    receipts.append((started, completed, value["attempt"]))
            except Exception:
                continue
    if not receipts:
        return None
    started, completed, _attempt = max(receipts, key=lambda item: item[1])
    return {"capture_started_utc": stamp(started), "capture_completed_utc": stamp(completed)}


def proposed_since(store):
    evidence = latest_initial_evidence(store)
    if evidence is None:
        raise RefreshError("HISTORY_OR_STORAGE_UNAVAILABLE")
    # Preserve the collector's existing whole-second, one-second client overlap.
    return stamp(
        instant(evidence["capture_started_utc"]).replace(microsecond=0) - timedelta(seconds=1)
    )


def review(store, now, since=None):
    evidence = latest_initial_evidence(store)
    lower = since or proposed_since(store)
    current = instant(stamp(now))
    requested = instant(lower)
    timestamp_diagnostic = None
    try:
        delta_request(lower, current)
    except RefreshError as error:
        if str(error) not in ("CLOCK_ROLLBACK", "DELTA_GAP"):
            raise
        timestamp_diagnostic = str(error)
    budget = store.delta_budget_review(now)
    storage_free, storage_ready, storage_diagnostic = _storage_capacity(store.root)
    within_lookback = requested <= current and current - requested <= timedelta(hours=24)
    blockers = list(budget["blockers"])
    if timestamp_diagnostic is not None:
        blockers.append(timestamp_diagnostic)
    if not storage_ready:
        blockers.append(storage_diagnostic or "INSUFFICIENT_PRIVATE_STORAGE")
    blockers.append("EXTERNAL_ACCOUNT_ACTIVITY_ATTESTATION_REQUIRED")
    blockers.append("OWNER_EXECUTION_APPROVAL_REQUIRED")
    return {
        "operation": operation(lower),
        "operation_approval_digest": operation_digest(lower),
        "intended_request": {
            "method": "GET",
            "path": "/nmsapi/v1/notams",
            "lastUpdatedDate_utc": operation(lower)["delta"]["query"]["lastUpdatedDate"],
            "nmsResponseFormat": "GEOJSON",
        },
        "initial_load_evidence": evidence,
        "within_documented_24_hour_lookback": within_lookback,
        "timestamp_diagnostic": timestamp_diagnostic,
        "budget": budget,
        "storage_free_bytes": storage_free,
        "storage_required_bytes": STORAGE_REQUIRED_BYTES,
        "storage_ready": storage_ready,
        "storage_diagnostic": storage_diagnostic,
        "locally_eligible": (
            not budget["blockers"] and timestamp_diagnostic is None and storage_ready
        ),
        "actual_request_blocked": True,
        "blockers": blockers,
        "credentials_read": False,
        "provider_requests_made": False,
        "reservation_created": False,
        "files_modified": False,
    }


def _token(body):
    try:
        token = json.loads(body)["access_token"]
        if (
            not isinstance(token, str)
            or not token
            or any(ord(character) < 33 or ord(character) > 126 for character in token)
        ):
            raise ValueError()
        return token
    except Exception:
        raise RefreshError("AUTH_FAILED") from None


def execute(store, *, since, credentials, transport, clock):
    """Capture one validated global delta; never reconcile, activate, or publish it."""
    if not callable(transport):
        raise RefreshError("INVALID_REQUEST")
    attempt = None
    with store.connect() as db:
        try:
            started = clock()
            request = delta_request(since, started)
            store.storage.verify_private(store.root)
            _free, storage_ready, _diagnostic = _storage_capacity(store.root)
            if not storage_ready:
                raise RefreshError("HISTORY_OR_STORAGE_UNAVAILABLE")
            attempt, _ = store.reserve_delta_probe(db, since, started)
            evidence_parent = store.root / "delta-probe-evidence"
            if not evidence_parent.exists():
                store.storage.create_attempt(evidence_parent)
            store.storage.verify_private(evidence_parent)
            evidence = evidence_parent / attempt
            store.storage.create_attempt(evidence)
            stages = []

            def call(prepared, token=None, limit=MAX_RESPONSE_BYTES):
                at = clock()
                store.call_reserved(db, attempt, prepared.stage, at)
                stages.append({"stage": prepared.stage, "reserved_utc": stamp(at)})
                headers = dict(prepared.headers)
                if token is not None:
                    headers["Authorization"] = "Bearer " + token
                outbound = Request(
                    prepared.stage, prepared.url, headers, prepared.body, prepared.method
                )
                try:
                    status, _, body = transport(outbound, limit)
                except Exception:
                    raise RefreshError("TRANSPORT_FAILED") from None
                if not isinstance(body, bytes) or len(body) > limit:
                    raise RefreshError("RESPONSE_TOO_LARGE")
                if status != 200:
                    raise RefreshError("AUTH_FAILED" if prepared.stage == "auth" else "HTTP_FAILED")
                if prepared.stage != "auth":
                    store.received(db, attempt, prepared.stage, body, clock())
                return body

            token = _token(call(auth_request(credentials), limit=65536))
            body = call(request, token)
            store.storage.private_write(evidence / "response.geojson", body)
            try:
                payload = json.loads(
                    body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
                )
                features = payload_features(payload)
                identities = set()
                duplicates = 0
                cancelation_date_fields = 0
                provider_cancellation_types = 0
                other_lifecycle_fields = 0
                for feature in features:
                    record = source_record(feature)
                    if record["id"] in identities:
                        duplicates += 1
                    identities.add(record["id"])
                    if "cancelationDate" in record:
                        cancelation_date_fields += 1
                    if record.get("type") in ("C", "NOTAMC"):
                        provider_cancellation_types += 1
                    if any(
                        key in record for key in ("inactive", "isActive", "status", "lifecycle")
                    ):
                        other_lifecycle_fields += 1
            except RefreshError:
                raise
            except Exception:
                raise RefreshError("INVALID_RESPONSE") from None
            digest = hashlib.sha256(body).hexdigest()
            manifest = {
                "schema": 1,
                "attempt": attempt,
                "capture_started_utc": stamp(started),
                "capture_completed_utc": stamp(clock()),
                "requested_since_utc": stamp(_wire_lower_bound(since)),
                "bytes": len(body),
                "sha256": digest,
                "diagnostic_counts": {
                    "features": len(features),
                    "distinct_source_ids": len(identities),
                    "duplicate_source_ids": duplicates,
                    "records_with_cancelation_date_field": cancelation_date_fields,
                    "records_with_provider_cancellation_type": provider_cancellation_types,
                    "records_with_other_provider_lifecycle_fields": other_lifecycle_fields,
                },
                "stage_receipts": stages,
                "validated_geojson": True,
                "reconciled": False,
                "baseline_established": False,
                "watermark": None,
                "published": False,
            }
            receipt = encode(manifest)
            store.storage.private_write(evidence / "receipt.json", receipt)
            store.received(db, attempt, "delta-probe-receipt", receipt, clock())
            with store.transaction(db):
                state = store.load(db)
                if state["active"] != attempt:
                    raise RefreshError("RECOVERY_REQUIRED")
                state["active"] = None
                store.save(db, state)
                db.execute(
                    "UPDATE attempts SET status=? WHERE id=?", ("CAPTURED_DELTA_PROBE", attempt)
                )
            return {"attempt": attempt, "status": "CAPTURED_DELTA_PROBE", **manifest}
        except Exception as error:
            code = str(error) if isinstance(error, RefreshError) else "LOCAL_FAILURE"
            if attempt is not None:
                try:
                    store.failed(db, attempt, code, clock())
                except Exception:
                    raise RefreshError("PERSISTENCE_UNCERTAIN") from None
            raise RefreshError(code) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = default_store_path()
    parser.add_argument("--store", default=default, required=default is None)
    parser.add_argument("--account", required=True)
    parser.add_argument(
        "--since", help="explicit UTC lower bound; default is verified IL start minus one second"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approve-operation")
    parser.add_argument("--external-history-attested", action="store_true")
    args = parser.parse_args()
    store = Store(args.store, account=args.account)
    try:
        since = args.since or proposed_since(store)
        if not args.execute:
            if args.approve_operation or args.external_history_attested:
                raise RefreshError("INVALID_REQUEST")
            print(json.dumps(review(store, datetime.now(timezone.utc), since), indent=2))
            return
        if args.approve_operation != operation_digest(since) or not args.external_history_attested:
            raise RefreshError("INVALID_REQUEST")
        credentials = {
            "client_id": os.environ.get("FAA_NMS_CLIENT_ID"),
            "client_secret": os.environ.get("FAA_NMS_CLIENT_SECRET"),
        }
        result = execute(
            store,
            since=since,
            credentials=credentials,
            transport=HTTPAdapter(timeout=TIMEOUT_SECONDS, max_bytes=MAX_RESPONSE_BYTES),
            clock=lambda: datetime.now(timezone.utc),
        )
        print(json.dumps(result, indent=2))
    except RefreshError as error:
        print(str(error))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
