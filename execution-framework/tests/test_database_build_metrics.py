#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.database_build_metrics import (
    build_metrics_from_phase,
    measure_persistent_paths,
)
from bench_executor.resource_memory_sampler import PhaseAwareMemorySampler


class DatabaseBuildMetricsTests(unittest.TestCase):
    def test_sampler_snapshot_does_not_stop_sampling(self):
        values = iter((10, 20, 30, 40))
        sampler = PhaseAwareMemorySampler(
            lambda: next(values, 40), 'test', interval_s=60
        )
        sampler.start()
        sampler.set_phase('build')
        snapshot = sampler.snapshot()
        sampler.set_phase('query')
        final = sampler.stop()
        self.assertGreaterEqual(snapshot['phases']['build']['sample_count'], 2)
        self.assertIn('query', final['phases'])

    def test_build_record_uses_only_declared_phase(self):
        memory = {
            'scope': 'docker-container-cgroup-v2', 'unit': 'bytes',
            'sampling_interval_ms': 10.0, 'sample_errors': 0,
            'phases': {'build': {'sample_count': 3, 'peak_rss_bytes': 99}},
        }
        value = build_metrics_from_phase(123, memory, 'build')
        self.assertEqual(value['elapsed_ns'], 123)
        self.assertEqual(value['memory']['sample_count'], 3)
        self.assertEqual(value['memory']['peak_rss_bytes'], 99)

    def test_persistent_size_applies_explicit_filename_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'database'
            root.mkdir()
            (root / 'store.db').write_bytes(b'abc')
            (root / 'LOCK').write_bytes(b'x')
            (root / 'LOG.old.1').write_bytes(b'old log')
            (root / 'server.log').write_bytes(b'log')
            value = measure_persistent_paths(
                [root],
                excluded_names=['LOCK'],
                excluded_prefixes=['LOG.old.'],
                excluded_suffixes=['.log'],
            )
        self.assertEqual(value['logical_bytes'], 3)
        self.assertEqual(value['file_count'], 1)
        self.assertEqual(value['directory_count'], 1)
        self.assertEqual(value['exclusion_policy']['excluded_file_count'], 3)
        self.assertEqual(value['exclusion_policy']['prefixes'], ['LOG.old.'])


if __name__ == '__main__':
    unittest.main()
