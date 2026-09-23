#!/usr/bin/env python3
"""Run canonical SPARQL SELECT and ASK workloads over HTTP."""

import codecs
import json
import multiprocessing as mp
import os
import re
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



_BINDINGS_PREFIX = re.compile(r'"bindings"\s*:\s*\[')
_MAX_JSON_PREFIX_CHARS = 1024 * 1024


def _count_select_bindings(chunks) -> tuple[int, int]:
    """Count complete top-level binding objects with bounded retained text."""
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer = ''
    found = False
    count = 0
    response_bytes = 0
    in_string = False
    escaped = False
    object_depth = 0
    array_depth = 0
    saw_value = False
    finished = False
    for raw in chunks:
        response_bytes += len(raw)
        text = decoder.decode(raw)
        if not found:
            buffer += text
            match = _BINDINGS_PREFIX.search(buffer)
            if match is None:
                if len(buffer) > _MAX_JSON_PREFIX_CHARS:
                    raise ValueError('SPARQL JSON bindings prefix exceeds limit')
                continue
            text = buffer[match.end():]
            buffer = ''
            found = True
        for character in text:
            if finished:
                continue
            if in_string:
                if escaped:
                    escaped = False
                elif character == '\\':
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == '{':
                object_depth += 1
                saw_value = True
            elif character == '}':
                if object_depth == 0:
                    raise ValueError('invalid SPARQL binding object')
                object_depth -= 1
                if object_depth == 0 and array_depth == 0:
                    count += 1
            elif character == '[':
                array_depth += 1
            elif character == ']':
                if object_depth == 0 and array_depth == 0:
                    finished = True
                elif array_depth == 0:
                    raise ValueError('invalid SPARQL binding array')
                else:
                    array_depth -= 1
            elif (not character.isspace() and character != ','
                  and object_depth == 0 and array_depth == 0):
                saw_value = True
                raise ValueError('SPARQL SELECT binding must be an object')
    tail = decoder.decode(b'', final=True)
    if tail:
        raise ValueError('unexpected buffered UTF-8 tail')
    if not found or not finished or in_string or object_depth or array_depth:
        raise ValueError('incomplete SPARQL JSON SELECT response')
    if saw_value and count == 0:
        raise ValueError('invalid SPARQL JSON SELECT response')
    return count, response_bytes


def _count_ntriples(chunks) -> tuple[int, int]:
    """Count complete non-empty N-Triples lines without retaining the graph."""
    pending = b''
    count = 0
    response_bytes = 0
    for raw in chunks:
        response_bytes += len(raw)
        pending += raw
        lines = pending.split(b'\n')
        pending = lines.pop()
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith(b'#'):
                count += 1
        if len(pending) > 16 * 1024 * 1024:
            raise ValueError('N-Triples response line exceeds 16 MiB')
    stripped = pending.strip()
    if stripped and not stripped.startswith(b'#'):
        count += 1
    return count, response_bytes


def _count_http_result_worker(connection, endpoint, query, system, request_max_rows):
    """Stream and count one complete HTTP result in a killable process."""
    try:
        result_type = classify_query(query).result_type
        accept = ('application/n-triples'
                  if result_type in {'construct', 'describe'}
                  else 'application/sparql-results+json')
        data = {'query': query}
        if request_max_rows is not None:
            data['maxrows'] = str(request_max_rows)
        if system == _VIRTUOSO_SYSTEM:
            data['default-graph-uri'] = _VIRTUOSO_DEFAULT_GRAPH
        started_ns = time.perf_counter_ns()
        response = requests.post(
            endpoint, data=data, headers={'Accept': accept},
            timeout=None, stream=True,
        )
        headers_ns = time.perf_counter_ns() - started_ns
        response.raise_for_status()
        consume_started_ns = time.perf_counter_ns()
        content_type = response.headers.get('Content-Type', '')
        media_type = content_type.split(';', 1)[0].strip().lower()
        chunks = response.iter_content(chunk_size=64 * 1024)
        if result_type == 'ask':
            body = b''.join(chunks)
            if len(body) > _MAX_JSON_PREFIX_CHARS:
                raise ValueError('SPARQL ASK response exceeds 1 MiB')
            response_bytes = len(body)
            document = json.loads(body)
            if not isinstance(document.get('boolean'), bool):
                raise ValueError('SPARQL ASK boolean must be true or false')
            result_count = 1 if document['boolean'] else 0
            result_kind = 'ask'
        elif result_type == 'select':
            if media_type not in {'application/sparql-results+json', 'application/json'}:
                raise ValueError(f'Unsupported SPARQL SELECT response type: {media_type!r}')
            result_count, response_bytes = _count_select_bindings(chunks)
            result_kind = 'select'
        else:
            if media_type not in {'application/n-triples', 'text/plain'}:
                raise ValueError(f'Unsupported streaming graph response type: {media_type!r}')
            result_count, response_bytes = _count_ntriples(chunks)
            result_kind = 'graph'
        consume_ns = time.perf_counter_ns() - consume_started_ns
        connection.send({
            'status': 'ok', 'result_count': result_count,
            'headers_ns': headers_ns, 'consume_ns': consume_ns,
            'response_bytes': response_bytes,
            'http_status': response.status_code, 'result_kind': result_kind,
        })
    except BaseException as error:
        try:
            connection.send({'status': 'error', 'error_type': type(error).__name__,
                             'error_message': str(error)})
        except (BrokenPipeError, OSError):
            pass
    finally:
        connection.close()

class _SparqlHttpAdapter(_RdfQueryAdapter):
    """Send SPARQL over HTTP and consume each complete response body."""

    def __init__(self, endpoint: str, timeout_s: float,
                 correctness_mode: str = 'fingerprint',
                 full_result_max_rows: int = 10000,
                 system: str | None = None,
                 request_max_rows: int | None = None,
                 memory_sampler=None, warmup_attempt_count: int = 0):
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
        if request_max_rows is not None:
            if (not isinstance(request_max_rows, int)
                    or isinstance(request_max_rows, bool)
                    or request_max_rows <= 0):
                raise ValueError('request_max_rows must be a positive integer or None')
            if system != _QLEVER_SYSTEM:
                raise ValueError('request_max_rows is supported only for qlever/default')
        self._endpoint = endpoint
        self._timeout_s = timeout_s
        self._correctness_mode = correctness_mode
        self._full_result_max_rows = full_result_max_rows
        self._system = system
        self._request_max_rows = request_max_rows
        self._memory_sampler = memory_sampler
        self._warmup_attempt_count = warmup_attempt_count
        self._attempt_index = 0
        self._session = None

    def open(self) -> None:
        if self._session is not None:
            raise RuntimeError('SPARQL HTTP adapter is already open')
        self._session = requests.Session()

    def execute(self, query: str) -> _QueryOutcome:
        if self._session is None:
            raise RuntimeError('SPARQL HTTP adapter is not open')
        if self._memory_sampler is not None:
            phase = (
                'warmup' if self._attempt_index < self._warmup_attempt_count
                else 'measured'
            )
            self._memory_sampler.set_phase(phase)
            self._attempt_index += 1
        result_type = classify_query(query).result_type
        if result_type in {'construct', 'describe'}:
            accept = 'application/n-triples, text/turtle;q=0.9'
        else:
            accept = 'application/sparql-results+json'
        headers = {'Accept': accept}
        data = {'query': query}
        if self._request_max_rows is not None:
            data['maxrows'] = str(self._request_max_rows)
        if self._system == _VIRTUOSO_SYSTEM:
            data['default-graph-uri'] = _VIRTUOSO_DEFAULT_GRAPH
        if self._correctness_mode == 'count-only':
            parent, child = mp.Pipe(duplex=False)
            process = mp.Process(target=_count_http_result_worker,
                args=(child, self._endpoint, query, self._system, self._request_max_rows),
                name='krown-sparql-http-attempt', daemon=True)
            attempt_started_ns = time.perf_counter_ns(); process.start(); child.close()
            if not parent.poll(self._timeout_s):
                process.terminate(); process.join(timeout=0.5)
                if process.is_alive(): process.kill(); process.join(timeout=0.5)
                parent.close()
                raise _QueryTimeoutError(
                    f'SPARQL HTTP complete attempt exceeded {self._timeout_s}s')
            message = parent.recv(); parent.close(); process.join(timeout=0.5)
            if message.get('status') != 'ok':
                raise RuntimeError(f"{message.get('error_type')}: {message.get('error_message')}")
            attempt_ns = time.perf_counter_ns() - attempt_started_ns
            headers_ns = int(message['headers_ns'])
            consume_ns = int(message['consume_ns'])
            return _QueryOutcome(
                result_count=int(message['result_count']),
                result_fingerprint=None,
                elapsed_ns=attempt_ns,
                metadata={
                    'measurement_boundary': 'complete-result-consumption',
                    'comparison_mode': 'count-only',
                    'http_status': message['http_status'],
                    'response_bytes': message['response_bytes'],
                    'result_kind': message['result_kind'],
                    'streaming_result_count': True,
                    'request_max_rows': self._request_max_rows,
                    'result_cap_requested': self._request_max_rows is not None,
                },
                stage_timings_ns={
                    'request_until_response_headers': headers_ns,
                    'response_stream_parse_and_count': consume_ns,
                    'worker_dispatch': max(0, attempt_ns - headers_ns - consume_ns),
                },
            )
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
            'request_max_rows': self._request_max_rows,
            'result_cap_requested': self._request_max_rows is not None,
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
            elapsed_ns=execute_ns,
            metadata=metadata,
            stage_timings_ns={
                'engine_execute': execute_ns,
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
        self.last_lifecycle_timing = None
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
                request_max_rows: int | None = None,
                skip_after_warmup_timeout: bool = True,
                skip_after_warmup_error: bool = True,
                memory_sampler=None, manual_skip_rules=(),
                automatic_quarantine_rules=(), probe_rules=(),
                force_include: bool = False,
                in_run_timeout_quarantine_threshold: int = 0) -> bool:
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
                    request_max_rows=request_max_rows,
                    memory_sampler=memory_sampler,
                    warmup_attempt_count=len(manifest.queries) * warmup_runs,
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
                manual_skip_rules=manual_skip_rules,
                automatic_quarantine_rules=automatic_quarantine_rules,
                probe_rules=probe_rules, force_include=force_include,
                in_run_timeout_quarantine_threshold=(
                    in_run_timeout_quarantine_threshold
                ),
            )
            records = benchmark.run(output_path)
            self.last_lifecycle_timing = benchmark.last_lifecycle_timing
            self.last_lifecycle_timing['execution_mode'].update({
                'storage': 'server-managed',
                'transport': 'sparql-http',
            })
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
