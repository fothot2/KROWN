#!/usr/bin/env python3
"""Run pinned QLever index and server containers through stock KROWN code."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from time import monotonic, sleep

import requests

from bench_executor.container import Container
from bench_executor.docker_cgroup_memory import container_memory_current_bytes
from bench_executor.resource_memory_sampler import PhaseAwareMemorySampler
from bench_executor.logger import Logger
from bench_executor.resource_profile import QLEVER_CACHE_MEMORY, QLEVER_QUERY_MEMORY, QLEVER_SIMULTANEOUS_QUERIES, QLEVER_THREADS


READY_TIMEOUT_SECONDS = 120
READY_POLL_SECONDS = 1
READY_REQUEST_TIMEOUT_SECONDS = 5
READY_QUERY = 'ASK { ?s ?p ?o }'
_QLEVER_RUNTIME_FILE_SUFFIXES = (
    '.metrics-log.jsonl',
    '.resource-usage-log.tsv',
)


class QLever:
    """Own QLever index construction and server execution."""

    _CONTAINER_NAMES = ("qlever_index", "qlever_server")

    @classmethod
    def cleanup_containers(cls) -> bool:
        """Remove stopped or running containers from earlier QLever attempts."""
        result = subprocess.run(
            ["docker", "rm", "--force", *cls._CONTAINER_NAMES],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode in (0, 1)

    def __init__(self, data_path: str, directory: str, verbose: bool,
                 image: str, index_command: str, server_command: str,
                 port: int = 7001, index_path: str | None = None):
        if not isinstance(image, str) or not image.strip() or ':' not in image:
            raise ValueError('image must be a non-empty pinned image reference')
        if image.rsplit(':', 1)[1] == 'latest':
            raise ValueError('image must not use the latest tag')
        for value, name in ((index_command, 'index_command'),
                            (server_command, 'server_command')):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{name} must be a non-empty string')
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError('port must be an integer from 1 to 65535')
        self._data_path = Path(data_path).resolve()
        default_index = self._data_path / 'qlever-index'
        selected_index = (
            default_index if index_path is None
            else Path(index_path).expanduser()
        )
        if not selected_index.is_absolute():
            raise ValueError('index_path must be absolute')
        self._index_path = selected_index.resolve()
        self._index_path.mkdir(parents=True, exist_ok=True)
        self._directory = Path(directory).resolve()
        self._logger = Logger(__name__, str(self._directory), verbose)
        self._image = image
        self._index_command = index_command
        tuning = (
            f' --memory-max-size {QLEVER_QUERY_MEMORY}'
            f' --cache-max-size {QLEVER_CACHE_MEMORY}'
            f' -j {QLEVER_SIMULTANEOUS_QUERIES}'
        )
        self._server_command = server_command if '--memory-max-size' in server_command else server_command.rstrip(" '") + tuning + ("'" if server_command.rstrip().endswith("'") else "")
        self._port = port
        self._server: Container | None = None
        self.build_metrics = None
        self.representation_size = None

    @property
    def endpoint(self) -> str:
        return f'http://localhost:{self._port}'

    def build_index(self) -> bool:
        if not self.cleanup_containers():
            self._logger.error('Failed to remove stale QLever containers')
            return False
        indexer = Container(
            self._image, 'qlever_index', self._logger,
            environment={'UID': str(os.getuid()), 'GID': str(os.getgid())},
            volumes=[
                f'{self._data_path}:/data',
                f'{getattr(self, '_index_path', self._data_path / 'qlever-index')}:/data/qlever-index',
            ],
            working_directory='/data',
        )
        started_ns = time.perf_counter_ns()
        sampler = None
        returncode = None
        try:
            if not indexer.run(self._index_command):
                return False
            sampler = PhaseAwareMemorySampler(
                lambda: container_memory_current_bytes('qlever_index'),
                'docker-container-cgroup-v2',
            )
            sampler.start()
            returncode = indexer._docker.wait(indexer._container_id)
            logs = indexer._docker.logs(indexer._container_id)
            for line in logs or []:
                (self._logger.debug if returncode == 0 else self._logger.error)(line)
            memory = sampler.stop()
            sampler = None
            elapsed_ns = time.perf_counter_ns() - started_ns
            self.build_metrics = {
                'schema': 'rdf-representation-build-metrics-v1',
                'status': 'ok' if returncode == 0 else 'failed',
                'clock': 'perf_counter_ns',
                'elapsed_ns': elapsed_ns,
                'returncode': returncode,
                'memory': {key: memory[key] for key in (
                    'scope', 'unit', 'sampling_interval_ms', 'sample_count',
                    'sample_errors', 'peak_rss_bytes',
                )},
            }
            if returncode != 0:
                return False
            self.representation_size = self._index_size()
            return True
        finally:
            if sampler is not None:
                sampler.stop()
            self.cleanup_containers()

    def _index_size(self) -> dict[str, object]:
        root = getattr(
            self, '_index_path', self._data_path / 'qlever-index'
        ).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f'QLever index directory is missing: {root}')
        logical = allocated = files = directories = excluded_files = 0
        for path in [root, *root.rglob('*')]:
            if path.is_symlink():
                raise ValueError(f'QLever index contains a symlink: {path}')
            info = path.stat(follow_symlinks=False)
            if path.is_file():
                if path.name.endswith(_QLEVER_RUNTIME_FILE_SUFFIXES):
                    excluded_files += 1
                    continue
                files += 1
                logical += info.st_size
                allocated += info.st_blocks * 512
            elif path.is_dir():
                directories += 1
            else:
                raise ValueError(f'Unsupported QLever index entry: {path}')
        return {
            'schema': 'rdf-representation-size-v1',
            'boundary': 'adapter-declared-paths',
            'paths': [str(root)],
            'exclusion_policy': {
                'kind': 'filename-suffixes',
                'suffixes': list(_QLEVER_RUNTIME_FILE_SUFFIXES),
                'excluded_file_count': excluded_files,
            },
            'logical_bytes': logical,
            'allocated_bytes': allocated,
            'file_count': files,
            'directory_count': directories,
        }

    def start(self) -> bool:
        self._server = Container(
            self._image, 'qlever_server', self._logger,
            ports={str(self._port): str(self._port)},
            environment={'UID': str(os.getuid()), 'GID': str(os.getgid())},
            volumes=[
                f'{self._data_path}:/data',
                f'{getattr(self, '_index_path', self._data_path / 'qlever-index')}:/data/qlever-index',
            ],
            working_directory='/data',
        )
        return self._server.run(self._server_command)

    def wait_until_ready(self) -> bool:
        """Wait for one successful SPARQL response within a fixed bound."""
        if self._server is None or not self._server.started:
            return False
        deadline = monotonic() + READY_TIMEOUT_SECONDS
        while monotonic() < deadline:
            try:
                response = requests.post(
                    self.endpoint,
                    data={'query': READY_QUERY},
                    headers={'Accept': 'application/sparql-results+json'},
                    timeout=READY_REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                document = response.json()
                if isinstance(document, dict) and 'boolean' in document:
                    return True
            except (requests.RequestException, ValueError):
                pass
            sleep(READY_POLL_SECONDS)
        self._logger.error(
            f'Waiting for QLever HTTP readiness timed out after '
            f'{READY_TIMEOUT_SECONDS} seconds'
        )
        return False

    def stop(self) -> bool:
        success = True
        if self._server is not None:
            success = self._server.stop()
        cleanup = self.cleanup_containers()
        return success and cleanup
