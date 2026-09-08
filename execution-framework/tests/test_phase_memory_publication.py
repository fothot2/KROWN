#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from summarize_rdf_experiment import build_report


def summary(memory):
    return {
        'status': 'ok',
        'experiments': [{
            'system': 'vortex-rdf/reference',
            'representation': 'vortex-rdf/reference',
            'status': 'ok',
            'record_count': 1,
            'failure_count': 0,
            'resource_metrics': {'max_rss_kib': 2048},
            'phase_memory_metrics': memory,
            'execution_mode': {'storage': 'file-backed'},
            'workload_timing': {
                'schema': 'rdf-workload-timing-v1',
                'phases': {
                    'measured': {'attempt_count': 1, 'attempt_total_ns': 1},
                },
            },
            'system_timing': {
                'schema': 'rdf-system-timing-v1',
                'stages_ns': {'measured': 1},
                'stages_sum_ns': 1,
                'total_wall_ns': 1,
                'reconciled': True,
            },
        }],
    }


class PhaseMemoryPublicationTests(unittest.TestCase):
    def memory(self):
        return {
            'schema': 'rdf-phase-memory-metrics-v1',
            'scope': 'rdflib-worker-process-tree',
            'unit': 'bytes',
            'sampling_interval_ms': 10.0,
            'sample_errors': 0,
            'sample_count': 7,
            'peak_rss_bytes': 3 * 1024 * 1024,
            'phases': {
                'artifact_open_or_load': {
                    'first_rss_bytes': 1,
                    'last_rss_bytes': 2,
                    'peak_rss_bytes': 2 * 1024 * 1024,
                    'sample_count': 2,
                },
                'measured': {
                    'first_rss_bytes': 2,
                    'last_rss_bytes': 3,
                    'peak_rss_bytes': 3 * 1024 * 1024,
                    'sample_count': 5,
                },
            },
        }

    def test_report_publishes_sampled_memory_separately(self):
        row = build_report(summary(self.memory()))['experiments'][0]
        self.assertEqual(row['max_rss_mib'], 2.0)
        self.assertEqual(row['peak_rss_mib'], 3.0)
        self.assertEqual(row['open_or_load_peak_rss_mib'], 2.0)
        self.assertEqual(row['measured_peak_rss_mib'], 3.0)
        self.assertIsNone(row['warmup_peak_rss_mib'])
        self.assertEqual(row['memory_scope'], 'rdflib-worker-process-tree')
        self.assertEqual(row['memory_sample_count'], 7)

    def test_report_accepts_unsupported_memory_scope(self):
        row = build_report(summary(None))['experiments'][0]
        self.assertIsNone(row['peak_rss_mib'])
        self.assertIsNone(row['memory_scope'])

    def test_report_rejects_invalid_memory_schema(self):
        memory = self.memory()
        memory['schema'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'phase memory'):
            build_report(summary(memory))

    def test_matrix_source_propagates_phase_memory(self):
        source = (
            Path(__file__).resolve().parents[1]
            / 'bench_executor/rdf_experiment_matrix_resource.py'
        ).read_text(encoding='utf-8')
        self.assertIn(
            'phase_memory_metrics = query_lifecycle.get("phase_memory_metrics")',
            source,
        )
        self.assertIn(
            'summary["phase_memory_metrics"] = phase_memory_metrics',
            source,
        )


if __name__ == '__main__':
    unittest.main()
