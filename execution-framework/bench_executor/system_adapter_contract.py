#!/usr/bin/env python3
"""Define the benchmark-neutral lifecycle contract for query systems."""
from __future__ import annotations

import dataclasses
import enum
from collections.abc import Iterable
from types import MappingProxyType
from typing import Any, Mapping

from bench_executor.experiment_matrix_contract import SystemConfiguration


class LifecycleOperation(enum.StrEnum):
    """Name one operation that a query-system adapter can perform."""

    PREPARE = 'prepare'
    START = 'start'
    READY = 'ready'
    EXECUTE = 'execute'
    STOP = 'stop'
    COLLECT = 'collect'


class LifecycleState(enum.StrEnum):
    """Describe the current state of one system-adapter lifecycle."""

    CREATED = 'created'
    PREPARED = 'prepared'
    STARTED = 'started'
    READY = 'ready'
    EXECUTED = 'executed'
    STOPPED = 'stopped'
    COLLECTED = 'collected'
    FAILED = 'failed'


_KIND_OPERATIONS = {
    'server': frozenset(LifecycleOperation),
    'file-backed': frozenset({
        LifecycleOperation.PREPARE,
        LifecycleOperation.EXECUTE,
        LifecycleOperation.COLLECT,
    }),
    'embedded': frozenset({
        LifecycleOperation.PREPARE,
        LifecycleOperation.EXECUTE,
        LifecycleOperation.COLLECT,
    }),
}

_KIND_TRANSITIONS = {
    'server': {
        LifecycleState.CREATED: (LifecycleOperation.PREPARE, LifecycleState.PREPARED),
        LifecycleState.PREPARED: (LifecycleOperation.START, LifecycleState.STARTED),
        LifecycleState.STARTED: (LifecycleOperation.READY, LifecycleState.READY),
        LifecycleState.READY: (LifecycleOperation.EXECUTE, LifecycleState.EXECUTED),
        LifecycleState.EXECUTED: (LifecycleOperation.STOP, LifecycleState.STOPPED),
        LifecycleState.STOPPED: (LifecycleOperation.COLLECT, LifecycleState.COLLECTED),
    },
    'file-backed': {
        LifecycleState.CREATED: (LifecycleOperation.PREPARE, LifecycleState.PREPARED),
        LifecycleState.PREPARED: (LifecycleOperation.EXECUTE, LifecycleState.EXECUTED),
        LifecycleState.EXECUTED: (LifecycleOperation.COLLECT, LifecycleState.COLLECTED),
    },
    'embedded': {
        LifecycleState.CREATED: (LifecycleOperation.PREPARE, LifecycleState.PREPARED),
        LifecycleState.PREPARED: (LifecycleOperation.EXECUTE, LifecycleState.EXECUTED),
        LifecycleState.EXECUTED: (LifecycleOperation.COLLECT, LifecycleState.COLLECTED),
    },
}


def _json_mapping(value: Mapping[str, Any] | None, field: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f'{field} must be an object with string keys')
    return MappingProxyType(dict(value))


@dataclasses.dataclass(frozen=True)
class LifecycleCapabilities:
    """Declare and validate lifecycle operations for one system kind."""

    kind: str
    operations: frozenset[LifecycleOperation]

    def __post_init__(self) -> None:
        if self.kind not in _KIND_OPERATIONS:
            raise ValueError('kind must be server, file-backed, or embedded')
        if not isinstance(self.operations, frozenset):
            raise TypeError('operations must be a frozenset')
        if any(not isinstance(item, LifecycleOperation) for item in self.operations):
            raise TypeError('operations must contain LifecycleOperation values')
        required = _KIND_OPERATIONS[self.kind]
        if self.operations != required:
            missing = sorted(item.value for item in required - self.operations)
            extra = sorted(item.value for item in self.operations - required)
            raise ValueError(
                f'{self.kind} lifecycle operations differ from the contract; '
                f'missing={missing}, extra={extra}'
            )

    @classmethod
    def for_kind(cls, kind: str) -> 'LifecycleCapabilities':
        """Return the canonical capabilities for one system kind."""
        if kind not in _KIND_OPERATIONS:
            raise ValueError('kind must be server, file-backed, or embedded')
        return cls(kind=kind, operations=_KIND_OPERATIONS[kind])

    def supports(self, operation: LifecycleOperation) -> bool:
        """Return whether this lifecycle includes one operation."""
        if not isinstance(operation, LifecycleOperation):
            raise TypeError('operation must be a LifecycleOperation')
        return operation in self.operations


@dataclasses.dataclass(frozen=True)
class SystemAdapterSpecification:
    """Bind one system configuration to its lifecycle and adapter metadata."""

    configuration: SystemConfiguration
    adapter: str
    capabilities: LifecycleCapabilities
    parameters: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.configuration, SystemConfiguration):
            raise TypeError('configuration must be a SystemConfiguration')
        if not isinstance(self.adapter, str) or not self.adapter or self.adapter != self.adapter.strip():
            raise ValueError('adapter must be a non-empty stable string')
        if not isinstance(self.capabilities, LifecycleCapabilities):
            raise TypeError('capabilities must be LifecycleCapabilities')
        if self.capabilities.kind != self.configuration.kind:
            raise ValueError('adapter lifecycle kind differs from system configuration kind')
        object.__setattr__(self, 'parameters', _json_mapping(self.parameters, 'parameters'))

    @property
    def system_id(self) -> str:
        return self.configuration.system_id


@dataclasses.dataclass
class LifecycleTracker:
    """Validate operation order without starting or executing a real system."""

    specification: SystemAdapterSpecification
    state: LifecycleState = LifecycleState.CREATED
    history: list[LifecycleOperation] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.specification, SystemAdapterSpecification):
            raise TypeError('specification must be a SystemAdapterSpecification')
        if not isinstance(self.state, LifecycleState):
            raise TypeError('state must be a LifecycleState')
        if not isinstance(self.history, list) or self.history:
            raise ValueError('history must start as an empty list')

    @property
    def complete(self) -> bool:
        return self.state == LifecycleState.COLLECTED

    def advance(self, operation: LifecycleOperation) -> LifecycleState:
        """Apply one valid lifecycle operation and return the new state."""
        if not isinstance(operation, LifecycleOperation):
            raise TypeError('operation must be a LifecycleOperation')
        if self.state == LifecycleState.FAILED:
            raise ValueError('failed lifecycle cannot advance')
        transition = _KIND_TRANSITIONS[self.specification.configuration.kind].get(self.state)
        if transition is None:
            raise ValueError(f'lifecycle is terminal in state {self.state.value}')
        expected, target = transition
        if operation != expected:
            raise ValueError(
                f'invalid lifecycle operation {operation.value} from {self.state.value}; '
                f'expected {expected.value}'
            )
        self.history.append(operation)
        self.state = target
        return self.state

    def fail(self) -> LifecycleState:
        """Move a non-terminal lifecycle into the failed state."""
        if self.complete:
            raise ValueError('completed lifecycle cannot fail')
        self.state = LifecycleState.FAILED
        return self.state

    def run_plan(self, operations: Iterable[LifecycleOperation]) -> LifecycleState:
        """Validate a complete operation sequence."""
        for operation in operations:
            self.advance(operation)
        if not self.complete:
            raise ValueError(f'incomplete lifecycle ended in state {self.state.value}')
        return self.state
