#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.persistent_jsonl_query_adapter import (
    PersistentJsonlQueryAdapter,
)


class Adapter:
    container_artifact = "/data/dataset.hdt"

    def worker_command(self, **kwargs):
        return ["worker"]

    def force_stop_command(self, name):
        return ["stop", name]


class BoundaryTests(unittest.TestCase):
    def query_adapter(self, process):
        return PersistentJsonlQueryAdapter(
            adapter=Adapter(), artifact=Path("dataset.hdt"), timeout_s=1,
            startup_timeout_s=1, normalizer=lambda document, query: document,
        )

    def test_verified_ready_enables_load_temperature(self):
        process = MagicMock()
        process.poll.return_value = None
        message = {
            "kind": "ready", "protocol": "jsonl-v1", "source_open": True,
            "source_type": "hdt",
            "source_boundary": "comunica-query-source-identify",
            "source_reference": "/data/dataset.hdt",
        }
        with patch(
            "bench_executor.persistent_jsonl_query_adapter.subprocess.Popen",
            return_value=process,
        ), patch.object(PersistentJsonlQueryAdapter, "_read_message", return_value=message):
            adapter = self.query_adapter(process)
            adapter.open()
        self.assertTrue(adapter.supports_load_temperature)

    def test_plain_ready_is_rejected(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch(
            "bench_executor.persistent_jsonl_query_adapter.subprocess.Popen",
            return_value=process,
        ), patch.object(
            PersistentJsonlQueryAdapter, "_read_message",
            return_value={"kind": "ready", "protocol": "jsonl-v1"},
        ), patch.object(
            PersistentJsonlQueryAdapter, "_force_stop"
        ), self.assertRaisesRegex(RuntimeError, "verified HDT"):
            self.query_adapter(process).open()

    def test_worker_retains_and_disposes_identified_source(self):
        worker = (Path(__file__).resolve().parents[1]
                  / "dockers/ComunicaHDT/persistent-worker.js").read_text()
        self.assertIn("sourceIdentifier.identifySource", worker)
        self.assertIn("KeysQueryOperation.querySources", worker)
        self.assertIn("await source.dispose()", worker)
        self.assertIn('source_open: true', worker)
        self.assertNotIn('sources: [', worker)


if __name__ == "__main__":
    unittest.main()
