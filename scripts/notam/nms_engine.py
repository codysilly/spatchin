"""Guarded production-state NOTAM engine with an offline injected-input mode.

There is deliberately no HTTP client, credential lookup, retry loop, scheduler,
or public writer here.  Authorized acquisition uses the existing account-bound
Store reservation/response ledger and passes decoded inputs into this engine.
Tests and validation use synthetic inputs and isolated stores.
"""

from __future__ import annotations

import base64
import json

from import_nms_history import strict_json
from nms_baseline_candidate import (
    CandidateError,
    accept_production_candidate,
    build_initial_candidate,
    promote_baseline,
    reconcile_delta,
)
from nms_refresh_contract import instant, stamp
from nms_refresh_contract import (
    RefreshError,
    Request,
    auth_request,
    content_request,
    delta_request,
    initial_request,
)


def accepted_candidate(state):
    try:
        candidate = json.loads(base64.b64decode(state["production_candidate_b64"], validate=True))
    except Exception:
        raise CandidateError("STORE_STATE_INVALID") from None
    if (
        state.get("baseline") is not True
        or candidate.get("baseline_established") is not True
        or state.get("watermark") != candidate.get("watermark")
        or state.get("catalog") != candidate.get("catalog")
    ):
        raise CandidateError("STORE_STATE_INVALID")
    return candidate


def _accepted_candidate(store):
    with store.review_connect() as db:
        return accepted_candidate(store.load(db))


def execute_offline_cycle(
    store,
    *,
    mode,
    now,
    initial_records=None,
    initial_body=None,
    capture_started_utc=None,
    activation_gates=None,
    delta_payload=None,
    delta_started_utc=None,
    before_accept=None,
):
    """Execute one complete synthetic/input-injected acceptance cycle.

    Offline mode intentionally creates no provider request reservation.  It is
    for deterministic validation and recovery exercises only; a live adapter
    must reserve/account network I/O through ``Store`` before invoking the same
    decode/reconcile/accept functions.
    """
    accepted_utc = stamp(now)
    if mode == "baseline":
        if capture_started_utc is None or (initial_records is None) == (initial_body is None):
            raise CandidateError("INVALID_CANDIDATE")
        if initial_body is not None:
            from nms_initial_decoder import decode_initial_candidate

            candidate = decode_initial_candidate(
                initial_body,
                "initial-aixm-soap",
                capture_started_utc=capture_started_utc,
            )
        else:
            candidate = build_initial_candidate(
                initial_records, capture_started_utc=capture_started_utc
            )
        candidate = promote_baseline(candidate, gates=activation_gates, accepted_utc=accepted_utc)
    elif mode == "delta":
        if delta_payload is None:
            raise CandidateError("INVALID_CANDIDATE")
        prior = _accepted_candidate(store)
        candidate = reconcile_delta(
            prior,
            delta_payload,
            requested_since_utc=prior["watermark"],
            received_utc=accepted_utc,
            request_started_utc=delta_started_utc or accepted_utc,
        )
    else:
        raise CandidateError("INVALID_CANDIDATE")
    result = accept_production_candidate(
        store,
        candidate,
        generated_utc=accepted_utc,
        before_accept=before_accept,
    )
    result["mode"] = mode
    result["transport_invoked"] = False
    result["live_network_authorized"] = False
    return result


def collect_engine(
    store,
    *,
    mode,
    credentials,
    transport,
    clock,
    activation_gates=None,
    before_accept=None,
    max_bytes=64 * 1024 * 1024,
    validate_reservation=None,
    validate_candidate=None,
    progress=lambda _message: None,
):
    """Run one ledger-accounted acquisition with injected, single-call transport.

    No retry, environment read, scheduler, or public write is present. The caller
    supplies the existing guarded HTTP adapter only for a separately authorized
    live run; tests supply a synthetic transport.
    """
    if mode not in ("baseline", "delta") or not callable(transport) or max_bytes < 1:
        raise RefreshError("INVALID_REQUEST")
    auth = auth_request(credentials)
    attempt = None
    with store.connect() as db:
        try:

            def check_reservation(db, state, now):
                nonlocal prior
                if mode == "delta":
                    try:
                        prior = accepted_candidate(state)
                    except CandidateError:
                        raise RefreshError("BASELINE_REQUIRED") from None
                if validate_reservation is not None:
                    return validate_reservation(db, state, now)
                return None

            prior = None
            attempt, _ = store.reserve(
                db,
                "bulk" if mode == "baseline" else "delta",
                clock(),
                validate_state=check_reservation,
                production=validate_reservation is not None,
            )
            progress("Request reservation committed.")
            received_at = started = None

            def send(request, token=None):
                nonlocal received_at, started
                at = clock()
                if request.stage == "delta":
                    # The wire window and the cursor use the reserved data-call time.
                    request = delta_request(prior["watermark"], at)
                    started = at
                store.call_reserved(db, attempt, request.stage, at)
                headers = dict(request.headers)
                if token is not None:
                    headers["Authorization"] = "Bearer " + token
                prepared = Request(
                    request.stage, request.url, headers, request.body, request.method
                )
                before_io = clock()
                if before_io < at:
                    raise RefreshError("CLOCK_ROLLBACK")
                if request.stage == "delta":
                    delta_request(prior["watermark"], before_io)
                try:
                    status, _response_headers, body = transport(
                        prepared, 65536 if request.stage == "auth" else max_bytes
                    )
                except Exception:
                    raise RefreshError("TRANSPORT_FAILED") from None
                if not isinstance(body, bytes) or len(body) > (
                    65536 if request.stage == "auth" else max_bytes
                ):
                    raise RefreshError("RESPONSE_TOO_LARGE")
                if status != 200:
                    raise RefreshError("AUTH_FAILED" if request.stage == "auth" else "HTTP_FAILED")
                if request.stage != "auth":
                    received_at = clock()
                    store.received(db, attempt, request.stage, body, received_at)
                return body

            try:
                token = strict_json(send(auth))["access_token"]
                if (
                    not isinstance(token, str)
                    or not token
                    or any(ord(char) < 33 or ord(char) > 126 for char in token)
                ):
                    raise ValueError()
            except RefreshError:
                raise
            except Exception:
                raise RefreshError("AUTH_FAILED") from None

            started = clock()
            if mode == "baseline":
                control_request = initial_request()
                try:
                    control = json.loads(send(control_request, token))
                    if control["status"] != "Success" or control.get("errors") not in (
                        None,
                        [],
                    ):
                        raise ValueError()
                    path = control["data"]["url"]
                except RefreshError:
                    raise
                except Exception:
                    raise RefreshError("INVALID_RESPONSE") from None
                body = send(content_request(path, stamp(started), clock()), token)
                try:
                    from nms_initial_decoder import decode_initial_candidate

                    candidate = decode_initial_candidate(
                        body,
                        "initial-aixm-soap",
                        capture_started_utc=stamp(started),
                    )
                    candidate = promote_baseline(
                        candidate,
                        gates=activation_gates,
                        accepted_utc=stamp(clock()),
                    )
                except CandidateError:
                    raise RefreshError("BASELINE_CUTOVER_REQUIRED") from None
                except Exception:
                    raise RefreshError("INVALID_RESPONSE") from None
            else:
                request = delta_request(prior["watermark"], started)
                try:
                    payload = strict_json(send(request, token))
                    progress("Delta response accounted. Reconciling private state.")
                    candidate = reconcile_delta(
                        prior,
                        payload,
                        requested_since_utc=prior["watermark"],
                        received_utc=stamp(received_at),
                        request_started_utc=stamp(started),
                    )
                except RefreshError:
                    raise
                except CandidateError as error:
                    code = {
                        "DELTA_GAP": "DELTA_GAP",
                        "INVALID_RECORD": "INVALID_RESPONSE",
                    }.get(str(error), "CONFLICT")
                    raise RefreshError(code) from None
                except Exception:
                    raise RefreshError("INVALID_RESPONSE") from None

            if validate_candidate is not None:
                try:
                    validate_candidate(candidate)
                except Exception:
                    raise RefreshError("PUBLICATION_FAILED") from None

            def check_acceptance(db, _state):
                last_io = db.execute(
                    "SELECT last_io FROM attempts WHERE id=?", (attempt,)
                ).fetchone()
                if instant(last_io[0]) > clock():
                    raise RefreshError("CLOCK_ROLLBACK")
                if mode == "delta" and instant(candidate["watermark"]) <= instant(
                    prior["watermark"]
                ):
                    raise RefreshError("CLOCK_ROLLBACK")

            result = accept_production_candidate(
                store,
                candidate,
                generated_utc=stamp(clock()),
                before_accept=before_accept,
                attempt=attempt,
                validate_state=check_acceptance,
            )
            result.update(
                {
                    "mode": mode,
                    "attempt": attempt,
                    "transport_invoked": True,
                    "live_network_authorized": False,
                }
            )
            return result
        except Exception as error:
            code = str(error) if isinstance(error, RefreshError) else "LOCAL_FAILURE"
            if attempt is not None:
                try:
                    store.failed(db, attempt, code, clock())
                except Exception:
                    raise RefreshError("PERSISTENCE_UNCERTAIN") from None
            raise RefreshError(code) from None
