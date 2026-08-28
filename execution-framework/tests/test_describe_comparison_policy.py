#!/usr/bin/env python3
"""Regression tests for implementation-defined DESCRIBE comparison."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import URIRef

from bench_executor.query_features import classify_query, comparison_metadata
from bench_executor.sparql_result import normalize_graph_terms


class DescribeComparisonPolicyTests(unittest.TestCase):
    def test_describe_is_implementation_defined(self):
        features = classify_query('DESCRIBE <http://example/s>')
        metadata = comparison_metadata(features, False)

        self.assertEqual(features.result_type, 'describe')
        self.assertEqual(
            metadata['comparison_mode'],
            'implementation_defined_describe',
        )
        self.assertIn('implementation-defined', metadata['comparison_warning'])

    def test_describe_policy_precedes_blank_node_policy(self):
        metadata = comparison_metadata(
            classify_query('DESCRIBE ?s WHERE { ?s ?p ?o }'),
            True,
        )

        self.assertEqual(
            metadata['comparison_mode'],
            'implementation_defined_describe',
        )

    def test_describe_retains_count_and_fingerprint(self):
        result = normalize_graph_terms(
            [(URIRef('http://e/s'), URIRef('http://e/p'), URIRef('http://e/o'))],
            'DESCRIBE <http://e/s>',
        )

        self.assertEqual(result['result_count'], 1)
        self.assertIsInstance(result['result_fingerprint'], str)
        self.assertEqual(len(result['result_fingerprint']), 64)
        self.assertEqual(
            result['comparison_mode'],
            'implementation_defined_describe',
        )

    def test_construct_remains_strictly_comparable(self):
        metadata = comparison_metadata(
            classify_query(
                'CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }'
            ),
            False,
        )

        self.assertEqual(
            metadata['comparison_mode'],
            'unordered_multiset_fingerprint',
        )
        self.assertIsNone(metadata['comparison_warning'])

    def test_select_and_ask_policies_are_unchanged(self):
        select = comparison_metadata(
            classify_query('SELECT ?s WHERE { ?s ?p ?o }'),
            False,
        )
        ask = comparison_metadata(
            classify_query('ASK { ?s ?p ?o }'),
            False,
        )

        self.assertEqual(
            select['comparison_mode'],
            'unordered_multiset_fingerprint',
        )
        self.assertEqual(ask['comparison_mode'], 'boolean')


if __name__ == '__main__':
    unittest.main()
