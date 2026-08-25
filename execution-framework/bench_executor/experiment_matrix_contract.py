#!/usr/bin/env python3
"""Define benchmark-neutral experiment matrix contracts."""
from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

SCHEMA_VERSION = 1
_ID = re.compile(r'^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*$')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_SYSTEM_KINDS = frozenset({'server', 'file-backed', 'embedded'})


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f'{field} must be a stable lowercase slash-separated identifier')
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'{field} must be a non-empty string without surrounding whitespace')
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f'{field} must be a lowercase SHA-256 value')
    return value


def _json_mapping(value: Mapping[str, Any] | None, field: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f'{field} must be an object with string keys')
    copied = dict(value)
    try:
        json.dumps(copied, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{field} must contain JSON values: {error}') from error
    return MappingProxyType(copied)


@dataclasses.dataclass(frozen=True)
class ArtifactFile:
    """Identify one file in a physical dataset representation."""
    path: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        path = _text(self.path, 'artifact file path')
        if path.startswith('/') or '..' in path.split('/'):
            raise ValueError('artifact file path must be relative and contained')
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError('artifact file size_bytes must be a non-negative integer')
        object.__setattr__(self, 'path', path)
        object.__setattr__(self, 'sha256', _sha256(self.sha256, 'artifact file sha256'))

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class DatasetArtifact:
    """Bind one logical RDF dataset to one physical representation."""
    benchmark: str
    dataset: str
    source_format: str
    source_size_bytes: int
    source_sha256: str
    representation: str
    files: tuple[ArtifactFile, ...]
    producer: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f'Unsupported dataset artifact schema_version: {self.schema_version}')
        object.__setattr__(self, 'benchmark', _identifier(self.benchmark, 'benchmark'))
        object.__setattr__(self, 'dataset', _identifier(self.dataset, 'dataset'))
        object.__setattr__(self, 'source_format', _identifier(self.source_format, 'source_format'))
        if not isinstance(self.source_size_bytes, int) or isinstance(self.source_size_bytes, bool) or self.source_size_bytes < 0:
            raise ValueError('source_size_bytes must be a non-negative integer')
        object.__setattr__(self, 'source_sha256', _sha256(self.source_sha256, 'source_sha256'))
        object.__setattr__(self, 'representation', _identifier(self.representation, 'representation'))
        if not isinstance(self.files, tuple) or not self.files:
            raise ValueError('files must be a non-empty tuple')
        if any(not isinstance(item, ArtifactFile) for item in self.files):
            raise TypeError('files must contain ArtifactFile values')
        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError('dataset artifact file paths must be unique')
        object.__setattr__(self, 'producer', _json_mapping(self.producer, 'producer'))

    @property
    def artifact_id(self) -> str:
        return f'{self.benchmark}/{self.dataset}/{self.representation}'

    def to_dict(self) -> dict[str, Any]:
        return {'schema_version': self.schema_version, 'benchmark': self.benchmark,
                'dataset': self.dataset, 'source_format': self.source_format,
                'source_size_bytes': self.source_size_bytes,
                'source_sha256': self.source_sha256,
                'representation': self.representation,
                'files': [item.to_dict() for item in self.files],
                'producer': dict(self.producer)}


@dataclasses.dataclass(frozen=True)
class SystemConfiguration:
    """Identify one query system and its reproducible configuration."""
    system: str
    configuration: str
    kind: str
    representation: str
    parameters: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f'Unsupported system configuration schema_version: {self.schema_version}')
        object.__setattr__(self, 'system', _identifier(self.system, 'system'))
        object.__setattr__(self, 'configuration', _identifier(self.configuration, 'configuration'))
        if self.kind not in _SYSTEM_KINDS:
            raise ValueError('kind must be server, file-backed, or embedded')
        object.__setattr__(self, 'representation', _identifier(self.representation, 'representation'))
        object.__setattr__(self, 'parameters', _json_mapping(self.parameters, 'parameters'))

    @property
    def system_id(self) -> str:
        return f'{self.system}/{self.configuration}'

    def to_dict(self) -> dict[str, Any]:
        return {'schema_version': self.schema_version, 'system': self.system,
                'configuration': self.configuration, 'kind': self.kind,
                'representation': self.representation,
                'parameters': dict(self.parameters)}


@dataclasses.dataclass(frozen=True)
class ExperimentSpecification:
    """Bind one workload, dataset artifact, system, and execution policy."""
    experiment_id: str
    benchmark: str
    dataset: str
    workload: str
    dataset_artifact: str
    system_configuration: str
    execution_policy: Mapping[str, Any]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f'Unsupported experiment schema_version: {self.schema_version}')
        for field in ('experiment_id', 'benchmark', 'dataset', 'workload',
                      'dataset_artifact', 'system_configuration'):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        object.__setattr__(self, 'execution_policy', _json_mapping(self.execution_policy, 'execution_policy'))

    def validate_bindings(self, artifact: DatasetArtifact,
                          system: SystemConfiguration) -> None:
        if (artifact.benchmark, artifact.dataset) != (self.benchmark, self.dataset):
            raise ValueError('experiment logical dataset differs from dataset artifact')
        if artifact.artifact_id != self.dataset_artifact:
            raise ValueError('experiment dataset_artifact identity mismatch')
        if system.system_id != self.system_configuration:
            raise ValueError('experiment system_configuration identity mismatch')
        if system.representation != artifact.representation:
            raise ValueError('system and dataset artifact representations differ')

    def to_dict(self) -> dict[str, Any]:
        return {'schema_version': self.schema_version,
                'experiment_id': self.experiment_id, 'benchmark': self.benchmark,
                'dataset': self.dataset, 'workload': self.workload,
                'dataset_artifact': self.dataset_artifact,
                'system_configuration': self.system_configuration,
                'execution_policy': dict(self.execution_policy)}
