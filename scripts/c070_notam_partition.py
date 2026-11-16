"""Offline C070 registry validation and exact GeoJSON airport partitioning.

No network, FAA authentication, capture, scheduling, or publication is present.
"""
import copy
import json
from pathlib import Path
import re


def c070_codes(path=None):
    path = path or Path(__file__).resolve().parents[1] / 'docs/reference/c070-airports.csv'
    codes = [line.strip() for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(codes) != 130 or len(set(codes)) != 130 or any(not re.fullmatch(r'[A-Z]{3}', code) for code in codes):
        raise ValueError('invalid C070 Sheet1 column A export')
    return tuple(codes)


def load_registry(value, *, codes=None):
    """Validate an explicit mapping; never infer ICAO from an IATA code."""
    codes = tuple(codes or c070_codes())
    records = value.get('airports') if isinstance(value, dict) else value
    if not isinstance(records, list) or len(records) != len(codes):
        raise ValueError('registry must contain exactly the C070 airports')
    result = {}
    for item in records:
        if not isinstance(item, dict):
            raise ValueError('invalid registry airport')
        iata, icao, name, coverage = (item.get(key) for key in ('iata', 'icao', 'name', 'source_coverage'))
        if (not isinstance(iata, str) or not isinstance(icao, str) or not isinstance(name, str)
                or not name.strip() or not isinstance(coverage, dict) or set(item) != {'iata', 'icao', 'name', 'source_coverage'}):
            raise ValueError('registry airport fields are incomplete')
        if not re.fullmatch(r'[A-Z]{3}', iata) or not re.fullmatch(r'[A-Z0-9]{4}', icao):
            raise ValueError('registry airport identifier is invalid')
        if iata in result:
            raise ValueError('duplicate registry IATA code')
        result[iata] = copy.deepcopy(item)
    if set(result) != set(codes):
        raise ValueError('registry does not match C070 Sheet1 column A')
    return result


def _feature_codes(feature):
    try:
        record = feature['properties']['coreNOTAMData']['notam']
    except (KeyError, TypeError):
        return None
    values = [record.get('location'), record.get('icaoLocation')]
    if any(not isinstance(value, str) or not re.fullmatch(r'[A-Z0-9]{3,4}', value) for value in values):
        return None
    return tuple(values)


def partition(payload, registry, *, retrieved_utc):
    """Keep a feature only when both source identifiers match one registry airport."""
    registry = load_registry(registry) if not isinstance(registry, dict) or not all(isinstance(v, dict) and 'icao' in v for v in registry.values()) else registry
    if not isinstance(retrieved_utc, str) or not retrieved_utc.strip():
        raise ValueError('capture retrieval timestamp is required')
    try:
        features = payload['data']['geojson']
    except (KeyError, TypeError):
        raise ValueError('inline GeoJSON capture required') from None
    if not isinstance(features, list):
        raise ValueError('inline GeoJSON capture required')
    by_pair = {(entry['iata'], entry['icao']): entry for entry in registry.values()}
    airports = {entry['icao']: {'notices': [], 'completeness': 'UNKNOWN',
                'source_coverage': copy.deepcopy(entry['source_coverage'])} for entry in registry.values()}
    excluded = {'missing_or_invalid_identifiers': 0, 'cross_airport_or_unregistered': 0}
    for index, feature in enumerate(features):
        pair = _feature_codes(feature)
        entry = by_pair.get(pair) if pair else None
        if entry is None:
            excluded['missing_or_invalid_identifiers' if pair is None else 'cross_airport_or_unregistered'] += 1
            continue
        record = feature['properties']['coreNOTAMData']['notam']
        notice = {'source_index': index, 'original_feature': copy.deepcopy(feature),
                  'source': 'FAA NMS GeoJSON offline capture', 'retrieved_utc': retrieved_utc,
                  'formatted_texts': []}
        for name in ('id', 'number', 'text', 'issued', 'effectiveStart', 'effectiveEnd', 'lastUpdated'):
            notice[name] = record.get(name) if isinstance(record.get(name), str) else None
        for translation in feature.get('properties', {}).get('coreNOTAMData', {}).get('notamTranslation', []):
            if isinstance(translation, dict):
                for field in ('simpleText', 'formattedText'):
                    if isinstance(translation.get(field), str):
                        notice['formatted_texts'].append({'type': translation.get('type') if isinstance(translation.get('type'), str) else 'Not supplied', 'field': field, 'text': translation[field]})
        airports[entry['icao']]['notices'].append(notice)
    return {'retrieved_utc': retrieved_utc, 'airports': airports,
            'partition': {'coverage': 'UNKNOWN', 'excluded_record_counts': excluded,
                          'input_record_count': len(features)}}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', required=True, help='reviewed registry JSON, local path')
    parser.add_argument('--capture', required=True, help='private local GeoJSON capture path')
    parser.add_argument('--retrieved-utc', required=True)
    args = parser.parse_args()
    registry = json.loads(Path(args.registry).read_text(encoding='utf-8'))
    capture = json.loads(Path(args.capture).read_text(encoding='utf-8'))
    print(json.dumps(partition(capture, registry, retrieved_utc=args.retrieved_utc), ensure_ascii=False))


if __name__ == '__main__':
    main()
