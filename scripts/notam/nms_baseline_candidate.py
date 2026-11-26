"""Offline-only Initial Load candidate and synthetic global-delta reconciliation.

This module has no collector, transport, credential, scheduler, production decoder,
public writer, or live-baseline integration. It adapts SPA-58 private records into
an explicitly non-activated candidate, reconciles supplied GeoJSON deltas, and can
store candidate bytes transactionally in the existing NMS Store state without
changing the accepted snapshot, baseline flag, or watermark.
"""

from __future__ import annotations

import base64
import copy
from datetime import timedelta
import hashlib
import json

from c070_notam_partition import load_registry, load_versioned_registry
from nms_refresh import encode, payload_features, source_record
from nms_refresh_contract import RefreshError, instant, stamp


MAX_RECORDS = 100_000
MAX_CANDIDATE_BYTES = 512 * 1024 * 1024
DISPLAY_LIMIT = 30


class CandidateError(Exception):
    CODES = frozenset(
        (
            "INVALID_CANDIDATE",
            "INVALID_RECORD",
            "RECORD_LIMIT",
            "OUTPUT_LIMIT",
            "IDENTITY_CONFLICT",
            "CONFLICTING_UPDATE",
            "DELTA_GAP",
            "BASELINE_CUTOVER_REQUIRED",
            "STORE_STATE_INVALID",
            "LOCAL_FAILURE",
        )
    )

    def __init__(self, code):
        super().__init__(code if code in self.CODES else "LOCAL_FAILURE")


def _one(values):
    return values[0] if isinstance(values, list) and len(values) == 1 else None


def _exact_strings(values):
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise CandidateError("INVALID_RECORD")
    return list(values)


def _size(value):
    try:
        return len(encode(value))
    except Exception:
        raise CandidateError("INVALID_CANDIDATE") from None


def _registry_indexes(registry):
    registry = load_versioned_registry() if registry is None else load_registry(registry)
    codes = {}
    by_icao = {}
    for entry in registry.values():
        by_icao[entry["icao"]] = entry
        codes[entry["iata"]] = entry["icao"]
        codes[entry["icao"]] = entry["icao"]
    return registry, codes, by_icao


def _initial_current(record):
    identifiers = _exact_strings(record.get("source_identifiers"))
    source_id = record.get("source_message_id")
    notam = record.get("notam")
    representations = record.get("representations")
    classifications = _exact_strings(record.get("classifications", []))
    last_updated = _exact_strings(record.get("source_last_updated", []))
    airports = record.get("accepted_airports")
    if (
        not isinstance(source_id, str)
        or not source_id
        or not isinstance(notam, dict)
        or not isinstance(representations, list)
        or not isinstance(airports, list)
        or any(not isinstance(code, str) for code in airports)
    ):
        raise CandidateError("INVALID_RECORD")
    for values in notam.values():
        _exact_strings(values)
    return source_id, {
        "format": "AIXM_5_1_INITIAL_LOAD",
        "source_identity": source_id,
        "source_message_id": source_id,
        "source_identifiers": identifiers,
        "source_gml_ids": _exact_strings(record.get("source_gml_ids", [])),
        "source_aliases": _exact_strings(record.get("source_event_aliases", [])),
        "notam": copy.deepcopy(notam),
        "representations": copy.deepcopy(representations),
        "classifications": classifications,
        "last_updated": last_updated,
        "airport_associations": sorted(set(airports)),
        "association_evidence": copy.deepcopy(record.get("association_evidence", {})),
        "association_status": record.get("status"),
    }


class InitialCandidateSink:
    """Callable bounded adapter used directly as SPA-58's streaming record sink."""

    def __init__(
        self,
        *,
        capture_started_utc,
        registry=None,
        max_records=MAX_RECORDS,
        max_bytes=MAX_CANDIDATE_BYTES,
    ):
        _, _, self.by_icao = _registry_indexes(registry)
        self.started = stamp(instant(capture_started_utc))
        if (
            type(max_records) is not int
            or type(max_bytes) is not int
            or min(max_records, max_bytes) < 1
        ):
            raise CandidateError("INVALID_CANDIDATE")
        self.max_records = max_records
        self.max_bytes = max_bytes
        self.catalog = {}
        self.unresolved = []
        self.seen_source_ids = set()
        self.counts = {
            "input_records": 0,
            "associated_records": 0,
            "unresolved_records": 0,
            "duplicate_replays": 0,
            "identity_conflicts": 0,
        }

    def __call__(self, record):
        self.counts["input_records"] += 1
        if self.counts["input_records"] > self.max_records:
            raise CandidateError("RECORD_LIMIT")
        source_id, current = _initial_current(record)
        if source_id in self.seen_source_ids:
            self.counts["identity_conflicts"] += 1
            raise CandidateError("IDENTITY_CONFLICT")
        self.seen_source_ids.add(source_id)
        if any(code not in self.by_icao for code in current["airport_associations"]):
            raise CandidateError("INVALID_RECORD")
        if current["association_status"] != "associated":
            self.unresolved.append(current)
            self.counts["unresolved_records"] += 1
            return
        entry = {
            "identity": source_id,
            "current": current,
            "versions": [copy.deepcopy(current)],
            "lifecycle": "UNINTERPRETED",
        }
        self.catalog[source_id] = entry
        self.counts["associated_records"] += 1

    def finish(self):
        candidate = {
            "schema": 1,
            "kind": "NMS_PRIVATE_BASELINE_CANDIDATE",
            "capture_started_utc": self.started,
            "first_delta_lower_bound_utc": instant(self.started).replace(microsecond=0).isoformat(),
            "coverage": "UNKNOWN",
            "baseline_established": False,
            "watermark": None,
            "activation_diagnostic": "BASELINE_CUTOVER_REQUIRED",
            "catalog": self.catalog,
            "unresolved_records": self.unresolved,
            "audit": self.counts,
        }
        if _size(candidate) > self.max_bytes:
            raise CandidateError("OUTPUT_LIMIT")
        return copy.deepcopy(candidate)


def build_initial_candidate(
    records,
    *,
    capture_started_utc,
    registry=None,
    max_records=MAX_RECORDS,
    max_bytes=MAX_CANDIDATE_BYTES,
):
    """Build a bounded private candidate from an iterable of SPA-58 records."""
    sink = InitialCandidateSink(
        capture_started_utc=capture_started_utc,
        registry=registry,
        max_records=max_records,
        max_bytes=max_bytes,
    )
    for record in records:
        sink(record)
    return sink.finish()


def _delta_airports(record, codes):
    values = [
        record.get(name)
        for name in ("location", "icaoLocation")
        if record.get(name) not in (None, "")
    ]
    if any(not isinstance(value, str) for value in values):
        return [], "invalid"
    matches = {codes[value.strip().upper()] for value in values if value.strip().upper() in codes}
    if len(matches) > 1:
        return [], "conflicting"
    return sorted(matches), "associated" if matches else "unresolved"


def _logical_initial_value(current, name):
    return _one(current["notam"].get(name, []))


def _same_logical_notice(initial, delta, airports, association_status):
    for name in ("number", "text", "issued", "effectiveStart", "effectiveEnd", "type"):
        left = _logical_initial_value(initial, name)
        right = delta.get(name)
        if left is None or not isinstance(right, str) or left != right:
            return False
    classifications = initial.get("classifications")
    if (
        not isinstance(classifications, list)
        or len(classifications) != 1
        or not isinstance(delta.get("classification"), str)
        or classifications[0] != delta["classification"]
    ):
        return False
    if (
        initial.get("association_status") != "associated"
        or association_status != "associated"
        or initial.get("airport_associations") != airports
    ):
        return False
    initial_cancellation = initial.get("notam", {}).get("cancelationDate", [])
    if not isinstance(initial_cancellation, list) or len(initial_cancellation) > 1:
        return False
    delta_has_cancellation = "cancelationDate" in delta
    if bool(initial_cancellation) != delta_has_cancellation:
        return False
    if initial_cancellation and (
        not isinstance(delta["cancelationDate"], str)
        or initial_cancellation[0] != delta["cancelationDate"]
    ):
        return False
    return True


def reconcile_delta(
    candidate,
    payload,
    *,
    requested_since_utc,
    received_utc,
    registry=None,
    max_records=MAX_RECORDS,
    max_bytes=MAX_CANDIDATE_BYTES,
):
    """Reconcile supplied global GeoJSON without deleting absent records or activating."""
    if (
        not isinstance(candidate, dict)
        or candidate.get("schema") != 1
        or candidate.get("baseline_established") is not False
        or candidate.get("watermark") is not None
        or not isinstance(candidate.get("catalog"), dict)
        or not isinstance(candidate.get("unresolved_records"), list)
    ):
        raise CandidateError("INVALID_CANDIDATE")
    _, codes, _ = _registry_indexes(registry)
    requested = instant(requested_since_utc)
    received = instant(received_utc)
    if requested > received:
        raise CandidateError("INVALID_CANDIDATE")
    if received - requested > timedelta(hours=24):
        raise CandidateError("DELTA_GAP")
    features = payload_features(payload)
    if len(features) > max_records:
        raise CandidateError("RECORD_LIMIT")
    result = copy.deepcopy(candidate)
    catalog = result["catalog"]
    audit = {
        "received": len(features),
        "inserted": 0,
        "updated": 0,
        "replayed": 0,
        "cancellation_signals_preserved": 0,
        "unresolved": 0,
        "missing_prior_records_preserved": 0,
    }
    touched = set()
    for feature in features:
        try:
            record = source_record(feature)
        except RefreshError:
            raise CandidateError("INVALID_RECORD") from None
        identity = record["id"]
        airports, association_status = _delta_airports(record, codes)
        current = {
            "format": "NMS_GEOJSON_DELTA",
            "source_identity": identity,
            "notam": copy.deepcopy(record),
            "representations": copy.deepcopy(
                feature.get("properties", {}).get("coreNOTAMData", {}).get("notamTranslation", [])
            ),
            "classifications": [record["classification"]]
            if isinstance(record.get("classification"), str)
            else [],
            "last_updated": [record["lastUpdated"]],
            "airport_associations": airports,
            "association_status": association_status,
            "original_feature": copy.deepcopy(feature),
            "received_utc": stamp(received),
        }
        if record.get("type") in ("C", "NOTAMC") or "cancelationDate" in record:
            audit["cancellation_signals_preserved"] += 1
        prior = catalog.get(identity)
        if prior is None:
            result["unresolved_records"].append(current)
            audit["unresolved"] += 1
            continue
        previous = prior["current"]
        previous_updated = _one(previous.get("last_updated", []))
        if previous_updated is None:
            raise CandidateError("BASELINE_CUTOVER_REQUIRED")
        new_time = instant(record["lastUpdated"])
        old_time = instant(previous_updated)
        if new_time < old_time:
            raise CandidateError("CONFLICTING_UPDATE")
        if new_time == old_time:
            if (
                previous["format"] == "NMS_GEOJSON_DELTA"
                and previous.get("original_feature") == feature
            ) or (
                previous["format"] == "AIXM_5_1_INITIAL_LOAD"
                and _same_logical_notice(previous, record, airports, association_status)
            ):
                audit["replayed"] += 1
                touched.add(identity)
                continue
            raise CandidateError("CONFLICTING_UPDATE")
        old_airports = set(previous.get("airport_associations", []))
        if old_airports and airports and old_airports != set(airports):
            raise CandidateError("CONFLICTING_UPDATE")
        prior["versions"].append(copy.deepcopy(current))
        prior["current"] = current
        audit["updated"] += 1
        touched.add(identity)
    audit["missing_prior_records_preserved"] = len(set(catalog) - touched)
    result["delta_candidate"] = {
        "requested_since_utc": stamp(requested),
        "received_utc": stamp(received),
        "proposed_replay_cursor_utc": stamp(received.replace(microsecond=0) - timedelta(seconds=1)),
        "audit": audit,
    }
    result["baseline_established"] = False
    result["watermark"] = None
    result["activation_diagnostic"] = "BASELINE_CUTOVER_REQUIRED"
    if _size(result) > max_bytes:
        raise CandidateError("OUTPUT_LIMIT")
    return result


def continuity_report(
    candidate,
    *,
    now_utc,
    baseline_inclusion_proven=False,
    delta_ordering_proven=False,
    account_scope_proven=False,
    ledger_budget=None,
    external_activity_attested=False,
):
    """Evaluate cutover evidence without changing baseline or watermark."""
    try:
        lower = instant(candidate["first_delta_lower_bound_utc"])
        now = instant(now_utc)
    except Exception:
        raise CandidateError("INVALID_CANDIDATE") from None
    gap = now - lower > timedelta(hours=24)
    budget_ok = bool(ledger_budget and ledger_budget.get("ledger_time_eligible"))
    gates = {
        "initial_inclusion_proven": bool(baseline_inclusion_proven),
        "delta_ordering_proven": bool(delta_ordering_proven),
        "account_scope_proven": bool(account_scope_proven),
        "within_24_hour_lookback": not gap,
        "ledger_budget_eligible": budget_ok,
        "external_activity_attested": bool(external_activity_attested),
    }
    diagnostic = (
        "DELTA_GAP"
        if gap
        else "BASELINE_CUTOVER_REQUIRED"
        if not all(gates.values())
        else "CUTOVER_EVIDENCE_COMPLETE_NOT_ACTIVATED"
    )
    return {
        "gates": gates,
        "diagnostic": diagnostic,
        "proposed_first_delta_lower_bound_utc": stamp(lower),
        "baseline_established": False,
        "watermark": None,
        "bulk_budget": "one account-wide bulk acquisition per 24 hours",
        "data_budget": "one account-wide data/delta acquisition per 3 minutes",
        "delta_lookback": "24 hours",
    }


def accept_private_candidate(store, candidate, *, before_accept=None):
    """Persist candidate bytes in existing Store state without replacing its snapshot."""
    body = encode(candidate)
    if before_accept is not None:
        try:
            before_accept(body)
        except Exception:
            raise CandidateError("LOCAL_FAILURE") from None
    with store.connect() as db, store.transaction(db):
        state = store.load(db)
        if (
            state["active"] is not None
            or state["recovery"] is not None
            or state["baseline"] is not False
            or state["watermark"] is not None
        ):
            raise CandidateError("STORE_STATE_INVALID")
        state["offline_candidate_b64"] = base64.b64encode(body).decode()
        state["offline_candidate_status"] = "PRIVATE_ONLY_NOT_ACTIVATED"
        store.save(db, state)
    return {
        "status": "PRIVATE_ONLY_NOT_ACTIVATED",
        "bytes": len(body),
        "baseline_established": False,
        "watermark": None,
    }


def dashboard_projection(candidate, selected_airports, *, generated_utc, registry=None):
    """Return a private reader-shape preview; never writes the dashboard snapshot."""
    _, _, by_icao = _registry_indexes(registry)
    if (
        not isinstance(selected_airports, list)
        or len(selected_airports) > DISPLAY_LIMIT
        or len(set(selected_airports)) != len(selected_airports)
        or any(code not in by_icao for code in selected_airports)
    ):
        raise CandidateError("INVALID_CANDIDATE")
    airports = {
        code: {
            "completeness": "UNKNOWN",
            "notices": [],
            "warning": "Private NMS candidate; completeness and current applicability UNKNOWN.",
        }
        for code in selected_airports
    }
    for entry in candidate.get("catalog", {}).values():
        current = entry["current"]
        for code in set(current.get("airport_associations", [])) & set(selected_airports):
            if current["format"] == "AIXM_5_1_INITIAL_LOAD":
                fields = current["notam"]
                notice = {
                    name: _one(fields.get(name, []))
                    for name in ("number", "text", "issued", "effectiveStart", "effectiveEnd")
                }
                notice["id"] = current["source_identity"]
                notice["formatted_texts"] = copy.deepcopy(current["representations"])
            else:
                record = current["notam"]
                notice = {
                    name: record.get(name)
                    for name in ("id", "number", "text", "issued", "effectiveStart", "effectiveEnd")
                }
                notice["formatted_texts"] = copy.deepcopy(current["representations"])
            notice.update(
                {
                    "source": "NMS service response; field semantics unverified",
                    "retrieved_utc": generated_utc,
                    "warnings": ["Lifecycle and operational applicability are not inferred."],
                }
            )
            airports[code]["notices"].append(notice)
    return {
        "retrieved_utc": generated_utc,
        "publication": {
            "automatic_updates": False,
            "status": "PRIVATE_PREVIEW_NOT_AUTHORIZED_FOR_PUBLICATION",
            "source": "NMS service response",
            "coverage": "UNKNOWN",
            "runway_matching_behavior": "UNCHANGED",
        },
        "airports": airports,
    }


def compatibility_matrix():
    """Field-level contract; actual equality counts are supplied by evidence probes."""
    return [
        {
            "initial": "AIXMBasicMessage/@gml:id",
            "delta": "notam.id",
            "behavior": "exact equality only",
            "status": "REQUIRES_EVIDENCE_MATCH",
        },
        {
            "initial": "event:text",
            "delta": "notam.text",
            "behavior": "preserve exact value",
            "status": "STRUCTURALLY_COMPATIBLE",
        },
        {
            "initial": "event:issued/effectiveStart/effectiveEnd",
            "delta": "same named fields",
            "behavior": "preserve exact lexical values",
            "status": "STRUCTURALLY_COMPATIBLE",
        },
        {
            "initial": "FNSE:classification",
            "delta": "notam.classification",
            "behavior": "preserve raw codes; no enum equivalence inference",
            "status": "UNCERTAIN",
        },
        {
            "initial": "NOTAMTranslation",
            "delta": "notamTranslation",
            "behavior": "preserve type/simpleText/formattedText",
            "status": "STRUCTURALLY_COMPATIBLE",
        },
        {
            "initial": "event:type",
            "delta": "notam.type/cancelationDate",
            "behavior": "preserve only; never delete or infer cancellation",
            "status": "SEMANTICS_UNPROVEN",
        },
    ]


class CompatibilityProbe:
    """Bounded hashed Initial Load index for private equality measurement."""

    def __init__(self, max_records=MAX_RECORDS):
        self.max_records = max_records
        self.identifier_index = {}
        self.gml_id_index = {}
        self.alias_index = {}
        self.logical_index = {}
        self.initial_records = 0

    @staticmethod
    def _digest(value):
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).digest()

    def __call__(self, record):
        self.initial_records += 1
        if self.initial_records > self.max_records:
            raise CandidateError("RECORD_LIMIT")
        entry = {
            "fields": {
                name: self._digest(record.get("notam", {}).get(name, []))
                for name in ("text", "issued", "effectiveStart", "effectiveEnd")
            },
            "classification": self._digest(record.get("classifications", [])),
            "representations": self._digest(record.get("representations", [])),
        }
        message_id = record.get("source_message_id")
        if not isinstance(message_id, str) or not message_id:
            raise CandidateError("INVALID_RECORD")
        if message_id in self.identifier_index:
            raise CandidateError("IDENTITY_CONFLICT")
        self.identifier_index[message_id] = entry
        for identity in record.get("source_gml_ids", []):
            self.gml_id_index[identity] = entry
        for identity in record.get("source_event_aliases", []):
            self.alias_index[identity] = entry
        fields = record.get("notam", {})
        logical = self._digest(
            {
                name: fields.get(name, [])
                for name in ("number", "text", "issued", "effectiveStart", "effectiveEnd")
            }
        )
        self.logical_index.setdefault(logical, []).append(entry)

    def compare(self, payload):
        counts = {
            "delta_records": 0,
            "exact_identity_matches": 0,
            "exact_gml_id_matches": 0,
            "exact_alias_matches": 0,
            "unique_logical_field_matches": 0,
            "field_equal": {
                name: 0 for name in ("text", "issued", "effectiveStart", "effectiveEnd")
            },
            "classification_equal": 0,
            "representations_equal": 0,
        }
        for feature in payload_features(payload):
            record = source_record(feature)
            counts["delta_records"] += 1
            if record["id"] in self.gml_id_index:
                counts["exact_gml_id_matches"] += 1
            if record["id"] in self.alias_index:
                counts["exact_alias_matches"] += 1
            initial = self.identifier_index.get(record["id"])
            if initial is None:
                logical = self._digest(
                    {
                        name: [record[name]] if isinstance(record.get(name), str) else []
                        for name in ("number", "text", "issued", "effectiveStart", "effectiveEnd")
                    }
                )
                logical_matches = self.logical_index.get(logical, [])
                if len(logical_matches) != 1:
                    continue
                initial = logical_matches[0]
                counts["unique_logical_field_matches"] += 1
            else:
                counts["exact_identity_matches"] += 1
            for name in counts["field_equal"]:
                if initial["fields"][name] == self._digest(
                    [record[name]] if isinstance(record.get(name), str) else []
                ):
                    counts["field_equal"][name] += 1
            classifications = (
                [record["classification"]] if isinstance(record.get("classification"), str) else []
            )
            if initial["classification"] == self._digest(classifications):
                counts["classification_equal"] += 1
            translations = (
                feature.get("properties", {}).get("coreNOTAMData", {}).get("notamTranslation", [])
            )
            if initial["representations"] == self._digest(translations):
                counts["representations_equal"] += 1
        return counts
