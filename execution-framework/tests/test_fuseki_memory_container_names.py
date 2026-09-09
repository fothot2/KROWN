#!/usr/bin/env python3
from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_executor.fuseki import MEMORY_MODE, TDB2_MODE
from bench_executor.fuseki_system_adapter import FusekiSystemAdapter

class FusekiMemoryContainerNameTests(unittest.TestCase):
    def test_memory_mode_uses_actual_container_name(self):
        adapter = FusekiSystemAdapter.__new__(FusekiSystemAdapter)
        adapter._dataset_mode = MEMORY_MODE
        self.assertEqual(adapter.memory_container, 'Fuseki-memory')

    def test_tdb2_mode_uses_actual_container_name(self):
        adapter = FusekiSystemAdapter.__new__(FusekiSystemAdapter)
        adapter._dataset_mode = TDB2_MODE
        self.assertEqual(adapter.memory_container, 'Fuseki-tdb2')

    def test_missing_mode_keeps_legacy_tdb2_test_semantics(self):
        adapter = FusekiSystemAdapter.__new__(FusekiSystemAdapter)
        self.assertEqual(adapter.memory_container, 'Fuseki-tdb2')

if __name__ == '__main__':
    unittest.main()
