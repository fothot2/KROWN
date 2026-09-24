#!/usr/bin/env python3
"""Connect Oxigraph memory and RocksDB systems to KROWN."""
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
from bench_executor.oxigraph import Oxigraph
from bench_executor.sparql_http_system_adapter import (
    SparqlHttpSystemAdapter,
    sparql_http_system_specifications,
)

BUILD_MODE = "build"
REUSE_MODE = "reuse"
_RECEIPT_SCHEMA = "oxigraph-rocksdb-store-receipt-v1"
_METADATA_NAME = ".krown-oxigraph-store.json"
_EXCLUDED_NAMES = ("LOCK", "LOG", _METADATA_NAME)
_EXCLUDED_PREFIXES = ("LOG.old.",)


def _system_specification(system_id: str):
    matches = [
        specification
        for specification in sparql_http_system_specifications()
        if specification.system_id == system_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one system specification for {system_id}")
    return matches[0]


def _validate_store_structure(store: Path) -> None:
    if not store.is_dir() or store.is_symlink():
        raise ValueError("Oxigraph RocksDB store is not a regular directory")
    for path in store.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Oxigraph RocksDB store contains a symlink: {path}")
    current = store / "CURRENT"
    if not current.is_file() or current.stat().st_size <= 0:
        raise ValueError("Oxigraph RocksDB CURRENT marker is missing or empty")
    if not any(path.is_file() and path.stat().st_size > 0 for path in store.rglob("*.sst")):
        raise ValueError("Oxigraph RocksDB store has no non-empty SST files")


def _verify_store_receipt(store: Path, receipt_path: Path) -> dict:
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    if value.get("schema") != _RECEIPT_SCHEMA:
        raise ValueError("unsupported Oxigraph RocksDB receipt")
    if Path(value.get("store_path", "")).resolve() != store.resolve():
        raise ValueError("Oxigraph receipt store path differs")
    graph_count = value.get("graph_triple_count")
    if not isinstance(graph_count, int) or isinstance(graph_count, bool) or graph_count <= 0:
        raise ValueError("Oxigraph receipt graph_triple_count is invalid")
    _validate_store_structure(store)
    return value


class OxigraphSystemAdapter(SparqlHttpSystemAdapter):
    """Control a fresh memory store or a build/reuse RocksDB lifecycle."""

    def __init__(
        self,
        artifact: DatasetArtifact,
        data_path: str,
        directory: str,
        backend: str,
        verbose: bool = False,
        port: int = 7878,
        lifecycle_mode: str | None = None,
        reuse_store_path: str | None = None,
        reuse_receipt_path: str | None = None,
    ) -> None:
        if backend not in {"memory", "rocksdb"}:
            raise ValueError("backend must be 'memory' or 'rocksdb'")
        if artifact.source_format != "ntriples" or len(artifact.files) != 1:
            raise ValueError("Oxigraph requires one N-Triples source file")

        super().__init__(_system_specification(f"oxigraph/{backend}"), artifact)
        self._data_path = Path(data_path).resolve()
        self._backend = backend
        self._artifact_file = artifact.files[0]
        self._lifecycle_mode = BUILD_MODE
        self._reuse_store = None
        self._reuse_receipt = None
        self._receipt_value = None

        if backend == "rocksdb":
            selected_mode = lifecycle_mode or os.environ.get(
                "KROWN_OXIGRAPH_ROCKSDB_MODE", BUILD_MODE
            )
            if selected_mode not in {BUILD_MODE, REUSE_MODE}:
                raise ValueError("Oxigraph RocksDB lifecycle mode must be build or reuse")
            self._lifecycle_mode = selected_mode
            if selected_mode == REUSE_MODE:
                store_text = reuse_store_path or os.environ.get(
                    "KROWN_OXIGRAPH_ROCKSDB_REUSE_PATH"
                )
                receipt_text = reuse_receipt_path or os.environ.get(
                    "KROWN_OXIGRAPH_ROCKSDB_RECEIPT"
                )
                if not store_text or not receipt_text:
                    raise ValueError("Oxigraph RocksDB reuse requires store and receipt paths")
                self._reuse_store = Path(store_text).expanduser().resolve()
                self._reuse_receipt = Path(receipt_text).expanduser().resolve()

        store_path = str(self._reuse_store) if self._reuse_store is not None else None
        self._oxigraph = Oxigraph(
            data_path, directory, verbose, backend, port, store_path=store_path
        )
        self.build_metrics = None
        self.representation_size = None

    @property
    def memory_container(self) -> str:
        return f"Oxigraph-{self._backend}"

    @property
    def endpoint(self) -> str:
        return self._oxigraph.endpoint

    @property
    def _store_path(self) -> Path:
        if self._reuse_store is not None:
            return self._reuse_store
        return self._data_path / "oxigraph-rocksdb"

    def prepare(self) -> bool:
        if self._backend == "rocksdb" and self._lifecycle_mode == REUSE_MODE:
            try:
                self._receipt_value = _verify_store_receipt(
                    self._store_path, self._reuse_receipt
                )
                self.representation_size = measure_persistent_paths(
                    [self._store_path],
                    excluded_names=_EXCLUDED_NAMES,
                    excluded_prefixes=_EXCLUDED_PREFIXES,
                )
                self.representation_size["boundary"] = "verified-existing-representation"
                self.build_metrics = {
                    "schema": "rdf-database-build-metrics-v1",
                    "boundary": "prebuilt-representation-reuse",
                    "status": "not-measured-in-query-run",
                    "receipt": str(self._reuse_receipt),
                }
                return True
            except (OSError, ValueError, json.JSONDecodeError):
                return False

        shared = (self._data_path / "shared").resolve()
        source = (shared / self._artifact_file.path).resolve()
        try:
            source.relative_to(shared)
        except ValueError:
            return False
        if not source.is_file() or source.stat().st_size != self._artifact_file.size_bytes:
            return False
        return True

    def start(self) -> bool:
        if self._backend == "rocksdb":
            if self._lifecycle_mode == BUILD_MODE:
                return self._oxigraph.reset_store()
            return self._oxigraph.start_server()
        if not self._oxigraph.reset_store():
            return False
        return self._oxigraph.start_server()

    def ready(self) -> bool:
        if self._backend == "rocksdb" and self._lifecycle_mode == REUSE_MODE:
            return self._oxigraph.is_ready()

        if self.memory_sampler is None:
            raise RuntimeError("Oxigraph build memory sampler is not active")
        started_ns = time.perf_counter_ns()
        succeeded = (
            self._oxigraph.load_rocksdb_file(self._artifact_file.path)
            if self._backend == "rocksdb"
            else self._oxigraph.load(self._artifact_file.path)
        )
        elapsed_ns = time.perf_counter_ns() - started_ns
        memory = self.memory_sampler.snapshot()
        self.build_metrics = build_metrics_from_phase(
            elapsed_ns,
            memory,
            "artifact_open_or_load",
            status="ok" if succeeded else "failed",
            returncode=0 if succeeded else None,
        )
        if not succeeded:
            diagnostic = getattr(self._oxigraph, "last_load_error", None)
            if isinstance(diagnostic, dict):
                self.build_metrics["failure"] = dict(diagnostic)
                detail = json.dumps(diagnostic, sort_keys=True)
            else:
                detail = "no structured Oxigraph load diagnostic is available"
            raise RuntimeError(f"Oxigraph RDF import failed: {detail}")

        if self._backend == "rocksdb":
            if not self._oxigraph.start_server():
                raise RuntimeError(
                    "Oxigraph server failed to start after CLI construction"
                )
            graph_count = self._oxigraph.count_triples()
            if graph_count is None or graph_count <= 0:
                return False
            metadata = {
                "schema": "oxigraph-rocksdb-build-metadata-v1",
                "source_sha256": self._artifact_file.sha256,
                "source_size_bytes": self._artifact_file.size_bytes,
                "graph_triple_count": graph_count,
            }
            (self._store_path / _METADATA_NAME).write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.representation_size = measure_persistent_paths(
                [self._store_path],
                excluded_names=_EXCLUDED_NAMES,
                excluded_prefixes=_EXCLUDED_PREFIXES,
            )
        else:
            self.representation_size = {
                "schema": "rdf-representation-size-v1",
                "boundary": "not-applicable",
                "reason": "in-memory-representation",
                "paths": [],
                "logical_bytes": None,
                "allocated_bytes": None,
                "file_count": 0,
                "directory_count": 0,
            }
        return True

    def stop(self) -> bool:
        stopped = self._oxigraph.stop()
        if not stopped:
            return False
        if self._backend == "rocksdb" and self._lifecycle_mode == REUSE_MODE:
            try:
                _validate_store_structure(self._store_path)
            except ValueError:
                return False
        return True

    def collect(self) -> bool:
        return True
