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
    def execute(self, benchmark: str, input_env: str, input_option: str,
                output_file: str, workload: str, dataset: str,
                environment_options: dict[str, str] | None = None,
                adapter_options: dict[str, str] | None = None,
                benchmark_command: str = 'vortex-rdf-bench',
                benchmark_root: str | None = None) -> bool:
        temporary = None
        try:
            if not input_option.startswith('--'):
                raise ValueError('input_option must be a long CLI option')
            source_value = os.environ.get(input_env)
            if not source_value:
                raise ValueError(f'Environment variable is not set: {input_env}')
            source = Path(source_value).expanduser().resolve()
            if not source.exists():
                raise FileNotFoundError(f'Adapter input does not exist: {source}')
            output = resolve_shared_path(self._shared, output_file, 'Output')
            temporary = temporary_output(output)
            command, environment = standalone_command(benchmark_command, benchmark_root)
            command.extend([benchmark, 'prepare', input_option, str(source),
                            '--output', str(temporary), '--workload', workload,
                            '--dataset', dataset])
            for option, variable in (environment_options or {}).items():
                if not option.startswith('--'):
                    raise ValueError('environment option must be a long CLI option')
                value = os.environ.get(variable)
                if not value:
                    raise ValueError(f'Environment variable is not set: {variable}')
                resolved = Path(value).expanduser().resolve()
                if not resolved.exists():
                    raise FileNotFoundError(f'Adapter option input does not exist: {resolved}')
                command.extend([option, str(resolved)])
            for option, value in (adapter_options or {}).items():
                if not option.startswith('--') or not isinstance(value, str) or not value:
                    raise ValueError('adapter_options must map long CLI options to non-empty strings')
                command.extend([option, value])
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
