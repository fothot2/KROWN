#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
from bench_executor.fuseki import Fuseki, MEMORY_MODE, TDB2_MODE
from bench_executor.fuseki_system_adapter import FusekiSystemAdapter
from bench_executor.rdf_experiment_manifest import system_adapter_specifications


def artifact():
    return DatasetArtifact(
        "bsbm", "explore-10k", "ntriples", 3, "a" * 64, "rdf/source",
        (ArtifactFile("dataset.nt", 3, "b" * 64),),
    )


class FusekiDualModeTests(unittest.TestCase):
    def test_registry_has_only_canonical_dual_modes(self):
        specifications = {
            item.system_id: item for item in system_adapter_specifications()
        }
        self.assertIn("fuseki/memory", specifications)
        self.assertIn("fuseki/tdb2", specifications)
        self.assertNotIn("fuseki/default", specifications)
        self.assertEqual(
            specifications["fuseki/memory"].configuration.parameters["dataset_mode"],
            MEMORY_MODE,
        )
        self.assertEqual(
            specifications["fuseki/tdb2"].configuration.parameters["dataset_mode"],
            TDB2_MODE,
        )

    def test_runtime_commands_and_mounts_are_mode_specific(self):
        in_memory = Fuseki(
            "data", "config", "log", False, MEMORY_MODE
        )
        tdb2 = Fuseki(
            "data", "config", "log", False, TDB2_MODE
        )
        self.assertEqual(in_memory.command_arguments, "--mem --update /ds")
        self.assertEqual(tdb2.command_arguments, "--tdb2 --update --loc /fuseki/databases/DB /ds")
        self.assertNotIn("/fuseki/databases/DB", " ".join(in_memory._volumes))
        self.assertIn("/fuseki/databases/DB", " ".join(tdb2._volumes))
        memory_adapter = FusekiSystemAdapter.__new__(FusekiSystemAdapter)
        memory_adapter._dataset_mode = MEMORY_MODE
        tdb2_adapter = FusekiSystemAdapter.__new__(FusekiSystemAdapter)
        tdb2_adapter._dataset_mode = TDB2_MODE
        self.assertEqual(memory_adapter.memory_container, "Fuseki-memory")
        self.assertEqual(tdb2_adapter.memory_container, "Fuseki-tdb2")

    def test_memory_metrics_are_explicitly_not_applicable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = root / "shared"
            shared.mkdir()
            source = shared / "dataset.nt"
            source.write_bytes(b"abc")
            item = artifact().files[0]
            item = ArtifactFile(item.path, 3, __import__("hashlib").sha256(b"abc").hexdigest())
            data = DatasetArtifact("bsbm", "explore-10k", "ntriples", 3, "a" * 64, "rdf/source", (item,))
            with patch("bench_executor.fuseki_system_adapter.Fuseki") as runtime:
                instance = runtime.return_value
                instance.wait_until_ready.return_value = True
                instance.load.return_value = True
                instance.endpoint = "http://localhost:3030/ds/sparql"
                adapter = FusekiSystemAdapter(data, str(root), str(root), str(root), False, MEMORY_MODE)
                self.assertTrue(adapter.prepare())
                adapter.memory_sampler = MagicMock()
                adapter.memory_sampler.snapshot.return_value = {
                    "scope": "docker-container-cgroup-v2",
                    "unit": "bytes",
                    "sampling_interval_ms": 10.0,
                    "sample_errors": 0,
                    "phases": {
                        "artifact_open_or_load": {
                            "sample_count": 1,
                            "peak_rss_bytes": 10,
                        },
                    },
                }
                self.assertTrue(adapter.start())
                self.assertTrue(adapter.ready())
        self.assertEqual(adapter.build_metrics["boundary"], "not-applicable")
        self.assertEqual(adapter.representation_size["boundary"], "not-applicable")
        self.assertEqual(adapter.load_metrics["status"], "ok")
        instance.reset_store.assert_not_called()

    def test_tdb2_keeps_build_and_size_metrics(self):
        adapter = FusekiSystemAdapter.__new__(FusekiSystemAdapter)
        adapter._dataset_mode = TDB2_MODE
        adapter._data_path = Path("/tmp")
        adapter._rdf_file = SimpleNamespace(path="dataset.nt")
        adapter._fuseki = MagicMock()
        adapter._fuseki.load.return_value = True
        adapter.memory_sampler = MagicMock()
        adapter.memory_sampler.snapshot.return_value = {
            "scope": "docker-container-cgroup-v2",
            "unit": "bytes",
            "sampling_interval_ms": 10.0,
            "sample_errors": 0,
            "phases": {
                "artifact_open_or_load": {
                    "sample_count": 2,
                    "peak_rss_bytes": 20,
                },
            },
        }
        with patch("bench_executor.fuseki_system_adapter.measure_persistent_paths", return_value={"logical_bytes": 7}):
            self.assertTrue(adapter.ready())
        self.assertEqual(adapter.build_metrics["status"], "ok")
        self.assertEqual(adapter.representation_size["logical_bytes"], 7)


if __name__ == "__main__":
    unittest.main()
