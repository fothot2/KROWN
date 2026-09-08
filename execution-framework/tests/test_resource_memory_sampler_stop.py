#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.resource_memory_sampler import PhaseAwareMemorySampler


class ResourceMemorySamplerStopTests(unittest.TestCase):
    def test_stop_does_not_probe_after_thread_has_stopped(self):
        calls = 0

        def probe():
            nonlocal calls
            calls += 1
            if calls > 2:
                raise OSError('container disappeared')
            return calls * 10

        sampler = PhaseAwareMemorySampler(probe, 'test', interval_s=60)
        sampler.start()
        sampler.set_phase('engine_shutdown')
        result = sampler.stop()

        self.assertEqual(calls, 2)
        self.assertEqual(result['sample_errors'], 0)
        self.assertEqual(
            result['phases']['engine_shutdown']['peak_rss_bytes'],
            20,
        )

    def test_live_snapshot_still_reports_probe_failures(self):
        calls = 0

        def probe():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('real sampling failure')
            return 10

        sampler = PhaseAwareMemorySampler(probe, 'test', interval_s=60)
        sampler.start()
        sampler.set_phase('measured')
        result = sampler.snapshot()
        final = sampler.stop()

        self.assertEqual(result['sample_errors'], 1)
        self.assertEqual(final['sample_errors'], 1)


if __name__ == '__main__':
    unittest.main()
