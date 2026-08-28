#!/usr/bin/env python3
"""Regression tests for Virtuoso default graph loading."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

FRAMEWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK))

from bench_executor.sparql_http_benchmark import (
    _SparqlHttpAdapter,
    _VIRTUOSO_DEFAULT_GRAPH,
)
from bench_executor.virtuoso import (
    LOAD_GRAPH_IRI,
    SPARQL_ENDPOINT,
    _ld_dir_command,
)


class VirtuosoDefaultGraphTests(unittest.TestCase):
    def test_query_uses_loader_graph_as_post_default(self):
        adapter = _SparqlHttpAdapter(
            SPARQL_ENDPOINT, 5.0, system="virtuoso/default"
        )
        response = MagicMock()
        response.content = b'{"head": {"vars": []}, "results": {"bindings": []}}'
        response.headers = {"Content-Type": "application/sparql-results+json"}
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "head": {"vars": []}, "results": {"bindings": []},
        }
        adapter._session = MagicMock()
        adapter._session.post.return_value = response
        adapter.execute("SELECT * WHERE { ?s ?p ?o } LIMIT 1")
        call = adapter._session.post.call_args
        self.assertEqual(call.args[0], SPARQL_ENDPOINT)
        self.assertEqual(
            call.kwargs["data"]["default-graph-uri"], LOAD_GRAPH_IRI
        )
        self.assertEqual(_VIRTUOSO_DEFAULT_GRAPH, LOAD_GRAPH_IRI)

    def test_loader_registers_the_same_graph(self):
        command = _ld_dir_command(
            "/usr/share/proj/rdf-matrix-artifacts",
            "rdf--source--0.nt",
        )
        self.assertIn("ld_dir(", command)
        self.assertIn("'/usr/share/proj/rdf-matrix-artifacts'", command)
        self.assertIn("'rdf--source--0.nt'", command)
        self.assertIn(f"'{LOAD_GRAPH_IRI}'", command)
        self.assertNotIn("default-graph-uri", command)

    def test_contract_does_not_enable_union_default_graph(self):
        self.assertNotIn("default-graph-uri", SPARQL_ENDPOINT)
        self.assertNotIn("union", SPARQL_ENDPOINT.lower())
        self.assertEqual(LOAD_GRAPH_IRI, "http://example.com/graph")


if __name__ == "__main__":
    unittest.main()
