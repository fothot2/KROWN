#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    'dbbench_launcher', ROOT / 'prepare_and_run_dbbench_campaign_v1.py'
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DbbenchOvernightLauncherTests(unittest.TestCase):
    def test_gate_invalid_set_is_stable_and_exact(self):
        invalid, evidence = MODULE.validated_invalid_source_queries()
        self.assertEqual(len(invalid), 20)
        self.assertEqual(len(evidence), 20)
        self.assertEqual(
            {item['source_query_id'] for item in evidence}, invalid
        )

    def test_preexpanded_manifest_excludes_invalid_queries(self):
        base = json.loads(
            (MODULE.DBBENCH / 'generated/dbpedia-full-base.json').read_text()
        )
        invalid, _ = MODULE.validated_invalid_source_queries()
        manifest = MODULE.preexpanded_manifest(base, invalid)
        self.assertEqual(manifest['source_query_count'], 4808)
        self.assertEqual(manifest['measured_query_count'], 4808)
        source_ids = {
            query['source_query_id'] for query in manifest['queries']
        }
        self.assertTrue(invalid.isdisjoint(source_ids))
        positions = [query['stream_position'] for query in manifest['queries']]
        self.assertEqual(positions, list(range(len(positions))))

    def test_repetitions_is_forwarded(self):
        argv = [
            'prepare_and_run_dbbench_campaign_v1.py',
            '--campaign-id', 'unit-test', '--repetitions', '1', '--dry-run',
            '--system', 'vortex-rdf/dictionary-secondary-by-copy-memory',
        ]
        with patch.object(sys, 'argv', argv):
            self.assertEqual(MODULE.main(), 0)


if __name__ == '__main__':
    unittest.main()
