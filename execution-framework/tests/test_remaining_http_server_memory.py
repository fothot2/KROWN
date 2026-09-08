#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.fuseki_system_adapter import FusekiSystemAdapter
from bench_executor.qlever_system_adapter import QLeverSystemAdapter
from bench_executor.virtuoso_system_adapter import VirtuosoSystemAdapter


class RemainingHttpServerMemoryTests(unittest.TestCase):
    def test_fuseki_uses_only_the_query_server_container(self):
        adapter = FusekiSystemAdapter.__new__(FusekiSystemAdapter)
        self.assertEqual(adapter.memory_container, 'Fuseki')

    def test_virtuoso_uses_only_the_query_server_container(self):
        adapter = VirtuosoSystemAdapter.__new__(VirtuosoSystemAdapter)
        self.assertEqual(adapter.memory_container, 'Virtuoso')

    def test_qlever_excludes_the_index_build_container(self):
        adapter = QLeverSystemAdapter.__new__(QLeverSystemAdapter)
        self.assertEqual(adapter.memory_container, 'qlever_server')
        self.assertNotEqual(adapter.memory_container, 'qlever_index')


if __name__ == '__main__':
    unittest.main()
