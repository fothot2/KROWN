#!/usr/bin/env python3
"""Define the benchmark-neutral contract for RDF query workloads."""
from __future__ import annotations

import dataclasses
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

MANIFEST_SCHEMA_VERSION = 1
_RESERVED_MANIFEST_FIELDS = frozenset({
    'schema_version', 'workload', 'dataset', 'query_count', 'queries',
})
_RESERVED_QUERY_FIELDS = frozenset({'query_id', 'query'})
_COMPARISON_FIELDS = ('query_result_type', 'comparison_mode')


def _json_mapping(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    """Copy one mapping after it passes strict JSON validation."""
    copied = dict(value)
    if any(not isinstance(key, str) for key in copied):
        raise ValueError(f'{label} keys must be strings')
    try:
        json.dumps(copied, ensure_ascii=False, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{label} must contain valid JSON values: {error}') from error
    return copied


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f'{field} must be a non-empty string')
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError(f'{field} must be stable text without surrounding whitespace or control characters')
    return value


@dataclasses.dataclass(frozen=True)
class RdfQuerySpec:
    """Store one normalized RDF query and benchmark metadata."""

    query_id: str
    query: str
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        query_id = _required_text(self.query_id, 'query_id')
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError('query must be a non-empty string')
        metadata = _json_mapping(self.metadata, 'query metadata')
        overlap = sorted(_RESERVED_QUERY_FIELDS.intersection(metadata))
        if overlap:
            raise ValueError('query metadata replaces reserved fields: ' + ', '.join(overlap))
        for field in _COMPARISON_FIELDS:
            if field in metadata and (
                    not isinstance(metadata[field], str) or not metadata[field]):
                raise ValueError(f'{field} must be a non-empty string when present')
        object.__setattr__(self, 'query_id', query_id)
        object.__setattr__(self, 'metadata', MappingProxyType(metadata))

    def to_dict(self) -> dict[str, Any]:
        return {'query_id': self.query_id, 'query': self.query, **dict(self.metadata)}


@dataclasses.dataclass(frozen=True)
class RdfWorkloadManifest:
    """Store one normalized benchmark-neutral RDF workload manifest."""

    workload: str
    dataset: str
    queries: tuple[RdfQuerySpec, ...]
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)
    schema_version: int = MANIFEST_SCHEMA_VERSION
    declares_query_count: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f'Unsupported manifest schema_version: {self.schema_version}')
        workload = _required_text(self.workload, 'workload')
        dataset = _required_text(self.dataset, 'dataset')
        if not isinstance(self.queries, tuple) or not self.queries:
            raise ValueError('queries must be a non-empty tuple')
        if any(not isinstance(query, RdfQuerySpec) for query in self.queries):
            raise TypeError('queries must contain RdfQuerySpec values')
        query_ids = [query.query_id for query in self.queries]
        duplicate = next((item for item in query_ids if query_ids.count(item) > 1), None)
        if duplicate is not None:
            raise ValueError(f'Duplicate query_id: {duplicate}')
        metadata = _json_mapping(self.metadata, 'manifest metadata')
        overlap = sorted(_RESERVED_MANIFEST_FIELDS.intersection(metadata))
        if overlap:
            raise ValueError('manifest metadata replaces reserved fields: ' + ', '.join(overlap))
        object.__setattr__(self, 'workload', workload)
        object.__setattr__(self, 'dataset', dataset)
        object.__setattr__(self, 'metadata', MappingProxyType(metadata))

    @property
    def query_count(self) -> int:
        return len(self.queries)

    def to_dict(self) -> dict[str, Any]:
        manifest = {
            'schema_version': self.schema_version,
            'workload': self.workload,
            'dataset': self.dataset,
        }
        if self.declares_query_count:
            manifest['query_count'] = self.query_count
        manifest['queries'] = [query.to_dict() for query in self.queries]
        manifest.update(self.metadata)
        return manifest


def normalize_rdf_workload_manifest(
        source: Mapping[str, Any]) -> RdfWorkloadManifest:
    """Validate adapter output and return the common RDF workload form."""
    if not isinstance(source, Mapping):
        raise TypeError('manifest must be a mapping')
    data = _json_mapping(source, 'manifest')
    schema_version = data.get('schema_version')
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError('schema_version must be an integer')
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise ValueError(f'Unsupported manifest schema_version: {schema_version}')
    raw_queries = data.get('queries')
    if (not isinstance(raw_queries, Sequence)
            or isinstance(raw_queries, (str, bytes)) or not raw_queries):
        raise ValueError('queries must be a non-empty array')
    queries = []
    for index, raw_query in enumerate(raw_queries):
        if not isinstance(raw_query, Mapping):
            raise ValueError(f'query {index} must be an object')
        item = _json_mapping(raw_query, f'query {index}')
        queries.append(RdfQuerySpec(
            query_id=item.get('query_id'),
            query=item.get('query'),
            metadata={key: value for key, value in item.items()
                      if key not in _RESERVED_QUERY_FIELDS},
        ))
    declares_query_count = 'query_count' in data
    if declares_query_count:
        query_count = data['query_count']
        if (not isinstance(query_count, int) or isinstance(query_count, bool)
                or query_count != len(queries)):
            raise ValueError(
                f'query_count must equal the number of queries: {len(queries)}'
            )
    return RdfWorkloadManifest(
        workload=data.get('workload'),
        dataset=data.get('dataset'),
        queries=tuple(queries),
        metadata={key: value for key, value in data.items()
                  if key not in _RESERVED_MANIFEST_FIELDS},
        schema_version=schema_version,
        declares_query_count=declares_query_count,
    )


def load_rdf_workload_manifest(
        path: os.PathLike[str] | str) -> RdfWorkloadManifest:
    """Load one JSON file through the benchmark-neutral contract."""
    file_path = Path(path)
    with file_path.open('r', encoding='utf-8') as stream:
        source = json.load(stream)
    return normalize_rdf_workload_manifest(source)
