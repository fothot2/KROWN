#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_query_benchmark import (
    _QueryManifest,
    _QueryOutcome,
    _QuerySpec,
    _RdfQueryAdapter,
    _RdfQueryBenchmark,
)


class Adapter(_RdfQueryAdapter):
    opens = 0
    closes = 0

    @property
    def supports_load_temperature(self):
        return True

    def open(self):
        type(self).opens += 1

    def close(self):
        type(self).closes += 1

    def execute(self, query):
        return _QueryOutcome(result_count=1)


class ProcessLoadTemperatureTests(unittest.TestCase):
    def test_shared_lifecycle_measures_two_separate_opens(self):
        Adapter.opens = Adapter.closes = 0
        manifest = _QueryManifest(
            "w", "d", (_QuerySpec("q", "ASK {}"),)
        )
        benchmark = _RdfQueryBenchmark(
            lambda: Adapter(),
            "e",
            "s",
            manifest,
            warmup_runs=0,
            measured_runs=1,
            progress=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            benchmark.run(str(Path(directory) / "r.jsonl"))
        metrics = benchmark.last_lifecycle_timing["load_temperature_metrics"]
        self.assertEqual(metrics["status"], "ok")
        self.assertEqual(Adapter.opens, 2)
        self.assertEqual(Adapter.closes, 2)
        self.assertIsInstance(
            metrics["process_cold_load_or_parse_ns"], int
        )
        self.assertIsInstance(
            metrics["process_warm_load_or_parse_ns"], int
        )


if __name__ == "__main__":
    unittest.main()
