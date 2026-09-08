#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.qlever import QLever


class QLeverBuildMetricTests(unittest.TestCase):
 def test_index_size_uses_exact_directory(self):
  with tempfile.TemporaryDirectory() as d:
   q=QLever.__new__(QLever); q._data_path=Path(d); root=Path(d)/'qlever-index'; root.mkdir(); (root/'a').write_bytes(b'abc')
   value=q._index_size()
  self.assertEqual(value['logical_bytes'],3); self.assertEqual(value['file_count'],1); self.assertEqual(value['directory_count'],1)
 def test_build_separates_index_metrics(self):
  with tempfile.TemporaryDirectory() as d:
   q=QLever.__new__(QLever); q._data_path=Path(d); q._image='image:v1'; q._logger=MagicMock(); q._index_command='index'; q.build_metrics=None; q.representation_size=None
   root=Path(d)/'qlever-index'; root.mkdir(); (root/'a').write_bytes(b'abc')
   indexer=MagicMock(); indexer.run.return_value=True; indexer._container_id='id'; indexer._docker.wait.return_value=0; indexer._docker.logs.return_value=[]
   sampler=MagicMock(); sampler.stop.return_value={'scope':'docker-container-cgroup-v2','unit':'bytes','sampling_interval_ms':10.0,'sample_count':2,'sample_errors':0,'peak_rss_bytes':123,'schema':'rdf-phase-memory-metrics-v1','phases':{}}
   with patch.object(QLever,'cleanup_containers',return_value=True), patch('bench_executor.qlever.Container',return_value=indexer), patch('bench_executor.qlever.PhaseAwareMemorySampler',return_value=sampler):
    self.assertTrue(q.build_index())
  self.assertEqual(q.build_metrics['memory']['peak_rss_bytes'],123); self.assertEqual(q.representation_size['logical_bytes'],3); sampler.start.assert_called_once()

class QLeverStableSizeBoundaryTests(unittest.TestCase):
    def test_runtime_log_growth_does_not_change_representation_size(self):
        with tempfile.TemporaryDirectory() as directory:
            qlever = QLever.__new__(QLever)
            qlever._data_path = Path(directory)
            root = Path(directory) / 'qlever-index'
            root.mkdir()
            (root / 'dataset.index.spo').write_bytes(b'index')
            runtime_logs = (
                root / 'dataset.metrics-log.jsonl',
                root / 'dataset.index.resource-usage-log.tsv',
                root / 'dataset.server.resource-usage-log.tsv',
            )
            for path in runtime_logs:
                path.write_bytes(b'initial')
            before = qlever._index_size()
            for path in runtime_logs:
                with path.open('ab') as stream:
                    stream.write(b' runtime growth')
            after = qlever._index_size()
        self.assertEqual(before['logical_bytes'], 5)
        self.assertEqual(before['allocated_bytes'], after['allocated_bytes'])
        self.assertEqual(before['logical_bytes'], after['logical_bytes'])
        self.assertEqual(before['file_count'], 1)
        self.assertEqual(before['directory_count'], 1)
        self.assertEqual(before['exclusion_policy'], after['exclusion_policy'])
        self.assertEqual(before['exclusion_policy']['excluded_file_count'], 3)
        self.assertEqual(
            before['exclusion_policy']['suffixes'],
            ['.metrics-log.jsonl', '.resource-usage-log.tsv'],
        )

if __name__=='__main__': unittest.main()
