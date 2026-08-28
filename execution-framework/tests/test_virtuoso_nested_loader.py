#!/usr/bin/env python3
"""Regression tests for nested Virtuoso loader paths."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

FRAMEWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK))

from bench_executor.virtuoso import _count_ntriples, _split_loader_path


class VirtuosoNestedLoaderTests(unittest.TestCase):
    def test_nested_artifact_uses_parent_directory_and_basename(self):
        self.assertEqual(
            _split_loader_path("rdf-matrix-artifacts/rdf--source--0.nt"),
            ("/usr/share/proj/rdf-matrix-artifacts", "rdf--source--0.nt"),
        )

    def test_optional_directory_is_combined_safely(self):
        self.assertEqual(
            _split_loader_path("nested/data.nt", "benchmark"),
            ("/usr/share/proj/benchmark/nested", "data.nt"),
        )

    def test_loader_path_rejects_absolute_and_parent_escape(self):
        for path in ("/data.nt", "../data.nt", "nested/../../data.nt"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    _split_loader_path(path)

    def test_ntriples_count_ignores_empty_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.nt"
            path.write_bytes(
                b"# comment\n\n<s> <p> <o> .\n  # another comment\n<s2> <p> <o> .\n"
            )
            self.assertEqual(_count_ntriples(str(path)), 2)


if __name__ == "__main__":
    unittest.main()
