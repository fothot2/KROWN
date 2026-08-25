#!/usr/bin/env python3
"""Run pinned QLever index and server containers through stock KROWN code."""
from __future__ import annotations

from pathlib import Path

import requests

from bench_executor.container import Container
from bench_executor.logger import Logger


class QLever:
    """Own QLever index construction and server execution."""

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
        indexer = Container(
            self._image, 'qlever_index', self._logger,
            volumes=[f'{self._data_path}:/qlever'],
        )
        return indexer.run_and_wait_for_exit(self._index_command)

    def start(self) -> bool:
        self._server = Container(
            self._image, 'qlever_server', self._logger,
            ports={str(self._port): str(self._port)},
            volumes=[f'{self._data_path}:/qlever'],
        )
        return self._server.run(self._server_command)

    def wait_until_ready(self) -> bool:
        if self._server is None or not self._server.started:
            return False
        try:
            response = requests.post(
                self.endpoint,
                data={'query': 'ASK { ?s ?p ?o }'},
                headers={'Accept': 'application/sparql-results+json'},
                timeout=5,
            )
            response.raise_for_status()
            response.json()
            return True
        except (requests.RequestException, ValueError):
            return False

    def stop(self) -> bool:
        if self._server is None:
            return True
        return self._server.stop()
