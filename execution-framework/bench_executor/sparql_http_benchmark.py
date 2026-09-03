#!/usr/bin/env python3
"""Run canonical SPARQL SELECT and ASK workloads over HTTP."""

import os
import time

import requests
from rdflib import Graph
from rdflib.compare import to_canonical_graph

from bench_executor.logger import Logger
from bench_executor.query_features import classify_query
from bench_executor.rdf_query_benchmark import _load_query_manifest, \
        _QueryOutcome, _QueryTimeoutError, _RdfQueryAdapter, \
        _RdfQueryBenchmark
from bench_executor.sparql_result import CORRECTNESS_MODES, \
        normalize_graph_terms, normalize_sparql_json_result


_QLEVER_SYSTEM = 'qlever/default'
_VIRTUOSO_SYSTEM = 'virtuoso/default'
_VIRTUOSO_DEFAULT_GRAPH = 'http://example.com/graph'
_XSD_INT = 'http://www.w3.org/2001/XMLSchema#int'
_XSD_INTEGER = 'http://www.w3.org/2001/XMLSchema#integer'


def _correct_qlever_integer_datatypes(document: dict) -> dict:
    """Correct QLever 0.6.0 integer datatypes without mutating input."""
    results = document.get('results')
    if not isinstance(results, dict):
        return document
    bindings = results.get('bindings')
    if not isinstance(bindings, list):
        return document
    corrected_bindings = []
    changed = False
    for row in bindings:
        if not isinstance(row, dict):
            corrected_bindings.append(row)
            continue
        corrected_row = {}
        row_changed = False
        for variable, term in row.items():
            if isinstance(term, dict) and term.get('datatype') == _XSD_INT:
                corrected_term = dict(term)
                corrected_term['datatype'] = _XSD_INTEGER
                corrected_row[variable] = corrected_term
                row_changed = True
            else:
                corrected_row[variable] = term
        corrected_bindings.append(corrected_row if row_changed else row)
        changed = changed or row_changed
    if not changed:
        return document
    corrected_results = dict(results)
    corrected_results['bindings'] = corrected_bindings
    corrected_document = dict(document)
    corrected_document['results'] = corrected_results
    return corrected_document


_GRAPH_MEDIA_TYPES = {
    'application/n-triples': 'nt',
    'text/plain': 'nt',
    'text/turtle': 'turtle',
    'application/rdf+xml': 'xml',
    'application/ld+json': 'json-ld',
}


def _normalize_graph_response(body: bytes, media_type: str) -> dict:
    """Parse one RDF graph response and create a stable graph fingerprint."""
    rdf_format = _GRAPH_MEDIA_TYPES.get(media_type)
    if rdf_format is None:
        raise RuntimeError(
            f'Unsupported SPARQL HTTP response type: {media_type!r}'
        )
    try:
        graph = Graph()
        graph.parse(data=body, format=rdf_format)
        canonical = to_canonical_graph(graph)
        rows = list(canonical)
    except Exception as error:
        preview = body[:200].decode('utf-8', errors='replace')
        raise RuntimeError(
            f'Invalid RDF graph response; content_type={media_type!r}; '
            f'preview={preview!r}'
        ) from error
    return normalize_graph_terms(
        rows, 'CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }'
    )


class _SparqlHttpAdapter(_RdfQueryAdapter):
    """Send SPARQL over HTTP and consume each complete response body."""

    def __init__(self, endpoint: str, timeout_s: float,
                 correctness_mode: str = 'fingerprint',
                 full_result_max_rows: int = 10000,
                 system: str | None = None):
        if not isinstance(endpoint, str) or not endpoint:
            raise ValueError('endpoint must be a non-empty string')
        if timeout_s <= 0:
            raise ValueError('timeout_s must be greater than zero')
        if correctness_mode not in CORRECTNESS_MODES:
            raise ValueError(
                f'Unsupported correctness_mode: {correctness_mode}'
            )
        if full_result_max_rows < 0:
            raise ValueError('full_result_max_rows must be zero or greater')
        self._endpoint = endpoint
        self._timeout_s = timeout_s
        self._correctness_mode = correctness_mode
        self._full_result_max_rows = full_result_max_rows
        self._system = system
        self._session = None

    def open(self) -> None:
        if self._session is not None:
            raise RuntimeError('SPARQL HTTP adapter is already open')
        self._session = requests.Session()

    def execute(self, query: str) -> _QueryOutcome:
        if self._session is None:
            raise RuntimeError('SPARQL HTTP adapter is not open')
        result_type = classify_query(query).result_type
        if result_type in {'construct', 'describe'}:
            accept = 'application/n-triples, text/turtle;q=0.9'
        else:
            accept = 'application/sparql-results+json'
        headers = {'Accept': accept}
        data = {
            'query': query,
            'maxrows': '3000000',
        }
        if self._system == _VIRTUOSO_SYSTEM:
            data['default-graph-uri'] = _VIRTUOSO_DEFAULT_GRAPH
        started_ns = time.perf_counter_ns()
        try:
            response = self._session.post(
                self._endpoint,
                data=data,
                headers=headers,
                timeout=self._timeout_s,
            )
            body = response.content
        except requests.Timeout as error:
            raise _QueryTimeoutError(
                f'SPARQL HTTP query exceeded {self._timeout_s}s'
            ) from error
        except requests.ConnectionError as error:
            raise ConnectionError(str(error)) from error
        execute_ns = time.perf_counter_ns() - started_ns
        response.raise_for_status()
        processing_started_ns = time.perf_counter_ns()

        content_type = response.headers.get('Content-Type', '')
        media_type = content_type.split(';', 1)[0].strip().lower()
        if media_type in {
                'application/sparql-results+json', 'application/json'}:
            try:
                document = response.json()
                if self._system == _QLEVER_SYSTEM:
                    document = _correct_qlever_integer_datatypes(document)
            except ValueError as error:
                preview = body[:200].decode('utf-8', errors='replace')
                raise RuntimeError(
                    'Invalid SPARQL JSON response; '
                    f'content_type={content_type!r}; preview={preview!r}'
                ) from error
            normalized = normalize_sparql_json_result(document, query)
        else:
            normalized = _normalize_graph_response(body, media_type)
        result_count = normalized.pop('result_count')
        fingerprint = normalized.pop('result_fingerprint')
        full_result = normalized.pop('normalized_result')
        metadata = {
            'measurement_boundary': 'sparql-http-complete-response',
            'http_status': response.status_code,
            'response_bytes': len(body),
        }
        if self._correctness_mode != 'none':
            metadata.update(normalized)
        else:
            fingerprint = None
        if self._correctness_mode == 'full':
            retained = result_count <= self._full_result_max_rows
            metadata['full_result_retained'] = retained
            if retained:
                metadata['normalized_result'] = full_result
        processing_ns = time.perf_counter_ns() - processing_started_ns
        return _QueryOutcome(
            result_count=result_count,
            result_fingerprint=fingerprint,
            elapsed_ns=elapsed_ns,
            metadata=metadata,
            stage_timings_ns={
                'engine_execute': elapsed_ns,
                'correctness': processing_ns,
            },
        )

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None


class SparqlHttpBenchmark:
    """Run one SELECT or ASK workload against a SPARQL HTTP endpoint."""

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

    def _shared_path(self, declared_path: str, output: bool) -> str:
        if not isinstance(declared_path, str) or not declared_path:
            raise ValueError('Path must be a non-empty string')
        if os.path.isabs(declared_path):
            raise ValueError('Path must be relative to data/shared')
        shared = os.path.realpath(self._shared_directory)
        path = os.path.realpath(os.path.join(shared, declared_path))
        if os.path.commonpath([shared, path]) != shared:
            raise ValueError(f'Path leaves data/shared: {declared_path}')
        if not output and not os.path.isfile(path):
            raise FileNotFoundError(f'Input is not an existing file: {path}')
        return path

    def execute(self, endpoint: str, manifest_file: str,
                results_file: str, experiment_id: str, system: str,
                timeout_s: float = 60.0, warmup_runs: int = 1,
                measured_runs: int = 5, shuffle: bool = False,
                seed: int = 42, lifecycle: str = 'shared',
                correctness_mode: str = 'fingerprint',
                full_result_max_rows: int = 10000,
                skip_after_warmup_timeout: bool = True,
                skip_after_warmup_error: bool = True) -> bool:
        """Execute the workload and write canonical JSON Lines records."""
        try:
            manifest_path = self._shared_path(manifest_file, output=False)
            output_path = self._shared_path(results_file, output=True)
            manifest = _load_query_manifest(manifest_path)

            def adapter_factory():
                return _SparqlHttpAdapter(
                    endpoint=endpoint,
                    timeout_s=timeout_s,
                    correctness_mode=correctness_mode,
                    full_result_max_rows=full_result_max_rows,
                    system=system,
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
                f'Wrote {len(records)} SPARQL HTTP records to '
                f'"{output_path}"; failures={failures}'
            )
            return True
        except Exception as error:
            self._logger.error(
                f'SPARQL HTTP benchmark failed: '
                f'{type(error).__name__}: {error}'
            )
            return False
