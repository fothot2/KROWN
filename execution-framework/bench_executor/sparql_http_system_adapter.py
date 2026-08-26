#!/usr/bin/env python3
"""Run benchmark-neutral SPARQL HTTP server lifecycles."""
from __future__ import annotations

import abc
import dataclasses
from collections.abc import Callable
from typing import Any

from bench_executor.experiment_matrix_contract import DatasetArtifact, SystemConfiguration
from bench_executor.system_adapter_contract import (
    LifecycleCapabilities,
    LifecycleOperation,
    LifecycleState,
    LifecycleTracker,
    SystemAdapterSpecification,
)

_REQUIRED_REPRESENTATION = 'rdf/source'
_SYSTEM_ADAPTERS = {
    'fuseki/default': 'bench_executor.fuseki_system_adapter:FusekiSystemAdapter',
    'virtuoso/default': 'bench_executor.virtuoso_system_adapter:VirtuosoSystemAdapter',
    'qlever/default': 'bench_executor.qlever_system_adapter:QLeverSystemAdapter',
    'oxigraph/memory': 'bench_executor.oxigraph_system_adapter:OxigraphSystemAdapter',
    'oxigraph/rocksdb': 'bench_executor.oxigraph_system_adapter:OxigraphSystemAdapter',
}


def sparql_http_system_specifications() -> tuple[SystemAdapterSpecification, ...]:
    """Return canonical specifications for supported SPARQL HTTP servers."""
    specifications = []
    for system_id, adapter in _SYSTEM_ADAPTERS.items():
        system, configuration = system_id.split('/', 1)
        system_configuration = SystemConfiguration(
            system=system,
            configuration=configuration,
            kind='server',
            representation=_REQUIRED_REPRESENTATION,
        )
        specifications.append(SystemAdapterSpecification(
            configuration=system_configuration,
            adapter=adapter,
            capabilities=LifecycleCapabilities.for_kind('server'),
        ))
    return tuple(specifications)


@dataclasses.dataclass(frozen=True)
class SparqlHttpRunResult:
    """Report the final lifecycle state and cleanup outcome."""

    system_id: str
    state: LifecycleState
    history: tuple[LifecycleOperation, ...]
    failed_operation: LifecycleOperation | None = None
    error: str | None = None
    stop_attempted: bool = False
    collect_attempted: bool = False

    @property
    def success(self) -> bool:
        """Return whether the complete lifecycle succeeded."""
        return self.state == LifecycleState.COLLECTED


class SparqlHttpSystemAdapter(abc.ABC):
    """Coordinate one server that exposes a SPARQL HTTP endpoint."""

    def __init__(self, specification: SystemAdapterSpecification,
                 artifact: DatasetArtifact):
        if not isinstance(specification, SystemAdapterSpecification):
            raise TypeError('specification must be a SystemAdapterSpecification')
        if not isinstance(artifact, DatasetArtifact):
            raise TypeError('artifact must be a DatasetArtifact')
        if specification.system_id not in _SYSTEM_ADAPTERS:
            raise ValueError(f'unsupported SPARQL HTTP system: {specification.system_id}')
        if specification.configuration.kind != 'server':
            raise ValueError('SPARQL HTTP system kind must be server')
        if specification.configuration.representation != _REQUIRED_REPRESENTATION:
            raise ValueError('SPARQL HTTP systems require rdf/source')
        if artifact.representation != _REQUIRED_REPRESENTATION:
            raise ValueError('SPARQL HTTP dataset artifact must use rdf/source')
        self.specification = specification
        self.artifact = artifact

    @property
    @abc.abstractmethod
    def endpoint(self) -> str:
        """Return the SPARQL HTTP endpoint after startup."""

    @abc.abstractmethod
    def prepare(self) -> bool:
        """Prepare persistent system data from the RDF source artifact."""

    @abc.abstractmethod
    def start(self) -> bool:
        """Start the query server."""

    @abc.abstractmethod
    def ready(self) -> bool:
        """Return whether the query endpoint is ready."""

    @abc.abstractmethod
    def stop(self) -> bool:
        """Stop the query server."""

    @abc.abstractmethod
    def collect(self) -> bool:
        """Collect system logs and adapter metadata."""

    def run(self, execute: Callable[[str], bool]) -> SparqlHttpRunResult:
        """Run one lifecycle and perform best-effort cleanup after failure."""
        if not callable(execute):
            raise TypeError('execute must be callable')

        tracker = LifecycleTracker(self.specification)
        start_attempted = False
        stop_attempted = False
        collect_attempted = False

        operations: tuple[tuple[LifecycleOperation, Callable[[], bool]], ...] = (
            (LifecycleOperation.PREPARE, self.prepare),
            (LifecycleOperation.START, self.start),
            (LifecycleOperation.READY, self.ready),
            (LifecycleOperation.EXECUTE, lambda: execute(self.endpoint)),
            (LifecycleOperation.STOP, self.stop),
            (LifecycleOperation.COLLECT, self.collect),
        )

        for operation, action in operations:
            if operation == LifecycleOperation.START:
                start_attempted = True
            if operation == LifecycleOperation.STOP:
                stop_attempted = True
            if operation == LifecycleOperation.COLLECT:
                collect_attempted = True
            try:
                succeeded = action()
                if not isinstance(succeeded, bool):
                    raise TypeError(f'{operation.value} must return bool')
                if not succeeded:
                    raise RuntimeError(f'{operation.value} returned false')
                tracker.advance(operation)
            except Exception as error:
                if operation != LifecycleOperation.STOP and start_attempted:
                    stop_attempted = True
                    try:
                        self.stop()
                    except Exception:
                        pass
                if operation != LifecycleOperation.COLLECT:
                    collect_attempted = True
                    try:
                        self.collect()
                    except Exception:
                        pass
                tracker.fail()
                return SparqlHttpRunResult(
                    system_id=self.specification.system_id,
                    state=tracker.state,
                    history=tuple(tracker.history),
                    failed_operation=operation,
                    error=f'{type(error).__name__}: {error}',
                    stop_attempted=stop_attempted,
                    collect_attempted=collect_attempted,
                )

        return SparqlHttpRunResult(
            system_id=self.specification.system_id,
            state=tracker.state,
            history=tuple(tracker.history),
            stop_attempted=stop_attempted,
            collect_attempted=collect_attempted,
        )
