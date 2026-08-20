#!/usr/bin/env python3
"""Generate a DBBench manifest through the public benchmark interface."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable

from bench_executor.logger import Logger
from bench_executor.standalone_benchmark import (
    input_directory, input_file, resolve_shared_path,
    standalone_command,
)
from bench_executor.rdf_query_benchmark import _load_query_manifest


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
                query_id_file: str | None = None,
                benchmark_command: str = 'vortex-rdf-bench',
                benchmark_root: str | None = None) -> bool:
        """Generate and validate one manifest inside data/shared."""
        try:
            if (inventory_file is None) == (query_root is None):
                raise ValueError(
                    'provide exactly one of inventory_file or query_root'
                )
            groups = tuple(groups)
            join_sizes = tuple(join_sizes)
            output = resolve_shared_path(
                self._shared_directory, output_file, 'Output'
            )
            command, environment = standalone_command(
                benchmark_command, benchmark_root
            )
            command.extend([
                'dbbench', 'prepare', '--output', str(output),
                '--workload', workload, '--dataset', dataset,
                '--groups', *groups, '--join-sizes', *join_sizes,
            ])
            if inventory_file is not None:
                command.extend(['--inventory', str(input_file(
                    self._shared_directory, inventory_file
                ))])
            else:
                command.extend(['--query-root', str(input_directory(
                    self._shared_directory, query_root
                ))])
            if query_id_file is not None:
                command.extend(['--query-id-file', str(input_file(
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
                manifest = json.load(stream)
            loaded = _load_query_manifest(str(output))
            if len(loaded.queries) != len(manifest.get('queries', [])):
                raise RuntimeError('generated manifest query count mismatch')
            self._logger.info(
                f'Wrote {len(loaded.queries)} DBBench queries to "{output}"'
            )
            return True
        except Exception as error:
            self._logger.error(
                f'DBBench manifest generation failed: '
                f'{type(error).__name__}: {error}'
            )
            return False
