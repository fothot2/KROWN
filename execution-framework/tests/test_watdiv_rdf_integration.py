#!/usr/bin/env python3
"""Focused static integration tests for benchmark-owned WatDiv assets."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = Path("/users/u0182905/benchmarks")
sys.path.insert(0, str(ROOT / "execution-framework"))

from bench_executor.rdf_experiment_manifest import load_rdf_experiment_declaration


class WatDivRdfIntegrationTests(unittest.TestCase):
    def test_external_scenario_metadata_binds_accepted_benchmark_commit(self):
        expected = {
            "watdiv-10m": {"smoke", "full"},
            "watdiv-100m": {"full"},
        }
        for dataset, modes in expected.items():
            path = ROOT / "benchmark-integration" / dataset / "metadata.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["schema"], "krown-external-benchmark-scenario-v1")
            self.assertEqual(value["benchmark"], "watdiv")
            self.assertEqual(value["dataset"], dataset)
            self.assertEqual(value["benchmark_repository"], str(BENCHMARKS))
            self.assertEqual(
                value["benchmark_commit"],
                "c273ecc48aebb01f6bda986b057b9fd0197511dc",
            )
            self.assertEqual(set(value["declarations"]), modes)
            self.assertEqual(set(value["manifests"]), modes)
            self.assertTrue(Path(value["source"]["path"]).is_file())

    def test_declarations_resolve_all_selected_representation_receipts(self):
        cases = (
            ("watdiv-10m-smoke.json", "watdiv-10m"),
            ("watdiv-10m-full.json", "watdiv-10m"),
            ("watdiv-100m-full.json", "watdiv-100m"),
        )
        selected = [
            "hdt-rdflib/optimized-in-memory",
            "pycottas/default",
            "rdflib/default",
            "vortex-rdf/dictionary-secondary-by-reference",
            "vortex-rdf/dictionary-secondary-by-copy",
        ]
        expected_representations = {
            "rdf/source",
            "hdt/default",
            "cottas/default",
            "vortex-rdf/dictionary-secondary-by-reference",
            "vortex-rdf/dictionary-secondary-by-copy",
        }
        for name, dataset in cases:
            declaration = BENCHMARKS / "WatDiv/experiments" / name
            experiments, artifacts = load_rdf_experiment_declaration(
                declaration,
                benchmark_root=BENCHMARKS / "WatDiv",
                selected_systems=selected,
                verify_artifact_files=False,
            )
            self.assertEqual(
                [item.system_configuration for item in experiments], selected
            )
            self.assertEqual(set(artifacts), expected_representations)
            self.assertTrue(all(item.dataset == dataset for item in artifacts.values()))
            identities = {
                (item.source_size_bytes, item.source_sha256)
                for item in artifacts.values()
            }
            self.assertEqual(len(identities), 1)

    def test_metadata_does_not_embed_generation_or_runtime_steps(self):
        for dataset in ("watdiv-10m", "watdiv-100m"):
            value = json.loads((
                ROOT / "benchmark-integration" / dataset / "metadata.json"
            ).read_text(encoding="utf-8"))
            self.assertNotIn("steps", value)
            self.assertNotIn("representation_build_command", value)
            self.assertNotIn("systems", value)


if __name__ == "__main__":
    unittest.main()
