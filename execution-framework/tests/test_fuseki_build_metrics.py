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
from bench_executor.fuseki import Fuseki
from bench_executor.fuseki_system_adapter import FusekiSystemAdapter


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


class FusekiBuildMetricsTests(unittest.TestCase):
    def make_adapter(self, directory: str):
        shared = Path(directory) / 'shared'
        shared.mkdir()
        source = shared / 'dataset.nt'
        source.write_bytes(b'<s> <p> <o> .\n')
        with patch('bench_executor.fuseki_system_adapter.Fuseki') as runtime:
            adapter = FusekiSystemAdapter(
                artifact(source), directory, directory, directory
            )
        adapter._fuseki = runtime.return_value
        adapter.memory_sampler = MagicMock()
        adapter.memory_sampler.snapshot.return_value = memory()
        return adapter

    def test_start_resets_store_before_server_start(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            adapter._fuseki.reset_store.return_value = True
            adapter._fuseki.wait_until_ready.return_value = True
            self.assertTrue(adapter.start())
        adapter._fuseki.reset_store.assert_called_once_with()
        adapter._fuseki.wait_until_ready.assert_called_once_with()

    def test_failed_reset_prevents_server_start(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            adapter._fuseki.reset_store.return_value = False
            self.assertFalse(adapter.start())
        adapter._fuseki.wait_until_ready.assert_not_called()

    def test_load_publishes_build_metrics_and_tdb2_size(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            store = Path(directory) / 'fuseki'
            data = store / 'Data-0001'
            data.mkdir(parents=True)
            (data / 'SPO.dat').write_bytes(b'abc')
            (data / 'tdb.lock').write_bytes(b'1')
            (data / 'journal.jrnl').write_bytes(b'journal')
            (store / 'tdb.lock').write_bytes(b'2')
            adapter._fuseki.load.return_value = True
            self.assertTrue(adapter.ready())
        self.assertEqual(adapter.build_metrics['status'], 'ok')
        self.assertEqual(adapter.build_metrics['memory']['sample_count'], 4)
        self.assertEqual(adapter.build_metrics['memory']['peak_rss_bytes'], 1234)
        self.assertEqual(adapter.representation_size['logical_bytes'], 3)
        self.assertEqual(adapter.representation_size['file_count'], 1)
        self.assertEqual(adapter.representation_size['directory_count'], 2)
        self.assertEqual(
            adapter.representation_size['exclusion_policy']['names'],
            ['tdb.lock', 'journal.jrnl'],
        )
        self.assertEqual(
            adapter.representation_size['exclusion_policy']['excluded_file_count'], 3
        )

    def test_failed_load_preserves_failed_build_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            adapter._fuseki.load.return_value = False
            self.assertFalse(adapter.ready())
        self.assertEqual(adapter.build_metrics['status'], 'failed')
        self.assertIsNone(adapter.build_metrics['returncode'])
        self.assertIsNone(adapter.representation_size)


class FusekiStoreResetTests(unittest.TestCase):
    def runtime(self, directory: str) -> Fuseki:
        runtime = Fuseki.__new__(Fuseki)
        runtime._data_path = directory
        runtime._logger = MagicMock()
        return runtime

    def test_reset_removes_nested_stale_files(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'fuseki'
            nested = store / 'Data-0001'
            nested.mkdir(parents=True)
            (nested / 'old.dat').write_bytes(b'old')
            runtime = self.runtime(directory)
            with patch.object(Fuseki, 'cleanup_data', return_value=True):
                self.assertTrue(runtime.reset_store())
            self.assertTrue(store.is_dir())
            self.assertEqual(list(store.iterdir()), [])

    def test_reset_rejects_store_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / 'outside'
            outside.mkdir()
            marker = outside / 'keep'
            marker.write_bytes(b'keep')
            (Path(directory) / 'fuseki').symlink_to(
                outside, target_is_directory=True
            )
            runtime = self.runtime(directory)
            self.assertFalse(runtime.reset_store())
            self.assertEqual(marker.read_bytes(), b'keep')

    def test_reset_rejects_nested_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'fuseki'
            outside = Path(directory) / 'outside'
            store.mkdir()
            outside.mkdir()
            marker = outside / 'keep'
            marker.write_bytes(b'keep')
            (store / 'escape').symlink_to(outside, target_is_directory=True)
            runtime = self.runtime(directory)
            self.assertFalse(runtime.reset_store())
            self.assertEqual(marker.read_bytes(), b'keep')

    def test_stop_preserves_loaded_representation(self):
        runtime = Fuseki.__new__(Fuseki)
        runtime._container_id = 'container-id'
        runtime._logger = MagicMock()
        runtime._data_path = '/tmp/data'
        with patch('bench_executor.fuseki.Container.stop', return_value=True), patch.object(
            Fuseki, 'cleanup_data', return_value=True
        ), patch('bench_executor.fuseki.requests.post') as post:
            self.assertTrue(runtime.stop())
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
