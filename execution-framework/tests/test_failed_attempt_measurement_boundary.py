#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_query_benchmark import (
    _QueryManifest,
    _QuerySpec,
    _QueryTimeoutError,
    _RdfQueryAdapter,
    _RdfQueryBenchmark,
)


class FailingAdapter(_RdfQueryAdapter):
    def execute(self, query):
        raise _QueryTimeoutError("focused timeout")


class FailedBoundaryTests(unittest.TestCase):
    def test_failed_attempt_has_compactable_measurement_boundary(self):
        manifest = _QueryManifest("w", "d", (_QuerySpec("q", "ASK {}"),))
        benchmark = _RdfQueryBenchmark(
            FailingAdapter, "e", "s", manifest,
            warmup_runs=0, measured_runs=1, progress=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            records = benchmark.run(str(Path(directory) / "result.jsonl"))
        record = records[0]
        self.assertEqual(record["status"], "timeout")
        self.assertEqual(
            record["measurement_boundary"],
            "rdf-adapter-attempt-until-failure",
        )
        self.assertTrue(record["timing_reconciled"])
        self.assertEqual(
            sum(record["timing_stages_ns"].values()),
            record["attempt_elapsed_ns"],
        )


if __name__ == "__main__":
    unittest.main()
