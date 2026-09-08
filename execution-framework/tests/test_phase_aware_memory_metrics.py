#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdflib_query_benchmark import _process_tree_rss_bytes
from bench_executor.resource_memory_sampler import PhaseAwareMemorySampler


class PhaseAwareMemoryMetricsTests(unittest.TestCase):
    def test_sampler_reports_separate_phase_peaks(self):
        values = iter((10, 20, 30, 40, 50, 60, 70, 80))
        last = [0]

        def probe():
            try:
                last[0] = next(values)
            except StopIteration:
                pass
            return last[0]

        sampler = PhaseAwareMemorySampler(probe, 'test-process-tree', 0.001)
        sampler.start()
        time.sleep(0.004)
        sampler.set_phase('measured')
        time.sleep(0.004)
        result = sampler.stop()
        self.assertEqual(result['schema'], 'rdf-phase-memory-metrics-v1')
        self.assertEqual(result['scope'], 'test-process-tree')
        self.assertGreater(result['phases']['pre_open']['sample_count'], 0)
        self.assertGreater(result['phases']['measured']['sample_count'], 0)
        self.assertGreaterEqual(result['peak_rss_bytes'], 10)

    def test_process_tree_rss_includes_current_process(self):
        self.assertGreater(_process_tree_rss_bytes(os.getpid()), 0)


if __name__ == '__main__':
    unittest.main()
