#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

FRAMEWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK))

from bench_executor.rdf_query_benchmark import (
    _QueryOutcome,
    _RdfQueryBenchmark,
)


class Adapter:
    def __init__(self, metadata):
        self.metadata = metadata

    def execute(self, query):
        return _QueryOutcome(
            result_count=0,
            result_fingerprint='fingerprint',
            elapsed_ns=1,
            metadata=self.metadata,
            stage_timings_ns={'engine_execute': 1},
        )


class DbbenchIdenticalResultMetadataTests(unittest.TestCase):
    def benchmark(self):
        value = _RdfQueryBenchmark.__new__(_RdfQueryBenchmark)
        return value

    def record(self):
        return {
            'status': 'ok',
            'comparison_mode': 'unordered_multiset_fingerprint',
            'comparison_warning': None,
        }

    def query(self):
        return MagicMock(query='SELECT * WHERE { ?s ?p ?o }')

    def test_identical_adapter_metadata_is_idempotent(self):
        record = self.benchmark()._execute_attempt(
            Adapter({
                'comparison_mode': 'unordered_multiset_fingerprint',
                'comparison_warning': None,
                'measurement_boundary': 'sparql-http-complete-response',
            }),
            self.query(),
            self.record(),
        )
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(
            record['comparison_mode'],
            'unordered_multiset_fingerprint',
        )
        self.assertEqual(
            record['measurement_boundary'],
            'sparql-http-complete-response',
        )

    def test_conflicting_adapter_metadata_fails_closed(self):
        record = self.benchmark()._execute_attempt(
            Adapter({'comparison_mode': 'ordered_fingerprint'}),
            self.query(),
            self.record(),
        )
        self.assertEqual(record['status'], 'result_error')
        self.assertEqual(record['error_type'], '_ResultProcessingError')
        self.assertIn(
            'adapter metadata conflicts with existing field: comparison_mode',
            record['error_message'],
        )
        self.assertIn('query=', record['error_message'])
        self.assertIn('adapter=', record['error_message'])


if __name__ == '__main__':
    unittest.main()
