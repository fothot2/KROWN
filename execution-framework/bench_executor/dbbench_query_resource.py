#!/usr/bin/env python3
"""Run standalone DBBench RDFLib execution through the public CLI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from bench_executor.benchmark_result import validate_query_record
from bench_executor.logger import Logger
from bench_executor.standalone_benchmark import (
    commit_output, discard_output, input_file, resolve_shared_path,
    standalone_command, temporary_output,
)
from bench_executor.rdf_query_benchmark import _load_query_manifest


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _load_results(path: Path) -> list[dict]:
    records = []
    with path.open('r', encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f'Invalid JSONL record at line {line_number}: {error}'
                ) from error
            try:
                record = validate_query_record(record)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f'Invalid result record at line {line_number}: {error}'
                ) from error
            records.append(record)
    if not records:
        raise ValueError('Result file must contain at least one record')
    return records


def _require_full_workload_opt_in(
        query_count: int, max_query_count: int, allow_full_env: str) -> None:
    """Reject large manifests unless one named environment variable is set."""
    if max_query_count < 1:
        raise ValueError('max_query_count must be at least 1')
    if query_count <= max_query_count:
        return
    if os.environ.get(allow_full_env) != '1':
        raise ValueError(
            f'DBBench manifest contains {query_count} queries, above the safe limit '
            f'{max_query_count}; set {allow_full_env}=1 to allow full execution'
        )


class DBBenchQueryResource:
    """Execute a DBBench manifest through the standalone benchmark CLI."""

    def __init__(self, data_path: str, config_path: str, directory: str,
                 verbose: bool):
        self._shared_directory = os.path.join(
            os.path.abspath(data_path), 'shared'
        )
        self._logger = Logger(__name__, directory, verbose)
        os.makedirs(self._shared_directory, exist_ok=True)

    @property
    def name(self):
        return __name__

    @property
    def root_mount_directory(self) -> str:
        return __name__.lower()

    def execute(self, manifest_file: str, dataset_file: str,
                results_file: str, experiment_id: str,
                warmup_runs: int = 1, measured_runs: int = 5,
                timeout_s: float = 60.0, resume: bool = False,
                benchmark_command: str = 'vortex-rdf-bench',
                benchmark_root: str | None = None,
                max_query_count: int = 100,
                allow_full_env: str = 'KROWN_DBBENCH_ALLOW_FULL') -> bool:
        """Run and validate one standalone DBBench execution artifact."""
        temporary = None
        try:
            manifest_path = input_file(
                self._shared_directory, manifest_file
            )
            dataset_path = input_file(
                self._shared_directory, dataset_file
            )
            results_path = resolve_shared_path(
                self._shared_directory, results_file, 'Output'
            )
            manifest = _load_query_manifest(str(manifest_path))
            _require_full_workload_opt_in(
                len(manifest.queries), max_query_count, allow_full_env
            )
            temporary = temporary_output(results_path, seed=resume)
            command, environment = standalone_command(
                benchmark_command, benchmark_root
            )
            command.extend([
                'dbbench', 'run',
                '--manifest', str(manifest_path),
                '--dataset-path', str(dataset_path),
                '--output', str(temporary),
                '--experiment-id', experiment_id,
                '--warmup-runs', str(warmup_runs),
                '--measured-runs', str(measured_runs),
                '--timeout-s', str(timeout_s),
            ])
            if resume:
                command.append('--resume')
            completed = subprocess.run(
                command, cwd=benchmark_root, env=environment,
                capture_output=True, text=True, check=False,
            )
            if completed.returncode != 0:
                message = completed.stderr.strip() or completed.stdout.strip()
                raise RuntimeError(
                    f'Benchmark command failed with exit code '
                    f'{completed.returncode}: {message}'
                )
            records = _load_results(temporary)
            expected_count = len(manifest.queries) * (
                warmup_runs + measured_runs
            )
            if len(records) != expected_count:
                raise ValueError(
                    f'Result count mismatch: expected {expected_count}, '
                    f'found {len(records)}'
                )
            expected = {
                'experiment_id': experiment_id,
                'system': 'rdflib',
                'dataset': manifest.dataset,
                'workload': manifest.workload,
                'manifest_sha256': _sha256_file(manifest_path),
                'dataset_sha256': _sha256_file(dataset_path),
            }
            keys = set()
            query_ids = {query.query_id for query in manifest.queries}
            for index, record in enumerate(records, start=1):
                for field, value in expected.items():
                    if record.get(field) != value:
                        raise ValueError(
                            f'Result {index} has incompatible {field}: '
                            f'{record.get(field)!r}'
                        )
                if record['query_id'] not in query_ids:
                    raise ValueError(
                        f'Result {index} has unknown query_id: '
                        f'{record["query_id"]}'
                    )
                key = (
                    record['query_id'], record['phase'], record['run']
                )
                if key in keys:
                    raise ValueError(f'Duplicate result key: {key}')
                keys.add(key)
            commit_output(temporary, results_path)
            temporary = None
            self._logger.info(
                f'Wrote {len(records)} DBBench result records to '
                f'"{results_path}"'
            )
            return True
        except Exception as error:
            self._logger.error(
                f'DBBench query execution failed: '
                f'{type(error).__name__}: {error}'
            )
            return False
        finally:
            discard_output(temporary)
