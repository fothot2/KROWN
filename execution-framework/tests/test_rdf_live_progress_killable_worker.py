#!/usr/bin/env python3
import io
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_query_benchmark import (
    _QueryManifest, _QueryOutcome, _QuerySpec, _QueryTimeoutError,
    _RdfQueryBenchmark,
)


class ObservableAdapter:
    def __init__(self):
        self.calls = 0
        self.pid = 101
        self.restarts = 0

    def open(self):
        pass

    def close(self):
        pass

    def progress_metadata(self):
        return {"worker_pid": self.pid, "worker_restarts": self.restarts}

    def execute(self, query):
        self.calls += 1
        if self.calls == 1:
            self.pid = 202
            self.restarts = 1
            raise _QueryTimeoutError("blocked worker was killed")
        return _QueryOutcome(result_count=1, result_fingerprint="f")


class LiveProgressTests(unittest.TestCase):
    def test_progress_flushes_start_and_done_and_observes_restart(self):
        manifest = _QueryManifest(
            "w", "d",
            (
                _QuerySpec("q1", "ASK {}", {"stream_position": 0}),
                _QuerySpec("q2", "ASK {}", {"stream_position": 1}),
            ),
        )
        adapter = ObservableAdapter()
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            records = _RdfQueryBenchmark(
                lambda: adapter, "e", "pycottas/default", manifest,
                warmup_runs=0, measured_runs=1,
                progress=True, progress_stream=stream,
            ).run(str(Path(directory) / "results.jsonl"))
        lines = stream.getvalue().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("RDF_PROGRESS start", lines[0])
        self.assertIn("attempt=1/2", lines[0])
        self.assertIn("position=0", lines[0])
        self.assertIn("query=q1", lines[0])
        self.assertIn("status=timeout", lines[1])
        self.assertIn("worker_restarts=1", lines[1])
        self.assertIn("attempt=2/2", lines[2])
        self.assertIn("query=q2", lines[2])
        self.assertIn("status=ok", lines[3])
        self.assertEqual([record["status"] for record in records], ["timeout", "ok"])

    def test_progress_can_be_disabled(self):
        manifest = _QueryManifest("w", "d", (_QuerySpec("q", "ASK {}"),))
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            _RdfQueryBenchmark(
                ObservableAdapter, "e", "s", manifest,
                warmup_runs=0, measured_runs=1,
                progress=False, progress_stream=stream,
            ).run(str(Path(directory) / "results.jsonl"))
        self.assertEqual(stream.getvalue(), "")


    def test_lifecycle_timing_reconciles_success_and_failure_attempts(self):
        manifest = _QueryManifest(
            "w", "d", (_QuerySpec("q1", "ASK {}"), _QuerySpec("q2", "ASK {}"))
        )
        adapter = ObservableAdapter()
        with tempfile.TemporaryDirectory() as directory:
            benchmark = _RdfQueryBenchmark(
                lambda: adapter, "e", "s", manifest,
                warmup_runs=0, measured_runs=1, progress=False,
            )
            records = benchmark.run(str(Path(directory) / "results.jsonl"))
        self.assertTrue(all(record["timing_reconciled"] for record in records))
        timing = benchmark.last_lifecycle_timing
        self.assertEqual(timing["schema"], "rdf-query-lifecycle-timing-v1")
        self.assertTrue(timing["reconciled"])
        self.assertEqual(sum(timing["stages_ns"].values()), timing["total_wall_ns"])


if __name__ == "__main__":
    unittest.main()
