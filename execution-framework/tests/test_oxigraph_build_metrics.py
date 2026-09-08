#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
from bench_executor.oxigraph_system_adapter import OxigraphSystemAdapter


def artifact(source: Path) -> DatasetArtifact:
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    return DatasetArtifact(
        benchmark='bsbm', dataset='tiny', source_format='ntriples',
        source_size_bytes=len(payload), source_sha256=digest,
        representation='rdf/source',
        files=(ArtifactFile('dataset.nt', len(payload), digest),),
    )


def memory() -> dict:
    return {
        'scope': 'docker-container-cgroup-v2', 'unit': 'bytes',
        'sampling_interval_ms': 10.0, 'sample_errors': 0,
        'phases': {
            'artifact_open_or_load': {
                'sample_count': 4, 'peak_rss_bytes': 1234,
            },
        },
    }


class OxigraphBuildMetricsTests(unittest.TestCase):
    def make_adapter(self, directory: str, backend: str):
        shared = Path(directory) / 'shared'
        shared.mkdir()
        source = shared / 'dataset.nt'
        source.write_bytes(b'<s> <p> <o> .\n')
        with patch('bench_executor.oxigraph_system_adapter.Oxigraph') as runtime:
            adapter = OxigraphSystemAdapter(
                artifact(source), directory, directory, backend
            )
        adapter._oxigraph = runtime.return_value
        adapter.memory_sampler = MagicMock()
        adapter.memory_sampler.snapshot.return_value = memory()
        return adapter

    def test_rocksdb_load_publishes_build_metrics_and_stable_size(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory, 'rocksdb')
            store = Path(directory) / 'oxigraph-rocksdb'
            store.mkdir()
            (store / '000001.sst').write_bytes(b'abc')
            (store / '000002.log').write_bytes(b'defg')
            (store / 'LOCK').write_bytes(b'x')
            (store / 'LOG').write_bytes(b'diagnostic')
            (store / 'LOG.old.1').write_bytes(b'rotated')
            adapter._oxigraph.load.return_value = True
            self.assertTrue(adapter.ready())
        self.assertEqual(adapter.build_metrics['status'], 'ok')
        self.assertEqual(adapter.build_metrics['memory']['sample_count'], 4)
        self.assertEqual(adapter.build_metrics['memory']['peak_rss_bytes'], 1234)
        self.assertEqual(adapter.representation_size['logical_bytes'], 7)
        self.assertEqual(adapter.representation_size['file_count'], 2)
        self.assertEqual(
            adapter.representation_size['exclusion_policy']['names'],
            ['LOCK', 'LOG'],
        )
        self.assertEqual(
            adapter.representation_size['exclusion_policy']['prefixes'],
            ['LOG.old.'],
        )
        self.assertEqual(
            adapter.representation_size['exclusion_policy']['suffixes'], []
        )
        self.assertEqual(
            adapter.representation_size['exclusion_policy']['excluded_file_count'], 3
        )

    def test_memory_load_reports_non_persistent_size(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory, 'memory')
            adapter._oxigraph.load.return_value = True
            self.assertTrue(adapter.ready())
        self.assertEqual(adapter.representation_size['boundary'], 'not-applicable')
        self.assertEqual(
            adapter.representation_size['reason'], 'in-memory-representation'
        )
        self.assertIsNone(adapter.representation_size['logical_bytes'])

    def test_failed_load_preserves_failed_build_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory, 'rocksdb')
            adapter._oxigraph.load.return_value = False
            self.assertFalse(adapter.ready())
        self.assertEqual(adapter.build_metrics['status'], 'failed')
        self.assertIsNone(adapter.build_metrics['returncode'])
        self.assertIsNone(adapter.representation_size)

    def test_ready_requires_active_lifecycle_sampler(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory, 'memory')
            adapter.memory_sampler = None
            with self.assertRaisesRegex(RuntimeError, 'sampler is not active'):
                adapter.ready()


class OxigraphCleanBuildTests(OxigraphBuildMetricsTests):
    def test_rocksdb_start_resets_store_before_server_start(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory, 'rocksdb')
            adapter._oxigraph.reset_store.return_value = True
            adapter._oxigraph.start_server.return_value = True
            self.assertTrue(adapter.start())
        adapter._oxigraph.reset_store.assert_called_once_with()
        adapter._oxigraph.start_server.assert_called_once_with()

    def test_failed_reset_prevents_server_start(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory, 'rocksdb')
            adapter._oxigraph.reset_store.return_value = False
            self.assertFalse(adapter.start())
        adapter._oxigraph.start_server.assert_not_called()

from bench_executor.database_build_metrics import measure_persistent_paths


class OxigraphStableSizeBoundaryTests(OxigraphBuildMetricsTests):
    def test_diagnostic_log_growth_does_not_change_size(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory, 'rocksdb')
            store = Path(directory) / 'oxigraph-rocksdb'
            store.mkdir()
            wal = store / '000002.log'
            wal.write_bytes(b'write-ahead')
            diagnostic = store / 'LOG'
            diagnostic.write_bytes(b'initial')
            (store / 'LOG.old.1').write_bytes(b'rotated')
            (store / 'LOCK').write_bytes(b'')
            adapter._oxigraph.load.return_value = True
            self.assertTrue(adapter.ready())
            before = adapter.representation_size
            with diagnostic.open('ab') as stream:
                stream.write(b' query diagnostic growth')
            (store / 'LOG.old.2').write_bytes(b'new rotation')
            after = measure_persistent_paths(
                [store],
                excluded_names=['LOCK', 'LOG'],
                excluded_prefixes=['LOG.old.'],
            )
        for field in (
            'logical_bytes',
            'allocated_bytes',
            'file_count',
            'directory_count',
        ):
            self.assertEqual(before[field], after[field])
        self.assertEqual(before['logical_bytes'], len(b'write-ahead'))
        self.assertEqual(before['file_count'], 1)
        self.assertEqual(after['exclusion_policy']['excluded_file_count'], 4)


if __name__ == '__main__':
    unittest.main()
