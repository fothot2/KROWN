#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_query_benchmark import (
    _QueryManifest,
    _QueryOutcome,
    _QuerySpec,
    _RdfQueryAdapter,
    _RdfQueryBenchmark,
)
from bench_executor.rdflib_query_benchmark import (
    _WorkerRdfLibAdapter,
)


class MemoryAdapter(_RdfQueryAdapter):
    def __init__(self):
        self.opened = False

    @property
    def supports_load_temperature(self):
        return True

    @property
    def memory_scope(self):
        return "test-worker"

    def current_rss_bytes(self):
        return 4096 if self.opened else None

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def execute(self, query):
        return _QueryOutcome(result_count=1)


class RuntimeFixTests(unittest.TestCase):
    def test_fast_opens_have_forced_memory_samples(self):
        manifest = _QueryManifest(
            "w", "d", (_QuerySpec("q", "ASK {}"),)
        )
        benchmark = _RdfQueryBenchmark(
            MemoryAdapter,
            "e",
            "s",
            manifest,
            warmup_runs=0,
            measured_runs=1,
            progress=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            benchmark.run(str(Path(directory) / "r.jsonl"))
        memory = benchmark.last_lifecycle_timing["phase_memory_metrics"]
        self.assertEqual(memory["sample_errors"], 0)
        for phase in (
            "process_cold_load_or_parse",
            "process_warm_load_or_parse",
        ):
            self.assertGreaterEqual(
                memory["phases"][phase]["sample_count"], 1
            )

    def worker(self):
        return _WorkerRdfLibAdapter(
            engine="default",
            artifact_path="/tmp/a.nt",
            vortex_layout="unused",
            timeout_s=1.0,
            startup_timeout_s=1.0,
            kill_grace_s=0.0,
        )

    def test_planned_warm_open_is_not_a_recovery_restart(self):
        worker = self.worker()
        worker._process = MagicMock()
        worker._process.is_alive.return_value = True
        worker._process.pid = 10
        worker._worker_starts = 2
        self.assertEqual(worker.progress_metadata()["worker_restarts"], 0)

    def test_recovery_open_increments_restart_counter(self):
        worker = self.worker()
        with patch.object(worker, "_discard"), patch.object(worker, "open"):
            self.assertTrue(worker.prepare_for_attempt())
        self.assertEqual(worker.progress_metadata()["worker_restarts"], 1)


if __name__ == "__main__":
    unittest.main()
