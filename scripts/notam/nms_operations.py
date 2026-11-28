"""Operator entry point for one approved NMS delta and controlled Pages delivery."""

import argparse
import contextlib
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4
import zlib
from urllib.parse import parse_qs, urlsplit

if __name__ == "__main__":
    sys.dont_write_bytecode = True

from c070_notam_partition import load_versioned_registry
from capture_global_delta import MAX_RESPONSE_BYTES, STORAGE_REQUIRED_BYTES, TIMEOUT_SECONDS
from capture_storage import StorageError
from import_nms_history import HistoryImportError, strict_json
from nms_baseline_candidate import CandidateError, production_state_values, reconcile_delta
from nms_engine import accepted_candidate, collect_engine
from nms_http import HTTPAdapter
from nms_pages_delivery import MAX_PUBLIC_BYTES, PUBLIC_URL, REMOTE, PagesDelivery, sha256, verify
from nms_publication import PublicationError, build_candidate, retrieval_evidence
from nms_refresh import Store, encode
from nms_refresh_contract import RefreshError, auth_request, delta_request, instant, stamp
from promote_nms_baseline import ACCOUNTED_STATUSES


LEGACY = {
    "bytes": 35545,
    "sha256": "3822538864528a1083628d2b847660408a32547c42a76715dfb0b3a8275c04ed",
    "retrieved_utc": "2026-11-15T10:39:04.087408+00:00",
}
LOOKBACK = timedelta(hours=24)
MIN_INTERVAL = timedelta(minutes=3)
DESTINATION = {"repository": REMOTE, "branch": "main", "url": PUBLIC_URL}
EMPTY = {"schema": 1, "verified": None, "pending": None}


def enforce(condition, code):
    if not condition:
        raise PublicationError(code)


def digest(value):
    return sha256(encode(value))


def approved(value, expected):
    enforce(
        isinstance(value, str)
        and re.fullmatch("[0-9a-f]{64}", value)
        and hmac.compare_digest(value, expected),
        "APPROVAL_MISMATCH",
    )


class Operations:
    def __init__(self, store, *, clock, delivery=None, progress=lambda _message: None):
        self.store = store
        self.clock = clock
        self.progress = progress
        self.root = store.root / "production-operations"
        self.delivery = delivery or PagesDelivery(self.root)
        self.scope = digest([str(store.root.resolve()), store.account])

    def _private(self, path):
        self.store.storage.validate_location(path)
        self.store.storage.verify_private(path)

    def _write(self, path, body):
        temp = path.with_name(f".{path.name}.{uuid4().hex}.next")
        self.store.storage.private_write(temp, body)
        self.store.storage.replace(temp, path)

    def _save(self, state):
        self._write(self.root / "operations.json", encode(state))

    def state(self):
        self._private(self.store.root)
        self.store.storage.validate_location(self.root)
        if not self.root.exists():
            return dict(EMPTY)
        self._private(self.root)
        path = self.root / "operations.json"
        self.store.storage.validate_location(path)
        if not path.exists():
            return dict(EMPTY)
        self._private(path)
        with path.open("rb") as stream:
            result = json.loads(stream.read(16385))
        enforce(
            isinstance(result, dict) and result.keys() == EMPTY.keys() and result["schema"] == 1,
            "OPERATIONS_STATE_INVALID",
        )
        return result

    @contextlib.contextmanager
    def lock(self):
        self._private(self.store.root)
        if not self.root.exists():
            try:
                self.store.storage.create_attempt(self.root)
            except (FileExistsError, StorageError):
                if not self.root.exists():
                    raise
        self._private(self.root)
        path = self.root / "operation.lock"
        self.store.storage.validate_location(path)
        if not path.exists():
            try:
                self.store.storage.private_write(path, b"\0")
            except (FileExistsError, StorageError):
                if not path.exists():
                    raise
        self._private(path)
        with path.open("r+b") as stream:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise PublicationError("OPERATOR_BUSY") from None
            yield

    def _ledger(self):
        with self.store.review_connect() as db:
            db.execute("BEGIN")
            state = self.store.load(db)
            rows = self._attempts(db)
        return state, rows

    @staticmethod
    def _attempts(db):
        return db.execute(
            "SELECT id,kind,reserved,last_io,status,error FROM attempts ORDER BY id"
        ).fetchall()

    @staticmethod
    def _health(state, rows, now):
        candidate = accepted_candidate(state)
        watermark = state["watermark"]
        deadline = instant(watermark) + LOOKBACK
        latest = max(
            instant(state["history_complete_through"]),
            instant(retrieval_evidence(candidate)),
            *(instant(row[3]) for row in rows),
        )
        ambiguous = sum(row[4] == "IMPORTED_UNCERTAIN" for row in rows)
        last_attempt = max(rows, key=lambda row: instant(row[3]), default=None)
        blockers = []
        if latest > now or any(instant(row[2]) > instant(row[3]) for row in rows):
            blockers.append("CLOCK_ROLLBACK")
        if now > deadline:
            blockers.append("DELTA_GAP")
        if (
            state["active"] is not None
            or state["recovery"] is not None
            or any(
                row[4] not in ACCOUNTED_STATUSES or row[1] not in ("bulk", "delta", "other-data")
                for row in rows
            )
        ):
            blockers.append("RECOVERY_REQUIRED")
        not_before = max((instant(row[3]) + MIN_INTERVAL for row in rows), default=now)
        if now < not_before:
            blockers.append("BUDGET_WAIT")
        return {
            "watermark": watermark,
            "retrieved_utc": retrieval_evidence(candidate),
            "lookback_expires_utc": stamp(deadline),
            "next_ledger_delta_utc": stamp(not_before),
            "coverage": "UNKNOWN",
            "catalog_records": len(candidate["catalog"]),
            "accounted_attempts": state["attempt_count"],
            "accounted_calls": state["call_count"],
            "retained_responses": state["response_count"],
            "imported_uncertain_attempts": ambiguous,
            "interrupted_uncertain_attempts": sum(
                row[5] == "INTERRUPTED_UNCERTAIN" for row in rows
            ),
            "history_complete_through_utc": state["history_complete_through"],
            "latest_accounted_utc": last_attempt[3] if last_attempt else None,
            "latest_attempt_status": last_attempt[4] if last_attempt else None,
            "last_production_delta": state.get("last_production_delta"),
            "active_attempt": state["active"],
            "ledger_recovery": state["recovery"],
            "blockers": blockers,
        }

    def status(self):
        state, rows = self._ledger()
        health = self._health(state, rows, self.clock())
        operations = self.state()
        return {"status": "READ_ONLY", **health, "publication": operations}

    def _delta_binding(self, state, rows, now, watermark):
        health = self._health(state, rows, now)
        for code in health["blockers"]:
            raise RefreshError(code)
        enforce(instant(health["watermark"]) == instant(watermark), "APPROVED_WATERMARK_CHANGED")
        binding = {
            "operation": "ONE_GLOBAL_NMS_DELTA_V1",
            "store_account_sha256": self.scope,
            "watermark": health["watermark"],
            "lookback_expires_utc": health["lookback_expires_utc"],
            "ledger_sha256": digest([rows, state["call_count"], state["response_count"]]),
            "history_complete_through_utc": state["history_complete_through"],
            "accepted_state_sha256": sha256(state["production_candidate_b64"].encode()),
            "external_account_attestation_required": True,
        }
        return {**binding, "approval_sha256": digest(binding)}

    def review_delta(self, watermark):
        enforce(self.state() == EMPTY, "PRODUCTION_PUBLICATION_ALREADY_STARTED")
        state, rows = self._ledger()
        return self._delta_binding(state, rows, self.clock(), watermark)

    @staticmethod
    def _project(candidate, stale_after_hours):
        snapshot, manifest, body = build_candidate(
            candidate,
            load_versioned_registry(),
            generated_utc=retrieval_evidence(candidate),
            stale_after_hours=stale_after_hours,
        )
        enforce(0 < len(body) <= MAX_PUBLIC_BYTES, "PUBLIC_SNAPSHOT_SIZE_LIMIT")
        return snapshot, manifest, body

    def _collect(self, *, credentials, transport, guard, freshness=None):
        auth_request(credentials)
        free = shutil.disk_usage(self.store.root).free
        enforce(
            free
            >= STORAGE_REQUIRED_BYTES + 2 * (self.store.root / "account.sqlite3").stat().st_size,
            "PRIVATE_STORAGE_CAPACITY_UNAVAILABLE",
        )
        return collect_engine(
            self.store,
            mode="delta",
            clock=self.clock,
            transport=transport,
            credentials=credentials,
            max_bytes=MAX_RESPONSE_BYTES,
            validate_reservation=guard,
            validate_candidate=lambda candidate: self._project(candidate, freshness),
            progress=self.progress,
        )

    def catch_up(self, watermark, approval, *, attest, credentials, transport):
        enforce(attest, "EXTERNAL_ACCOUNT_ATTESTATION_REQUIRED")
        # Check the digest before even creating local operator files.
        approved(approval, self.review_delta(watermark)["approval_sha256"])
        with self.lock():
            enforce(self.state() == EMPTY, "PRODUCTION_PUBLICATION_ALREADY_STARTED")

            def guard(db, state, now):
                binding = self._delta_binding(state, self._attempts(db), now, watermark)
                approved(approval, binding["approval_sha256"])
                return approval

            return self._collect(credentials=credentials, transport=transport, guard=guard)

    def _retained_delta(self, db, state, attempt, response_sha, watermark):
        rows = self._attempts(db)
        enforce(
            sum(row[0] == attempt for row in rows) == 1
            and all(row[4] in ACCOUNTED_STATUSES for row in rows),
            "RECOVERY_ATTEMPT_MISMATCH",
        )
        row = next(row for row in rows if row[0] == attempt)
        _, kind, reserved, accounted, status, error = row
        enforce(
            (kind, status, error) == ("delta", "FAILED_ACCOUNTED", "CONFLICT"),
            "RECOVERY_ATTEMPT_MISMATCH",
        )
        calls = db.execute(
            "SELECT stage,at FROM calls WHERE attempt=? ORDER BY stage", (attempt,)
        ).fetchall()
        responses = db.execute(
            "SELECT stage,at,typeof(body),length(body) FROM responses WHERE attempt=?", (attempt,)
        ).fetchall()
        enforce(
            [stage for stage, _ in calls] == ["auth", "delta"]
            and len(responses) == 1
            and responses[0][0] == "delta"
            and responses[0][2] == "blob"
            and 0 < responses[0][3] <= MAX_RESPONSE_BYTES,
            "RECOVERY_RESPONSE_MISMATCH",
        )
        _, received, _, size = responses[0]
        (body,) = db.execute(
            "SELECT body FROM responses WHERE attempt=? AND stage='delta'", (attempt,)
        ).fetchone()
        approved(response_sha, sha256(body))
        auth, started = (instant(at) for _, at in calls)
        lower = instant(watermark)
        enforce(
            lower.microsecond == 0
            and lower
            < instant(reserved)
            <= auth
            <= started
            <= instant(received)
            <= instant(accounted)
            <= self.clock(),
            "RECOVERY_REQUEST_TIMING_MISMATCH",
        )
        request = delta_request(watermark, started)
        wire_lower = parse_qs(urlsplit(request.url).query)["lastUpdatedDate"][0]
        enforce(instant(wire_lower) == lower, "RECOVERY_REQUEST_TIMING_MISMATCH")
        evidence = {
            "store_account_sha256": self.scope,
            "attempt": attempt,
            "attempt_reserved_utc": reserved,
            "auth_reserved_utc": stamp(auth),
            "delta_reserved_utc": stamp(started),
            "requested_since_utc": wire_lower,
            "received_utc": received,
            "accounted_utc": accounted,
            "response_sha256": response_sha,
            "response_bytes": size,
        }
        receipt = state.get("retained_delta_recovery")
        if receipt is not None and receipt["attempt"] == attempt:
            enforce(
                all(receipt[key] == value for key, value in evidence.items()),
                "RECOVERY_EVIDENCE_CHANGED",
            )
            return receipt, None
        enforce(
            state["active"] is None
            and state["recovery"] == "CONFLICT"
            and state.get("production_active_attempt") is None
            and state.get("production_active_approval") is None
            and instant(state["watermark"]) == lower
            and all(other[0] == attempt or instant(other[3]) < instant(reserved) for other in rows),
            "RECOVERY_BASELINE_OR_HOLD_CHANGED",
        )
        counts = {name: state[f"{name}_count"] for name in ("attempt", "call", "response")}
        evidence.update(
            ledger_counts=counts,
            ledger_sha256=digest([rows, counts, state["history_complete_through"]]),
            accepted_state_sha256=sha256(state["production_candidate_b64"].encode()),
            accepted_snapshot_sha256=sha256(state["published_b64"].encode()),
        )
        return evidence, body

    def _review_retained_delta(self, attempt, response_sha, watermark, preserve_pair):
        with self.store.review_connect() as db:
            db.execute("BEGIN")
            state = self.store.load(db)
            # Keep validation errors outside Store's connection error mapping.
            try:
                evidence, body = self._retained_delta(db, state, attempt, response_sha, watermark)
            except (PublicationError, RefreshError) as error:
                result = error
            else:
                result = None
        if result is not None:
            raise result
        if body is None:
            enforce(
                evidence["preserve_unresolved_pair_sha256"] == preserve_pair,
                "RECOVERY_EVIDENCE_CHANGED",
            )
            return {**evidence, "status": "ALREADY_RECOVERED"}, None
        enforce(self.state() == EMPTY, "PRODUCTION_PUBLICATION_ALREADY_STARTED")
        prior = accepted_candidate(state)
        enforce(
            instant(retrieval_evidence(prior)) <= instant(evidence["attempt_reserved_utc"]),
            "RECOVERY_REQUEST_TIMING_MISMATCH",
        )
        previous_delta = prior.get("delta_candidate")
        if previous_delta is not None:
            enforce(
                instant(previous_delta["proposed_replay_cursor_utc"]) == instant(watermark),
                "RECOVERY_BASELINE_OR_HOLD_CHANGED",
            )
        try:
            payload = strict_json(body)
        except HistoryImportError:
            raise PublicationError("RECOVERY_RESPONSE_MISMATCH") from None
        try:
            candidate = reconcile_delta(
                prior,
                payload,
                requested_since_utc=evidence["requested_since_utc"],
                received_utc=evidence["received_utc"],
                request_started_utc=evidence["delta_reserved_utc"],
                preserve_unresolved_pair=preserve_pair,
            )
        except CandidateError as error:
            if preserve_pair is None and error.unresolved_pair_sha256 is not None:
                return {
                    **evidence,
                    "status": "OWNER_DECISION_REQUIRED",
                    "error": str(error),
                    "unresolved_pair_sha256": error.unresolved_pair_sha256,
                }, None
            raise
        enforce(instant(candidate["watermark"]) > instant(watermark), "RECOVERY_CURSOR_INVALID")
        snapshot, manifest, _ = self._project(candidate, None)
        enforce(len(snapshot["airports"]) == 130, "INVALID_C070_REGISTRY")
        values, _ = production_state_values(candidate, generated_utc=evidence["received_utc"])
        binding = {
            "operation": "REPROCESS_RETAINED_NMS_DELTA_V1",
            **evidence,
            "preserve_unresolved_pair_sha256": preserve_pair,
            "candidate_sha256": sha256(values["production_candidate_b64"].encode()),
            "private_snapshot_sha256": sha256(values["published_b64"].encode()),
            "watermark": candidate["watermark"],
            "lookback_expires_utc": stamp(instant(candidate["watermark"]) + LOOKBACK),
            "catalog_records": len(candidate["catalog"]),
            "audit": candidate["delta_candidate"]["audit"],
            "manifest": manifest,
        }
        return {**binding, "approval_sha256": digest(binding), "status": "REVIEW_ONLY"}, values

    def review_retained_delta(self, attempt, response_sha, watermark, preserve_pair=None):
        review, _ = self._review_retained_delta(attempt, response_sha, watermark, preserve_pair)
        return review

    def recover_retained_delta(self, attempt, response_sha, watermark, preserve_pair, approval):
        review, values = self._review_retained_delta(
            attempt, response_sha, watermark, preserve_pair
        )
        enforce(review["status"] != "OWNER_DECISION_REQUIRED", "OWNER_DECISION_REQUIRED")
        approved(approval, review["approval_sha256"])
        if values is None:
            return review
        receipt = {key: value for key, value in review.items() if key != "status"}
        result = None
        with self.lock(), self.store.connect() as db:
            try:
                with self.store.transaction(db):
                    state = self.store.load(db)
                    evidence, body = self._retained_delta(
                        db, state, attempt, response_sha, watermark
                    )
                    if body is None:
                        approved(approval, evidence["approval_sha256"])
                        return {**evidence, "status": "ALREADY_RECOVERED"}
                    enforce(self.state() == EMPTY, "PRODUCTION_PUBLICATION_ALREADY_STARTED")
                    enforce(
                        all(review[key] == value for key, value in evidence.items()),
                        "RECOVERY_EVIDENCE_CHANGED",
                    )
                    state.update(values)
                    state["recovery"] = None
                    state["retained_delta_recovery"] = receipt
                    state["last_production_delta"] = {
                        "attempt": attempt,
                        "approval_sha256": approval,
                        "watermark": receipt["watermark"],
                        "mode": "RETAINED_RESPONSE_RECOVERY",
                    }
                    self.store.save(db, state)
            except (PublicationError, RefreshError) as error:
                result = error
        if result is not None:
            raise result
        return {**receipt, "status": "ACCEPTED_PRIVATE_NOT_PUBLISHED"}

    def _publication(self, freshness=None):
        state, _ = self._ledger()
        candidate = accepted_candidate(state)
        enforce(
            state["active"] is None and state["recovery"] is None,
            "RECOVERY_REQUIRED",
        )
        enforce(instant(retrieval_evidence(candidate)) <= self.clock(), "CLOCK_ROLLBACK")
        snapshot, manifest, body = self._project(candidate, freshness)
        binding = {
            "operation": "INITIAL_NMS_PAGES_PUBLICATION_V1",
            "store_account_sha256": self.scope,
            "watermark": candidate["watermark"],
            "previous": LEGACY,
            "destination": DESTINATION,
            "manifest": manifest,
        }
        return binding, snapshot, body

    def review_publication(self):
        binding, snapshot, body = self._publication()
        return {
            **binding,
            "approval_sha256": digest(binding),
            "airports": len(snapshot["airports"]),
            "notices": sum(len(entry["notices"]) for entry in snapshot["airports"].values()),
            "coverage": "UNKNOWN",
            "compressed_snapshot_bytes": len(zlib.compress(body)),
        }

    def _stage(self, body, manifest):
        verify(body, manifest)
        path = self.root / "candidate.json"
        self.store.storage.validate_location(path)
        if path.exists():
            self._private(path)
            with path.open("rb") as stream:
                old = stream.read(MAX_PUBLIC_BYTES + 1)
            if old == body:
                return path
            enforce(
                instant(json.loads(old)["retrieved_utc"]) < instant(manifest["retrieved_utc"]),
                "OLDER_OR_CONFLICTING_SNAPSHOT",
            )
        self._write(path, body)
        self._private(path)
        verify(path.read_bytes(), manifest)
        return path

    def stage_review(self, expected_sha):
        with self.lock():
            binding, _, body = self._publication()
            approved(expected_sha, binding["manifest"]["sha256"])
            path = self._stage(body, binding["manifest"])
            return {"status": "PRIVATE_REVIEW_COPY", "path": str(path), **binding["manifest"]}

    def serve_review(self, expected_sha):
        from nms_review_server import serve_review

        binding, _, body = self._publication()
        approved(expected_sha, binding["manifest"]["sha256"])
        serve_review(body)

    def _deliver(self, ops, pending, body, manifest):
        saved = pending.get("manifest")
        enforce(saved is None or saved == manifest, "PENDING_PUBLICATION_CHANGED")
        pending["manifest"] = manifest
        self._save(ops)
        self._stage(body, manifest)
        previous = ops["verified"] or LEGACY
        commit = self.delivery.publish(body, manifest, previous, progress=self.progress)
        verified = {**manifest, "git_commit": commit}
        if pending["kind"] == "recurring":
            verified["standing_anchor"] = pending["policy"]["initial_verified_sha256"]
        ops.update(verified=verified, pending=None)
        self._save(ops)
        return {"status": "PUBLIC_DIGEST_VERIFIED", **ops["verified"]}

    def publish_initial(self, approval):
        with self.lock():
            binding, _, body = self._publication()
            approved(approval, digest(binding))
            ops = self.state()
            if ops["verified"] is not None:
                enforce(
                    ops["pending"] is None
                    and ops["verified"]["sha256"] == binding["manifest"]["sha256"],
                    "INITIAL_PUBLICATION_ALREADY_COMPLETED",
                )
                self.delivery.check_current(ops["verified"])
                return {"status": "PUBLIC_DIGEST_VERIFIED", **ops["verified"]}
            pending = ops["pending"]
            if pending is None:
                state, rows = self._ledger()
                enforce(
                    state.get("last_production_delta", {}).get("watermark") == binding["watermark"],
                    "SUPERVISED_DELTA_REQUIRED",
                )
                health = self._health(state, rows, self.clock())
                for code in health["blockers"]:
                    if code != "BUDGET_WAIT":
                        raise RefreshError(code)
                pending = ops["pending"] = {"kind": "initial", "approval": approval}
            enforce(
                pending["kind"] == "initial" and pending["approval"] == approval,
                "PENDING_PUBLICATION_CHANGED",
            )
            return self._deliver(ops, pending, body, binding["manifest"])

    def standing(self, interval_hours, freshness_hours, release, anchor=None):
        enforce(
            1 <= interval_hours <= 12
            and interval_hours < freshness_hours <= 24
            and re.fullmatch("[0-9a-f]{40}", release),
            "INVALID_STANDING_CONFIGURATION",
        )
        ops = self.state()
        enforce(ops["verified"] is not None, "INITIAL_PUBLICATION_REQUIRED")
        policy = {
            "operation": "STANDING_NMS_DELTA_AND_PAGES_V1",
            "store_account_sha256": self.scope,
            "release_commit": release,
            "interval_hours": interval_hours,
            "publication_interval_hours": interval_hours,
            "scheduler_tick_minutes": 15,
            "freshness_hours": freshness_hours,
            "initial_verified_sha256": anchor
            or ops["verified"].get("standing_anchor", ops["verified"]["sha256"]),
            "destination": DESTINATION,
            "provider_retries": 0,
            "standalone_initial_load": False,
        }
        return {**policy, "approval_sha256": digest(policy)}

    def recurring(self, policy, approval, *, attest, credentials, transport):
        approved(approval, policy["approval_sha256"])
        enforce(attest, "EXTERNAL_ACCOUNT_ATTESTATION_REQUIRED")
        auth_request(credentials)
        with self.lock():
            ops = self.state()
            enforce(ops["pending"] is None, "RECOVERY_REQUIRED")
            previous = ops["verified"]
            enforce(previous is not None, "INITIAL_PUBLICATION_REQUIRED")
            enforce(
                previous.get("standing_anchor", previous["sha256"])
                == policy["initial_verified_sha256"],
                "STANDING_APPROVAL_ANCHOR_CHANGED",
            )
            state, rows = self._ledger()
            now = self.clock()
            health = self._health(state, rows, now)
            for blocker in health["blockers"]:
                if blocker != "BUDGET_WAIT":
                    raise RefreshError(blocker)
            enforce(
                instant(health["retrieved_utc"]) == instant(previous["retrieved_utc"]),
                "UNPUBLISHED_PRIVATE_STATE",
            )
            if now < instant(previous["retrieved_utc"]) + timedelta(hours=policy["interval_hours"]):
                return {"status": "CADENCE_WAIT"}
            binding = self._delta_binding(state, rows, now, state["watermark"])
            self.delivery.check_current(previous, check_write=True)
            pending = ops["pending"] = {
                "kind": "recurring",
                "prior_watermark": state["watermark"],
                "approval": approval,
                "policy": policy,
            }
            self._save(ops)

            def guard(db, current, at):
                new = self._delta_binding(current, self._attempts(db), at, state["watermark"])
                approved(binding["approval_sha256"], new["approval_sha256"])
                return approval

            self._collect(
                credentials=credentials,
                transport=transport,
                guard=guard,
                freshness=policy["freshness_hours"],
            )
            return self._resume_recurring(ops)

    def _resume_recurring(self, ops):
        pending = ops["pending"]
        enforce(
            pending is not None and pending["kind"] == "recurring",
            "NO_PENDING_RECURRING_PUBLICATION",
        )
        policy = pending["policy"]
        binding, _, body = self._publication(policy["freshness_hours"])
        enforce(
            instant(binding["watermark"]) > instant(pending["prior_watermark"]),
            "DELTA_NOT_ACCEPTED",
        )
        return self._deliver(ops, pending, body, binding["manifest"])

    def recover_publication(self, approval):
        with self.lock():
            ops = self.state()
            pending = ops["pending"]
            enforce(
                pending is not None and pending["kind"] == "recurring",
                "NO_PENDING_RECURRING_PUBLICATION",
            )
            approved(approval, pending["approval"])
            return self._resume_recurring(ops)

    def _reset_binding(self, state, rows, ops):
        pending, active = ops["pending"], state["active"]
        enforce(state["recovery"] is None, "LEDGER_RECOVERY_REQUIRES_REVIEW")
        enforce(
            active is None or state.get("production_active_attempt") == active,
            "UNKNOWN_RESERVATION",
        )
        enforce(
            (active is not None or pending is not None)
            and (
                pending is None
                or pending["kind"] == "recurring"
                and pending["prior_watermark"] == state["watermark"]
                and "manifest" not in pending
            ),
            "PENDING_PUBLICATION_MUST_BE_RECOVERED",
        )
        blockers = self._health(state, rows, self.clock())["blockers"]
        enforce("CLOCK_ROLLBACK" not in blockers, "CLOCK_ROLLBACK")
        if active is not None:
            match = [row for row in rows if row[0] == active]
            enforce(
                len(match) == 1
                and match[0][1] == "delta"
                and match[0][4] in ("RESERVED", "IO_RESERVED"),
                "UNKNOWN_RESERVATION",
            )
        binding = {
            "operation": "ACCOUNT_INTERRUPTED_NMS_CYCLE_V1",
            "store_account_sha256": self.scope,
            "watermark": state["watermark"],
            "active_attempt": active,
            "attempts_sha256": digest(rows),
            "pending_sha256": digest(pending),
            "external_account_attestation_required": True,
        }
        return {**binding, "approval_sha256": digest(binding)}

    def review_reset(self):
        state, rows = self._ledger()
        return self._reset_binding(state, rows, self.state())

    def reset_interruption(self, approval, *, attest):
        enforce(attest, "EXTERNAL_ACCOUNT_ATTESTATION_REQUIRED")
        approved(approval, self.review_reset()["approval_sha256"])
        with self.lock():
            ops = self.state()
            with self.store.connect() as db, self.store.transaction(db):
                state = self.store.load(db)
                binding = self._reset_binding(state, self._attempts(db), ops)
                approved(approval, binding["approval_sha256"])
                active = state["active"]
                if active is not None:
                    db.execute(
                        "UPDATE attempts SET status=?,error=?,last_io=? WHERE id=?",
                        ("FAILED_ACCOUNTED", "INTERRUPTED_UNCERTAIN", stamp(self.clock()), active),
                    )
                    state["active"] = None
                    state.pop("production_active_attempt", None)
                    state.pop("production_active_approval", None)
                    self.store.save(db, state)
            if ops["pending"] is not None:
                ops["pending"] = None
                self._save(ops)
            return {"status": "INTERRUPTION_ACCOUNTED", "watermark": binding["watermark"]}

    def verify_publication(self):
        manifest = self.state()["verified"]
        enforce(manifest is not None, "NO_VERIFIED_PUBLICATION")
        verify(self.delivery.read_public(), manifest)
        return {"status": "PUBLIC_DIGEST_VERIFIED", **manifest}

    def recover_journal(self):
        with self.lock():
            with self.store.connect() as db:
                self.store.load(db)
            return self.status()


ROOT = Path(__file__).resolve().parents[2]


def verify_release(expected):
    try:
        commands = (
            ("rev-parse", "HEAD"),
            ("diff", "--quiet", "HEAD", "--"),
            ("ls-files", "--others", "--exclude-standard", "--", "scripts/notam"),
        )
        results = [
            subprocess.run(
                ["git", "-C", str(ROOT), *command],
                capture_output=True,
                check=True,
                timeout=20,
            ).stdout.strip()
            for command in commands
        ]
        enforce(results == [expected.encode("ascii"), b"", b""], "COLLECTOR_RELEASE_CHANGED")
    except (OSError, subprocess.SubprocessError):
        raise PublicationError("COLLECTOR_RELEASE_CHANGED") from None


def task_configuration(store, policy):
    return {
        "task_name": "Spatchin-NMS-Production",
        "working_directory": str(ROOT),
        "executable": sys.executable,
        "arguments": subprocess.list2cmdline(
            [
                "-E",
                "-s",
                "-B",
                str(Path(__file__).resolve()),
                "--store",
                str(store.root),
                "--account",
                store.account,
                "cycle",
                "--release-commit",
                policy["release_commit"],
                "--interval-hours",
                str(policy["interval_hours"]),
                "--freshness-hours",
                str(policy["freshness_hours"]),
                "--initial-sha256",
                policy["initial_verified_sha256"],
                "--approve",
                policy["approval_sha256"],
                "--external-history-attested",
            ]
        ),
        "initial_state": "Disabled",
        "scheduler_tick_minutes": policy["scheduler_tick_minutes"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--account", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    sub = {
        name: commands.add_parser(name)
        for name in (
            "status",
            "review-delta",
            "catch-up",
            "review-retained-delta",
            "recover-retained-delta",
            "review-publication",
            "stage-review",
            "serve-review",
            "publish-initial",
            "verify-publication",
            "review-standing",
            "task-config",
            "cycle",
            "recover-publication",
            "review-interruption",
            "account-interruption",
            "recover-journal",
            "runtime-ready",
        )
    }
    for name in ("review-delta", "catch-up", "review-retained-delta", "recover-retained-delta"):
        sub[name].add_argument("--expect-watermark", required=True)
    for name in ("review-retained-delta", "recover-retained-delta"):
        sub[name].add_argument("--attempt", required=True)
        sub[name].add_argument("--response-sha256", required=True)
        sub[name].add_argument("--preserve-unresolved-pair")
    for name in (
        "catch-up",
        "recover-retained-delta",
        "publish-initial",
        "cycle",
        "recover-publication",
        "account-interruption",
        "task-config",
    ):
        sub[name].add_argument("--approve", required=True)
    for name in ("catch-up", "cycle", "account-interruption"):
        sub[name].add_argument("--external-history-attested", action="store_true", required=True)
    sub["stage-review"].add_argument("--sha256", required=True)
    sub["serve-review"].add_argument("--sha256", required=True)
    for name in ("review-standing", "cycle", "task-config"):
        sub[name].add_argument("--interval-hours", type=int, default=6)
        sub[name].add_argument("--freshness-hours", type=int, default=12)
        sub[name].add_argument("--release-commit", required=True)
    sub["cycle"].add_argument("--initial-sha256", required=True)
    sub["recover-journal"].add_argument(
        "--confirm-sqlite-recovery", action="store_true", required=True
    )
    args = parser.parse_args()
    try:
        operations = Operations(
            Store(args.store, account=args.account),
            clock=lambda: datetime.now(timezone.utc),
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        command = args.command.replace("-", "_")
        if command in ("catch_up", "cycle"):
            if command == "catch_up":
                review = operations.review_delta(args.expect_watermark)
            else:
                verify_release(args.release_commit)
                review = operations.standing(
                    args.interval_hours,
                    args.freshness_hours,
                    args.release_commit,
                    args.initial_sha256,
                )
            approved(args.approve, review["approval_sha256"])
            connection = {
                "attest": args.external_history_attested,
                "credentials": {
                    "client_id": os.environ.get("FAA_NMS_CLIENT_ID"),
                    "client_secret": os.environ.get("FAA_NMS_CLIENT_SECRET"),
                },
                "transport": HTTPAdapter(timeout=TIMEOUT_SECONDS, max_bytes=MAX_RESPONSE_BYTES),
            }
            if command == "catch_up":
                result = operations.catch_up(args.expect_watermark, args.approve, **connection)
                result["live_network_authorized"] = True
            else:
                result = operations.recurring(review, args.approve, **connection)
        elif command in ("review_standing", "task_config"):
            verify_release(args.release_commit)
            result = operations.standing(
                args.interval_hours, args.freshness_hours, args.release_commit
            )
            if command == "task_config":
                approved(args.approve, result["approval_sha256"])
                result = task_configuration(operations.store, result)
        elif command == "account_interruption":
            result = operations.reset_interruption(
                args.approve, attest=args.external_history_attested
            )
        elif command == "review_interruption":
            result = operations.review_reset()
        elif command == "runtime_ready":
            result = operations.status()
            auth_request(
                {
                    "client_id": os.environ.get("FAA_NMS_CLIENT_ID"),
                    "client_secret": os.environ.get("FAA_NMS_CLIENT_SECRET"),
                }
            )
            result["provider_environment_present"] = True
        elif command == "review_delta":
            result = operations.review_delta(args.expect_watermark)
        elif command in ("review_retained_delta", "recover_retained_delta"):
            evidence = (
                args.attempt,
                args.response_sha256,
                args.expect_watermark,
                args.preserve_unresolved_pair,
            )
            if command == "review_retained_delta":
                result = operations.review_retained_delta(*evidence)
            else:
                result = operations.recover_retained_delta(*evidence, args.approve)
        elif command == "stage_review":
            result = operations.stage_review(args.sha256)
        elif command == "serve_review":
            operations.serve_review(args.sha256)
            return
        elif command in ("publish_initial", "recover_publication"):
            result = getattr(operations, command)(args.approve)
        else:
            result = getattr(operations, command)()
        print(json.dumps(result, indent=2))
    except (RefreshError, PublicationError, CandidateError, StorageError) as error:
        parser.exit(1, f"{error}\n")
    except (OSError, ValueError, TypeError, KeyError):
        parser.exit(1, "OPERATIONS_STORAGE_OR_STATE_INVALID\n")


if __name__ == "__main__":
    main()
