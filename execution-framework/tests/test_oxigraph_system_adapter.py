#!/usr/bin/env python3
"Focused tests for the Oxigraph system adapter."

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
from bench_executor.oxigraph import Oxigraph
from bench_executor.oxigraph_system_adapter import OxigraphSystemAdapter
from bench_executor.sparql_http_system_adapter import sparql_http_system_specifications


class OxigraphSystemAdapterTests(unittest.TestCase):
    def _artifact(self, source: Path) -> DatasetArtifact:
        payload = source.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        return DatasetArtifact(
            benchmark="bsbm",
            dataset="explore-1k",
            source_format="ntriples",
            source_size_bytes=len(payload),
            source_sha256=digest,
            representation="rdf/source",
            files=(ArtifactFile("dataset.nt", len(payload), digest),),
        )

    def test_system_specifications_are_registered(self):
        system_ids = {
            specification.system_id
            for specification in sparql_http_system_specifications()
        }
        self.assertIn("oxigraph/memory", system_ids)
        self.assertIn("oxigraph/rocksdb", system_ids)

    def test_prepare_verifies_the_source(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "shared"
            shared.mkdir()
            source = shared / "dataset.nt"
            source.write_text(
                "<http://s> <http://p> <http://o> .\n",
                encoding="utf-8",
            )
            artifact = self._artifact(source)
            with mock.patch(
                "bench_executor.oxigraph_system_adapter.Oxigraph"
            ) as oxigraph:
                oxigraph.return_value.endpoint = "http://localhost:7878/query"
                adapter = OxigraphSystemAdapter(
                    artifact, directory, directory, "memory"
                )
            self.assertTrue(adapter.prepare())

    def test_invalid_backend_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "shared"
            shared.mkdir()
            source = shared / "dataset.nt"
            source.write_text(
                "<http://s> <http://p> <http://o> .\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                OxigraphSystemAdapter(
                    self._artifact(source), directory, directory, "invalid"
                )


class OxigraphStoreResetTests(unittest.TestCase):
    def runtime(self, directory: str, backend: str) -> Oxigraph:
        runtime = Oxigraph.__new__(Oxigraph)
        runtime._data_path = Path(directory).resolve()
        runtime._backend = backend
        runtime._logger = mock.MagicMock()
        return runtime

    def test_rocksdb_reset_removes_nested_stale_files(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'oxigraph-rocksdb'
            nested = store / 'nested'
            nested.mkdir(parents=True)
            (store / 'old.sst').write_bytes(b'old')
            (nested / 'old.log').write_bytes(b'old')
            runtime = self.runtime(directory, 'rocksdb')
            self.assertTrue(runtime.reset_store())
            self.assertTrue(store.is_dir())
            self.assertEqual(list(store.iterdir()), [])

    def test_memory_reset_does_not_modify_existing_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'oxigraph-rocksdb'
            store.mkdir()
            stale = store / 'old.sst'
            stale.write_bytes(b'old')
            runtime = self.runtime(directory, 'memory')
            self.assertTrue(runtime.reset_store())
            self.assertEqual(stale.read_bytes(), b'old')

    def test_reset_rejects_store_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / 'outside'
            outside.mkdir()
            marker = outside / 'keep'
            marker.write_bytes(b'keep')
            (Path(directory) / 'oxigraph-rocksdb').symlink_to(
                outside, target_is_directory=True
            )
            runtime = self.runtime(directory, 'rocksdb')
            self.assertFalse(runtime.reset_store())
            self.assertEqual(marker.read_bytes(), b'keep')

    def test_reset_rejects_nested_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / 'oxigraph-rocksdb'
            outside = Path(directory) / 'outside'
            store.mkdir()
            outside.mkdir()
            marker = outside / 'keep'
            marker.write_bytes(b'keep')
            (store / 'escape').symlink_to(outside, target_is_directory=True)
            runtime = self.runtime(directory, 'rocksdb')
            self.assertFalse(runtime.reset_store())
            self.assertEqual(marker.read_bytes(), b'keep')


if __name__ == "__main__":
    unittest.main()
