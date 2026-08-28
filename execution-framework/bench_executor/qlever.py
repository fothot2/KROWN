#!/usr/bin/env python3
"""Run pinned QLever index and server containers through stock KROWN code."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
from time import monotonic, sleep

import requests

from bench_executor.container import Container
from bench_executor.logger import Logger


READY_TIMEOUT_SECONDS = 120
READY_POLL_SECONDS = 1
READY_REQUEST_TIMEOUT_SECONDS = 5
READY_QUERY = 'ASK { ?s ?p ?o }'


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
                 port: int = 7001):
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
        self._directory = Path(directory).resolve()
        self._logger = Logger(__name__, str(self._directory), verbose)
        self._image = image
        self._index_command = index_command
        self._server_command = server_command
        self._port = port
        self._server: Container | None = None

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
            volumes=[f'{self._data_path}:/data'],
            working_directory='/data',
        )
        try:
            return indexer.run_and_wait_for_exit(self._index_command)
        finally:
            self.cleanup_containers()

    def start(self) -> bool:
        self._server = Container(
            self._image, 'qlever_server', self._logger,
            ports={str(self._port): str(self._port)},
            environment={'UID': str(os.getuid()), 'GID': str(os.getgid())},
            volumes=[f'{self._data_path}:/data'],
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
