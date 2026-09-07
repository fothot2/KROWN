#!/usr/bin/env python3
"""Preserve the SPARQL HTTP request-cap contract in compact archives."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_experiment_matrix_resource import (
    _COMPACT_RESULT_FIELDS,
    _compact_result_record,
)


class QLeverRequestCapProvenanceTests(unittest.TestCase):
    @staticmethod
    def record():
        stages = {'dispatch': 2, 'engine_execute': 5, 'correctness': 4}
        return {
            'query_id': 'q1',
            'phase': 'measured',
            'run': 0,
            'status': 'ok',
            'elapsed_ns': 5,
            'result_count': 1,
            'result_fingerprint': 'abc',
            'client_elapsed_ns': 11,
            'attempt_elapsed_ns': 11,
            'timing_clock': 'perf_counter_ns',
            'timing_schema': 'rdf-attempt-timing-v1',
            'timing_stages_ns': stages,
            'timing_stages_sum_ns': 11,
            'timing_reconciled': True,
            'measurement_boundary': 'sparql-http-complete-response',
            'request_max_rows': None,
            'result_cap_requested': False,
            'discard_me': 'large normalized value',
        }

    def test_contract_fields_are_mandatory_compact_fields(self):
        self.assertTrue({
            'measurement_boundary',
            'request_max_rows',
            'result_cap_requested',
        }.issubset(_COMPACT_RESULT_FIELDS))

    def test_uncapped_qlever_contract_survives_compaction(self):
        compact = _compact_result_record(self.record())
        self.assertEqual(
            compact['measurement_boundary'],
            'sparql-http-complete-response',
        )
        self.assertIsNone(compact['request_max_rows'])
        self.assertIs(compact['result_cap_requested'], False)
        self.assertNotIn('discard_me', compact)

    def test_explicit_cap_survives_compaction(self):
        record = self.record()
        record['request_max_rows'] = 4000000
        record['result_cap_requested'] = True
        compact = _compact_result_record(record)
        self.assertEqual(compact['request_max_rows'], 4000000)
        self.assertIs(compact['result_cap_requested'], True)

    def test_missing_contract_field_fails_closed(self):
        for field in (
            'measurement_boundary',
            'request_max_rows',
            'result_cap_requested',
        ):
            with self.subTest(field=field):
                record = self.record()
                del record[field]
                with self.assertRaisesRegex(ValueError, field):
                    _compact_result_record(record)


if __name__ == '__main__':
    unittest.main()
