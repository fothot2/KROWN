#!/usr/bin/env python3
"""Generate a DBBench manifest through the public benchmark interface."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
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

IMPLEMENTATIONS = frozenset({'standalone', 'legacy', 'verify'})


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


def _semantic_manifest(manifest: dict) -> dict:
    """Return fields that must remain equal across implementations."""
    query_fields = (
        'query_id', 'query', 'query_sha256', 'query_parse_status',
        'query_parse_error', 'query_result_type', 'query_has_order_by',
        'query_has_limit', 'query_has_offset', 'query_limit', 'query_offset',
        'comparison_mode', 'comparison_warning', 'source_relative_path',
        'source_top_group', 'source_dataset', 'source_size_group',
        'source_file_name', 'source_query_index', 'source_line',
        'source_contains_limit',
    )
    return {
        'schema_version': manifest.get('schema_version'),
        'workload': manifest.get('workload'),
        'dataset': manifest.get('dataset'),
        'source_format': manifest.get('source_format'),
        'query_count': manifest.get('query_count'),
        'duplicate_query_content': manifest.get('duplicate_query_content'),
        'queries': [
            {field: query.get(field) for field in query_fields}
            for query in manifest.get('queries', [])
        ],
    }


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

    def _legacy(self, *, output: Path, workload: str, dataset: str,
                inventory_file: str | None, query_root: str | None,
                groups: tuple[str, ...], join_sizes: tuple[str, ...],
                query_id_file: str | None) -> dict:
        if inventory_file is not None:
            source_path = _input_file(self._shared_directory, inventory_file)
            records = load_inventory(source_path)
            source = {'kind': 'inventory', 'path': inventory_file,
                      'sha256': sha256_file(source_path)}
        else:
            source_path = _input_directory(self._shared_directory, query_root)
            records = build_inventory(source_path, dataset, groups, join_sizes)
            provenance = query_tree_provenance(
                source_path, dataset, groups, join_sizes
            )
            source = {'kind': 'query_tree', 'path': query_root,
                      'sha256': provenance['sha256'],
                      'files': provenance['files']}
        selected_ids = None
        selection_hash = None
        if query_id_file is not None:
            selection_path = _input_file(self._shared_directory, query_id_file)
            selected_ids = read_query_ids(selection_path)
            selection_hash = sha256_file(selection_path)
        records = select_query_records(records, selected_ids)
        manifest = convert_records(records, workload, dataset)
        source.update({
            'selected_query_count': len(records),
            'groups': sorted(groups), 'join_sizes': sorted(join_sizes),
            'query_id_file': query_id_file,
            'query_id_file_sha256': selection_hash,
        })
        manifest['source'] = source
        _atomic_json(output, manifest)
        return manifest

    def _standalone_command(self, benchmark_command: str,
                            benchmark_root: str | None) -> tuple[list[str], dict]:
        environment = os.environ.copy()
        if benchmark_root is not None:
            root = Path(benchmark_root).resolve()
            if not (root / 'benchmark_core/cli.py').is_file():
                raise FileNotFoundError(
                    f'benchmark_root does not contain benchmark_core: {root}'
                )
            current = environment.get('PYTHONPATH')
            environment['PYTHONPATH'] = (
                str(root) if not current
                else str(root) + os.pathsep + current
            )
            return [sys.executable, '-m', 'benchmark_core.cli'], environment
        executable = shutil.which(benchmark_command)
        if executable is None:
            raise FileNotFoundError(
                f'Benchmark command not found: {benchmark_command}; '
                'install the benchmarks package or provide benchmark_root'
            )
        return [executable], environment

    def _standalone(self, *, output: Path, workload: str, dataset: str,
                    inventory_file: str | None, query_root: str | None,
                    groups: tuple[str, ...], join_sizes: tuple[str, ...],
                    query_id_file: str | None, benchmark_command: str,
                    benchmark_root: str | None) -> dict:
        command, environment = self._standalone_command(
            benchmark_command, benchmark_root
        )
        command.extend([
            'dbbench', 'prepare', '--output', str(output),
            '--workload', workload, '--dataset', dataset,
            '--groups', *groups, '--join-sizes', *join_sizes,
        ])
        if inventory_file is not None:
            command.extend(['--inventory', str(_input_file(
                self._shared_directory, inventory_file
            ))])
        else:
            command.extend(['--query-root', str(_input_directory(
                self._shared_directory, query_root
            ))])
        if query_id_file is not None:
            command.extend(['--query-id-file', str(_input_file(
                self._shared_directory, query_id_file
            ))])
        completed = subprocess.run(
            command, cwd=benchmark_root, env=environment,
            capture_output=True, text=True, check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f'Benchmark command failed with exit code '
                f'{completed.returncode}: {message}'
            )
        with output.open('r', encoding='utf-8') as stream:
            return json.load(stream)

    def execute(self, output_file: str, workload: str, dataset: str,
                inventory_file: str | None = None,
                query_root: str | None = None,
                groups: Iterable[str] = ('TP', 'JOINS'),
                join_sizes: Iterable[str] = ('small', 'big'),
                query_id_file: str | None = None,
                implementation: str = 'standalone',
                benchmark_command: str = 'vortex-rdf-bench',
                benchmark_root: str | None = None) -> bool:
        """Generate and validate one manifest inside data/shared."""
        verification_output = None
        try:
            if implementation not in IMPLEMENTATIONS:
                raise ValueError(f'Unsupported implementation: {implementation}')
            if (inventory_file is None) == (query_root is None):
                raise ValueError(
                    'provide exactly one of inventory_file or query_root'
                )
            groups = tuple(groups)
            join_sizes = tuple(join_sizes)
            output = _resolve_shared_path(
                self._shared_directory, output_file, 'Output'
            )
            arguments = dict(
                output=output, workload=workload, dataset=dataset,
                inventory_file=inventory_file, query_root=query_root,
                groups=groups, join_sizes=join_sizes,
                query_id_file=query_id_file,
            )
            if implementation == 'legacy':
                manifest = self._legacy(**arguments)
            else:
                manifest = self._standalone(
                    **arguments, benchmark_command=benchmark_command,
                    benchmark_root=benchmark_root,
                )
            if implementation == 'verify':
                output.parent.mkdir(parents=True, exist_ok=True)
                descriptor, name = tempfile.mkstemp(
                    prefix=f'.{output.name}.legacy.', suffix='.json',
                    dir=output.parent,
                )
                os.close(descriptor)
                verification_output = Path(name)
                legacy_arguments = dict(arguments)
                legacy_arguments['output'] = verification_output
                legacy = self._legacy(**legacy_arguments)
                if _semantic_manifest(manifest) != _semantic_manifest(legacy):
                    raise ValueError(
                        'Standalone and legacy DBBench manifests differ'
                    )
            loaded = _load_query_manifest(str(output))
            if len(loaded.queries) != len(manifest.get('queries', [])):
                raise RuntimeError('generated manifest query count mismatch')
            self._logger.info(
                f'Wrote {len(loaded.queries)} DBBench queries to '
                f'"{output}" using {implementation}'
            )
            return True
        except Exception as error:
            self._logger.error(
                f'DBBench manifest generation failed: '
                f'{type(error).__name__}: {error}'
            )
            return False
        finally:
            if verification_output is not None:
                verification_output.unlink(missing_ok=True)
