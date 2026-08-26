#!/usr/bin/env python3
"Oxigraph container lifecycle support."

from __future__ import annotations

from pathlib import Path
from time import monotonic, sleep

import requests

from bench_executor.container import Container
from bench_executor.logger import Logger

OXIGRAPH_VERSION = "0.5.9"
OXIGRAPH_IMAGE = f"dtaikg/oxigraph:{OXIGRAPH_VERSION}"


class Oxigraph(Container):
    "Own one Oxigraph server process."

    def __init__(
        self,
        data_path: str,
        directory: str,
        verbose: bool,
        backend: str,
        port: int = 7878,
    ) -> None:
        if backend not in {"memory", "rocksdb"}:
            raise ValueError("backend must be 'memory' or 'rocksdb'")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")

        self._data_path = Path(data_path).resolve()
        self._backend = backend
        self._port = port
        self._logger = Logger(__name__, directory, verbose)

        shared = self._data_path / "shared"
        shared.mkdir(parents=True, exist_ok=True)
        volumes = [f"{shared}:/data:ro"]

        command = f"serve --bind 0.0.0.0:{port}"
        if backend == "rocksdb":
            store = self._data_path / "oxigraph-rocksdb"
            store.mkdir(parents=True, exist_ok=True)
            volumes.append(f"{store}:/store")
            command += " --location /store"

        super().__init__(
            OXIGRAPH_IMAGE,
            f"Oxigraph-{backend}",
            self._logger,
            ports={str(port): str(port)},
            volumes=volumes,
        )
        self._command = command

    @property
    def endpoint(self) -> str:
        return f"http://localhost:{self._port}/query"

    def start_server(self) -> bool:
        if not self.run(self._command):
            return False
        deadline = monotonic() + 600
        while monotonic() < deadline:
            if self.is_ready():
                return True
            sleep(1)
        return False

    def is_ready(self) -> bool:
        try:
            response = requests.post(
                self.endpoint,
                data={"query": "ASK { ?s ?p ?o }"},
                headers={"Accept": "application/sparql-results+json"},
                timeout=30,
            )
            response.raise_for_status()
            response.json()
            return True
        except (requests.RequestException, ValueError):
            return False

    def load(self, relative_path: str) -> bool:
        shared = (self._data_path / "shared").resolve()
        source = (shared / relative_path).resolve()
        try:
            source.relative_to(shared)
        except ValueError:
            return False
        if not source.is_file():
            return False

        try:
            with source.open("rb") as stream:
                response = requests.post(
                    f"http://localhost:{self._port}/store?default",
                    data=stream,
                    headers={"Content-Type": "application/n-triples"},
                    timeout=600,
                )
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False
