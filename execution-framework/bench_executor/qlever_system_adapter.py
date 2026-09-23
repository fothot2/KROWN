#!/usr/bin/env python3
"""Connect the shared server lifecycle to QLever."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex

from bench_executor.experiment_matrix_contract import DatasetArtifact
from bench_executor.qlever import QLever
from bench_executor.sparql_http_system_adapter import (
    SparqlHttpSystemAdapter,
    sparql_http_system_specifications,
)



BUILD_MODE = 'build'
REUSE_MODE = 'reuse'
_RECEIPT_SCHEMA = 'qlever-index-receipt-v1'
_RUNTIME_SUFFIXES = ('.metrics-log.jsonl', '.resource-usage-log.tsv')


def _index_inventory(path: Path) -> list[dict]:
    if not path.is_dir() or path.is_symlink():
        raise ValueError('QLever index must be a real directory')
    records = []
    for item in sorted(path.rglob('*')):
        if item.is_symlink():
            raise ValueError(f'QLever index contains a symlink: {item}')
        if item.is_file() and not item.name.endswith(_RUNTIME_SUFFIXES):
            records.append({
                'path': item.relative_to(path).as_posix(),
                'size_bytes': item.stat().st_size,
            })
    if not records:
        raise ValueError('QLever stable index inventory is empty')
    return records


def _verify_index_receipt(index: Path, receipt_path: Path) -> dict:
    value = json.loads(receipt_path.read_text(encoding='utf-8'))
    if value.get('schema') != _RECEIPT_SCHEMA:
        raise ValueError('unsupported QLever index receipt')
    if Path(value.get('index_path', '')).resolve() != index.resolve():
        raise ValueError('QLever receipt index path differs')
    declared = value.get('files')
    if not isinstance(declared, list) or not declared:
        raise ValueError('QLever receipt has no stable index files')
    current = _index_inventory(index)
    if declared != current:
        raise ValueError('QLever stable index differs from its receipt')
    value = dict(value)
    value['current_files'] = current
    return value

def _qlever_specification():
    return next(
        item for item in sparql_http_system_specifications()
        if item.system_id == 'qlever/default'
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class QLeverSystemAdapter(SparqlHttpSystemAdapter):
    """Apply the generic lifecycle to a pinned QLever container."""

    def __init__(self, artifact: DatasetArtifact, data_path: str,
                 directory: str, image: str = 'kgconstruct/qlever:v0.6.0',
                 index_command: str | None = None,
                 server_command: str | None = None, verbose: bool = False,
                 port: int = 7001, request_max_rows: int | None = None,
                 lifecycle_mode: str | None = None,
                 reuse_index_path: str | None = None,
                 reuse_receipt_path: str | None = None):
        super().__init__(_qlever_specification(), artifact)
        if isinstance(request_max_rows, str):
            if not request_max_rows.isdigit():
                raise ValueError('request_max_rows must be a positive integer or None')
            request_max_rows = int(request_max_rows)
        if (request_max_rows is not None
                and (not isinstance(request_max_rows, int)
                     or isinstance(request_max_rows, bool)
                     or request_max_rows <= 0)):
            raise ValueError('request_max_rows must be a positive integer or None')
        self.query_request_max_rows = request_max_rows
        if artifact.source_format != 'ntriples':
            raise ValueError('QLever rdf/source artifact must use ntriples')
        if len(artifact.files) != 1:
            raise ValueError('QLever rdf/source artifact must contain one file')
        self._data_path = Path(data_path).resolve()
        self._directory = Path(directory).resolve()
        self._rdf_file = artifact.files[0]
        self._lifecycle_mode = lifecycle_mode or os.environ.get(
            'KROWN_QLEVER_MODE', BUILD_MODE
        )
        if self._lifecycle_mode not in {BUILD_MODE, REUSE_MODE}:
            raise ValueError(
                f'Unsupported QLever lifecycle mode: {self._lifecycle_mode}'
            )
        index_value = reuse_index_path or os.environ.get(
            'KROWN_QLEVER_REUSE_PATH', ''
        )
        receipt_value = reuse_receipt_path or os.environ.get(
            'KROWN_QLEVER_RECEIPT', ''
        )
        self._reuse_index = (
            Path(index_value).expanduser().resolve() if index_value else None
        )
        self._reuse_receipt = (
            Path(receipt_value).expanduser().resolve() if receipt_value else None
        )
        container_source = f'/data/shared/{self._rdf_file.path}'
        index_basename = '/data/qlever-index/dataset'
        if index_command is None:
            batch_command = (
                'mkdir -p /data/qlever-index && '
                f'/qlever/qlever-index --index-basename {index_basename} '
                f'--kg-input-file {shlex.quote(container_source)} --file-format nt'
            )
            index_command = '-c ' + shlex.quote(batch_command)
        if server_command is None:
            batch_command = (
                f'exec /qlever/qlever-server --index-basename {index_basename} '
                f'--port {port}'
            )
            server_command = '-c ' + shlex.quote(batch_command)
        self._qlever = QLever(
            str(self._data_path), str(self._directory), verbose,
            image, index_command, server_command, port,
            index_path=(
                str(self._reuse_index)
                if self._lifecycle_mode == REUSE_MODE else None
            ),
        )

    @property
    def memory_container(self) -> str:
        return 'qlever_server'

    @property
    def endpoint(self) -> str:
        return self._qlever.endpoint

    @property
    def build_metrics(self):
        return self._qlever.build_metrics

    @property
    def representation_size(self):
        return self._qlever.representation_size

    def prepare(self) -> bool:
        shared = (self._data_path / 'shared').resolve()
        source = (shared / self._rdf_file.path).resolve()
        try:
            source.relative_to(shared)
        except ValueError:
            return False
        if self._lifecycle_mode == BUILD_MODE:
            if not source.is_file():
                return False
            if source.stat().st_size != self._rdf_file.size_bytes:
                return False
            if _sha256(source) != self._rdf_file.sha256:
                return False
            return self._qlever.build_index()
        if self._reuse_index is None or self._reuse_receipt is None:
            return False
        if not self._reuse_receipt.is_file():
            return False
        try:
            receipt = _verify_index_receipt(
                self._reuse_index, self._reuse_receipt
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        if receipt.get('source_sha256') != self.artifact.source_sha256:
            return False
        files = receipt['current_files']
        self._qlever.build_metrics = {
            'schema': 'rdf-representation-build-metrics-v1',
            'boundary': 'prebuilt-representation-reuse',
            'status': 'not-measured-in-query-run',
            'receipt': str(self._reuse_receipt),
        }
        self._qlever.representation_size = {
            'schema': 'rdf-representation-size-v1',
            'boundary': 'verified-existing-representation',
            'paths': [str(self._reuse_index)],
            'logical_bytes': sum(item['size_bytes'] for item in files),
            'allocated_bytes': sum(
                (self._reuse_index / item['path']).stat().st_blocks * 512
                for item in files
            ),
            'file_count': len(files),
            'directory_count': sum(
                1 for item in self._reuse_index.rglob('*')
                if item.is_dir()
            ) + 1,
        }
        return True

    def start(self) -> bool:
        return self._qlever.start()

    def ready(self) -> bool:
        return self._qlever.wait_until_ready()

    def stop(self) -> bool:
        if not self._qlever.stop():
            return False
        if self._lifecycle_mode == REUSE_MODE:
            try:
                _verify_index_receipt(
                    self._reuse_index, self._reuse_receipt
                )
            except (OSError, ValueError, json.JSONDecodeError):
                return False
        return True

    def collect(self) -> bool:
        """Leave log collection to the stock KROWN logger and executor."""
        return True
