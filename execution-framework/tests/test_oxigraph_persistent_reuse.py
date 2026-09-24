#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
from bench_executor.oxigraph_system_adapter import (
    BUILD_MODE,
    REUSE_MODE,
    OxigraphSystemAdapter,
    _validate_store_structure,
)


def artifact(root: Path) -> DatasetArtifact:
    shared = root / "shared"
    shared.mkdir()
    source = shared / "dataset.nt"
    payload = b"<s> <p> <o> .\n"
    source.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return DatasetArtifact(
        "dbbench", "tiny", "ntriples", len(payload), digest,
        "rdf/source", (ArtifactFile("dataset.nt", len(payload), digest),),
    )


def make_store(root: Path) -> Path:
    store = root / "store"
    store.mkdir()
    (store / "CURRENT").write_text("MANIFEST-000001\n")
    (store / "000001.sst").write_bytes(b"sst")
    return store


class OxigraphPersistentReuseTests(unittest.TestCase):
    def test_reuse_does_not_reset_or_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = artifact(root)
            store = make_store(root)
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({
                "schema": "oxigraph-rocksdb-store-receipt-v1",
                "store_path": str(store.resolve()),
                "graph_triple_count": 1,
            }))
            with patch("bench_executor.oxigraph_system_adapter.Oxigraph") as runtime:
                runtime.return_value.endpoint = "http://localhost:7878/query"
                runtime.return_value.start_server.return_value = True
                runtime.return_value.is_ready.return_value = True
                runtime.return_value.stop.return_value = True
                adapter = OxigraphSystemAdapter(
                    item, str(root), str(root), "rocksdb",
                    lifecycle_mode=REUSE_MODE,
                    reuse_store_path=str(store),
                    reuse_receipt_path=str(receipt),
                )
                self.assertTrue(adapter.prepare())
                self.assertTrue(adapter.start())
                self.assertTrue(adapter.ready())
                self.assertTrue(adapter.stop())
            runtime.return_value.reset_store.assert_not_called()
            runtime.return_value.load.assert_not_called()

    def test_reuse_uses_ask_readiness_without_full_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = artifact(root)
            store = make_store(root)
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({
                "schema": "oxigraph-rocksdb-store-receipt-v1",
                "store_path": str(store.resolve()),
                "graph_triple_count": 2,
            }))
            with patch("bench_executor.oxigraph_system_adapter.Oxigraph") as runtime:
                runtime.return_value.endpoint = "http://localhost:7878/query"
                runtime.return_value.is_ready.return_value = True
                adapter = OxigraphSystemAdapter(
                    item, str(root), str(root), "rocksdb",
                    lifecycle_mode=REUSE_MODE,
                    reuse_store_path=str(store),
                    reuse_receipt_path=str(receipt),
                )
                self.assertTrue(adapter.prepare())
                self.assertTrue(adapter.ready())
            runtime.return_value.is_ready.assert_called_once_with()
            runtime.return_value.count_triples.assert_not_called()

    def test_memory_mode_keeps_fresh_load_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = artifact(root)
            with patch("bench_executor.oxigraph_system_adapter.Oxigraph") as runtime:
                runtime.return_value.endpoint = "http://localhost:7878/query"
                adapter = OxigraphSystemAdapter(item, str(root), str(root), "memory")
            adapter._oxigraph = runtime.return_value
            adapter._oxigraph.reset_store.return_value = True
            adapter._oxigraph.start_server.return_value = True
            adapter._oxigraph.load.return_value = True
            adapter.memory_sampler = MagicMock()
            adapter.memory_sampler.snapshot.return_value = {
                "scope": "docker-container-cgroup-v2",
                "unit": "bytes",
                "sampling_interval_ms": 10.0,
                "sample_errors": 0,
                "phases": {"artifact_open_or_load": {
                    "sample_count": 1,
                    "peak_rss_bytes": 1,
                }},
            }
            self.assertTrue(adapter.start())
            self.assertTrue(adapter.ready())
            adapter._oxigraph.reset_store.assert_called_once_with()
            adapter._oxigraph.load.assert_called_once_with("dataset.nt")

    def test_store_structure_rejects_missing_current(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory)
            (store / "000001.sst").write_bytes(b"sst")
            with self.assertRaisesRegex(ValueError, "CURRENT"):
                _validate_store_structure(store)


if __name__ == "__main__":
    unittest.main()
