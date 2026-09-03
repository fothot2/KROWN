#!/usr/bin/env python3
"""Integrate RDFLib-backed RDF query systems with the KROWN runner."""

import multiprocessing as mp
import os
import time
import traceback
from pathlib import Path

import psutil

from rdflib import Graph

from bench_executor.sparql_result import CORRECTNESS_MODES, \
        normalize_materialized_result

from bench_executor.logger import Logger
from bench_executor.rdf_query_benchmark import _load_query_manifest, \
        _QueryOutcome, _QueryTimeoutError, _RdfQueryAdapter, \
        _RdfQueryBenchmark

SUPPORTED_ENGINES = frozenset({'default', 'vortex', 'cottas'})


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
                 vortex_layout: str, correctness_mode: str = 'none',
                 full_result_max_rows: int = 10000):
        if engine not in SUPPORTED_ENGINES:
            raise ValueError(f'Unsupported RDFLib engine: {engine}')
        self._engine = engine
        self._artifact_path = artifact_path
        self._vortex_layout = vortex_layout
        self._correctness_mode = correctness_mode
        self._full_result_max_rows = full_result_max_rows
        self._graph = None

    def open(self) -> None:
        if self._graph is not None:
            raise RuntimeError('RDFLib adapter is already open')

        self._graph = _make_rdflib_graph(
            self._engine, self._artifact_path, self._vortex_layout
        )

    def execute(self, query: str) -> _QueryOutcome:
        if self._graph is None:
            raise RuntimeError('RDFLib adapter is not open')
        started_ns = time.perf_counter_ns()
        result = self._graph.query(query)
        execute_ns = time.perf_counter_ns() - started_ns
        materialize_started_ns = time.perf_counter_ns()
        rows = list(result)
        materialize_ns = time.perf_counter_ns() - materialize_started_ns
        elapsed_ns = execute_ns + materialize_ns
        correctness_started_ns = time.perf_counter_ns()
        metadata = {
            'measurement_boundary': 'rdflib-full-result-materialization',
        }
        fingerprint = None
        if self._correctness_mode != 'none':
            correctness = normalize_materialized_result(result, rows, query)
            fingerprint = correctness.pop('result_fingerprint')
            normalized = correctness.pop('normalized_result')
            metadata.update(correctness)
            if self._correctness_mode == 'full':
                metadata['full_result_retained'] = (
                    len(rows) <= self._full_result_max_rows
                )
                if metadata['full_result_retained']:
                    metadata['normalized_result'] = normalized
        correctness_ns = time.perf_counter_ns() - correctness_started_ns
        return _QueryOutcome(
            result_count=len(rows), result_fingerprint=fingerprint,
            elapsed_ns=elapsed_ns + correctness_ns, metadata=metadata,
            stage_timings_ns={
                'engine_execute': execute_ns,
                'result_materialize': materialize_ns,
                'correctness': correctness_ns,
            },
        )

    def close(self) -> None:
        if self._graph is not None:
            self._graph.close()
            self._graph = None


def _make_rdflib_graph(engine: str, artifact_path: str,
                       vortex_layout: str) -> Graph:
    """Create one RDFLib graph for a supported prepared artifact."""
    if engine == 'default':
        graph = Graph()
        try:
            graph.parse(artifact_path, format='nt')
        except BaseException:
            graph.close()
            raise
        return graph
    if engine == 'vortex':
        from vortex_rdflib import VortexRdflibStore
        # Vortex-RDF 0.10 files are self-describing. The store detects the
        # physical layout and indexes from the artifact.
        store = VortexRdflibStore(path=artifact_path)
    elif engine == 'cottas':
        from pycottas.cottas_store import COTTASStore
        store = COTTASStore(artifact_path)
    else:
        raise ValueError(f'Unsupported RDFLib engine: {engine}')
    return Graph(store=store)


def _rdflib_worker(connection, engine: str, artifact_path: str,
                   vortex_layout: str, correctness_mode: str,
                   full_result_max_rows: int) -> None:
    """Own one RDFLib graph and execute parent-issued queries serially."""
    graph = None
    try:
        graph = _make_rdflib_graph(
            engine, artifact_path, vortex_layout
        )
        connection.send({'kind': 'ready'})
        while True:
            request = connection.recv()
            if request.get('kind') == 'shutdown':
                return
            request_id = request['request_id']
            try:
                query = request['query']
                started_ns = time.perf_counter_ns()
                result = graph.query(query)
                rows = list(result)
                elapsed_ns = time.perf_counter_ns() - started_ns
                response = {
                    'kind': 'result',
                    'request_id': request_id,
                    'status': 'ok',
                    'result_count': len(rows),
                    'elapsed_ns': elapsed_ns,
                    'metadata': {
                        'measurement_boundary': (
                            'rdflib-full-result-materialization'
                        ),
                    },
                    'result_fingerprint': None,
                }
                if correctness_mode != 'none':
                    correctness = normalize_materialized_result(
                        result, rows, query
                    )
                    response['result_fingerprint'] = correctness.pop(
                        'result_fingerprint'
                    )
                    normalized = correctness.pop('normalized_result')
                    response['metadata'].update(correctness)
                    if correctness_mode == 'full':
                        retained = len(rows) <= full_result_max_rows
                        response['metadata']['full_result_retained'] = retained
                        if retained:
                            response['metadata']['normalized_result'] = normalized
                connection.send(response)
            except BaseException as error:
                connection.send({
                    'kind': 'result',
                    'request_id': request_id,
                    'status': 'error',
                    'error_type': type(error).__name__,
                    'error_message': str(error),
                    'traceback': traceback.format_exc(),
                })
    except (EOFError, BrokenPipeError):
        return
    except BaseException as error:
        try:
            connection.send({
                'kind': 'startup_error',
                'error_type': type(error).__name__,
                'error_message': str(error),
                'traceback': traceback.format_exc(),
            })
        except (BrokenPipeError, OSError):
            pass
    finally:
        if graph is not None:
            graph.close()
        connection.close()


def _terminate_process_tree(pid: int, grace_s: float) -> None:
    """Terminate one process tree and kill processes that do not stop."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    processes = parent.children(recursive=True) + [parent]
    for process in processes:
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(
        processes, timeout=max(grace_s, 0.0)
    )
    for process in alive:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=max(grace_s, 0.0))


class _WorkerRdfLibAdapter(_RdfQueryAdapter):
    """Run queries in one persistent worker that the parent can terminate."""

    def __init__(self, engine: str, artifact_path: str,
                 vortex_layout: str, timeout_s: float,
                 startup_timeout_s: float, kill_grace_s: float,
                 correctness_mode: str = 'none',
                 full_result_max_rows: int = 10000):
        if timeout_s <= 0:
            raise ValueError('timeout_s must be greater than zero')
        if startup_timeout_s <= 0:
            raise ValueError('startup_timeout_s must be greater than zero')
        if kill_grace_s < 0:
            raise ValueError('kill_grace_s must be zero or greater')
        self._engine = engine
        self._artifact_path = artifact_path
        self._vortex_layout = vortex_layout
        self._timeout_s = timeout_s
        self._startup_timeout_s = startup_timeout_s
        if correctness_mode not in CORRECTNESS_MODES:
            raise ValueError(f'Unsupported correctness_mode: {correctness_mode}')
        if full_result_max_rows < 0:
            raise ValueError('full_result_max_rows must be zero or greater')
        self._kill_grace_s = kill_grace_s
        self._correctness_mode = correctness_mode
        self._full_result_max_rows = full_result_max_rows
        self._connection = None
        self._process = None
        self._next_request_id = 0
        self._worker_starts = 0

    def progress_metadata(self):
        process = self._process
        return {
            'worker_pid': process.pid if process is not None and process.is_alive() else 'none',
            'worker_restarts': max(0, self._worker_starts - 1),
        }

    def _discard(self) -> None:
        connection = self._connection
        process = self._process
        self._connection = None
        self._process = None
        if connection is not None:
            connection.close()
        if process is not None and process.is_alive():
            _terminate_process_tree(process.pid, self._kill_grace_s)
            process.join(timeout=max(self._kill_grace_s, 0.0))

    def open(self) -> None:
        if self._process is not None:
            raise RuntimeError('RDFLib worker is already open')
        parent, child = mp.Pipe(duplex=True)
        process = mp.Process(
            target=_rdflib_worker,
            args=(
                child,
                self._engine,
                self._artifact_path,
                self._vortex_layout,
                self._correctness_mode,
                self._full_result_max_rows,
            ),
            name=f'krown-{self._engine}-query-worker',
            daemon=True,
        )
        process.start()
        self._worker_starts += 1
        child.close()
        self._connection = parent
        self._process = process
        if not parent.poll(self._startup_timeout_s):
            pid = process.pid
            self._discard()
            raise RuntimeError(
                f'RDFLib worker did not start within '
                f'{self._startup_timeout_s}s; killed pid={pid}'
            )
        message = parent.recv()
        if message.get('kind') != 'ready':
            error = message.get('error_message', 'unknown startup error')
            self._discard()
            raise RuntimeError(f'RDFLib worker startup failed: {error}')

    def execute(self, query: str) -> _QueryOutcome:
        if (self._connection is None or self._process is None
                or not self._process.is_alive()):
            self._discard()
            self.open()
        request_id = self._next_request_id
        self._next_request_id += 1
        self._connection.send({
            'kind': 'query',
            'request_id': request_id,
            'query': query,
        })
        if not self._connection.poll(self._timeout_s):
            pid = self._process.pid
            self._discard()
            raise _QueryTimeoutError(
                f'Query exceeded {self._timeout_s}s; killed worker pid={pid}'
            )
        try:
            message = self._connection.recv()
        except EOFError as error:
            exitcode = self._process.exitcode
            self._discard()
            raise RuntimeError(
                f'RDFLib worker exited without a response; '
                f'exitcode={exitcode}'
            ) from error
        if (message.get('kind') != 'result'
                or message.get('request_id') != request_id):
            self._discard()
            raise RuntimeError(
                f'Unexpected RDFLib worker response: {message!r}'
            )
        if message.get('status') != 'ok':
            raise RuntimeError(
                f'{message.get("error_type", "WorkerError")}: '
                f'{message.get("error_message", "unknown worker error")}'
            )
        return _QueryOutcome(
            result_count=message['result_count'],
            result_fingerprint=message.get('result_fingerprint'),
            elapsed_ns=message.get('elapsed_ns'),
            metadata=message.get('metadata', {}),
        )

    def close(self) -> None:
        if (self._connection is not None and self._process is not None
                and self._process.is_alive()):
            try:
                self._connection.send({'kind': 'shutdown'})
                self._process.join(timeout=self._kill_grace_s)
            except (BrokenPipeError, EOFError, OSError):
                pass
        self._discard()


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
                skip_after_warmup_error: bool = True,
                timeout_s: float = 60.0,
                timeout_mode: str = 'worker',
                startup_timeout_s: float = 120.0,
                kill_grace_s: float = 1.0,
                correctness_mode: str = 'fingerprint',
                full_result_max_rows: int = 10000) -> bool:
        """Execute an RDFLib-backed workload and save JSON Lines records."""
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

            if correctness_mode not in CORRECTNESS_MODES:
                raise ValueError(
                    f'Unsupported correctness_mode: {correctness_mode}'
                )
            if full_result_max_rows < 0:
                raise ValueError(
                    'full_result_max_rows must be zero or greater'
                )
            if timeout_mode not in {'none', 'worker'}:
                raise ValueError(
                    f'Unsupported timeout_mode: {timeout_mode}'
                )
            if timeout_mode == 'none':
                def adapter_factory():
                    return _RdfLibAdapter(
                        engine=engine,
                        artifact_path=artifact_path,
                        vortex_layout=vortex_layout,
                        correctness_mode=correctness_mode,
                        full_result_max_rows=full_result_max_rows,
                    )
            else:
                def adapter_factory():
                    return _WorkerRdfLibAdapter(
                        engine=engine,
                        artifact_path=artifact_path,
                        vortex_layout=vortex_layout,
                        timeout_s=timeout_s,
                        startup_timeout_s=startup_timeout_s,
                        kill_grace_s=kill_grace_s,
                        correctness_mode=correctness_mode,
                        full_result_max_rows=full_result_max_rows,
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
