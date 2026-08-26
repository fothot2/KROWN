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


if __name__ == "__main__":
    unittest.main()
