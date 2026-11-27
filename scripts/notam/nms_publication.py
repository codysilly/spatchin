"""Offline, guarded projection and atomic publication of accepted NMS state.

This module has no network, credential, scheduler, Git, or provider code.  A
separately authorized collector may call it after private acceptance.  CLI
execution is intentionally absent so repository work cannot publish real data.
"""

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from c070_notam_partition import load_registry


class PublicationError(ValueError):
    pass


PRIVATE_KEYS = frozenset(
    {"original_feature", "received_utc", "transport", "receipt", "ledger", "credentials"}
)


def _instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise PublicationError("INVALID_RETRIEVAL_TIME") from None
    if parsed.tzinfo is None:
        raise PublicationError("INVALID_RETRIEVAL_TIME")
    return parsed.astimezone(timezone.utc)


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()


def _digest(body):
    return hashlib.sha256(body).hexdigest()


def _replace_file(final, data):
    handle = tempfile.NamedTemporaryFile(dir=final.parent, delete=False)
    temporary = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temporary, final)
    finally:
        if not handle.closed:
            handle.close()
        temporary.unlink(missing_ok=True)


def _retrieval_evidence(candidate):
    """Use accepted acquisition evidence, never publication generation time."""
    delta = candidate.get("delta_candidate")
    value = delta.get("received_utc") if isinstance(delta, dict) else None
    value = value or candidate.get("capture_completed_utc") or candidate.get("capture_started_utc")
    if value is None:
        raise PublicationError("RETRIEVAL_EVIDENCE_REQUIRED")
    return _instant(value).isoformat().replace("+00:00", "Z")


def _strings(value):
    if isinstance(value, str):
        return [value]
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def _display_value(value):
    """Project a source scalar without choosing among ambiguous source values."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) <= 1 and all(isinstance(item, str) for item in value):
        return value[0] if value else None
    raise PublicationError("AMBIGUOUS_DISPLAY_FIELD")


def _representations(value):
    """Convert provider representations without trimming or newline conversion."""
    output = []
    for index, item in enumerate(value if isinstance(value, list) else []):
        if not isinstance(item, dict):
            continue
        types = _strings(item.get("type")) or ["Not supplied"]
        for field in ("simpleText", "formattedText", "text"):
            for text in _strings(item.get(field)):
                for kind in types:
                    output.append(
                        {"type": kind, "field": field, "source_index": index, "text": text}
                    )
    return output


def project(candidate, registry, *, generated_utc):
    """Create the public reader contract for the complete reviewed C070 registry."""
    registry = load_registry(registry)
    codes = [entry["icao"] for entry in registry.values()]
    if len(codes) != 130 or len(set(codes)) != 130:
        raise PublicationError("INVALID_C070_REGISTRY")
    if candidate.get("baseline_established") is not True or not candidate.get("watermark"):
        raise PublicationError("BASELINE_NOT_ACCEPTED")
    generated = _instant(generated_utc).isoformat().replace("+00:00", "Z")
    retrieved = _retrieval_evidence(candidate)
    airports = {
        code: {
            "completeness": "UNKNOWN",
            "notices": [],
            "warning": "Coverage UNKNOWN; lifecycle and operational applicability are not inferred.",
        }
        for code in codes
    }
    for identity, entry in candidate.get("catalog", {}).items():
        current = entry.get("current", {})
        record = current.get("notam", {})
        if not isinstance(record, dict):
            raise PublicationError("INVALID_PRIVATE_RECORD")
        notice = {
            key: _display_value(record.get(key))
            for key in (
                "id",
                "number",
                "year",
                "text",
                "issued",
                "effectiveStart",
                "effectiveEnd",
                "lastUpdated",
                "classification",
                "type",
                "cancelationDate",
            )
            if key in record
        }
        notice["id"] = notice.get("id") or identity
        notice["source"] = "NMS-API snapshot"
        notice["retrieved_utc"] = retrieved
        notice["formatted_texts"] = _representations(current.get("representations", []))
        notice["classifications"] = copy.deepcopy(current.get("classifications", []))
        notice["provider_lifecycle"] = {
            key: _display_value(record[key]) for key in ("type", "cancelationDate") if key in record
        }
        notice["warnings"] = ["Lifecycle and operational applicability are not inferred."]
        if not any(item["type"] == "LOCAL_FORMAT" for item in notice["formatted_texts"]):
            notice["warnings"].append("LOCAL_FORMAT representation not supplied.")
        for code in current.get("airport_associations", []):
            if code in airports:
                airports[code]["notices"].append(copy.deepcopy(notice))
    snapshot = {
        "schema_version": 1,
        "retrieved_utc": retrieved,
        "publication": {
            "source": "NMS-API snapshot",
            "coverage": "UNKNOWN",
            "automatic_updates": False,
            "freshness_policy": "NOT_ESTABLISHED",
            "generated_utc": generated,
        },
        "airports": airports,
    }
    if any(key in json.dumps(snapshot) for key in PRIVATE_KEYS):
        raise PublicationError("PRIVATE_DATA_LEAK")
    return snapshot


def build_candidate(candidate, registry, *, generated_utc):
    snapshot = project(candidate, registry, generated_utc=generated_utc)
    body = _encoded(snapshot)
    return (
        snapshot,
        {
            "schema_version": 1,
            "retrieved_utc": snapshot["retrieved_utc"],
            "bytes": len(body),
            "sha256": _digest(body),
        },
        body,
    )


def publish_atomic(
    body, manifest, target, state_path, *, before_replace=None, after_snapshot_replace=None
):
    """Atomically retain last-good output and reject stale/digest-mismatched input."""
    target, state_path = Path(target), Path(state_path)
    if manifest.get("bytes") != len(body) or manifest.get("sha256") != _digest(body):
        raise PublicationError("MANIFEST_MISMATCH")
    incoming = _instant(manifest.get("retrieved_utc"))
    prior = None
    if state_path.exists():
        prior = json.loads(state_path.read_text(encoding="utf-8"))
        if incoming < _instant(prior.get("retrieved_utc")):
            raise PublicationError("OLDER_SNAPSHOT_REJECTED")
    if target.exists() and prior is not None:
        target_digest = _digest(target.read_bytes())
        if target_digest != prior.get("sha256"):
            # The only automatic recovery is the known crash window where the
            # new snapshot landed and its matching manifest did not. Unknown
            # bytes require operator inspection and are never overwritten.
            if target_digest != manifest.get("sha256"):
                raise PublicationError("PUBLICATION_RECOVERY_REQUIRED")
            _replace_file(state_path, _encoded(manifest))
            return copy.deepcopy(manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for final, data in ((target, body), (state_path, _encoded(manifest))):
            handle = tempfile.NamedTemporaryFile(dir=final.parent, delete=False)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            staged.append((Path(handle.name), final))
        if before_replace:
            before_replace()
        os.replace(staged[0][0], target)
        if after_snapshot_replace:
            after_snapshot_replace()
        os.replace(staged[1][0], state_path)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return copy.deepcopy(manifest)
