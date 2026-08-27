#!/usr/bin/env python3
"""Test the dedicated BSBM HTTP matrix-stage wrapper."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "run_rdf_matrix_http.py"
)
SPEC = importlib.util.spec_from_file_location("run_rdf_matrix_http", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RdfMatrixHttpStageTests(unittest.TestCase):
    def test_http_systems_are_complete_and_in_declaration_order(self):
        self.assertEqual(
            MODULE.HTTP_SYSTEMS,
            (
                "fuseki/default",
                "virtuoso/default",
                "oxigraph/memory",
                "oxigraph/rocksdb",
            ),
        )

    def test_wrapper_uses_separate_http_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            scenario = Path(directory) / "scenario"
            declaration = Path(directory) / "declaration.json"
            declaration.write_text("{}", encoding="utf-8")
            with patch.object(
                MODULE, "RdfExperimentMatrixResource"
            ) as resource_class:
                resource_class.return_value.execute.return_value = True
                success = MODULE.execute_http_stage(
                    scenario, declaration, verbose=False
                )
        self.assertTrue(success)
        resource_class.assert_called_once_with(
            data_path=str(scenario.resolve() / "data"),
            config_path=str(scenario.resolve() / "config"),
            directory=str(scenario.resolve() / "log"),
            verbose=False,
        )
        arguments = resource_class.return_value.execute.call_args.kwargs
        self.assertEqual(arguments["selected_systems"], list(MODULE.HTTP_SYSTEMS))
        self.assertEqual(arguments["results_file"], "raw/bsbm-http-summary.json")
        self.assertEqual(arguments["output_file"], "raw/bsbm-http-results.tar.gz")
        self.assertEqual(
            arguments["failure_results_file"],
            "raw/bsbm-http-failed-summary.json",
        )
        self.assertEqual(
            arguments["failure_output_file"],
            "raw/bsbm-http-failed-results.tar.gz",
        )
        self.assertNotIn("adapter_options", arguments)

    def test_wrapper_propagates_structural_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            scenario = Path(directory) / "scenario"
            declaration = Path(directory) / "declaration.json"
            declaration.write_text("{}", encoding="utf-8")
            with patch.object(
                MODULE, "RdfExperimentMatrixResource"
            ) as resource_class:
                resource_class.return_value.execute.return_value = False
                success = MODULE.execute_http_stage(scenario, declaration)
        self.assertFalse(success)


if __name__ == "__main__":
    unittest.main()
