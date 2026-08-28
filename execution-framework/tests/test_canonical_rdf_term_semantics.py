#!/usr/bin/env python3
"""Test canonical RDF term semantics across RDFLib and SPARQL JSON."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Literal, URIRef, Variable

from bench_executor.sparql_result import (
    _normalize_term,
    normalize_materialized_result,
    normalize_sparql_json_result,
)

XSD = 'http://www.w3.org/2001/XMLSchema#'


class CanonicalRdfTermSemanticsTests(unittest.TestCase):
    def test_int_and_integer_are_equivalent(self):
        self.assertEqual(
            _normalize_term(Literal('3', datatype=URIRef(XSD + 'int'))),
            _normalize_term(Literal('3', datatype=URIRef(XSD + 'integer'))),
        )

    def test_plain_and_xsd_string_are_equivalent(self):
        self.assertEqual(
            _normalize_term(Literal('value')),
            _normalize_term(Literal('value', datatype=URIRef(XSD + 'string'))),
        )

    def test_language_and_custom_datatypes_are_preserved(self):
        language = _normalize_term(Literal('hello', lang='en'))
        custom = _normalize_term(Literal('1.25', datatype=URIRef('http://example/USD')))
        self.assertEqual(language['language'], 'en')
        self.assertIsNone(language['datatype'])
        self.assertEqual(custom['datatype'], 'http://example/USD')

    def test_sparql_json_and_rdflib_select_fingerprints_match(self):
        class Result:
            type = 'SELECT'
            vars = [Variable('text'), Variable('number')]

        query = 'SELECT ?text ?number WHERE { ?s ?p ?o }'
        rdflib_result = normalize_materialized_result(Result(), [(
            Literal('value', datatype=URIRef(XSD + 'string')),
            Literal('3', datatype=URIRef(XSD + 'integer')),
        )], query)
        json_result = normalize_sparql_json_result({
            'head': {'vars': ['text', 'number']},
            'results': {'bindings': [{
                'text': {'type': 'literal', 'value': 'value'},
                'number': {
                    'type': 'literal', 'value': '3',
                    'datatype': XSD + 'int',
                },
            }]},
        }, query)
        self.assertEqual(
            rdflib_result['result_fingerprint'],
            json_result['result_fingerprint'],
        )


if __name__ == '__main__':
    unittest.main()
