#!/usr/bin/env python3
"Oxigraph container lifecycle support."

from __future__ import annotations

import os
import shutil
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
        store_path: str | None = None,
    ) -> None:
        if backend not in {"memory", "rocksdb"}:
            raise ValueError("backend must be 'memory' or 'rocksdb'")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")

        self._data_path = Path(data_path).resolve()
        self._backend = backend
        self._port = port
        self._logger = Logger(__name__, directory, verbose)
        timeout_text = os.environ.get("KROWN_OXIGRAPH_BUILD_TIMEOUT_S", "10800")
        try:
            self._build_timeout_s = float(timeout_text)
        except ValueError as error:
            raise ValueError(
                "KROWN_OXIGRAPH_BUILD_TIMEOUT_S must be numeric"
            ) from error
        if self._build_timeout_s <= 0:
            raise ValueError(
                "KROWN_OXIGRAPH_BUILD_TIMEOUT_S must be greater than zero"
            )
        self.last_load_error = None

        shared = self._data_path / "shared"
        shared.mkdir(parents=True, exist_ok=True)
        volumes = [f"{shared}:/data:ro"]

        command = f"serve --bind 0.0.0.0:{port}"
        self._store_path = None
        if backend == "rocksdb":
            store = (
                self._data_path / "oxigraph-rocksdb"
                if store_path is None
                else Path(store_path).expanduser().resolve()
            )
            store.mkdir(parents=True, exist_ok=True)
            self._store_path = store
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

    def reset_store(self) -> bool:
        """Create an empty RocksDB directory before one measured load."""
        if self._backend != "rocksdb":
            return True
        data_root = self._data_path.resolve()
        store = getattr(
            self,
            "_store_path",
            self._data_path / "oxigraph-rocksdb",
        )
        if store.is_symlink():
            self._logger.error("Oxigraph RocksDB path is a symbolic link")
            return False
        resolved_store = store.resolve()
        try:
            resolved_store.relative_to(data_root)
        except ValueError:
            self._logger.error("Oxigraph RocksDB path leaves the data directory")
            return False
        if resolved_store.exists() and not resolved_store.is_dir():
            self._logger.error("Oxigraph RocksDB path is not a directory")
            return False
        if resolved_store.is_dir():
            for path in resolved_store.rglob("*"):
                if path.is_symlink():
                    self._logger.error(
                        f"Oxigraph RocksDB store contains a symbolic link: {path}"
                    )
                    return False
            try:
                shutil.rmtree(resolved_store)
            except OSError as error:
                self._logger.error(f"Cannot reset Oxigraph RocksDB store: {error}")
                return False
        try:
            resolved_store.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            self._logger.error(f"Cannot create Oxigraph RocksDB store: {error}")
            return False
        return True

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

    def load_rocksdb_file(self, relative_path: str) -> bool:
        """Load one staged N-Triples file with the dedicated CLI loader."""
        if self._backend != "rocksdb":
            raise RuntimeError("CLI loading requires the RocksDB backend")
        shared = (self._data_path / "shared").resolve()
        source = (shared / relative_path).resolve()
        try:
            source.relative_to(shared)
        except ValueError:
            self.last_load_error = {
                "error_type": "ValueError",
                "error_message": "Oxigraph source path leaves data/shared",
                "build_timeout_s": self._build_timeout_s,
            }
            return False
        if not source.is_file():
            self.last_load_error = {
                "error_type": "FileNotFoundError",
                "error_message": f"Oxigraph source file is missing: {source}",
                "build_timeout_s": self._build_timeout_s,
            }
            return False

        relative = source.relative_to(shared).as_posix()
        command = (
            "load --location /store "
            f"--file /data/{relative} "
            "--format nt --non-atomic"
        )
        self.last_load_error = None
        if self.run_and_wait_for_exit(command):
            return True
        self.last_load_error = {
            "error_type": "OxigraphCliLoadError",
            "error_message": "Oxigraph CLI loader exited unsuccessfully",
            "build_timeout_s": self._build_timeout_s,
            "command": command,
        }
        return False

    def load(self, relative_path: str) -> bool:
        """Upload N-Triples and retain structured failure diagnostics."""
        self.last_load_error = None
        shared = (self._data_path / "shared").resolve()
        source = (shared / relative_path).resolve()
        try:
            source.relative_to(shared)
        except ValueError:
            self.last_load_error = {
                "error_type": "ValueError",
                "error_message": "Oxigraph source path leaves data/shared",
                "build_timeout_s": self._build_timeout_s,
            }
            return False
        if not source.is_file():
            self.last_load_error = {
                "error_type": "FileNotFoundError",
                "error_message": f"Oxigraph source file is missing: {source}",
                "build_timeout_s": self._build_timeout_s,
            }
            return False

        response = None
        try:
            with source.open("rb") as stream:
                response = requests.post(
                    f"http://localhost:{self._port}/store?default",
                    data=stream,
                    headers={"Content-Type": "application/n-triples"},
                    timeout=(30, self._build_timeout_s),
                )
            response.raise_for_status()
            return True
        except requests.RequestException as error:
            response = getattr(error, "response", None) or response
            diagnostic = {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "build_timeout_s": self._build_timeout_s,
            }
            if response is not None:
                diagnostic["http_status"] = response.status_code
                diagnostic["response_preview"] = response.text[:2000]
            self.last_load_error = diagnostic
            self._logger.error(
                "Oxigraph RDF import failed: " + str(diagnostic)
            )
            return False

    def count_triples(self) -> int | None:
        """Return the exact default-graph cardinality when the server is ready."""
        query = "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"
        try:
            response = requests.post(
                self.endpoint,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
                timeout=120,
            )
            response.raise_for_status()
            bindings = response.json()["results"]["bindings"]
            if len(bindings) != 1:
                return None
            return int(bindings[0]["count"]["value"])
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return None
