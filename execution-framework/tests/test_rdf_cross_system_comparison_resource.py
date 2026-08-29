#!/usr/bin/env python3
"""Tests for the generic cross-system RDF comparison resource."""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_cross_system_comparison_resource import (
    RdfCrossSystemComparisonResource,
)


class RdfCrossSystemComparisonResourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.shared = self.root / "data" / "shared"
        self.shared.mkdir(parents=True)
        self.resource = RdfCrossSystemComparisonResource(
            data_path=str(self.root / "data"),
            config_path=str(self.root / "config"),
            directory=str(self.root / "log"),
            verbose=False,
        )
        (self.shared / "manifests").mkdir()
        (self.shared / "raw").mkdir()
        (self.shared / "comparison").mkdir()
        (self.shared / "manifests" / "workload.json").write_text(
            "{}", encoding="utf-8"
        )
        for name in ("one.tar.gz", "two.tar.gz"):
            (self.shared / "raw" / name).write_bytes(b"archive")

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, **overrides):
        arguments = {
            "manifest_file": "manifests/workload.json",
            "archive_files": ["raw/one.tar.gz", "raw/two.tar.gz"],
            "output_file": "raw/comparison.json",
        }
        arguments.update(overrides)
        return self.resource.execute(**arguments)

    @patch(
        "bench_executor.rdf_cross_system_comparison_resource."
        "compare_archives"
    )
    def test_resolves_inputs_and_writes_atomic_report(self, compare):
        compare.return_value = {
            "schema": "rdf-cross-system-comparison-v1",
            "classification_counts": {"strict_match": 1},
        }
        self.assertTrue(self.execute())
        compare.assert_called_once_with(
            (self.shared / "manifests/workload.json").resolve(),
            [
                (self.shared / "raw/one.tar.gz").resolve(),
                (self.shared / "raw/two.tar.gz").resolve(),
            ],
            None,
        )
        output = self.shared / "raw/comparison.json"
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8")),
            compare.return_value,
        )
        self.assertFalse(list(output.parent.glob(".comparison.json.*.tmp")))

    @patch(
        "bench_executor.rdf_cross_system_comparison_resource."
        "compare_archives"
    )
    def test_resolves_optional_policy(self, compare):
        policy = self.shared / "comparison/policy.json"
        policy.write_text("{}", encoding="utf-8")
        compare.return_value = {"schema": "report"}
        self.assertTrue(self.execute(policy_file="comparison/policy.json"))
        self.assertEqual(compare.call_args.args[2], policy.resolve())

    def test_rejects_empty_or_scalar_archive_list(self):
        for value in ([], "raw/one.tar.gz", None):
            with self.subTest(value=value):
                self.assertFalse(self.execute(archive_files=value))

    def test_rejects_missing_and_unsafe_inputs(self):
        cases = (
            {"manifest_file": "../manifest.json"},
            {"archive_files": ["/tmp/result.tar.gz"]},
            {"archive_files": ["raw/missing.tar.gz"]},
            {"policy_file": "../policy.json"},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assertFalse(self.execute(**arguments))

    @patch(
        "bench_executor.rdf_cross_system_comparison_resource."
        "compare_archives",
        side_effect=ValueError("comparison failed"),
    )
    def test_failure_preserves_existing_output_and_removes_temporary(self, _):
        output = self.shared / "raw/comparison.json"
        output.write_text("existing\n", encoding="utf-8")
        self.assertFalse(self.execute())
        self.assertEqual(output.read_text(encoding="utf-8"), "existing\n")
        self.assertFalse(list(output.parent.glob(".comparison.json.*.tmp")))
        self.assertEqual(self.resource.last_outcome, "failure")

    def test_executor_discovers_resource(self):
        module = importlib.import_module(
            "bench_executor.rdf_cross_system_comparison_resource"
        )
        self.assertIs(
            module.RdfCrossSystemComparisonResource,
            RdfCrossSystemComparisonResource,
        )
        parameters = set(
            __import__("inspect").signature(
                RdfCrossSystemComparisonResource.execute
            ).parameters
        )
        self.assertEqual(
            parameters,
            {"self", "manifest_file", "archive_files", "output_file",
             "policy_file"},
        )
        self.assertNotIn("results_file", parameters)


if __name__ == "__main__":
    unittest.main()
