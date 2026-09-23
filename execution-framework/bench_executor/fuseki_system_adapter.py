#!/usr/bin/env python3
"""Connect the shared server lifecycle to the stock KROWN Fuseki class."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from bench_executor.database_build_metrics import (
    build_metrics_from_phase,
    measure_persistent_paths,
)
from bench_executor.experiment_matrix_contract import DatasetArtifact
from bench_executor.fuseki import Fuseki, MEMORY_MODE, TDB2_MODE
from bench_executor.sparql_http_system_adapter import (
    SparqlHttpSystemAdapter,
    sparql_http_system_specifications,
)


BUILD_MODE = 'build'
REUSE_MODE = 'reuse'

def _store_inventory(path: Path) -> list[dict]:
    excluded = {'tdb.lock', 'journal.jrnl'}
    return [
        {'path': item.relative_to(path).as_posix(), 'size_bytes': item.stat().st_size}
        for item in sorted(path.rglob('*'))
        if item.is_file() and item.name not in excluded
    ]

def _verify_store_receipt(store: Path, receipt: Path) -> dict:
    value = json.loads(receipt.read_text(encoding='utf-8'))
    if value.get('schema') != 'fuseki-tdb2-store-receipt-v1':
        raise ValueError('unsupported Fuseki TDB2 receipt')
    if not store.is_dir() or _store_inventory(store) != value.get('files'):
        raise ValueError('Fuseki TDB2 store differs from its receipt')
    return value

def _fuseki_specification(dataset_mode: str):
    system_id = f'fuseki/{dataset_mode}'
    return next(
        specification for specification in sparql_http_system_specifications()
        if specification.system_id == system_id
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class FusekiSystemAdapter(SparqlHttpSystemAdapter):
    """Apply the generic lifecycle without duplicating Fuseki behavior."""

    def __init__(self, artifact: DatasetArtifact, data_path: str,
                 config_path: str, directory: str, verbose: bool = False,
                 dataset_mode: str = TDB2_MODE,
                 lifecycle_mode: str | None = None,
                 reuse_store_path: str | None = None,
                 reuse_receipt_path: str | None = None):
        if dataset_mode not in {MEMORY_MODE, TDB2_MODE}:
            raise ValueError(f'Unsupported Fuseki dataset mode: {dataset_mode}')
        super().__init__(_fuseki_specification(dataset_mode), artifact)
        self._dataset_mode = dataset_mode
        default_lifecycle = (
            os.environ.get('KROWN_FUSEKI_TDB2_MODE', BUILD_MODE)
            if dataset_mode == TDB2_MODE else BUILD_MODE
        )
        self._lifecycle_mode = lifecycle_mode or default_lifecycle
        if self._lifecycle_mode not in {BUILD_MODE, REUSE_MODE}:
            raise ValueError(f'Unsupported Fuseki lifecycle mode: {self._lifecycle_mode}')
        self._reuse_store = Path(reuse_store_path or os.environ.get(
            'KROWN_FUSEKI_TDB2_REUSE_PATH', '')).expanduser().resolve()
        self._reuse_receipt = Path(reuse_receipt_path or os.environ.get(
            'KROWN_FUSEKI_TDB2_RECEIPT', '')).expanduser().resolve()
        if getattr(self, '_lifecycle_mode', BUILD_MODE) == REUSE_MODE and dataset_mode != TDB2_MODE:
            raise ValueError('reuse mode is supported only for Fuseki TDB2')
        if artifact.source_format != 'ntriples':
            raise ValueError('Fuseki rdf/source artifact must use ntriples')
        if len(artifact.files) != 1:
            raise ValueError('Fuseki rdf/source artifact must contain one file')
        self._data_path = Path(data_path).resolve()
        self._config_path = Path(config_path).resolve()
        self._directory = Path(directory).resolve()
        self._verbose = verbose
        self._rdf_file = artifact.files[0]
        self._fuseki: Fuseki | None = None
        self.build_metrics = None
        self.representation_size = None
        self.load_metrics = None

    @property
    def memory_container(self) -> str:
        dataset_mode = getattr(self, '_dataset_mode', TDB2_MODE)
        if dataset_mode not in {MEMORY_MODE, TDB2_MODE}:
            raise ValueError(
                f'Unsupported Fuseki dataset mode: {dataset_mode}'
            )
        return f'Fuseki-{dataset_mode}'

    @property
    def endpoint(self) -> str:
        if self._fuseki is None:
            raise RuntimeError('Fuseki is not prepared')
        return self._fuseki.endpoint

    def prepare(self) -> bool:
        shared = (self._data_path / 'shared').resolve()
        source = (shared / self._rdf_file.path).resolve()
        try:
            source.relative_to(shared)
        except ValueError:
            return False
        if not source.is_file():
            return False
        if source.stat().st_size != self._rdf_file.size_bytes:
            return False
        if _sha256(source) != self._rdf_file.sha256:
            return False
        database_path = None
        if getattr(self, '_lifecycle_mode', BUILD_MODE) == REUSE_MODE:
            if not self._reuse_receipt.is_file():
                return False
            try:
                receipt = _verify_store_receipt(self._reuse_store, self._reuse_receipt)
            except (OSError, ValueError, json.JSONDecodeError):
                return False
            if receipt.get('source_sha256') != self.artifact.source_sha256:
                return False
            database_path = str(self._reuse_store)
            self.representation_size = {
                'schema': 'rdf-database-representation-size-v1',
                'boundary': 'verified-existing-representation',
                'logical_bytes': sum(item['size_bytes'] for item in receipt['files']),
                'allocated_bytes': receipt.get('allocated_bytes'),
                'file_count': len(receipt['files']),
            }
            self.build_metrics = {
                'schema': 'rdf-database-build-metrics-v1',
                'boundary': 'prebuilt-representation-reuse',
                'status': 'not-measured-in-query-run',
                'receipt': str(self._reuse_receipt),
            }
        self._fuseki = Fuseki(
            str(self._data_path), str(self._config_path),
            str(self._directory), self._verbose, self._dataset_mode,
            database_path=database_path,
        )
        return True

    def start(self) -> bool:
        if self._fuseki is None:
            return False
        if (self._dataset_mode == TDB2_MODE
                and getattr(self, '_lifecycle_mode', BUILD_MODE) == BUILD_MODE):
            if not self._fuseki.reset_store():
                return False
        return self._fuseki.wait_until_ready()

    def ready(self) -> bool:
        if self._fuseki is None:
            return False
        if self.memory_sampler is None:
            raise RuntimeError('Fuseki build memory sampler is not active')
        if getattr(self, '_lifecycle_mode', BUILD_MODE) == REUSE_MODE:
            self.load_metrics = {
                'schema': 'rdf-database-build-metrics-v1',
                'boundary': 'prebuilt-representation-reuse',
                'status': 'not-applicable',
            }
            return True
        started_ns = time.perf_counter_ns()
        succeeded = self._fuseki.load(self._rdf_file.path)
        elapsed_ns = time.perf_counter_ns() - started_ns
        memory = self.memory_sampler.snapshot()
        self.load_metrics = build_metrics_from_phase(
            elapsed_ns, memory, 'artifact_open_or_load',
            status='ok' if succeeded else 'failed',
            returncode=0 if succeeded else None,
        )
        if self._dataset_mode == MEMORY_MODE:
            self.build_metrics = {
                'schema': 'rdf-database-build-metrics-v1',
                'boundary': 'not-applicable',
                'reason': 'transient-in-memory-dataset',
            }
            self.representation_size = {
                'schema': 'rdf-database-representation-size-v1',
                'boundary': 'not-applicable',
                'reason': 'transient-in-memory-dataset',
                'logical_bytes': None,
                'allocated_bytes': None,
            }
        else:
            self.build_metrics = self.load_metrics
        if not succeeded:
            return False
        if self._dataset_mode == TDB2_MODE:
            self.representation_size = measure_persistent_paths(
                [self._data_path / 'fuseki'],
                excluded_names=['tdb.lock', 'journal.jrnl'],
            )
        return True

    def stop(self) -> bool:
        if self._fuseki is None:
            return True
        succeeded = self._fuseki.stop()
        if succeeded and getattr(self, '_lifecycle_mode', BUILD_MODE) == REUSE_MODE:
            try:
                _verify_store_receipt(self._reuse_store, self._reuse_receipt)
            except (OSError, ValueError, json.JSONDecodeError):
                return False
        return succeeded

    def collect(self) -> bool:
        """Leave log collection to the stock KROWN logger and executor."""
        return True
