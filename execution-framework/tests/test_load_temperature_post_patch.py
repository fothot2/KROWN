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


class CountingAdapter(_RdfQueryAdapter):
    def __init__(self, supported=True, restart_on_attempt=None):
        self.supported = supported
        self.restart_on_attempt = restart_on_attempt
        self.opens = 0
        self.closes = 0
        self.attempts = 0

    @property
    def supports_load_temperature(self):
        return self.supported

    def open(self):
        self.opens += 1

    def close(self):
        self.closes += 1

    def prepare_for_attempt(self):
        self.attempts += 1
        if self.restart_on_attempt == self.attempts:
            self.open()
            return True
        return False

    def execute(self, query):
        return _QueryOutcome(result_count=1)


class PostPatchTests(unittest.TestCase):
    def run_benchmark(self, adapter):
        manifest = _QueryManifest("w", "d", (_QuerySpec("q", "ASK {}"),))
        benchmark = _RdfQueryBenchmark(
            lambda: adapter, "e", "s", manifest,
            warmup_runs=1, measured_runs=1, progress=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            benchmark.run(str(Path(directory) / "r.jsonl"))
        return benchmark.last_lifecycle_timing

    def test_supported_metrics_reconcile_without_double_counting(self):
        timing = self.run_benchmark(CountingAdapter())
        stages = timing["stages_ns"]
        self.assertNotIn("process_cold_load_or_parse", stages)
        self.assertNotIn("process_warm_load_or_parse", stages)
        self.assertEqual(sum(stages.values()), timing["total_wall_ns"])
        self.assertTrue(timing["reconciled"])

    def test_noop_preparation_does_not_count_as_restart(self):
        timing = self.run_benchmark(CountingAdapter())
        self.assertEqual(
            timing["load_temperature_metrics"]["restart_load_or_parse_ns"], 0
        )

    def test_actual_reopen_counts_as_restart(self):
        timing = self.run_benchmark(CountingAdapter(restart_on_attempt=2))
        self.assertGreater(
            timing["load_temperature_metrics"]["restart_load_or_parse_ns"], 0
        )

    def test_unsupported_load_values_are_null(self):
        timing = self.run_benchmark(CountingAdapter(supported=False))
        metrics = timing["load_temperature_metrics"]
        self.assertEqual(metrics["status"], "unsupported")
        self.assertIsNone(metrics["process_cold_load_or_parse_ns"])
        self.assertIsNone(metrics["process_warm_load_or_parse_ns"])


if __name__ == "__main__":
    unittest.main()
