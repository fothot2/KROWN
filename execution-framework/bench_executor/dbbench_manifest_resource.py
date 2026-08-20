#!/usr/bin/env python3
"""Generate a reproducible DBBench manifest as a KROWN resource."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Iterable

from bench_executor.dbbench_manifest import (
    _atomic_json,
    build_inventory,
    convert_records,
    load_inventory,
    query_tree_provenance,
    read_query_ids,
    select_query_records,
    sha256_file,
)
from bench_executor.logger import Logger
from bench_executor.rdf_query_benchmark import _load_query_manifest


def _resolve_shared_path(shared: str, declared: str, kind: str) -> Path:
    if not isinstance(declared, str) or not declared:
        raise ValueError(f'{kind} path must be a non-empty string')
    if os.path.isabs(declared):
        raise ValueError(f'{kind} path must be relative')
    shared_path = Path(shared).resolve()
    path = (shared_path / declared).resolve()
    if os.path.commonpath((str(shared_path), str(path))) != str(shared_path):
        raise ValueError(f'{kind} path leaves the shared directory: {declared}')
    return path


def _input_file(shared: str, declared: str) -> Path:
    path = _resolve_shared_path(shared, declared, 'Input')
    if not path.is_file():
        raise FileNotFoundError(f'Input is not an existing file: {declared}')
    return path


def _input_directory(shared: str, declared: str) -> Path:
    path = _resolve_shared_path(shared, declared, 'Input')
    if not path.is_dir():
        raise FileNotFoundError(f'Input is not an existing directory: {declared}')
    return path


class DBBenchManifestResource:
    """Generate one validated DBBench query manifest."""

    def __init__(self, data_path: str, config_path: str, directory: str,
                 verbose: bool):
        self._shared_directory = os.path.join(os.path.abspath(data_path), 'shared')
        self._logger = Logger(__name__, directory, verbose)
        os.makedirs(self._shared_directory, exist_ok=True)

    @property
    def name(self):
        return __name__

    @property
    def root_mount_directory(self) -> str:
        return __name__.lower()

    def execute(self, output_file: str, workload: str, dataset: str,
                inventory_file: str | None = None,
                query_root: str | None = None,
                groups: Iterable[str] = ('TP', 'JOINS'),
                join_sizes: Iterable[str] = ('small', 'big'),
                query_id_file: str | None = None) -> bool:
        """Generate and validate one manifest inside data/shared."""
        try:
            if (inventory_file is None) == (query_root is None):
                raise ValueError(
                    'provide exactly one of inventory_file or query_root'
                )
            groups = tuple(groups)
            join_sizes = tuple(join_sizes)
            output = _resolve_shared_path(
                self._shared_directory, output_file, 'Output'
            )
            if inventory_file is not None:
                source_path = _input_file(self._shared_directory, inventory_file)
                records = load_inventory(source_path)
                source = {
                    'kind': 'inventory', 'path': inventory_file,
                    'sha256': sha256_file(source_path),
                }
            else:
                source_path = _input_directory(self._shared_directory, query_root)
                records = build_inventory(source_path, dataset, groups, join_sizes)
                provenance = query_tree_provenance(
                    source_path, dataset, groups, join_sizes
                )
                source = {
                    'kind': 'query_tree', 'path': query_root,
                    'sha256': provenance['sha256'],
                    'files': provenance['files'],
                }
            selection_hash = None
            selected_ids = None
            if query_id_file is not None:
                selection_path = _input_file(
                    self._shared_directory, query_id_file
                )
                selected_ids = read_query_ids(selection_path)
                selection_hash = sha256_file(selection_path)
            records = select_query_records(records, selected_ids)
            manifest = convert_records(records, workload, dataset)
            source.update({
                'selected_query_count': len(records),
                'groups': sorted(groups),
                'join_sizes': sorted(join_sizes),
                'query_id_file': query_id_file,
                'query_id_file_sha256': selection_hash,
            })
            manifest['source'] = source
            _atomic_json(output, manifest)
            loaded = _load_query_manifest(str(output))
            if len(loaded.queries) != len(records):
                raise RuntimeError('generated manifest query count mismatch')
            self._logger.info(
                f'Wrote {len(records)} DBBench queries to "{output}"'
            )
            return True
        except Exception as error:
            self._logger.error(
                f'DBBench manifest generation failed: '
                f'{type(error).__name__}: {error}'
            )
            return False
