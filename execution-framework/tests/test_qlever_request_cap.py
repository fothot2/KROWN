#!/usr/bin/env python3
"""Regression tests for the QLever request-cap contract."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.sparql_http_benchmark import _SparqlHttpAdapter


class FakeResponse:
    status_code = 200
    headers = {'Content-Type': 'application/sparql-results+json'}

    def __init__(self):
        self.content_reads = 0

    @property
    def content(self):
        self.content_reads += 1
        return b'{}'

    def raise_for_status(self):
        return None

    def json(self):
        return {'head': {'vars': []}, 'results': {'bindings': []}}


class QLeverRequestCapTests(unittest.TestCase):
    def adapter(self, request_max_rows=None, system='qlever/default'):
        response = FakeResponse()
        adapter = _SparqlHttpAdapter(
            'http://example.test', 1.0, system=system,
            request_max_rows=request_max_rows,
        )
        adapter._session = MagicMock()
        adapter._session.post.return_value = response
        return adapter, response

    def test_qlever_has_no_default_request_cap(self):
        adapter, response = self.adapter()
        outcome = adapter.execute('SELECT * WHERE { ?s ?p ?o }')
        data = adapter._session.post.call_args.kwargs['data']
        self.assertEqual(data, {'query': 'SELECT * WHERE { ?s ?p ?o }'})
        self.assertEqual(response.content_reads, 1)
        self.assertFalse(outcome.metadata['result_cap_requested'])
        self.assertIsNone(outcome.metadata['request_max_rows'])

    def test_explicit_qlever_request_cap_is_sent_and_recorded(self):
        adapter, _ = self.adapter(4000000)
        outcome = adapter.execute('SELECT * WHERE { ?s ?p ?o }')
        data = adapter._session.post.call_args.kwargs['data']
        self.assertEqual(data['maxrows'], '4000000')
        self.assertTrue(outcome.metadata['result_cap_requested'])
        self.assertEqual(outcome.metadata['request_max_rows'], 4000000)

    def test_request_cap_rejects_invalid_values(self):
        for value in (0, -1, True, 1.5, '3000000'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _SparqlHttpAdapter(
                    'http://example.test', 1.0,
                    system='qlever/default', request_max_rows=value,
                )

    def test_request_cap_is_qlever_only(self):
        with self.assertRaisesRegex(ValueError, 'qlever/default'):
            _SparqlHttpAdapter(
                'http://example.test', 1.0,
                system='fuseki/default', request_max_rows=10,
            )

    def test_full_result_retention_limit_does_not_cap_request(self):
        response = FakeResponse()
        adapter = _SparqlHttpAdapter(
            'http://example.test', 1.0,
            correctness_mode='full', full_result_max_rows=0,
            system='qlever/default',
        )
        adapter._session = MagicMock()
        adapter._session.post.return_value = response
        outcome = adapter.execute('SELECT * WHERE { ?s ?p ?o }')
        self.assertNotIn('maxrows', adapter._session.post.call_args.kwargs['data'])
        self.assertTrue(outcome.metadata['full_result_retained'])
        self.assertIsNotNone(outcome.result_fingerprint)


if __name__ == '__main__':
    unittest.main()
