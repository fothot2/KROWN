#!/usr/bin/env python3
"""Prepare a benchmark manifest through one standalone adapter."""
from __future__ import annotations
import os, subprocess
from pathlib import Path
from bench_executor.logger import Logger
from bench_executor.rdf_workload_contract import load_rdf_workload_manifest
from bench_executor.standalone_benchmark import resolve_shared_path, standalone_command, temporary_output, commit_output, discard_output

class RdfManifestResource:
    def __init__(self, data_path: str, config_path: str, directory: str, verbose: bool):
        self._shared = os.path.join(os.path.abspath(data_path), 'shared')
        self._logger = Logger(__name__, directory, verbose)
    @property
    def name(self): return __name__
    @property
    def root_mount_directory(self): return __name__.lower()
    def execute(self, benchmark: str, query_root_env: str, output_file: str,
                workload: str, dataset: str,
                benchmark_command: str = 'vortex-rdf-bench',
                benchmark_root: str | None = None) -> bool:
        temporary = None
        try:
            source = os.environ.get(query_root_env)
            if not source: raise ValueError(f'Environment variable is not set: {query_root_env}')
            query_root = Path(source).expanduser().resolve()
            if not query_root.is_dir(): raise FileNotFoundError(f'Query root is not a directory: {query_root}')
            output = resolve_shared_path(self._shared, output_file, 'Output')
            temporary = temporary_output(output)
            command, environment = standalone_command(benchmark_command, benchmark_root)
            command.extend([benchmark, 'prepare', '--query-root', str(query_root),
                            '--output', str(temporary), '--workload', workload,
                            '--dataset', dataset])
            completed = subprocess.run(command, cwd=benchmark_root, env=environment,
                                       capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
            load_rdf_workload_manifest(temporary)
            commit_output(temporary, output); temporary = None
            self._logger.info(f'Wrote RDF workload manifest to "{output}"')
            return True
        except Exception as error:
            self._logger.error(f'RDF manifest preparation failed: {type(error).__name__}: {error}')
            return False
        finally: discard_output(temporary)
