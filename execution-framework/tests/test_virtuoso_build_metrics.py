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
from bench_executor.virtuoso import Virtuoso
from bench_executor.virtuoso_system_adapter import VirtuosoSystemAdapter


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
        'phases': {'artifact_open_or_load': {
            'sample_count': 4, 'peak_rss_bytes': 1234,
        }},
    }


class VirtuosoBuildMetricsTests(unittest.TestCase):
    def make_adapter(self, directory: str):
        shared = Path(directory) / 'shared'
        shared.mkdir()
        source = shared / 'dataset.nt'
        source.write_bytes(b'<s> <p> <o> .\n')
        with patch('bench_executor.virtuoso_system_adapter.Virtuoso') as runtime:
            adapter = VirtuosoSystemAdapter(
                artifact(source), directory, directory, directory
            )
        adapter._virtuoso = runtime.return_value
        adapter.memory_sampler = MagicMock()
        adapter.memory_sampler.snapshot.return_value = memory()
        return adapter

    def test_prepare_does_not_run_separate_initialization_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / 'shared'
            shared.mkdir()
            source = shared / 'dataset.nt'
            source.write_bytes(b'<s> <p> <o> .\n')
            with patch('bench_executor.virtuoso_system_adapter.Virtuoso') as runtime:
                adapter = VirtuosoSystemAdapter(
                    artifact(source), directory, directory, directory
                )
                self.assertTrue(adapter.prepare())
            runtime.return_value.initialization.assert_not_called()

    def test_start_resets_benchmark_local_store(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            adapter._virtuoso.reset_store.return_value = True
            adapter._virtuoso.wait_until_ready.return_value = True
            self.assertTrue(adapter.start())
        adapter._virtuoso.reset_store.assert_called_once_with()
        adapter._virtuoso.wait_until_ready.assert_called_once_with()

    def test_load_publishes_build_metrics_and_database_size(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            store = Path(directory) / 'virtuoso'
            store.mkdir()
            (store / 'virtuoso.db').write_bytes(b'durable')
            for name in (
                'virtuoso-temp.db', 'virtuoso.ini', 'virtuoso.log',
                'virtuoso.pxa', 'virtuoso.trx',
            ):
                (store / name).write_bytes(b'runtime')
            adapter._virtuoso.load_parallel.return_value = True
            self.assertTrue(adapter.ready())
        self.assertEqual(adapter.build_metrics['status'], 'ok')
        self.assertEqual(adapter.build_metrics['memory']['peak_rss_bytes'], 1234)
        self.assertEqual(adapter.representation_size['logical_bytes'], 7)
        self.assertEqual(adapter.representation_size['file_count'], 1)
        self.assertEqual(
            adapter.representation_size['exclusion_policy']['excluded_file_count'], 5
        )

    def test_failed_load_preserves_failed_build_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            adapter._virtuoso.load_parallel.return_value = False
            self.assertFalse(adapter.ready())
        self.assertEqual(adapter.build_metrics['status'], 'failed')
        self.assertIsNone(adapter.representation_size)


class VirtuosoStoreTests(unittest.TestCase):
    def runtime(self, directory: str) -> Virtuoso:
        runtime = Virtuoso.__new__(Virtuoso)
        runtime._data_path = directory
        runtime._logger = MagicMock()
        return runtime

    def test_reset_removes_stale_database(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'virtuoso'
            store.mkdir()
            (store / 'virtuoso.db').write_bytes(b'old')
            runtime = self.runtime(directory)
            self.assertTrue(runtime.reset_store())
            self.assertEqual(list(store.iterdir()), [])

    def test_reset_rejects_store_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / 'outside'
            outside.mkdir()
            marker = outside / 'keep'
            marker.write_bytes(b'keep')
            (Path(directory) / 'virtuoso').symlink_to(
                outside, target_is_directory=True
            )
            runtime = self.runtime(directory)
            self.assertFalse(runtime.reset_store())
            self.assertEqual(marker.read_bytes(), b'keep')

    def test_stop_checkpoints_without_global_reset(self):
        runtime = Virtuoso.__new__(Virtuoso)
        runtime._container_id = 'container-id'
        runtime._logger = MagicMock()
        runtime.exec = MagicMock(return_value=(True, []))
        with patch('bench_executor.virtuoso.Container.stop', return_value=True):
            self.assertTrue(runtime.stop())
        command = runtime.exec.call_args.args[0]
        self.assertEqual(
            command,
            "'isql' -U dba -P root " 'exec="checkpoint;"',
        )
        self.assertNotIn('rdf_global_reset', command)


class VirtuosoPostShutdownSizeTests(VirtuosoBuildMetricsTests):
    def test_stop_replaces_pre_shutdown_size_with_stable_size(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            store = Path(directory) / 'virtuoso'
            store.mkdir()
            transient = store / 'load-list.tmp'
            transient.write_bytes(b'temporary')
            adapter.representation_size = {
                'logical_bytes': len(b'temporary'),
                'file_count': 1,
            }
            adapter._virtuoso.stop.return_value = True
            transient.unlink()
            (store / 'virtuoso.db').write_bytes(b'durable')
            for name in (
                'virtuoso-temp.db', 'virtuoso.ini', 'virtuoso.log',
                'virtuoso.pxa', 'virtuoso.trx',
            ):
                (store / name).write_bytes(b'runtime')
            self.assertTrue(adapter.stop())
        self.assertEqual(adapter.representation_size['logical_bytes'], 7)
        self.assertEqual(adapter.representation_size['file_count'], 1)
        self.assertEqual(
            adapter.representation_size['exclusion_policy']['excluded_file_count'],
            5,
        )

    def test_failed_stop_does_not_publish_post_shutdown_size(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = self.make_adapter(directory)
            before = {'logical_bytes': 11, 'file_count': 2}
            adapter.representation_size = before
            adapter._virtuoso.stop.return_value = False
            self.assertFalse(adapter.stop())
        self.assertIs(adapter.representation_size, before)


if __name__ == '__main__':
    unittest.main()
