#!/usr/bin/env python3
"""Validate one DBBench JSONL artifact against a semantic baseline."""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
from bench_executor.logger import Logger
from bench_executor.standalone_benchmark import input_file


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open('r', encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f'Invalid JSONL at line {line_number}: {error}') from error
            if not isinstance(record, dict):
                raise ValueError(f'Result at line {line_number} must be an object')
            records.append(record)
    return records


def _semantic_record(record: dict) -> dict:
    fields = ('query_id', 'phase', 'run', 'status', 'result_count', 'result_fingerprint')
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError('Result misses semantic fields: ' + ', '.join(missing))
    return {field: record[field] for field in fields}


def semantic_signature(records: list[dict]) -> list[dict]:
    # Return deterministic semantic fields and omit runtime measurements.
    return sorted(
        (_semantic_record(record) for record in records),
        key=lambda item: (item['query_id'], item['phase'], item['run']),
    )


class DBBenchBaselineResource:
    """Check DBBench identities, provenance, and semantic results."""
    def __init__(self, data_path: str, config_path: str, directory: str, verbose: bool):
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
            if baseline.get('schema') != 'dbbench-smoke-baseline-v1':
                raise ValueError('Unsupported DBBench smoke baseline schema')
            dataset = baseline['dataset']
            if dataset_path.stat().st_size != dataset['size_bytes']:
                raise ValueError('DBBench smoke dataset size mismatch')
            if _sha256_file(dataset_path) != dataset['sha256']:
                raise ValueError('DBBench smoke dataset SHA-256 mismatch')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            expected_manifest = baseline['manifest']
            for field in ('dataset', 'workload', 'query_count'):
                if manifest.get(field) != expected_manifest[field]:
                    raise ValueError(f'DBBench smoke manifest {field} mismatch')
            manifest_hash = _sha256_file(manifest_path)
            if manifest_hash != expected_manifest['sha256']:
                raise ValueError('DBBench smoke manifest SHA-256 mismatch')
            records = _read_jsonl(results_path)
            expected = semantic_signature(baseline['records'])
            actual = semantic_signature(records)
            if actual != expected:
                raise ValueError('DBBench smoke semantic records differ from baseline')
            dataset_hash = dataset['sha256']
            if any(record.get('dataset_sha256') != dataset_hash for record in records):
                raise ValueError('DBBench smoke result dataset provenance mismatch')
            if any(record.get('manifest_sha256') != manifest_hash for record in records):
                raise ValueError('DBBench smoke result manifest provenance mismatch')
            keys = [(record['query_id'], record['phase'], record['run']) for record in records]
            if len(keys) != len(set(keys)):
                raise ValueError('DBBench smoke results contain duplicate execution keys')
            non_empty = sum(record['result_count'] > 0 for record in actual)
            empty = sum(record['result_count'] == 0 for record in actual)
            fingerprints = {record['result_fingerprint'] for record in actual}
            if (non_empty, empty) != (3, 3) or len(fingerprints) != 4:
                raise ValueError('DBBench smoke semantic coverage mismatch')
            self._logger.info(f'Validated {len(actual)} DBBench smoke records against "{baseline_path}"')
            return True
        except Exception as error:
            self._logger.error(f'DBBench baseline validation failed: {type(error).__name__}: {error}')
            return False
