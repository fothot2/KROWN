#!/usr/bin/env python3
"Connect Oxigraph memory and RocksDB systems to KROWN."

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from bench_executor.database_build_metrics import (
    build_metrics_from_phase,
    measure_persistent_paths,
)
from bench_executor.experiment_matrix_contract import DatasetArtifact
from bench_executor.oxigraph import Oxigraph
from bench_executor.sparql_http_system_adapter import (
    SparqlHttpSystemAdapter,
    sparql_http_system_specifications,
)


def _system_specification(system_id: str):
    matches = [
        specification
        for specification in sparql_http_system_specifications()
        if specification.system_id == system_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one system specification for {system_id}")
    return matches[0]


class OxigraphSystemAdapter(SparqlHttpSystemAdapter):
    "Verify an RDF source and control one Oxigraph backend."

    def __init__(
        self,
        artifact: DatasetArtifact,
        data_path: str,
        directory: str,
        backend: str,
        verbose: bool = False,
        port: int = 7878,
    ) -> None:
        if backend not in {"memory", "rocksdb"}:
            raise ValueError("backend must be 'memory' or 'rocksdb'")
        if artifact.source_format != "ntriples" or len(artifact.files) != 1:
            raise ValueError("Oxigraph requires one N-Triples source file")

        super().__init__(_system_specification(f"oxigraph/{backend}"), artifact)
        self._data_path = Path(data_path).resolve()
        self._backend = backend
        self._artifact_file = artifact.files[0]
        self._oxigraph = Oxigraph(data_path, directory, verbose, backend, port)
        self.build_metrics = None
        self.representation_size = None

    @property
    def memory_container(self) -> str:
        return f"Oxigraph-{self._backend}"

    @property
    def endpoint(self) -> str:
        return self._oxigraph.endpoint

    def prepare(self) -> bool:
        shared = (self._data_path / "shared").resolve()
        source = (shared / self._artifact_file.path).resolve()
        try:
            source.relative_to(shared)
        except ValueError:
            return False
        if not source.is_file():
            return False
        if source.stat().st_size != self._artifact_file.size_bytes:
            return False

        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest() == self._artifact_file.sha256

    def start(self) -> bool:
        if not self._oxigraph.reset_store():
            return False
        return self._oxigraph.start_server()

    def ready(self) -> bool:
        if self.memory_sampler is None:
            raise RuntimeError('Oxigraph build memory sampler is not active')
        started_ns = time.perf_counter_ns()
        succeeded = self._oxigraph.load(self._artifact_file.path)
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
        if self._backend == 'rocksdb':
            self.representation_size = measure_persistent_paths(
                [self._data_path / 'oxigraph-rocksdb'],
                excluded_names=['LOCK', 'LOG'],
                excluded_prefixes=['LOG.old.'],
            )
        else:
            self.representation_size = {
                'schema': 'rdf-representation-size-v1',
                'boundary': 'not-applicable',
                'reason': 'in-memory-representation',
                'paths': [],
                'logical_bytes': None,
                'allocated_bytes': None,
                'file_count': 0,
                'directory_count': 0,
            }
        return True

    def stop(self) -> bool:
        return self._oxigraph.stop()

    def collect(self) -> bool:
        return True
