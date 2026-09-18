#!/usr/bin/env python3
"""Regression tests for the canonical BSBM query phase contract."""
import sys
import unittest
from pathlib import Path

FRAMEWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK))

from bench_executor.benchmark_result import validate_query_record
from bench_executor.rdf_experiment_matrix_resource import _attempt_timing_summary


def record(phase="warmup", position=0):
    return {
        "schema_version": 1,
        "experiment_id": "phase-contract",
        "system": "test/default",
        "dataset": "test",
        "workload": "test",
        "query_id": "stream/query-01",
        "phase": phase,
        "stream_phase": phase,
        "stream_position": position,
        "run": 0,
        "order": position,
        "status": "ok",
        "elapsed_ns": 7,
        "timing_schema": "rdf-attempt-timing-v1",
        "timing_clock": "perf_counter_ns",
        "attempt_elapsed_ns": 7,
        "timing_stages_ns": {"engine_execute": 7},
        "timing_stages_sum_ns": 7,
        "timing_reconciled": True,
    }


class BsbmPhaseContractTests(unittest.TestCase):
    def test_canonical_record_preserves_stream_metadata(self):
        value = validate_query_record(record())
        self.assertEqual(value["phase"], "warmup")
        self.assertEqual(value["stream_phase"], "warmup")
        self.assertEqual(value["stream_position"], 0)

    def test_canonical_record_rejects_phase_disagreement(self):
        value = record()
        value["stream_phase"] = "measured"
        with self.assertRaisesRegex(ValueError, "stream_phase must equal phase"):
            validate_query_record(value)

    def test_attempt_summary_separates_phases(self):
        summary = _attempt_timing_summary([
            record("warmup", 0), record("measured", 1)
        ])
        self.assertEqual(summary["phases"]["warmup"]["attempt_count"], 1)
        self.assertEqual(summary["phases"]["measured"]["attempt_count"], 1)

    def test_attempt_summary_rejects_missing_stream_contract(self):
        value = record()
        del value["stream_phase"]
        with self.assertRaisesRegex(ValueError, "stream_phase differs"):
            _attempt_timing_summary([value])


if __name__ == "__main__":
    unittest.main()
