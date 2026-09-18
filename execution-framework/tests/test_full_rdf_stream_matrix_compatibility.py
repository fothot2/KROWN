#!/usr/bin/env python3
"""Focused tests for full pre-expanded RDF stream matrix compatibility."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_experiment_matrix_resource import (
    _compact_result_record,
    _execution_strategy,
)
from bench_executor.sparql_http_system_adapter import (
    sparql_http_system_specifications,
)


class FullRdfStreamMatrixCompatibilityTests(unittest.TestCase):
    def test_all_http_systems_declare_sparql_http_strategy(self):
        specifications = sparql_http_system_specifications()
        self.assertEqual(
            {item.system_id for item in specifications},
            {
                "fuseki/memory",
                "fuseki/tdb2",
                "virtuoso/default",
                "qlever/default",
                "oxigraph/memory",
                "oxigraph/rocksdb",
            },
        )
        self.assertTrue(all(
            item.parameters.get("execution_strategy") == "sparql-http"
            for item in specifications
        ))
        self.assertTrue(all(
            _execution_strategy(item) == "sparql-http"
            for item in specifications
        ))

    def test_compact_result_preserves_optional_stream_metadata(self):
        record = {
            "query_id": "explore/stream-000000/query-01",
            "phase": "warmup",
            "run": 0,
            "status": "ok",
            "elapsed_ns": 7,
            "result_count": 1,
            "result_fingerprint": "f",

            "client_elapsed_ns": 7,
            "attempt_elapsed_ns": 7,
            "timing_clock": "perf_counter_ns",
            "timing_schema": "rdf-attempt-timing-v1",
            "timing_stages_ns": {"dispatch": 7},
            "timing_stages_sum_ns": 7,
            "timing_reconciled": True,
            "measurement_boundary": "test-adapter-complete-result",
            "stream_position": 0,
            "bsbm_template_id": "1",
            "query_sha256": "a" * 64,
        }
        compact = _compact_result_record(record)
        self.assertEqual(compact["stream_position"], 0)
        self.assertEqual(compact["bsbm_template_id"], "1")
        self.assertNotIn("query_sha256", compact)

    def test_compact_result_accepts_legacy_records_without_stream_metadata(self):
        record = {
            "query_id": "q1",
            "phase": "measured",
            "run": 0,
            "status": "ok",
            "elapsed_ns": 7,
            "result_count": 1,
            "result_fingerprint": "f",

            "client_elapsed_ns": 7,
            "attempt_elapsed_ns": 7,
            "timing_clock": "perf_counter_ns",
            "timing_schema": "rdf-attempt-timing-v1",
            "timing_stages_ns": {"dispatch": 7},
            "timing_stages_sum_ns": 7,
            "timing_reconciled": True,
            "measurement_boundary": "test-adapter-complete-result",
        }
        compact = _compact_result_record(record)
        self.assertNotIn("stream_position", compact)
        self.assertNotIn("bsbm_template_id", compact)

    def test_execution_strategy_still_rejects_missing_strategy(self):
        specification = SimpleNamespace(
            system_id="unknown/default", parameters={}
        )
        with self.assertRaisesRegex(ValueError, "unsupported execution strategy"):
            _execution_strategy(specification)

    def test_declaration_loader_source_allows_only_optional_baseline(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "bench_executor/rdf_experiment_manifest.py"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            source, r'optional\s*=\s*\{["\']semantic_baseline["\']\}'
        )
        self.assertRegex(source, r'required\.issubset\(fields\)')
        self.assertRegex(
            source, r'fields\.difference\(required\s*\|\s*optional\)'
        )


if __name__ == "__main__":
    unittest.main()
