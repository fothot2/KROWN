#!/usr/bin/env python3
from __future__ import annotations
import unittest
from bench_executor.sparql_http_benchmark import _count_ntriples, _count_select_bindings

class StreamingCountTests(unittest.TestCase):
    def test_select_counts_across_chunk_boundaries(self):
        chunks=[b'{"head":{"vars":["s"]},"results":{"bind',b'ings":[{"s":{"type":"uri","value":"http://e/a"}},',b'{"s":{"type":"literal","value":"x}y\\\"z"}}]}}']
        count,size=_count_select_bindings(chunks)
        self.assertEqual(count,2);self.assertEqual(size,sum(map(len,chunks)))
    def test_select_empty(self):
        self.assertEqual(_count_select_bindings([b'{"results":{"bindings":[]}}'])[0],0)
    def test_select_rejects_incomplete(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):_count_select_bindings([b'{"results":{"bindings":[{}'])
    def test_ntriples_counts_complete_stream(self):
        chunks=[b'# comment\n<s> <p> ',b'<o> .\n\n<s2> <p> <o2> .']
        self.assertEqual(_count_ntriples(chunks),(2,sum(map(len,chunks))))
if __name__=='__main__':unittest.main()
