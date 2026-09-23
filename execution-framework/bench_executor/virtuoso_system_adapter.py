#!/usr/bin/env python3
"""Connect the shared server lifecycle to the stock KROWN Virtuoso class."""
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
from bench_executor.sparql_http_system_adapter import (
    SparqlHttpSystemAdapter,
    sparql_http_system_specifications,
)
from bench_executor.virtuoso import Virtuoso



BUILD_MODE = 'build'
REUSE_MODE = 'reuse'
_RECEIPT_SCHEMA = 'virtuoso-store-receipt-v1'
_EXCLUDED_NAMES = {
    'virtuoso-temp.db', 'virtuoso.ini', 'virtuoso.lck',
    'virtuoso.log', 'virtuoso.pxa', 'virtuoso.trx',
}


def _store_inventory(path: Path) -> list[dict]:
    if not path.is_dir() or path.is_symlink():
        raise ValueError('Virtuoso store must be a real directory')
    records = []
    for item in sorted(path.rglob('*')):
        if item.is_symlink():
            raise ValueError(f'Virtuoso store contains a symlink: {item}')
        if item.is_file() and item.name not in _EXCLUDED_NAMES:
            records.append({
                'path': item.relative_to(path).as_posix(),
                'size_bytes': item.stat().st_size,
            })
    if not records:
        raise ValueError('Virtuoso stable store inventory is empty')
    return records


def _verify_store_receipt(store: Path, receipt_path: Path) -> dict:
    """Verify stable Virtuoso store structure without freezing file sizes."""
    value = json.loads(receipt_path.read_text(encoding='utf-8'))

    if value.get('schema') != _RECEIPT_SCHEMA:
        raise ValueError('unsupported Virtuoso store receipt')

    if Path(value.get('store_path', '')).resolve() != store.resolve():
        raise ValueError('Virtuoso receipt store path differs')

    declared = value.get('files')

    if not isinstance(declared, list) or not declared:
        raise ValueError('Virtuoso receipt has no stable files')

    current = _store_inventory(store)

    declared_paths = {
        item.get('path')
        for item in declared
        if isinstance(item, dict)
    }

    current_paths = {
        item['path']
        for item in current
    }

    if declared_paths != current_paths:
        raise ValueError(
            'Virtuoso stable store file set differs from its receipt'
        )

    for item in current:
        if item['size_bytes'] <= 0:
            raise ValueError(
                'Virtuoso stable store contains an empty file: '
                + item['path']
            )

    value = dict(value)
    value['current_files'] = current
    value['current_logical_bytes'] = sum(
        item['size_bytes']
        for item in current
    )

    return value

def _virtuoso_specification():
    return next(
        specification for specification in sparql_http_system_specifications()
        if specification.system_id == 'virtuoso/default'
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class VirtuosoSystemAdapter(SparqlHttpSystemAdapter):
    """Apply the generic lifecycle without duplicating Virtuoso behavior."""

    def __init__(self, artifact: DatasetArtifact, data_path: str,
                 config_path: str, directory: str, verbose: bool = False,
                 loader_cores: int = 1, lifecycle_mode: str | None = None,
                 reuse_store_path: str | None = None,
                 reuse_receipt_path: str | None = None):
        super().__init__(_virtuoso_specification(), artifact)
        if artifact.source_format != 'ntriples':
            raise ValueError('Virtuoso rdf/source artifact must use ntriples')
        if len(artifact.files) != 1:
            raise ValueError('Virtuoso rdf/source artifact must contain one file')
        if not isinstance(loader_cores, int) or isinstance(loader_cores, bool) \
                or loader_cores < 1:
            raise ValueError('loader_cores must be a positive integer')
        self._data_path = Path(data_path).resolve()
        self._config_path = Path(config_path).resolve()
        self._directory = Path(directory).resolve()
        self._verbose = verbose
        self._loader_cores = loader_cores
        self._rdf_file = artifact.files[0]
        self._lifecycle_mode = lifecycle_mode or os.environ.get(
            'KROWN_VIRTUOSO_MODE', BUILD_MODE
        )
        if self._lifecycle_mode not in {BUILD_MODE, REUSE_MODE}:
            raise ValueError(
                f'Unsupported Virtuoso lifecycle mode: {self._lifecycle_mode}'
            )
        store_value = reuse_store_path or os.environ.get(
            'KROWN_VIRTUOSO_REUSE_PATH', ''
        )
        receipt_value = reuse_receipt_path or os.environ.get(
            'KROWN_VIRTUOSO_RECEIPT', ''
        )
        self._reuse_store = (
            Path(store_value).expanduser().resolve() if store_value else None
        )
        self._reuse_receipt = (
            Path(receipt_value).expanduser().resolve() if receipt_value else None
        )
        self._virtuoso: Virtuoso | None = None
        self.build_metrics = None
        self.representation_size = None

    @property
    def memory_container(self) -> str:
        return 'Virtuoso'

    @property
    def endpoint(self) -> str:
        if self._virtuoso is None:
            raise RuntimeError('Virtuoso is not prepared')
        return self._virtuoso.endpoint

    def prepare(self) -> bool:
        shared = (self._data_path / 'shared').resolve()
        source = (shared / self._rdf_file.path).resolve()
        try:
            source.relative_to(shared)
        except ValueError:
            return False
        database_path = None
        if self._lifecycle_mode == BUILD_MODE:
            if not source.is_file():
                return False
            if source.stat().st_size != self._rdf_file.size_bytes:
                return False
            if _sha256(source) != self._rdf_file.sha256:
                return False
        else:
            if self._reuse_store is None or self._reuse_receipt is None:
                return False
            if not self._reuse_receipt.is_file():
                return False
            try:
                receipt = _verify_store_receipt(
                    self._reuse_store, self._reuse_receipt
                )
            except (OSError, ValueError, json.JSONDecodeError):
                return False
            if receipt.get('source_sha256') != self.artifact.source_sha256:
                return False
            database_path = str(self._reuse_store)
            self.build_metrics = {
                'schema': 'rdf-database-build-metrics-v1',
                'boundary': 'prebuilt-representation-reuse',
                'status': 'not-measured-in-query-run',
                'receipt': str(self._reuse_receipt),
            }
            current_files = receipt['current_files']

            self.representation_size = {
                'schema': 'rdf-database-representation-size-v1',
                'boundary': 'verified-existing-representation',
                'logical_bytes': receipt['current_logical_bytes'],
                'allocated_bytes': sum(
                    (self._reuse_store / item['path'])
                    .stat()
                    .st_blocks
                    * 512
                    for item in current_files
                ),
                'file_count': len(current_files),
            }
        self._virtuoso = Virtuoso(
            str(self._data_path), str(self._config_path),
            str(self._directory), self._verbose,
            database_path=database_path,
        )
        return True

    def start(self) -> bool:
        if self._virtuoso is None:
            return False
        if self._lifecycle_mode == BUILD_MODE:
            if not self._virtuoso.reset_store():
                return False
        return self._virtuoso.wait_until_ready()

    def ready(self) -> bool:
        if self._virtuoso is None:
            return False

        if self._lifecycle_mode == REUSE_MODE:
            return True

        if self.memory_sampler is None:
            raise RuntimeError(
                'Virtuoso build memory sampler is not active'
            )

        started_ns = time.perf_counter_ns()
        succeeded = self._virtuoso.load_parallel(
            self._rdf_file.path, self._loader_cores,
        )
        elapsed_ns = time.perf_counter_ns() - started_ns
        memory = self.memory_sampler.snapshot()
        self.build_metrics = build_metrics_from_phase(
            elapsed_ns,
            memory,
            'artifact_open_or_load',
            status='ok' if succeeded else 'failed',
            returncode=0 if succeeded else None,
        )
        if not succeeded:
            return False
        self.representation_size = measure_persistent_paths(
            [self._data_path / 'virtuoso'],
            excluded_names=[
                'virtuoso-temp.db',
                'virtuoso.ini',
                'virtuoso.log',
                'virtuoso.pxa',
                'virtuoso.trx',
            ],
        )
        return True

    def stop(self) -> bool:
        if self._virtuoso is None:
            return True
        if not self._virtuoso.stop():
            return False
        if self._lifecycle_mode == REUSE_MODE:
            try:
                _verify_store_receipt(
                    self._reuse_store, self._reuse_receipt
                )
            except (OSError, ValueError, json.JSONDecodeError):
                return False
            return True
        self.representation_size = measure_persistent_paths(
            [self._data_path / 'virtuoso'],
            excluded_names=[
                'virtuoso-temp.db',
                'virtuoso.ini',
                'virtuoso.log',
                'virtuoso.pxa',
                'virtuoso.trx',
            ],
        )
        return True

    def collect(self) -> bool:
        """Leave log collection to the stock KROWN logger and executor."""
        return True
