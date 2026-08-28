#!/usr/bin/env python3
"""Focused tests for QLever 0.6.0 command and cleanup semantics."""
from __future__ import annotations

import os
from pathlib import Path
import requests
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.benchmark_result import sha256_file
from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
from bench_executor.qlever import (
    QLever, READY_POLL_SECONDS, READY_QUERY,
    READY_REQUEST_TIMEOUT_SECONDS, READY_TIMEOUT_SECONDS,
)
from bench_executor.qlever_system_adapter import QLeverSystemAdapter


class QLeverRuntimeCommandTests(unittest.TestCase):
    @staticmethod
    def artifact(source: Path, relative: str) -> DatasetArtifact:
        return DatasetArtifact(
            benchmark="bsbm",
            dataset="explore-1k",
            source_format="ntriples",
            source_size_bytes=source.stat().st_size,
            source_sha256=sha256_file(source),
            representation="rdf/source",
            files=(ArtifactFile(
                path=relative,
                size_bytes=source.stat().st_size,
                sha256=sha256_file(source),
            ),),
        )

    def test_default_commands_use_entrypoint_batch_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            source = data / "shared/rdf-matrix-artifacts/rdf--source--0.nt"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"<s> <p> <o> .\n")
            with patch("bench_executor.qlever_system_adapter.QLever") as runtime:
                QLeverSystemAdapter(
                    self.artifact(
                        source, "rdf-matrix-artifacts/rdf--source--0.nt"
                    ),
                    str(data),
                    directory,
                )
        arguments = runtime.call_args.args
        self.assertEqual(arguments[3], "kgconstruct/qlever:v0.6.0")
        self.assertTrue(arguments[4].startswith("-c '"))
        self.assertIn("mkdir -p /data/qlever-index &&", arguments[4])
        self.assertIn("/qlever/qlever-index --index-basename", arguments[4])
        self.assertIn("--file-format nt", arguments[4])
        self.assertTrue(arguments[5].startswith("-c 'exec "))
        self.assertIn("/qlever/qlever-server --index-basename", arguments[5])
        self.assertIn("--port 7001", arguments[5])

    def test_explicit_commands_remain_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            source = data / "shared/dataset.nt"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"<s> <p> <o> .\n")
            with patch("bench_executor.qlever_system_adapter.QLever") as runtime:
                QLeverSystemAdapter(
                    self.artifact(source, "dataset.nt"),
                    str(data), directory,
                    index_command="custom-index",
                    server_command="custom-server",
                )
        self.assertEqual(runtime.call_args.args[4:6], ("custom-index", "custom-server"))

    def test_index_cleanup_runs_before_and_after_attempt(self):
        qlever = QLever.__new__(QLever)
        qlever._image = "kgconstruct/qlever:v0.6.0"
        qlever._data_path = Path("/tmp/data")
        qlever._logger = MagicMock()
        qlever._index_command = "-c 'index'"
        indexer = MagicMock()
        indexer.run_and_wait_for_exit.return_value = False
        with patch.object(QLever, "cleanup_containers", side_effect=[True, True]) as cleanup, patch(
            "bench_executor.qlever.Container", return_value=indexer
        ):
            self.assertFalse(qlever.build_index())
        self.assertEqual(cleanup.call_count, 2)

    def test_cleanup_removes_both_stable_names(self):
        with patch("bench_executor.qlever.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertTrue(QLever.cleanup_containers())
        self.assertEqual(
            run.call_args.args[0],
            ["docker", "rm", "--force", "qlever_index", "qlever_server"],
        )
        self.assertFalse(run.call_args.kwargs["check"])


    def test_qlever_containers_use_data_workdir_and_host_identity(self):
        qlever = QLever.__new__(QLever)
        qlever._image = "kgconstruct/qlever:v0.6.0"
        qlever._data_path = Path("/tmp/data")
        qlever._directory = Path("/tmp")
        qlever._logger = MagicMock()
        qlever._index_command = "-c 'index'"
        qlever._server_command = "-c 'server'"
        qlever._port = 7001
        qlever._server = None
        indexer = MagicMock()
        indexer.run_and_wait_for_exit.return_value = True
        server = MagicMock()
        server.run.return_value = True
        with patch.object(QLever, "cleanup_containers", return_value=True), patch(
            "bench_executor.qlever.Container", side_effect=[indexer, server]
        ) as container, patch("bench_executor.qlever.os.getuid", return_value=20001), patch(
            "bench_executor.qlever.os.getgid", return_value=6157
        ):
            self.assertTrue(qlever.build_index())
            self.assertTrue(qlever.start())
        for call in container.call_args_list:
            self.assertEqual(call.kwargs["working_directory"], "/data")
            self.assertEqual(call.kwargs["environment"], {
                "UID": "20001", "GID": "6157",
            })

    def test_qlever_readiness_retries_until_ask_response(self):
        qlever = QLever.__new__(QLever)
        qlever._server = MagicMock(started=True)
        qlever._port = 7001
        qlever._logger = MagicMock()
        ready = MagicMock()
        ready.raise_for_status.return_value = None
        ready.json.return_value = {"boolean": True}
        with patch(
            "bench_executor.qlever.requests.post",
            side_effect=[requests.ConnectionError("not ready"), ready],
        ) as post, patch(
            "bench_executor.qlever.monotonic", side_effect=[0, 0, 1, 2]
        ), patch("bench_executor.qlever.sleep") as wait:
            self.assertTrue(qlever.wait_until_ready())
        self.assertEqual(post.call_count, 2)
        post.assert_called_with(
            "http://localhost:7001",
            data={"query": READY_QUERY},
            headers={"Accept": "application/sparql-results+json"},
            timeout=READY_REQUEST_TIMEOUT_SECONDS,
        )
        wait.assert_called_once_with(READY_POLL_SECONDS)

    def test_qlever_readiness_timeout_is_bounded(self):
        qlever = QLever.__new__(QLever)
        qlever._server = MagicMock(started=True)
        qlever._port = 7001
        qlever._logger = MagicMock()
        with patch(
            "bench_executor.qlever.requests.post",
            side_effect=requests.ConnectionError("not ready"),
        ), patch(
            "bench_executor.qlever.monotonic",
            side_effect=[0, 0, READY_TIMEOUT_SECONDS],
        ), patch("bench_executor.qlever.sleep") as wait:
            self.assertFalse(qlever.wait_until_ready())
        wait.assert_called_once_with(READY_POLL_SECONDS)
        qlever._logger.error.assert_called_once_with(
            f"Waiting for QLever HTTP readiness timed out after "
            f"{READY_TIMEOUT_SECONDS} seconds"
        )


if __name__ == "__main__":
    unittest.main()
