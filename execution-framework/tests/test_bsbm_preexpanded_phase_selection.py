#!/usr/bin/env python3
"""Regression tests for BSBM pre-expanded stream phase selection."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench_executor.rdf_query_benchmark import (
    _QueryManifest,
    _QueryOutcome,
    _QuerySpec,
    _QueryTimeoutError,
    _RdfQueryBenchmark,
)


class _Adapter:
    supports_load_temperature = False
    memory_scope = None

    def __init__(self, dispatched=None):
        self.dispatched = dispatched

    def open(self):
        pass

    def close(self):
        pass

    def prepare_for_attempt(self):
        return False

    def execute(self, query):
        if self.dispatched is not None:
            self.dispatched.append(query)
        if query == 'timeout':
            raise _QueryTimeoutError('synthetic timeout')
        return _QueryOutcome(result_count=0, result_fingerprint='empty')


class BsbmPreexpandedPhaseSelectionTests(unittest.TestCase):
    def run_manifest(self, queries, adapter_factory=lambda: _Adapter(), threshold=0):
        manifest = _QueryManifest(
            workload='bsbm-preexpanded-test',
            dataset='synthetic',
            queries=tuple(queries),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'results.jsonl'
            return _RdfQueryBenchmark(
                adapter_factory,
                'experiment',
                'test/default',
                manifest,
                warmup_runs=0,
                measured_runs=1,
                in_run_timeout_quarantine_threshold=threshold,
                progress=False,
            ).run(str(output))

    def test_metadata_defines_phases_without_top_level_schedule(self):
        records = self.run_manifest([
            _QuerySpec('stream/query-01', 'ok', {
                'stream_phase': 'warmup', 'stream_position': 0,
                'bsbm_template_id': '1',
            }),
            _QuerySpec('stream/query-02', 'ok', {
                'stream_phase': 'measured', 'stream_position': 1,
                'bsbm_template_id': '2',
            }),
        ])
        self.assertEqual(
            [(item['phase'], item['stream_phase'], item['stream_position'])
             for item in records],
            [('warmup', 'warmup', 0), ('measured', 'measured', 1)],
        )

    def test_preexpanded_positions_must_be_contiguous(self):
        with self.assertRaisesRegex(ValueError, 'positions must be contiguous'):
            self.run_manifest([
                _QuerySpec('stream/query-01', 'ok', {
                    'stream_phase': 'measured', 'stream_position': 1,
                    'bsbm_template_id': '1',
                }),
            ])

    def test_warmup_timeouts_do_not_activate_measured_quarantine(self):
        dispatched = []
        queries = []
        for position in range(3):
            queries.append(_QuerySpec(
                f'warmup/{position}/query-10', 'timeout', {
                    'stream_phase': 'warmup', 'stream_position': position,
                    'bsbm_template_id': '10',
                },
            ))
        for offset in range(4):
            position = 3 + offset
            queries.append(_QuerySpec(
                f'measured/{offset}/query-10', 'timeout', {
                    'stream_phase': 'measured', 'stream_position': position,
                    'bsbm_template_id': '10',
                },
            ))
        records = self.run_manifest(
            queries,
            adapter_factory=lambda: _Adapter(dispatched),
            threshold=3,
        )
        self.assertEqual(len(dispatched), 6)
        self.assertEqual([item['status'] for item in records[:6]], ['timeout'] * 6)
        self.assertEqual(records[6]['status'], 'skipped')
        self.assertEqual(records[6]['skip_template_id'], '10')
        self.assertEqual(records[6]['skip_threshold'], 3)


if __name__ == '__main__':
    unittest.main()
