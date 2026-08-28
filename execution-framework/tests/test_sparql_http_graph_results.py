#!/usr/bin/env python3
"""Test SPARQL HTTP SELECT, ASK, CONSTRUCT, and DESCRIBE responses."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.sparql_http_benchmark import _SparqlHttpAdapter


class FakeResponse:
    def __init__(self, body, content_type, document=None):
        self.content = body
        self.headers = {'Content-Type': content_type}
        self.status_code = 200
        self._document = document

    def raise_for_status(self):
        return None

    def json(self):
        if self._document is None:
            raise ValueError('not JSON')
        return self._document


class SparqlHttpGraphResultTests(unittest.TestCase):
    def adapter(self, response):
        adapter = _SparqlHttpAdapter('http://example.test/query', 1.0)
        adapter._session = MagicMock()
        adapter._session.post.return_value = response
        return adapter

    def test_select_keeps_sparql_json_normalization(self):
        document = {
            'head': {'vars': ['s']},
            'results': {'bindings': [{
                's': {'type': 'uri', 'value': 'http://example/s'},
            }]},
        }
        adapter = self.adapter(FakeResponse(
            b'{}', 'application/sparql-results+json; charset=utf-8', document
        ))
        outcome = adapter.execute('SELECT ?s WHERE { ?s ?p ?o }')
        self.assertEqual(outcome.result_count, 1)
        self.assertIsNotNone(outcome.result_fingerprint)
        headers = adapter._session.post.call_args.kwargs['headers']
        self.assertEqual(headers['Accept'], 'application/sparql-results+json')

    def test_graph_result_accepts_turtle(self):
        body = b'@prefix ex: <http://example/> . ex:s ex:p ex:o .\n'
        adapter = self.adapter(FakeResponse(body, 'text/turtle; charset=utf-8'))
        outcome = adapter.execute('CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }')
        self.assertEqual(outcome.result_count, 1)
        self.assertIsNotNone(outcome.result_fingerprint)
        headers = adapter._session.post.call_args.kwargs['headers']
        self.assertNotIn('application/sparql-results+json', headers['Accept'])
        self.assertIn('application/n-triples', headers['Accept'])
        self.assertIn('text/turtle', headers['Accept'])

    def test_graph_fingerprint_is_triple_order_independent(self):
        first = self.adapter(FakeResponse(
            b'<http://e/a> <http://e/p> <http://e/b> .\n'
            b'<http://e/c> <http://e/p> <http://e/d> .\n',
            'application/n-triples',
        )).execute('DESCRIBE <http://e/a>')
        second = self.adapter(FakeResponse(
            b'<http://e/c> <http://e/p> <http://e/d> .\n'
            b'<http://e/a> <http://e/p> <http://e/b> .\n',
            'application/n-triples',
        )).execute('DESCRIBE <http://e/a>')
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)


    def test_graph_canonicalizes_int_and_integer(self):
        first = self.adapter(FakeResponse(
            b'<http://e/s> <http://e/p> "3"^^<http://www.w3.org/2001/XMLSchema#int> .\n',
            'application/n-triples',
        )).execute('CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }')
        second = self.adapter(FakeResponse(
            b'<http://e/s> <http://e/p> "3"^^<http://www.w3.org/2001/XMLSchema#integer> .\n',
            'application/n-triples',
        )).execute('CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }')
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)

    def test_graph_canonicalizes_plain_and_xsd_string(self):
        first = self.adapter(FakeResponse(
            b'<http://e/s> <http://e/p> "value" .\n',
            'application/n-triples',
        )).execute('CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }')
        second = self.adapter(FakeResponse(
            b'<http://e/s> <http://e/p> "value"^^<http://www.w3.org/2001/XMLSchema#string> .\n',
            'application/n-triples',
        )).execute('CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }')
        self.assertEqual(first.result_fingerprint, second.result_fingerprint)

    def test_unknown_response_type_is_reported(self):
        adapter = self.adapter(FakeResponse(b'not RDF', 'text/html'))
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
            adapter.execute('CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }')


if __name__ == '__main__':
    unittest.main()
