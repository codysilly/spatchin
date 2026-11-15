"""Bounded offline inspection and candidate assembly for saved NMS GeoJSON.

No network, decompression, baseline acceptance, cursor, or publication behavior is
present here.  Callers retain the supplied bytes in private storage.
"""
import argparse
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

try:
    from nms_refresh_contract import CLASSIFICATIONS
except ModuleNotFoundError:  # Package-style import used by the offline test suite.
    from .nms_refresh_contract import CLASSIFICATIONS

ORDER = ('INTERNATIONAL', 'MILITARY', 'LOCAL_MILITARY', 'DOMESTIC', 'FDC')
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_FEATURES = 1_000_000
DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_DEPTH = 64
DEFAULT_MAX_VALUES = 4_000_000
COMPRESSED = ((b'PK\x03\x04', 'zip'), (b'\x1f\x8b', 'gzip'),
              (b'BZh', 'bzip2'), (b'\xfd7zXZ\x00', 'xz'))


class CandidateError(Exception):
    CODES = frozenset(('INVALID_CLASSIFICATION', 'INPUT_TOO_LARGE', 'UNSUPPORTED_CONTENT',
                       'INVALID_JSON', 'INVALID_RESPONSE', 'INVALID_RECORD',
                       'INCOMPLETE_BASELINE', 'CLASSIFICATION_CONFLICT',
                       'IDENTITY_CONFLICT', 'OUTPUT_TOO_LARGE'))

    def __init__(self, code):
        super().__init__(code if code in self.CODES else 'INVALID_RESPONSE')


def _signature(body):
    for magic, name in COMPRESSED:
        if body.startswith(magic):
            return name
    stripped = body.lstrip()
    return 'json' if stripped[:1] in (b'{', b'[') else 'unknown'


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise CandidateError('INVALID_RECORD') from None


def _record(feature):
    try:
        record = feature['properties']['coreNOTAMData']['notam']
        if not isinstance(record, dict) or not isinstance(record['id'], str) or not record['id']:
            raise ValueError()
        _timestamp(record['lastUpdated'])
        return record
    except CandidateError:
        raise
    except (KeyError, TypeError, ValueError):
        raise CandidateError('INVALID_RECORD') from None


def _encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(',', ':')).encode('utf-8'))


def _bounded_tree(value, max_depth, max_values):
    pending = [(value, 1)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > max_values or depth > max_depth:
            raise CandidateError('INVALID_JSON')
        if isinstance(item, dict):
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def signature_report(body, classification):
    """Content-only report usable even when the saved file is not decodable JSON."""
    if classification not in CLASSIFICATIONS:
        raise CandidateError('INVALID_CLASSIFICATION')
    if not isinstance(body, bytes):
        raise CandidateError('INVALID_RESPONSE')
    return {'classification': classification, 'sha256': hashlib.sha256(body).hexdigest(),
            'bytes': len(body), 'signature': _signature(body), 'json_parseable': False}


@dataclass(frozen=True)
class InspectedDataset:
    classification: str
    provenance: dict
    original_bytes: bytes = field(repr=False)
    payload: dict = field(repr=False)
    report: dict


@dataclass(frozen=True)
class CandidateBaseline:
    """Validated candidate only: intentionally has no coverage/cursor fields."""
    payload: dict = field(repr=False)
    datasets: tuple[InspectedDataset, ...] = field(repr=False)
    record_evidence: dict = field(repr=False)
    audit: dict

    def normalize_partition(self, *, airport, location, retrieved_utc):
        """Reuse the existing mapper only for an explicitly reviewed partition."""
        try:
            from normalize_notam_snapshot import normalize
        except ModuleNotFoundError:
            from .normalize_notam_snapshot import normalize
        mapped = normalize(copy.deepcopy(self.payload), airport=airport,
                           retrieved_utc=retrieved_utc,
                           query_context={'location': location})
        for notice in mapped['airports'][airport]['notices']:
            notice['formatted_texts'] = [text for text in notice['formatted_texts']
                if (text['type'] == 'LOCAL_FORMAT' and text['field'] == 'simpleText')
                or text['type'] == 'ICAO']
        return mapped


def inspect_bytes(body, classification, *, provenance=None, max_bytes=DEFAULT_MAX_BYTES,
                  max_features=DEFAULT_MAX_FEATURES, max_depth=DEFAULT_MAX_DEPTH,
                  max_values=DEFAULT_MAX_VALUES):
    if classification not in CLASSIFICATIONS:
        raise CandidateError('INVALID_CLASSIFICATION')
    if not isinstance(body, bytes) or len(body) > max_bytes:
        raise CandidateError('INPUT_TOO_LARGE')
    basic = signature_report(body, classification)
    signature = basic['signature']
    if signature != 'json':
        raise CandidateError('UNSUPPORTED_CONTENT')
    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise CandidateError('INVALID_JSON') from None
    _bounded_tree(payload, max_depth, max_values)
    basic['json_parseable'] = True
    if (not isinstance(payload, dict) or payload.get('status') != 'Success'
            or payload.get('errors') not in (None, []) or not isinstance(payload.get('data'), dict)
            or not isinstance(payload['data'].get('geojson'), list)):
        raise CandidateError('INVALID_RESPONSE')
    features = payload['data']['geojson']
    if len(features) > max_features:
        raise CandidateError('INVALID_RESPONSE')
    ids = {}
    missing = duplicate = local = icao = no_local = cancelled = conflicts = 0
    unexpected_fields = set()
    missing_fields = {}
    times = []
    for feature in features:
        try:
            record = _record(feature)
        except CandidateError:
            missing += 1
            continue
        times.append((_timestamp(record['lastUpdated']), record['lastUpdated']))
        prior = ids.get(record['id'])
        if prior is not None:
            duplicate += 1
            if prior != feature and prior['properties']['coreNOTAMData']['notam'].get('lastUpdated') == record['lastUpdated']:
                conflicts += 1
        else:
            ids[record['id']] = feature
        core = feature['properties']['coreNOTAMData']
        translations = core.get('notamTranslation', [])
        kinds = {t.get('type') for t in translations if isinstance(t, dict)} if isinstance(translations, list) else set()
        local += 'LOCAL_FORMAT' in kinds
        icao += 'ICAO' in kinds
        no_local += 'LOCAL_FORMAT' not in kinds
        cancelled += 'cancelationDate' in record
        expected = {'id','number','text','issued','effectiveStart','effectiveEnd','lastUpdated',
                    'type','scope','location','icaoLocation','cancelationDate','classification'}
        for name in ('id','number','text','issued','effectiveStart','effectiveEnd','lastUpdated'):
            if name not in record:
                missing_fields[name] = missing_fields.get(name, 0) + 1
        for name in set(record) - expected:
            unexpected_fields.add(name if isinstance(name, str) and
                re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', name) else '<nonstandard-name>')
    basic.update({'geojson_array': True, 'record_count': len(features),
                  'distinct_id_count': len(ids), 'duplicate_id_count': duplicate,
                  'missing_or_invalid_id_count': missing,
                  'min_last_updated': min(times)[1] if times else None,
                  'max_last_updated': max(times)[1] if times else None,
                  'local_format_count': local, 'icao_count': icao,
                  'no_local_format_count': no_local, 'cancellation_field_count': cancelled,
                  'same_time_conflict_count': conflicts,
                  'missing_record_fields': dict(sorted(missing_fields.items())),
                  'unexpected_record_fields': sorted(unexpected_fields)[:100]})
    if not isinstance(provenance or {}, dict) or any(not isinstance(k, str) or
            not isinstance(v, (str, int, bool, type(None))) for k, v in (provenance or {}).items()):
        raise CandidateError('INVALID_RESPONSE')
    safe_provenance = dict(provenance or {})
    return InspectedDataset(classification, safe_provenance, bytes(body), payload, basic)


def assemble_candidate(datasets, *, max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES):
    by_class = {}
    for item in datasets:
        if not isinstance(item, InspectedDataset) or item.classification in by_class:
            raise CandidateError('INVALID_CLASSIFICATION')
        by_class[item.classification] = item
    if set(by_class) != set(ORDER):
        raise CandidateError('INCOMPLETE_BASELINE')
    chosen = {}
    evidence = {}
    exact = older = newer = 0
    for classification in ORDER:
        for index, feature in enumerate(by_class[classification].payload['data']['geojson']):
            record = _record(feature)
            declared = record.get('classification')
            if declared in CLASSIFICATIONS and declared != classification:
                raise CandidateError('CLASSIFICATION_CONFLICT')
            identity = record['id']
            marker = {'classification': classification, 'source_index': index,
                      'sha256': hashlib.sha256(json.dumps(feature, ensure_ascii=False,
                          sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
            evidence.setdefault(identity, []).append(marker)
            prior = chosen.get(identity)
            if prior is None:
                chosen[identity] = (feature, record['lastUpdated'], classification, index)
                continue
            old_feature, old_time, _, _ = prior
            if feature == old_feature:
                exact += 1
            elif _timestamp(record['lastUpdated']) > _timestamp(old_time):
                chosen[identity] = (feature, record['lastUpdated'], classification, index)
                newer += 1
            elif _timestamp(record['lastUpdated']) < _timestamp(old_time):
                older += 1
            else:
                raise CandidateError('IDENTITY_CONFLICT')
    features = [chosen[key][0] for key in sorted(chosen)]
    # Enforce the aggregate UTF-8 serialization budget incrementally, before a
    # potentially oversized combined payload is retained.
    prefix = len(b'{"status":"Success","data":{"geojson":[')
    suffix = len(b']}}')
    used = prefix + suffix
    for position, feature in enumerate(features):
        used += _encoded_size(feature) + (1 if position else 0)
        if used > max_output_bytes:
            raise CandidateError('OUTPUT_TOO_LARGE')
    payload = {'status': 'Success', 'data': {'geojson': copy.deepcopy(features)}}
    audit = {'candidate': True, 'classification_order': list(ORDER),
             'input_dataset_count': len(datasets), 'selected_record_count': len(features),
             'exact_duplicate_count': exact, 'older_duplicate_count': older,
             'newer_replacement_count': newer, 'serialized_bytes': _encoded_size(payload),
             'source_reports': [copy.deepcopy(by_class[c].report) for c in ORDER],
             'baseline_established': False, 'watermark': None,
             'diagnostic': 'BASELINE_CUTOVER_REQUIRED'}
    retained_evidence = {identity: tuple(markers) for identity, markers in evidence.items()}
    return CandidateBaseline(payload, tuple(by_class[c] for c in ORDER), retained_evidence, audit)


def read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise CandidateError('INPUT_TOO_LARGE')
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', action='append', required=True,
                        help='CLASSIFICATION=local-path (repeat; never a URL)')
    parser.add_argument('--max-bytes', type=int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    reports = []
    try:
        for value in args.dataset:
            classification, separator, path = value.partition('=')
            if not separator:
                raise CandidateError('INVALID_CLASSIFICATION')
            saved = read_bounded(path, args.max_bytes)
            if _signature(saved) != 'json':
                reports.append(signature_report(saved, classification))
            else:
                try:
                    reports.append(inspect_bytes(saved, classification,
                        provenance={'source': 'saved-local-bytes'}).report)
                except CandidateError as error:
                    if str(error) != 'INVALID_JSON':
                        raise
                    reports.append(signature_report(saved, classification))
    except (CandidateError, OSError) as error:
        parser.error(str(error) if isinstance(error, CandidateError) else 'LOCAL_READ_FAILED')
    print(json.dumps({'inspection_only': True, 'reports': reports}, separators=(',', ':')))


if __name__ == '__main__':
    main()
