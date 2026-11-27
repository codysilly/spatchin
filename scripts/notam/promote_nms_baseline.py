"""Review or explicitly accept a private Initial Load and overlapping delta."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True

from associate_initial_load_airports import associate_evidence
from capture_global_delta import MAX_RESPONSE_BYTES
from capture_initial_load import MAX_CONTENT_BYTES, MAX_CONTROL_BYTES
from capture_storage import StorageError
from import_nms_history import HistoryImportError, strict_json
from inspect_initial_load_stream import InspectionError, _hash_stream
from nms_baseline_candidate import (
    CandidateError,
    InitialCandidateSink,
    MAX_CANDIDATE_BYTES,
    REQUIRED_ACTIVATION_GATES,
    accept_production_candidate,
    promote_baseline,
    reconcile_delta,
)
from nms_refresh import Store, encode
from nms_refresh_contract import RefreshError, instant, stamp


LOOKBACK = timedelta(hours=24)
ACCOUNTED_STATUSES = {
    "ACCEPTED",
    "CAPTURED_CANDIDATE",
    "CAPTURED_INITIAL_LOAD",
    "CAPTURED_DELTA_PROBE",
    "FAILED_ACCOUNTED",
    "IMPORTED",
    "IMPORTED_FAILED",
    "IMPORTED_SUCCEEDED",
    "IMPORTED_UNCERTAIN",
}


class PromotionError(RefreshError):
    CODES = RefreshError.CODES | {
        "APPROVAL_MISMATCH",
        "BASELINE_ALREADY_ACCEPTED",
        "EVIDENCE_INVALID",
        "LEDGER_CHANGED",
        "STALE_APPROVAL",
    }


def _digest(body):
    return hashlib.sha256(body).hexdigest()


def _ledger_digest(db, store):
    digest = hashlib.sha256()
    for table, query in (
        ("state", "SELECT singleton,document FROM state ORDER BY singleton"),
        ("attempts", "SELECT * FROM attempts ORDER BY id"),
        ("calls", "SELECT * FROM calls ORDER BY attempt,stage"),
        ("responses", "SELECT attempt,stage,at,body FROM responses ORDER BY attempt,stage"),
    ):
        digest.update(encode(table) + b"\n")
        for row in db.execute(query):
            if table == "responses":
                row = (*row[:3], len(row[3]), _digest(row[3]))
            digest.update(encode(row) + b"\n")
    digest.update(encode(store.import_marker()))
    return digest.hexdigest()


def _ledger_ready(db, state, now):
    if (
        state["baseline"] is not False
        or state["watermark"] is not None
        or state.get("production_candidate_b64") is not None
    ):
        raise PromotionError("BASELINE_ALREADY_ACCEPTED")
    if state["recovery"] is not None or state["active"] is not None:
        raise PromotionError("RECOVERY_REQUIRED")
    if instant(state["history_complete_through"]) > now:
        raise PromotionError("CLOCK_ROLLBACK")
    for kind, reserved, last_io, status in db.execute(
        "SELECT kind,reserved,last_io,status FROM attempts"
    ):
        if kind not in ("bulk", "delta", "other-data") or status not in ACCOUNTED_STATUSES:
            raise PromotionError("RECOVERY_REQUIRED")
        reserved, last_io = instant(reserved), instant(last_io)
        if last_io < reserved or last_io > now:
            raise PromotionError("CLOCK_ROLLBACK")
        if now - last_io < timedelta(minutes=3):
            raise PromotionError("BUDGET_WAIT")


def _capture(db, attempt, *, initial):
    kind, status, receipt_stage = (
        ("bulk", "CAPTURED_INITIAL_LOAD", "initial-load-receipt")
        if initial
        else ("delta", "CAPTURED_DELTA_PROBE", "delta-probe-receipt")
    )
    try:
        recorded_kind, reserved, last_io, recorded_status, error = db.execute(
            "SELECT kind,reserved,last_io,status,error FROM attempts WHERE id=?", (attempt,)
        ).fetchone()
        responses = {
            stage: (at, body)
            for stage, at, body in db.execute(
                "SELECT stage,at,body FROM responses WHERE attempt=?", (attempt,)
            )
        }
        receipt_at, raw = responses.pop(receipt_stage)
        if len(raw) > 65536:
            raise ValueError()
        receipt = strict_json(raw)
        started = instant(receipt["capture_started_utc"])
        completed = instant(receipt["capture_completed_utc"])
        stages = receipt["stage_receipts"]
        if (
            (recorded_kind, recorded_status, error) != (kind, status, None)
            or type(receipt["schema"]) is not int
            or receipt["schema"] != 1
            or receipt["attempt"] != attempt
            or receipt["baseline_established"] is not False
            or receipt["watermark"] is not None
            or receipt["published"] is not False
            or not instant(reserved) <= started <= completed <= instant(receipt_at)
            or receipt_at != last_io
            or type(receipt["bytes"]) is not int
            or not re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"])
        ):
            raise ValueError()
        if initial:
            continuation = receipt["content_continuation_used"]
            expected_stages = ["auth", "initial-aixm-soap"] + (["content"] if continuation else [])
            if (
                type(continuation) is not bool
                or receipt["decoded"] is not False
                or not 0 < receipt["bytes"] <= MAX_CONTENT_BYTES
                or set(responses) != {"initial-aixm-soap"}
            ):
                raise ValueError()
            control = responses["initial-aixm-soap"][1]
            if (
                not 0 < len(control) <= MAX_CONTROL_BYTES
                or len(control) != receipt["initial_control_bytes"]
                or _digest(control) != receipt["initial_control_sha256"]
                or not continuation
                and (len(control), _digest(control)) != (receipt["bytes"], receipt["sha256"])
            ):
                raise ValueError()
            body = None
        else:
            expected_stages = ["auth", "delta"]
            if (
                receipt["validated_geojson"] is not True
                or receipt["reconciled"] is not False
                or not 0 < receipt["bytes"] <= MAX_RESPONSE_BYTES
                or set(responses) != {"delta"}
            ):
                raise ValueError()
            body = responses["delta"][1]
            if (len(body), _digest(body)) != (receipt["bytes"], receipt["sha256"]):
                raise ValueError()
        call_times = {item["stage"]: item["reserved_utc"] for item in stages}
        ledger_calls = dict(db.execute("SELECT stage,at FROM calls WHERE attempt=?", (attempt,)))
        times = [instant(item["reserved_utc"]) for item in stages]
        if (
            [item["stage"] for item in stages] != expected_stages
            or call_times != ledger_calls
            or times != sorted(times)
            or not instant(reserved) <= times[0] <= completed
            or not started <= times[1] <= times[-1] <= completed
            or any(
                not instant(call_times[stage]) <= instant(at) <= completed
                for stage, (at, _) in responses.items()
            )
            or initial
            and times[0] > started
        ):
            raise ValueError()
        return receipt, (len(raw), _digest(raw)), body
    except (HistoryImportError, KeyError, TypeError, ValueError, RefreshError):
        raise PromotionError("EVIDENCE_INVALID") from None


def _check_files(store, files):
    try:
        for path, (size, digest) in files.items():
            for location in (path.parent.parent, path.parent, path):
                store.storage.validate_location(location)
                store.storage.verify_private(location)
            with path.open("rb") as stream:
                if _hash_stream(stream, size) != (size, digest):
                    raise PromotionError("EVIDENCE_INVALID")
    except (OSError, StorageError, InspectionError):
        raise PromotionError("EVIDENCE_INVALID") from None


def _fresh(now, reviewed, deadline):
    if now < reviewed:
        raise PromotionError("CLOCK_ROLLBACK")
    if now > deadline:
        raise PromotionError("STALE_APPROVAL")


def review_or_promote(
    store,
    initial_attempt,
    delta_attempt,
    *,
    clock,
    approval=None,
    reviewed_utc=None,
    external_history_attested=False,
):
    """Build an approval from one read snapshot and recheck under the write lock."""
    if not all(re.fullmatch(r"[0-9a-f]{32}", item) for item in (initial_attempt, delta_attempt)):
        raise PromotionError("INVALID_REQUEST")
    if (
        initial_attempt == delta_attempt
        or (approval is None) != (reviewed_utc is None)
        or (approval is not None) != external_history_attested
        or approval is not None
        and not re.fullmatch(r"[0-9a-f]{64}", approval)
    ):
        raise PromotionError("INVALID_REQUEST")

    now = clock()
    reviewed = instant(reviewed_utc) if reviewed_utc is not None else now
    if reviewed > now:
        raise PromotionError("CLOCK_ROLLBACK")
    with store.review_connect() as db:
        db.execute("BEGIN")
        state = store.load(db)
        _ledger_ready(db, state, reviewed)
        initial, initial_receipt, _ = _capture(db, initial_attempt, initial=True)
        delta, delta_receipt, body = _capture(db, delta_attempt, initial=False)
        ledger = _ledger_digest(db, store)

    started = instant(initial["capture_started_utc"])
    initial_completed = instant(initial["capture_completed_utc"])
    delta_started = instant(delta["capture_started_utc"])
    delta_completed = instant(delta["capture_completed_utc"])
    requested = instant(delta["requested_since_utc"])
    lower = started.replace(microsecond=0) - timedelta(seconds=1)
    cursor = delta_started.replace(microsecond=0) - timedelta(seconds=1)
    if not (
        requested == requested.replace(microsecond=0)
        and requested <= lower < cursor
        and started <= initial_completed <= delta_started <= delta_completed <= reviewed
        and delta_completed - requested <= LOOKBACK
    ):
        raise PromotionError("DELTA_GAP")
    # Keep the original overlap and the proposed next request inside the lookback.
    deadline = min(started, lower, cursor) + LOOKBACK
    _fresh(now, reviewed, deadline)

    initial_dir = store.root / "initial-load-evidence" / initial_attempt
    delta_dir = store.root / "delta-probe-evidence" / delta_attempt
    files = {
        initial_dir / "receipt.json": initial_receipt,
        initial_dir / "initial-load.bin": (initial["bytes"], initial["sha256"]),
        delta_dir / "receipt.json": delta_receipt,
        delta_dir / "response.geojson": (delta["bytes"], delta["sha256"]),
    }
    _check_files(store, files)
    try:
        sink = InitialCandidateSink(capture_started_utc=stamp(started))
        report = associate_evidence(
            initial_dir,
            initial["sha256"],
            expected_bytes=initial["bytes"],
            storage=store.storage,
            record_sink=sink,
        )
        candidate = sink.finish()
        del sink
        candidate.update(
            initial_load_validation=report, capture_completed_utc=stamp(initial_completed)
        )
        candidate = reconcile_delta(
            candidate,
            strict_json(body),
            requested_since_utc=stamp(requested),
            request_started_utc=stamp(delta_started),
            received_utc=stamp(delta_completed),
        )
        del body
    except (HistoryImportError, InspectionError, TypeError, ValueError):
        raise PromotionError("EVIDENCE_INVALID") from None
    if candidate["delta_candidate"]["proposed_replay_cursor_utc"] != stamp(cursor):
        raise PromotionError("DELTA_GAP")

    binding = {
        "operation": "NMS_PRIVATE_BASELINE_PROMOTION_V1",
        "reviewed_utc": stamp(reviewed),
        "expires_utc": stamp(deadline),
        "store_account_sha256": _digest(encode([str(store.root.resolve()), store.account])),
        "ledger_sha256": ledger,
        "initial_evidence": {
            "attempt": initial_attempt,
            "bytes": initial["bytes"],
            "sha256": initial["sha256"],
            "receipt_sha256": initial_receipt[1],
        },
        "delta_evidence": {
            "attempt": delta_attempt,
            "bytes": delta["bytes"],
            "sha256": delta["sha256"],
            "receipt_sha256": delta_receipt[1],
        },
        "candidate_sha256": _digest(encode(candidate)),
        "proposed_watermark_utc": stamp(cursor),
        "requires_external_history_attestation": True,
    }
    digest = _digest(encode(binding))
    _fresh(clock(), reviewed, deadline)
    if approval is None:
        return {
            "status": "REVIEW_ONLY",
            **binding,
            "approval_sha256": digest,
            "initial_capture_started_utc": stamp(started),
            "requested_since_utc": stamp(requested),
            "catalog_records": len(candidate["catalog"]),
            "ledger_counts": {
                table: state[f"{table}_count"] for table in ("attempt", "call", "response")
            },
            "delta_audit": candidate["delta_candidate"]["audit"],
            "coverage": candidate["coverage"],
        }
    if not hmac.compare_digest(approval, digest):
        raise PromotionError("APPROVAL_MISMATCH")

    def validate_state(db, state):
        _ledger_ready(db, state, clock())
        if not hmac.compare_digest(_ledger_digest(db, store), ledger):
            raise PromotionError("LEDGER_CHANGED")
        _check_files(store, files)
        _fresh(clock(), reviewed, deadline)

    accepted = promote_baseline(
        candidate,
        gates=dict.fromkeys(sorted(REQUIRED_ACTIVATION_GATES), True),
        accepted_utc=stamp(clock()),
    )
    del candidate
    accepted.update(watermark=stamp(cursor), promotion_approval_sha256=digest)
    if len(encode(accepted)) > MAX_CANDIDATE_BYTES:
        raise CandidateError("OUTPUT_LIMIT")
    return accept_production_candidate(
        store,
        accepted,
        generated_utc=stamp(delta_completed),
        validate_state=validate_state,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--initial-attempt", required=True)
    parser.add_argument("--delta-attempt", required=True)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--reviewed-utc")
    parser.add_argument("--approve-promotion")
    parser.add_argument("--external-history-attested", action="store_true")
    args = parser.parse_args()
    approval_args = (
        args.reviewed_utc is not None,
        args.approve_promotion is not None,
        args.external_history_attested,
    )
    if (args.promote and not all(approval_args)) or (not args.promote and any(approval_args)):
        parser.error(
            "promotion requires --promote, --reviewed-utc, --approve-promotion and --external-history-attested together"
        )
    try:
        result = review_or_promote(
            Store(args.store, account=args.account),
            args.initial_attempt,
            args.delta_attempt,
            clock=lambda: datetime.now(timezone.utc),
            approval=args.approve_promotion,
            reviewed_utc=args.reviewed_utc,
            external_history_attested=args.external_history_attested,
        )
    except (RefreshError, CandidateError, StorageError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
