#!/usr/bin/env python3
"""Keep one external JSON Lines query worker alive for one workload."""
from __future__ import annotations

import inspect
import json
import select
import subprocess
import time
import uuid
from pathlib import Path

from bench_executor.docker_cgroup_memory import (
    container_memory_current_bytes,
)
from bench_executor.rdf_query_benchmark import (
    _QueryOutcome,
    _QueryTimeoutError,
    _RdfQueryAdapter,
)


class PersistentJsonlQueryAdapter(_RdfQueryAdapter):
    """Exchange complete query results with one persistent external process."""

    def __init__(self, *, adapter, artifact: Path, timeout_s: float,
                 normalizer, startup_timeout_s: float = 120.0):
        if timeout_s <= 0 or startup_timeout_s <= 0:
            raise ValueError("worker timeouts must be positive")
        self._adapter = adapter
        self._artifact = Path(artifact)
        self._timeout_s = timeout_s
        self._startup_timeout_s = startup_timeout_s
        self._normalizer = normalizer
        identity = getattr(adapter, "worker_identity", None)
        self._worker_name = (identity() if callable(identity) else
                             "KROWN-Comunica-" + uuid.uuid4().hex[:12])
        # Preserve the validated private alias for existing callers and tests.
        self._container_name = self._worker_name
        self._process = None
        self._request_id = 0

    @property
    def memory_scope(self) -> str:
        value = getattr(self._adapter, 'memory_scope', None)
        return value if isinstance(value, str) else 'docker-container-cgroup-v2'

    @property
    def supports_load_temperature(self) -> bool:
        return True

    def current_rss_bytes(self) -> int | None:
        probe = getattr(self._adapter, "current_rss_bytes", None)
        if callable(probe):
            return probe(self._process, self._worker_name)
        return container_memory_current_bytes(self._worker_name)

    def _stderr(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return ""
        if process.poll() is None:
            return ""
        try:
            return process.stderr.read().strip()
        except (OSError, ValueError):
            return ""

    def _read_message(self, timeout_s: float, phase: str):
        process = self._process
        if process is None or process.stdout is None:
            raise RuntimeError("persistent worker is not open")
        ready, _, _ = select.select([process.stdout], [], [], timeout_s)
        if not ready:
            if process.poll() is not None:
                detail = self._stderr()
                raise RuntimeError(
                    f"persistent worker exited during {phase}"
                    + (f": {detail}" if detail else "")
                )
            return None
        line = process.stdout.readline()
        if line == "":
            detail = self._stderr()
            raise RuntimeError(
                f"persistent worker closed stdout during {phase}"
                + (f": {detail}" if detail else "")
            )
        try:
            return json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"persistent worker returned invalid JSON during {phase}: "
                f"{line.rstrip()!r}"
            ) from error

    def _force_stop(self):
        process = self._process
        self._process = None
        direct_stop = getattr(self._adapter, "force_stop_process", None)
        if callable(direct_stop):
            direct_stop(process, self._worker_name)
        else:
            subprocess.run(
                self._adapter.force_stop_command(self._worker_name),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def open(self):
        if self._process is not None:
            raise RuntimeError("persistent worker is already open")
        command = self._adapter.worker_command(
            host_artifact=self._artifact,
            container_name=self._worker_name,
        )
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            message = self._read_message(
                self._startup_timeout_s, "startup"
            )
            if message is None:
                raise RuntimeError("persistent worker startup timed out")
            contract = getattr(self._adapter, "ready_response_contract", None)
            if callable(contract):
                expected = contract()
                error_label = "verified persistent worker"
            elif hasattr(self._adapter, "container_artifact"):
                expected = {
                    "kind": "ready",
                    "protocol": "jsonl-v1",
                    "source_open": True,
                    "source_type": "hdt",
                    "source_boundary": "comunica-query-source-identify",
                    "source_reference": self._adapter.container_artifact,
                }
                error_label = "verified HDT worker"
            else:
                expected = {"kind": "ready", "protocol": "jsonl-v1"}
                error_label = "persistent worker"
            if message != expected:
                raise RuntimeError(
                    f"invalid {error_label} ready response: {message!r}"
                )
        except BaseException:
            self._force_stop()
            raise

    def prepare_for_attempt(self) -> bool:
        process = self._process
        if process is None or process.poll() is not None:
            self._force_stop()
            self.open()
            return True
        return False

    def execute(self, query):
        process = self._process
        if process is None:
            raise RuntimeError("persistent worker is not running")
        if process.poll() is not None:
            detail = self._stderr()
            self._force_stop()
            raise RuntimeError(
                "persistent worker is not running"
                + (f": {detail}" if detail else "")
            )
        request_id = self._request_id
        self._request_id += 1
        request = {
            "kind": "query",
            "request_id": request_id,
            "query": query,
        }
        ipc_started_ns = time.perf_counter_ns()
        try:
            process.stdin.write(
                json.dumps(request, separators=(",", ":")) + "\n"
            )
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            detail = self._stderr()
            self._force_stop()
            raise RuntimeError(
                "persistent worker rejected the query request"
                + (f": {detail}" if detail else "")
            ) from error
        try:
            message = self._read_message(self._timeout_s, "query")
        except BaseException:
            self._force_stop()
            raise
        if message is None:
            self._force_stop()
            raise _QueryTimeoutError(
                f"persistent worker query exceeded {self._timeout_s}s"
            )
        if (message.get("kind") != "result"
                or message.get("request_id") != request_id):
            self._force_stop()
            raise RuntimeError(
                f"invalid persistent worker response: {message!r}"
            )
        ipc_ns = time.perf_counter_ns() - ipc_started_ns
        if message.get("status") != "ok":
            raise RuntimeError(
                f"{message.get('error_type', 'WorkerError')}: "
                f"{message.get('error_message', 'unknown worker error')}"
            )
        correctness_started_ns = time.perf_counter_ns()
        normalized = self._normalizer(message["document"], query)
        correctness_ns = time.perf_counter_ns() - correctness_started_ns
        metadata = {
            key: value for key, value in normalized.items()
            if key not in {
                "result_count", "result_fingerprint", "normalized_result"
            }
        }
        metadata["measurement_boundary"] = (
            "complete-result-consumption"
        )
        return _QueryOutcome(
            result_count=normalized["result_count"],
            result_fingerprint=normalized["result_fingerprint"],
            elapsed_ns=ipc_ns + correctness_ns,
            metadata=metadata,
            stage_timings_ns={
                "ipc": ipc_ns,
                "correctness": correctness_ns,
            },
        )

    def close(self):
        process = self._process
        if process is None:
            return
        try:
            if process.poll() is None:
                process.stdin.write('{"kind":"shutdown"}\n')
                process.stdin.flush()
                process.wait(timeout=5)
            self._process = None
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            self._force_stop()
