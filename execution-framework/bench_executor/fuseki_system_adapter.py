#!/usr/bin/env python3
"""Connect the shared server lifecycle to the stock KROWN Fuseki class."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from bench_executor.database_build_metrics import (
    build_metrics_from_phase,
    measure_persistent_paths,
)
from bench_executor.experiment_matrix_contract import DatasetArtifact
from bench_executor.fuseki import Fuseki
from bench_executor.sparql_http_system_adapter import (
    SparqlHttpSystemAdapter,
    sparql_http_system_specifications,
)


def _fuseki_specification():
    return next(
        specification for specification in sparql_http_system_specifications()
        if specification.system_id == 'fuseki/default'
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
                 config_path: str, directory: str, verbose: bool = False):
        super().__init__(_fuseki_specification(), artifact)
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

    @property
    def memory_container(self) -> str:
        return 'Fuseki'

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
        self._fuseki = Fuseki(
            str(self._data_path), str(self._config_path),
            str(self._directory), self._verbose,
        )
        return True

    def start(self) -> bool:
        if self._fuseki is None:
            return False
        if not self._fuseki.reset_store():
            return False
        return self._fuseki.wait_until_ready()

    def ready(self) -> bool:
        if self._fuseki is None:
            return False
        if self.memory_sampler is None:
            raise RuntimeError('Fuseki build memory sampler is not active')
        started_ns = time.perf_counter_ns()
        succeeded = self._fuseki.load(self._rdf_file.path)
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
            [self._data_path / 'fuseki'],
            excluded_names=['tdb.lock', 'journal.jrnl'],
        )
        return True

    def stop(self) -> bool:
        if self._fuseki is None:
            return True
        return self._fuseki.stop()

    def collect(self) -> bool:
        """Leave log collection to the stock KROWN logger and executor."""
        return True
