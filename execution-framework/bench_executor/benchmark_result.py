#!/usr/bin/env python3
"""Validate and write canonical per-query benchmark records."""

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
QUERY_STATUSES = frozenset({
    'ok',
    'timeout',
    'unsupported',
    'engine_error',
    'connection_error',
    'parse_error',
    'result_error',
    'validation_mismatch',
    'skipped',
})
REQUIRED_FIELDS = frozenset({
    'schema_version',
    'experiment_id',
    'system',
    'dataset',
    'workload',
    'query_id',
    'phase',
    'run',
    'order',
    'status',
    'elapsed_ns',
})
_STRING_FIELDS = (
    'experiment_id',
    'system',
    'dataset',
    'workload',
    'query_id',
    'phase',
    'status',
)
_INTEGER_FIELDS = ('schema_version', 'run', 'order')


def sha256_bytes(value: bytes) -> str:
    """Return the SHA-256 value for bytes as lowercase hexadecimal text."""
    if not isinstance(value, bytes):
        raise TypeError('value must be bytes')
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    """Return the SHA-256 value for UTF-8 text."""
    if not isinstance(value, str):
        raise TypeError('value must be a string')
    return sha256_bytes(value.encode('utf-8'))


def sha256_file(path: os.PathLike[str] | str) -> str:
    """Return the SHA-256 value for one regular file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f'Not an existing file: {file_path}')

    digest = hashlib.sha256()
    with file_path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_query_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one query record and return an independent dictionary."""
    if not isinstance(record, Mapping):
        raise TypeError('record must be a mapping')

    missing = sorted(REQUIRED_FIELDS.difference(record))
    if missing:
        raise ValueError(f'Missing required fields: {", ".join(missing)}')

    validated = dict(record)

    for field in _STRING_FIELDS:
        value = validated[field]
        if not isinstance(value, str) or not value:
            raise ValueError(f'{field} must be a non-empty string')

    for field in _INTEGER_FIELDS:
        if not _is_integer(validated[field]):
            raise ValueError(f'{field} must be an integer')

    if validated['schema_version'] != SCHEMA_VERSION:
        raise ValueError(
            f'Unsupported schema_version: {validated["schema_version"]}'
        )
    if validated['run'] < 0:
        raise ValueError('run must be zero or greater')
    if validated['order'] < 0:
        raise ValueError('order must be zero or greater')
    if validated['status'] not in QUERY_STATUSES:
        raise ValueError(f'Unsupported status: {validated["status"]}')

    elapsed_ns = validated['elapsed_ns']
    if elapsed_ns is not None:
        if not _is_integer(elapsed_ns) or elapsed_ns < 0:
            raise ValueError(
                'elapsed_ns must be null or a non-negative integer'
            )
    elif validated['status'] not in {'skipped', 'unsupported'}:
        raise ValueError(
            'elapsed_ns can be null only for skipped or unsupported records'
        )

    result_count = validated.get('result_count')
    if result_count is not None:
        if not _is_integer(result_count) or result_count < 0:
            raise ValueError(
                'result_count must be null or a non-negative integer'
            )

    try:
        json.dumps(
            validated,
            ensure_ascii=False,
            allow_nan=False,
            separators=(',', ':'),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f'Record is not valid JSON: {error}') from error

    return validated


def write_query_records_atomic(
        path: os.PathLike[str] | str,
        records: Iterable[Mapping[str, Any]]) -> int:
    """Validate all records and replace one JSON Lines file atomically."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    count = 0

    try:
        with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                newline='\n',
                prefix=f'.{target.name}.',
                suffix='.tmp',
                dir=target.parent,
                delete=False) as stream:
            temporary_path = Path(stream.name)
            for record in records:
                validated = validate_query_record(record)
                json.dump(
                    validated,
                    stream,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(',', ':'),
                    sort_keys=True,
                )
                stream.write('\n')
                count += 1
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary_path, target)
        temporary_path = None
        return count
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
