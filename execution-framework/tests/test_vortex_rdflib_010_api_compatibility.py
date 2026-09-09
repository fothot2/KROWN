#!/usr/bin/env python3
import importlib.metadata
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph

from bench_executor.rdflib_query_benchmark import _make_rdflib_graph


class VortexRdflib010ApiCompatibilityTests(unittest.TestCase):
    def test_installed_package_exports_only_current_store_name(self):
        import vortex_rdflib

        self.assertTrue(hasattr(vortex_rdflib, "VortexRdflibStore"))
        self.assertFalse(hasattr(vortex_rdflib, "VortexStore"))
        self.assertEqual(importlib.metadata.version("vortex-rdflib"), "0.1.0")

    def test_worker_opens_vortex_store_by_path_without_layout_override(self):
        calls = []

        class FakeStore:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

        class FakeGraph:
            def __init__(self, *, store):
                self.store = store

        with patch("vortex_rdflib.VortexRdflibStore", FakeStore), \
             patch("bench_executor.rdflib_query_benchmark.Graph", FakeGraph):
            graph = _make_rdflib_graph(
                "vortex", "/tmp/dataset.vortex", "obsolete-layout-label", False
            )

        self.assertIsInstance(graph, FakeGraph)
        self.assertEqual(calls, [((), {"path": "/tmp/dataset.vortex", "in_memory": False})])

    def test_current_constructor_accepts_path(self):
        from vortex_rdflib import VortexRdflibStore

        signature = inspect.signature(VortexRdflibStore)
        self.assertIn("path", signature.parameters)
        self.assertIn("in_memory", signature.parameters)


if __name__ == "__main__":
    unittest.main()
