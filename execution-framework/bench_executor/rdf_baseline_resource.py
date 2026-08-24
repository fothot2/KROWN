#!/usr/bin/env python3
"""Validate one RDF query JSONL artifact against a configured baseline."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from bench_executor.benchmark_result import validate_query_record
from bench_executor.logger import Logger
from bench_executor.rdf_workload_contract import load_rdf_workload_manifest
from bench_executor.standalone_benchmark import input_file

BASELINE_SCHEMA = 'rdf-query-baseline-v1'
_SEMANTIC_FIELDS = (
    'query_id', 'phase', 'run', 'status', 'result_count',
    'result_fingerprint',
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open('r', encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                record = validate_query_record(value)
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise ValueError(
                    f'Invalid result record at line {line_number}: {error}'
                ) from error
            records.append(record)
    if not records:
        raise ValueError('Result file must contain at least one record')
    return records


def _semantic_record(record: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in _SEMANTIC_FIELDS if field not in record]
    if missing:
        raise ValueError('Result misses semantic fields: ' + ', '.join(missing))
    return {field: record[field] for field in _SEMANTIC_FIELDS}


def semantic_signature(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return deterministic semantic fields without runtime measurements."""
    return sorted(
        (_semantic_record(record) for record in records),
        key=lambda item: (item['query_id'], item['phase'], item['run']),
    )


def _required_non_negative_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f'{field} must be a non-negative integer')
    return value


def validate_coverage(records: list[dict[str, Any]], coverage: Any) -> None:
    """Check only the semantic coverage rules declared by the baseline."""
    if coverage is None:
        return
    if not isinstance(coverage, dict):
        raise ValueError('coverage must be an object')
    supported = {'non_empty_records', 'empty_records', 'distinct_fingerprints'}
    unknown = sorted(set(coverage).difference(supported))
    if unknown:
        raise ValueError('Unsupported coverage fields: ' + ', '.join(unknown))
    actual = {
        'non_empty_records': sum(record['result_count'] > 0 for record in records),
        'empty_records': sum(record['result_count'] == 0 for record in records),
        'distinct_fingerprints': len({
            record['result_fingerprint'] for record in records
        }),
    }
    for field, expected_value in coverage.items():
        expected = _required_non_negative_integer(expected_value, f'coverage.{field}')
        if actual[field] != expected:
            raise ValueError(
                f'RDF baseline coverage {field} mismatch: '
                f'expected {expected}, found {actual[field]}'
            )


class RdfBaselineResource:
    """Check RDF workload identity, provenance, results, and configured coverage."""

    def __init__(self, data_path: str, config_path: str, directory: str,
                 verbose: bool):
        self._shared = os.path.join(os.path.abspath(data_path), 'shared')
        self._logger = Logger(__name__, directory, verbose)

    @property
    def name(self):
        return __name__

    @property
    def root_mount_directory(self) -> str:
        return __name__.lower()

    def execute(self, baseline_file: str, manifest_file: str,
                dataset_file: str, results_input_file: str) -> bool:
        try:
            baseline_path = input_file(self._shared, baseline_file)
            manifest_path = input_file(self._shared, manifest_file)
            dataset_path = input_file(self._shared, dataset_file)
            results_path = input_file(self._shared, results_input_file)
            baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
            if not isinstance(baseline, dict):
                raise ValueError('baseline root must be an object')
            if baseline.get('schema') != BASELINE_SCHEMA:
                raise ValueError(f'Unsupported RDF baseline schema: {baseline.get("schema")!r}')

            dataset = baseline.get('dataset')
            if not isinstance(dataset, dict):
                raise ValueError('baseline dataset must be an object')
            expected_size = _required_non_negative_integer(
                dataset.get('size_bytes'), 'dataset.size_bytes'
            )
            expected_dataset_hash = dataset.get('sha256')
            if not isinstance(expected_dataset_hash, str) or not expected_dataset_hash:
                raise ValueError('dataset.sha256 must be a non-empty string')
            if dataset_path.stat().st_size != expected_size:
                raise ValueError('RDF baseline dataset size mismatch')
            if _sha256_file(dataset_path) != expected_dataset_hash:
                raise ValueError('RDF baseline dataset SHA-256 mismatch')

            manifest = load_rdf_workload_manifest(manifest_path)
            expected_manifest = baseline.get('manifest')
            if not isinstance(expected_manifest, dict):
                raise ValueError('baseline manifest must be an object')
            expected_identity = {
                'dataset': manifest.dataset,
                'workload': manifest.workload,
                'query_count': manifest.query_count,
            }
            for field, actual in expected_identity.items():
                if expected_manifest.get(field) != actual:
                    raise ValueError(f'RDF baseline manifest {field} mismatch')
            manifest_hash = _sha256_file(manifest_path)
            if expected_manifest.get('sha256') != manifest_hash:
                raise ValueError('RDF baseline manifest SHA-256 mismatch')

            records = _read_jsonl(results_path)
            expected_records = baseline.get('records')
            if not isinstance(expected_records, list) or not expected_records:
                raise ValueError('baseline records must be a non-empty array')
            expected = semantic_signature(expected_records)
            actual = semantic_signature(records)
            if actual != expected:
                raise ValueError('RDF semantic records differ from baseline')
            if any(record.get('dataset_sha256') != expected_dataset_hash
                   for record in records):
                raise ValueError('RDF result dataset provenance mismatch')
            if any(record.get('manifest_sha256') != manifest_hash
                   for record in records):
                raise ValueError('RDF result manifest provenance mismatch')
            keys = [
                (record['query_id'], record['phase'], record['run'])
                for record in records
            ]
            if len(keys) != len(set(keys)):
                raise ValueError('RDF results contain duplicate execution keys')
            validate_coverage(actual, baseline.get('coverage'))
            self._logger.info(
                f'Validated {len(actual)} RDF query records against "{baseline_path}"'
            )
            return True
        except Exception as error:
            self._logger.error(
                f'RDF baseline validation failed: {type(error).__name__}: {error}'
            )
            return False
