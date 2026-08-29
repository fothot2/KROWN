#!/usr/bin/env python3
'''Compare compact RDF query results across independent matrix archives.'''
from __future__ import annotations
import json
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from bench_executor.query_features import classify_query, comparison_metadata

SCHEMA = 'rdf-cross-system-comparison-v1'
STRICT_MODES = frozenset({'boolean', 'ordered_fingerprint', 'unordered_multiset_fingerprint'})
NON_STRICT_MODES = frozenset({'implementation_defined_describe', 'provisional_blank_nodes', 'count_only_nondeterministic_limit', 'unsupported'})


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        raise ValueError(f'invalid JSON file {path}: {error}') from error


def load_manifest_modes(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    value = _read_json(path)
    if not isinstance(value, dict) or not isinstance(value.get('queries'), list):
        raise ValueError('manifest must contain a queries array')
    modes, hashes = {}, {}
    for index, query in enumerate(value['queries']):
        if not isinstance(query, dict):
            raise ValueError(f'manifest query {index} must be an object')
        query_id = query.get('query_id')
        if not isinstance(query_id, str) or not query_id:
            raise ValueError(f'manifest query {index} has no query_id')
        if query_id in modes:
            raise ValueError(f'duplicate manifest query_id: {query_id}')
        mode = query.get('comparison_mode')
        if mode is None:
            query_text = query.get('query')
            if not isinstance(query_text, str) or not query_text.strip():
                raise ValueError(
                    f'manifest query {query_id} needs comparison_mode or query text'
                )
            mode = comparison_metadata(
                classify_query(query_text), False
            )['comparison_mode']
        elif not isinstance(mode, str) or not mode:
            raise ValueError(
                f'manifest query {query_id} comparison_mode must be a non-empty string'
            )
        modes[query_id] = mode
        digest = query.get('query_sha256')
        if digest is not None:
            hashes[query_id] = digest
    if not modes:
        raise ValueError('manifest must contain at least one query')
    return modes, hashes


def _member_system(name: str) -> str:
    stem = Path(name).name
    if not stem.endswith('.jsonl'):
        raise ValueError(f'archive member is not JSONL: {name}')
    identity = stem[:-6]
    if '--' not in identity:
        raise ValueError(f'archive member does not use system--configuration: {name}')
    return identity.replace('--', '/', 1)


def _read_archive(path: Path) -> dict[str, list[dict[str, Any]]]:
    systems = {}
    try:
        archive = tarfile.open(path, 'r:*')
    except tarfile.TarError as error:
        raise ValueError(f'invalid result archive {path}: {error}') from error
    with archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if '/' in member.name or not member.name.endswith('.jsonl'):
                raise ValueError(f'unsafe or unsupported archive member: {member.name}')
            system = _member_system(member.name)
            if system in systems:
                raise ValueError(f'duplicate system across archives: {system}')
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f'cannot read archive member: {member.name}')
            records = []
            for number, raw in enumerate(stream, 1):
                try:
                    record = json.loads(raw.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError(f'invalid {member.name} line {number}: {error}') from error
                if not isinstance(record, dict):
                    raise ValueError(f'{member.name} line {number} is not an object')
                records.append(record)
            if not records:
                raise ValueError(f'empty result member: {member.name}')
            systems[system] = records
    if not systems:
        raise ValueError(f'archive has no JSONL result members: {path}')
    return systems


def load_archives(paths: Sequence[Path]) -> dict[str, list[dict[str, Any]]]:
    if not paths:
        raise ValueError('at least one result archive is required')
    combined = {}
    for path in paths:
        for system, records in _read_archive(path).items():
            if system in combined:
                raise ValueError(f'duplicate system across archives: {system}')
            combined[system] = records
    return combined


def _policy_rules(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, dict) or value.get('schema') != 'rdf-cross-system-policy-v1':
        raise ValueError('policy must use rdf-cross-system-policy-v1')
    rules = value.get('deferred_limitations', [])
    if not isinstance(rules, list):
        raise ValueError('deferred_limitations must be an array')
    validated = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {'system', 'query_id', 'status', 'reason'}:
            raise ValueError('each deferred limitation needs system, query_id, status, and reason')
        if any(not isinstance(rule[key], str) or not rule[key] for key in rule):
            raise ValueError('deferred limitation fields must be non-empty strings')
        validated.append(dict(rule))
    return validated


def compare_results(manifest_modes: Mapping[str, str], systems: Mapping[str, list[dict[str, Any]]], policy: Any = None) -> dict[str, Any]:
    expected_queries = set(manifest_modes)
    expected_systems = sorted(systems)
    if len(expected_systems) < 2:
        raise ValueError('cross-system comparison requires at least two systems')
    deferred = {(r['system'], r['query_id'], r['status']): r['reason'] for r in _policy_rules(policy)}
    indexed, duplicates, unexpected = {}, [], []
    for system in expected_systems:
        entries = {}
        for record in systems[system]:
            required = ('query_id', 'phase', 'run', 'status', 'result_count', 'result_fingerprint')
            missing = [field for field in required if field not in record]
            if missing:
                raise ValueError(f'{system} record misses fields: {", ".join(missing)}')
            key = (record['query_id'], record['phase'], record['run'])
            if key in entries:
                duplicates.append({'system': system, 'query_id': key[0], 'phase': key[1], 'run': key[2]})
            entries[key] = record
            if record['query_id'] not in expected_queries:
                unexpected.append({'system': system, 'query_id': record['query_id']})
        indexed[system] = entries
    all_keys = sorted(set().union(*(set(value) for value in indexed.values())))
    outcomes, counts = [], Counter()
    for query_id, phase, run in all_keys:
        mode = manifest_modes.get(query_id)
        records = {system: indexed[system].get((query_id, phase, run)) for system in expected_systems}
        missing_systems = [system for system, record in records.items() if record is None]
        if missing_systems:
            classification = 'incomplete'
        elif mode == 'implementation_defined_describe':
            classification = 'implementation_defined_describe'
        else:
            deferred_systems = [system for system, record in records.items() if (system, query_id, record['status']) in deferred]
            failures = [system for system, record in records.items() if record['status'] != 'ok']
            if failures:
                classification = 'deferred_limitation' if failures and set(failures) == set(deferred_systems) else 'execution_failure'
            elif mode in STRICT_MODES:
                signatures = {(record['result_count'], record['result_fingerprint']) for record in records.values()}
                classification = 'strict_match' if len(signatures) == 1 else 'strict_mismatch'
            elif mode in NON_STRICT_MODES:
                classification = 'non_strict'
            else:
                raise ValueError(f'unsupported comparison mode for {query_id}: {mode}')
        item = {'query_id': query_id, 'phase': phase, 'run': run, 'comparison_mode': mode, 'classification': classification, 'systems': {}}
        for system, record in records.items():
            if record is None:
                item['systems'][system] = None
            else:
                compact = {key: record.get(key) for key in ('status', 'result_count', 'result_fingerprint', 'error_type', 'error_message') if key in record}
                reason = deferred.get((system, query_id, record['status']))
                if reason is not None:
                    compact['deferred_reason'] = reason
                item['systems'][system] = compact
        outcomes.append(item); counts[classification] += 1
    structural = {'complete': not duplicates and not unexpected and all(set(indexed[s]) == set(all_keys) for s in expected_systems), 'duplicate_records': duplicates, 'unexpected_queries': unexpected, 'missing_records': [item for item in outcomes if item['classification'] == 'incomplete']}
    return {'schema': SCHEMA, 'systems': expected_systems, 'query_count': len(expected_queries), 'attempt_count': len(outcomes), 'structural_completeness': structural, 'classification_counts': dict(sorted(counts.items())), 'outcomes': outcomes}


def compare_archives(manifest: Path, archives: Sequence[Path], policy_path: Path | None = None) -> dict[str, Any]:
    modes, _ = load_manifest_modes(manifest)
    policy = None if policy_path is None else _read_json(policy_path)
    return compare_results(modes, load_archives(archives), policy)
