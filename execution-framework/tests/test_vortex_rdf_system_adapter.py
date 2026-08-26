#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
from bench_executor.vortex_rdf_system_adapter import (
    VortexRdfRuntimeConfiguration,
    VortexRdfSystemAdapter,
)


class VortexRdfSystemAdapterTests(unittest.TestCase):
    def artifact(self, path: Path, representation: str):
        payload = path.read_bytes()
        import hashlib
        return DatasetArtifact(
            benchmark="bsbm", dataset="explore-1k", source_format="ntriples",
            source_size_bytes=10, source_sha256="a" * 64,
            representation=representation,
            files=(ArtifactFile(
                path=path.name, size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            ),),
        )

    def test_runtime_keeps_binding_alias_separate(self):
        runtime = VortexRdfRuntimeConfiguration()
        self.assertEqual(runtime.system_id, "vortex-rdf/simple-dictionary-native-rdf-store")
        self.assertEqual(runtime.representation, runtime.system_id)
        self.assertEqual(runtime.storage_layout, "native-rdf-store")
        self.assertEqual(runtime.store_layout, "cottas-native-ids")
        specification = runtime.adapter_specification()
        self.assertEqual(specification.configuration.kind, "embedded")
        self.assertEqual(specification.parameters["vortex_layout"], "cottas-native-ids")

    def test_custom_store_layout_is_one_field_change(self):
        runtime = VortexRdfRuntimeConfiguration(store_layout="native-rdf-store")
        self.assertEqual(runtime.store_layout, "native-rdf-store")
        self.assertEqual(runtime.representation, "vortex-rdf/simple-dictionary-native-rdf-store")

    def test_prepare_and_query_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "shared"
            shared.mkdir()
            path = shared / "dataset.vortex"
            path.write_bytes(b"vortex")
            runtime = VortexRdfRuntimeConfiguration()
            adapter = VortexRdfSystemAdapter(
                self.artifact(path, runtime.representation), directory, runtime,
            )
            self.assertEqual(adapter.lifecycle, ("prepare", "execute", "collect"))
            self.assertTrue(adapter.prepare())
            parameters = adapter.query_parameters()
            self.assertEqual(parameters["engine"], "vortex")
            self.assertEqual(parameters["vortex_layout"], "cottas-native-ids")
            command = adapter.docker_smoke_command(
                "SELECT * WHERE { ?s ?p ?o } LIMIT 1"
            )
            self.assertIn("VortexStore", command[-1])
            self.assertIn("cottas-native-ids", command[-1])

    def test_rejects_representation_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / "shared"
            shared.mkdir()
            path = shared / "dataset.vortex"
            path.write_bytes(b"x")
            runtime = VortexRdfRuntimeConfiguration()
            with self.assertRaisesRegex(ValueError, "representation differs"):
                VortexRdfSystemAdapter(
                    self.artifact(path, "vortex-rdf/other"), directory, runtime,
                )


if __name__ == "__main__":
    unittest.main()
