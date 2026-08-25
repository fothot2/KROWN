#!/usr/bin/env python3
"""Connect the shared server lifecycle to the stock KROWN Virtuoso class."""
from __future__ import annotations

import hashlib
from pathlib import Path

from bench_executor.experiment_matrix_contract import DatasetArtifact
from bench_executor.sparql_http_system_adapter import (
    SparqlHttpSystemAdapter,
    sparql_http_system_specifications,
)
from bench_executor.virtuoso import Virtuoso


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
                 loader_cores: int = 1):
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
        self._virtuoso: Virtuoso | None = None

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
        if not source.is_file():
            return False
        if source.stat().st_size != self._rdf_file.size_bytes:
            return False
        if _sha256(source) != self._rdf_file.sha256:
            return False
        self._virtuoso = Virtuoso(
            str(self._data_path), str(self._config_path),
            str(self._directory), self._verbose,
        )
        return self._virtuoso.initialization()

    def start(self) -> bool:
        if self._virtuoso is None:
            return False
        return self._virtuoso.wait_until_ready()

    def ready(self) -> bool:
        if self._virtuoso is None:
            return False
        return self._virtuoso.load_parallel(
            self._rdf_file.path, self._loader_cores,
        )

    def stop(self) -> bool:
        if self._virtuoso is None:
            return True
        return self._virtuoso.stop()

    def collect(self) -> bool:
        """Leave log collection to the stock KROWN logger and executor."""
        return True
