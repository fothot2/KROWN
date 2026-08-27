#!/usr/bin/env python3
"""Keep one external JSON Lines query worker alive for one workload."""
from __future__ import annotations

import json
import select
import subprocess
import uuid
from pathlib import Path

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
        self._container_name = "KROWN-Comunica-" + uuid.uuid4().hex[:12]
        self._process = None
        self._request_id = 0

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
        subprocess.run(
            self._adapter.force_stop_command(self._container_name),
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
            container_name=self._container_name,
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
            if message != {"kind": "ready", "protocol": "jsonl-v1"}:
                raise RuntimeError(
                    f"invalid persistent worker ready response: {message!r}"
                )
        except BaseException:
            self._force_stop()
            raise

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
        if message.get("status") != "ok":
            raise RuntimeError(
                f"{message.get('error_type', 'WorkerError')}: "
                f"{message.get('error_message', 'unknown worker error')}"
            )
        normalized = self._normalizer(message["document"], query)
        metadata = {
            key: value for key, value in normalized.items()
            if key not in {
                "result_count", "result_fingerprint", "normalized_result"
            }
        }
        metadata["measurement_boundary"] = (
            "persistent-worker-complete-response"
        )
        return _QueryOutcome(
            result_count=normalized["result_count"],
            result_fingerprint=normalized["result_fingerprint"],
            metadata=metadata,
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
