#!/usr/bin/env python3
"""Connect the shared server lifecycle to QLever."""
from __future__ import annotations

import hashlib
from pathlib import Path
import shlex

from bench_executor.experiment_matrix_contract import DatasetArtifact
from bench_executor.qlever import QLever
from bench_executor.sparql_http_system_adapter import (
    SparqlHttpSystemAdapter,
    sparql_http_system_specifications,
)


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
                 port: int = 7001):
        super().__init__(_qlever_specification(), artifact)
        if artifact.source_format != 'ntriples':
            raise ValueError('QLever rdf/source artifact must use ntriples')
        if len(artifact.files) != 1:
            raise ValueError('QLever rdf/source artifact must contain one file')
        self._data_path = Path(data_path).resolve()
        self._directory = Path(directory).resolve()
        self._rdf_file = artifact.files[0]
        container_source = f'/data/shared/{self._rdf_file.path}'
        index_basename = '/data/qlever-index/bsbm-explore-1k'
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
        )

    @property
    def endpoint(self) -> str:
        return self._qlever.endpoint

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
        return self._qlever.build_index()

    def start(self) -> bool:
        return self._qlever.start()

    def ready(self) -> bool:
        return self._qlever.wait_until_ready()

    def stop(self) -> bool:
        return self._qlever.stop()

    def collect(self) -> bool:
        """Leave log collection to the stock KROWN logger and executor."""
        return True
