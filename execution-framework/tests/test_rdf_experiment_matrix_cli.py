#!/usr/bin/env python3
"""Tests for the benchmark-neutral RDF experiment-matrix CLI."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "run_rdf_experiment_matrix.py"
SPEC = importlib.util.spec_from_file_location("run_rdf_experiment_matrix", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RdfExperimentMatrixCliTests(unittest.TestCase):
    def test_system_parser_accepts_repeated_and_comma_separated_values(self):
        self.assertEqual(
            MODULE.parse_systems(["fuseki/default,oxigraph/memory", "qlever/default"]),
            ["fuseki/default", "oxigraph/memory", "qlever/default"],
        )

    def test_system_parser_rejects_duplicates_and_invalid_identity(self):
        for values in (["fuseki/default", "fuseki/default"], ["fuseki"]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                MODULE.parse_systems(values)

    def test_cli_rejects_absolute_and_parent_artifact_paths(self):
        for value in ("/tmp/result.json", "../result.json", ""):
            with self.subTest(value=value), self.assertRaises(Exception):
                MODULE._relative_shared_path(value)

    def test_execute_passes_only_declared_generic_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            scenario = Path(directory) / "scenario"
            declaration = Path(directory) / "declaration.json"
            declaration.write_text("{}", encoding="utf-8")
            with patch.object(MODULE, "RdfExperimentMatrixResource") as resource:
                resource.return_value.execute.return_value = True
                success = MODULE.execute_matrix(
                    scenario=scenario,
                    declaration=declaration,
                    manifest="manifests/workload.json",
                    systems=["qlever/default"],
                    results="raw/summary.json",
                    output="raw/results.tar.gz",
                    failure_results="raw/failed-summary.json",
                    failure_output="raw/failed-results.tar.gz",
                    verbose=False,
                )
        self.assertTrue(success)
        resource.assert_called_once_with(
            data_path=str(scenario.resolve() / "data"),
            config_path=str(scenario.resolve() / "config"),
            directory=str(scenario.resolve() / "log"),
            verbose=False,
        )
        resource.return_value.execute.assert_called_once_with(
            declaration_file=str(declaration.resolve()),
            manifest_file="manifests/workload.json",
            results_file="raw/summary.json",
            output_file="raw/results.tar.gz",
            selected_systems=["qlever/default"],
            failure_results_file="raw/failed-summary.json",
            failure_output_file="raw/failed-results.tar.gz",
        )

    def test_main_propagates_structural_failure(self):
        arguments = [
            "--scenario", "/tmp/scenario",
            "--declaration", "/tmp/declaration.json",
            "--manifest", "manifests/workload.json",
            "--system", "qlever/default",
            "--results", "raw/summary.json",
            "--output", "raw/results.tar.gz",
            "--failure-results", "raw/failed-summary.json",
            "--failure-output", "raw/failed-results.tar.gz",
        ]
        with patch.object(MODULE, "execute_matrix", return_value=False):
            self.assertEqual(MODULE.main(arguments), 1)


if __name__ == "__main__":
    unittest.main()
