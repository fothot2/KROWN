#!/usr/bin/env python3
"""Integrate RDFLib-backed RDF query systems with the KROWN runner."""

import os
from pathlib import Path

from rdflib import Graph

from bench_executor.logger import Logger
from bench_executor.rdf_query_benchmark import _load_query_manifest, \
        _QueryOutcome, _RdfQueryAdapter, _RdfQueryBenchmark

SUPPORTED_ENGINES = frozenset({'vortex', 'cottas'})


def _resolve_input_path(shared_directory: str, declared_path: str) -> str:
    """Resolve one existing input file from an absolute or shared path."""
    if not isinstance(declared_path, str) or not declared_path:
        raise ValueError('Input path must be a non-empty string')

    if os.path.isabs(declared_path):
        path = os.path.realpath(declared_path)
    else:
        shared_directory = os.path.realpath(shared_directory)
        path = os.path.realpath(
            os.path.join(shared_directory, declared_path)
        )
        if os.path.commonpath([shared_directory, path]) != shared_directory:
            raise ValueError(
                f'Input path leaves the shared directory: {declared_path}'
            )

    if not os.path.isfile(path):
        raise FileNotFoundError(f'Input is not an existing file: {path}')
    return path


def _resolve_output_path(shared_directory: str, declared_path: str) -> str:
    """Resolve one output file inside the shared data directory."""
    if not isinstance(declared_path, str) or not declared_path:
        raise ValueError('Output path must be a non-empty string')
    if os.path.isabs(declared_path):
        raise ValueError('Output path must be relative')

    shared_directory = os.path.realpath(shared_directory)
    path = os.path.realpath(os.path.join(shared_directory, declared_path))
    if os.path.commonpath([shared_directory, path]) != shared_directory:
        raise ValueError(
            f'Output path leaves the shared directory: {declared_path}'
        )
    return path


class _RdfLibAdapter(_RdfQueryAdapter):
    """Execute SPARQL with one RDFLib Graph and consume all result rows."""

    def __init__(self, engine: str, artifact_path: str,
                 vortex_layout: str):
        if engine not in SUPPORTED_ENGINES:
            raise ValueError(f'Unsupported RDFLib engine: {engine}')
        self._engine = engine
        self._artifact_path = artifact_path
        self._vortex_layout = vortex_layout
        self._graph = None

    def open(self) -> None:
        if self._graph is not None:
            raise RuntimeError('RDFLib adapter is already open')

        if self._engine == 'vortex':
            from vortex_rdflib import VortexStore
            store = VortexStore(
                self._artifact_path,
                layout=self._vortex_layout,
                backend='native',
            )
        else:
            from pycottas.cottas_store import COTTASStore
            store = COTTASStore(self._artifact_path)
        self._graph = Graph(store=store)

    def execute(self, query: str) -> _QueryOutcome:
        if self._graph is None:
            raise RuntimeError('RDFLib adapter is not open')
        rows = list(self._graph.query(query))
        return _QueryOutcome(result_count=len(rows))

    def close(self) -> None:
        if self._graph is not None:
            self._graph.close()
            self._graph = None


class RdfLibQueryBenchmark:
    """Run one RDFLib query workload as a KROWN resource."""

    def __init__(self, data_path: str, config_path: str, directory: str,
                 verbose: bool):
        self._data_path = os.path.abspath(data_path)
        self._shared_directory = os.path.join(self._data_path, 'shared')
        self._logger = Logger(__name__, directory, verbose)
        os.umask(0)
        os.makedirs(self._shared_directory, exist_ok=True)

    @property
    def name(self):
        return __name__

    @property
    def root_mount_directory(self) -> str:
        return __name__.lower()

    def execute(self, engine: str, artifact_file: str,
                manifest_file: str, results_file: str,
                experiment_id: str, system: str,
                warmup_runs: int = 1, measured_runs: int = 5,
                shuffle: bool = False, seed: int = 42,
                lifecycle: str = 'shared',
                vortex_layout: str = 'cottas-native-ids',
                skip_after_warmup_timeout: bool = True,
                skip_after_warmup_error: bool = True) -> bool:
        """Execute a Vortex or COTTAS workload and save JSON Lines records."""
        try:
            if engine not in SUPPORTED_ENGINES:
                raise ValueError(f'Unsupported RDFLib engine: {engine}')
            artifact_path = _resolve_input_path(
                self._shared_directory, artifact_file
            )
            manifest_path = _resolve_input_path(
                self._shared_directory, manifest_file
            )
            output_path = _resolve_output_path(
                self._shared_directory, results_file
            )
            manifest = _load_query_manifest(manifest_path)

            def adapter_factory():
                return _RdfLibAdapter(
                    engine=engine,
                    artifact_path=artifact_path,
                    vortex_layout=vortex_layout,
                )

            benchmark = _RdfQueryBenchmark(
                adapter_factory=adapter_factory,
                experiment_id=experiment_id,
                system=system,
                manifest=manifest,
                warmup_runs=warmup_runs,
                measured_runs=measured_runs,
                shuffle=shuffle,
                seed=seed,
                lifecycle=lifecycle,
                skip_after_warmup_timeout=skip_after_warmup_timeout,
                skip_after_warmup_error=skip_after_warmup_error,
            )
            records = benchmark.run(output_path)
            failures = sum(
                record['status'] not in {'ok', 'skipped', 'unsupported'}
                for record in records
            )
            self._logger.info(
                f'Wrote {len(records)} query attempt records to '
                f'"{output_path}"; failures={failures}'
            )
            return True
        except Exception as error:
            self._logger.error(
                f'RDFLib query benchmark failed: '
                f'{type(error).__name__}: {error}'
            )
            return False
