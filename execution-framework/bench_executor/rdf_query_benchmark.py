#!/usr/bin/env python3
"""Run RDF query workloads with one system-independent protocol."""

import dataclasses
import json
import random
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from bench_executor.benchmark_result import SCHEMA_VERSION, sha256_text, \
        write_query_records_atomic

MANIFEST_SCHEMA_VERSION = 1
LIFECYCLE_MODES = frozenset({'shared', 'per_attempt'})


class _QueryTimeoutError(TimeoutError):
    """Report an adapter-enforced query timeout."""


class _UnsupportedQueryError(RuntimeError):
    """Report a query that the adapter cannot execute."""


class _QueryParseError(RuntimeError):
    """Report invalid query syntax."""


class _ResultProcessingError(RuntimeError):
    """Report a failure while consuming query results."""


@dataclasses.dataclass(frozen=True)
class _QuerySpec:
    """Store one validated query and its optional metadata."""

    query_id: str
    query: str
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.query_id, str) or not self.query_id:
            raise ValueError('query_id must be a non-empty string')
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError('query must be a non-empty string')
        if not isinstance(self.metadata, Mapping):
            raise TypeError('metadata must be a mapping')
        try:
            json.dumps(self.metadata, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError(f'metadata is not valid JSON: {error}') from error

    @property
    def query_sha256(self) -> str:
        return sha256_text(self.query)


@dataclasses.dataclass(frozen=True)
class _QueryOutcome:
    """Store the result that one adapter returns."""

    result_count: int
    result_fingerprint: str | None = None
    elapsed_ns: int | None = None
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        if (not isinstance(self.result_count, int)
                or isinstance(self.result_count, bool)
                or self.result_count < 0):
            raise ValueError('result_count must be a non-negative integer')
        if (self.result_fingerprint is not None
                and (not isinstance(self.result_fingerprint, str)
                     or not self.result_fingerprint)):
            raise ValueError(
                'result_fingerprint must be null or a non-empty string'
            )
        if self.elapsed_ns is not None:
            if (not isinstance(self.elapsed_ns, int)
                    or isinstance(self.elapsed_ns, bool)
                    or self.elapsed_ns < 0):
                raise ValueError('elapsed_ns must be null or non-negative')
        if not isinstance(self.metadata, Mapping):
            raise TypeError('metadata must be a mapping')


class _RdfQueryAdapter:
    """Define the interface that each query-system adapter must implement."""

    def open(self) -> None:
        """Open the query system or its prepared artifact."""

    def execute(self, query: str) -> _QueryOutcome:
        """Execute one query and consume its complete result."""
        raise NotImplementedError

    def close(self) -> None:
        """Close the query system or its prepared artifact."""


@dataclasses.dataclass(frozen=True)
class _QueryManifest:
    """Store one validated workload manifest."""

    workload: str
    dataset: str
    queries: tuple[_QuerySpec, ...]


def _load_query_manifest(path: str) -> _QueryManifest:
    """Read and validate one JSON query manifest."""
    with open(path, 'r', encoding='utf-8') as stream:
        data = json.load(stream)

    if not isinstance(data, dict):
        raise ValueError('manifest root must be an object')
    if data.get('schema_version') != MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f'Unsupported manifest schema_version: '
            f'{data.get("schema_version")}'
        )

    workload = data.get('workload')
    dataset = data.get('dataset')
    raw_queries = data.get('queries')
    if not isinstance(workload, str) or not workload:
        raise ValueError('manifest workload must be a non-empty string')
    if not isinstance(dataset, str) or not dataset:
        raise ValueError('manifest dataset must be a non-empty string')
    if not isinstance(raw_queries, list) or not raw_queries:
        raise ValueError('manifest queries must be a non-empty array')

    queries = []
    query_ids = set()
    for index, raw_query in enumerate(raw_queries):
        if not isinstance(raw_query, dict):
            raise ValueError(f'query {index} must be an object')
        query_id = raw_query.get('query_id')
        if query_id in query_ids:
            raise ValueError(f'Duplicate query_id: {query_id}')
        query_text = raw_query.get('query')
        declared_query_sha256 = raw_query.get('query_sha256')
        if declared_query_sha256 is not None:
            if (not isinstance(declared_query_sha256, str)
                    or len(declared_query_sha256) != 64
                    or any(character not in '0123456789abcdef'
                           for character in declared_query_sha256)):
                raise ValueError(
                    f'query {index} query_sha256 must be a lowercase SHA-256'
                )
            calculated_query_sha256 = sha256_text(query_text)
            if declared_query_sha256 != calculated_query_sha256:
                raise ValueError(
                    f'query {index} query_sha256 differs from query text'
                )
        metadata = {
            key: value for key, value in raw_query.items()
            if key not in {'query_id', 'query', 'query_sha256'}
        }
        query = _QuerySpec(
            query_id=query_id,
            query=query_text,
            metadata=metadata,
        )
        query_ids.add(query.query_id)
        queries.append(query)

    return _QueryManifest(
        workload=workload,
        dataset=dataset,
        queries=tuple(queries),
    )


def _status_for_exception(error: BaseException) -> str:
    """Map an adapter exception to one canonical status."""
    if isinstance(error, _QueryTimeoutError):
        return 'timeout'
    if isinstance(error, _UnsupportedQueryError):
        return 'unsupported'
    if isinstance(error, _QueryParseError):
        return 'parse_error'
    if isinstance(error, _ResultProcessingError):
        return 'result_error'
    if isinstance(error, ConnectionError):
        return 'connection_error'
    return 'engine_error'


class _RdfQueryBenchmark:
    """Execute one query manifest and write canonical attempt records."""

    def __init__(
            self,
            adapter_factory: Callable[[], _RdfQueryAdapter],
            experiment_id: str,
            system: str,
            manifest: _QueryManifest,
            warmup_runs: int = 1,
            measured_runs: int = 5,
            shuffle: bool = False,
            seed: int = 42,
            lifecycle: str = 'shared',
            skip_after_warmup_timeout: bool = True,
            skip_after_warmup_error: bool = True):
        if not callable(adapter_factory):
            raise TypeError('adapter_factory must be callable')
        for name, value in (
                ('experiment_id', experiment_id), ('system', system)):
            if not isinstance(value, str) or not value:
                raise ValueError(f'{name} must be a non-empty string')
        for name, value in (
                ('warmup_runs', warmup_runs),
                ('measured_runs', measured_runs)):
            if (not isinstance(value, int) or isinstance(value, bool)
                    or value < 0):
                raise ValueError(f'{name} must be a non-negative integer')
        if measured_runs == 0:
            raise ValueError('measured_runs must be greater than zero')
        if lifecycle not in LIFECYCLE_MODES:
            raise ValueError(f'Unsupported lifecycle: {lifecycle}')

        self._adapter_factory = adapter_factory
        self._experiment_id = experiment_id
        self._system = system
        self._manifest = manifest
        self._warmup_runs = warmup_runs
        self._measured_runs = measured_runs
        self._shuffle = shuffle
        self._seed = seed
        self._lifecycle = lifecycle
        self._skip_after_warmup_timeout = skip_after_warmup_timeout
        self._skip_after_warmup_error = skip_after_warmup_error

    def _ordered_queries(self, phase_index: int) -> list[_QuerySpec]:
        queries = list(self._manifest.queries)
        if self._shuffle:
            random.Random(self._seed + phase_index).shuffle(queries)
        return queries

    def _base_record(
            self, query: _QuerySpec, phase: str, run: int,
            order: int, phase_seed: int) -> dict[str, Any]:
        record = {
            'schema_version': SCHEMA_VERSION,
            'experiment_id': self._experiment_id,
            'system': self._system,
            'dataset': self._manifest.dataset,
            'workload': self._manifest.workload,
            'query_id': query.query_id,
            'query_sha256': query.query_sha256,
            'phase': phase,
            'run': run,
            'order': order,
            'seed': phase_seed,
            'status': 'ok',
            'elapsed_ns': 0,
            'result_count': None,
            'result_fingerprint': None,
            'error_type': None,
            'error_message': None,
        }
        for key, value in query.metadata.items():
            if key in record:
                raise ValueError(
                    f'query metadata replaces reserved field: {key}'
                )
            record[key] = value
        return record

    def _execute_attempt(
            self, adapter: _RdfQueryAdapter,
            query: _QuerySpec,
            record: dict[str, Any]) -> dict[str, Any]:
        start_ns = time.perf_counter_ns()
        try:
            outcome = adapter.execute(query.query)
            elapsed_ns = time.perf_counter_ns() - start_ns
            if not isinstance(outcome, _QueryOutcome):
                raise _ResultProcessingError(
                    'adapter.execute() must return _QueryOutcome'
                )
            record.update({
                'elapsed_ns': (
                    outcome.elapsed_ns
                    if outcome.elapsed_ns is not None else elapsed_ns
                ),
                'client_elapsed_ns': elapsed_ns,
                'result_count': outcome.result_count,
                'result_fingerprint': outcome.result_fingerprint,
            })
            for key, value in outcome.metadata.items():
                if key in record:
                    raise _ResultProcessingError(
                        f'adapter metadata replaces reserved field: {key}'
                    )
                record[key] = value
        except BaseException as error:
            record.update({
                'status': _status_for_exception(error),
                'elapsed_ns': time.perf_counter_ns() - start_ns,
                'error_type': type(error).__name__,
                'error_message': str(error),
            })
            record['_traceback'] = traceback.format_exc()
        return record

    def run(self, output_path: str) -> list[dict[str, Any]]:
        """Run all attempts and atomically write their canonical records."""
        records = []
        skip_reasons: dict[str, tuple[str, str]] = {}
        shared_adapter = None
        phase_index = 0

        try:
            if self._lifecycle == 'shared':
                shared_adapter = self._adapter_factory()
                shared_adapter.open()

            phases: Sequence[tuple[str, int]] = (
                [('warmup', run) for run in range(self._warmup_runs)]
                + [('measured', run) for run in range(self._measured_runs)]
            )
            for phase, run in phases:
                phase_seed = self._seed + phase_index
                ordered_queries = self._ordered_queries(phase_index)
                phase_index += 1
                for order, query in enumerate(ordered_queries):
                    record = self._base_record(
                        query, phase, run, order, phase_seed
                    )
                    if phase == 'measured' and query.query_id in skip_reasons:
                        reason_type, reason_message = skip_reasons[query.query_id]
                        record.update({
                            'status': 'skipped',
                            'elapsed_ns': None,
                            'error_type': reason_type,
                            'error_message': reason_message,
                        })
                        records.append(record)
                        continue

                    adapter = shared_adapter
                    try:
                        if self._lifecycle == 'per_attempt':
                            adapter = self._adapter_factory()
                            adapter.open()
                        record = self._execute_attempt(adapter, query, record)
                    finally:
                        if self._lifecycle == 'per_attempt' and adapter is not None:
                            adapter.close()
                    records.append(record)

                    if phase == 'warmup':
                        status = record['status']
                        skip = (
                            status == 'timeout'
                            and self._skip_after_warmup_timeout
                        ) or (
                            status not in {'ok', 'timeout'}
                            and self._skip_after_warmup_error
                        )
                        if skip:
                            skip_reasons[query.query_id] = (
                                record['error_type'], record['error_message']
                            )
        finally:
            if shared_adapter is not None:
                shared_adapter.close()

        output_records = []
        for record in records:
            output_record = dict(record)
            output_record.pop('_traceback', None)
            output_records.append(output_record)
        write_query_records_atomic(output_path, output_records)
        return records
