#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
FRAMEWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK))
from bench_executor.sparql_http_benchmark import _correct_qlever_integer_datatypes
XSD_INT = "http://www.w3.org/2001/XMLSchema#int"
XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"

class Tests(unittest.TestCase):
    def test_corrects_int_without_mutation(self):
        source = {"head": {"vars": ["x"]}, "results": {"bindings": [{"x": {"type": "literal", "value": "3", "datatype": XSD_INT}}]}, "meta": {"result-size-total": 1}}
        result = _correct_qlever_integer_datatypes(source)
        self.assertEqual(result["results"]["bindings"][0]["x"]["datatype"], XSD_INTEGER)
        self.assertEqual(source["results"]["bindings"][0]["x"]["datatype"], XSD_INT)
        self.assertEqual(result["meta"], source["meta"])

    def test_preserves_other_datatypes(self):
        source = {"results": {"bindings": [{"x": {"type": "literal", "value": "1.2", "datatype": "http://www.w3.org/2001/XMLSchema#decimal"}}, {}]}}
        self.assertIs(_correct_qlever_integer_datatypes(source), source)

    def test_preserves_ask(self):
        source = {"boolean": True, "head": {}}
        self.assertIs(_correct_qlever_integer_datatypes(source), source)

if __name__ == "__main__":
    unittest.main()
