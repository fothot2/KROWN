#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / 'run_watdiv_10m_smoke_v1.py'
SPEC = importlib.util.spec_from_file_location('run_watdiv_10m_smoke_v1', MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WatDiv10mSmokeLauncherTests(unittest.TestCase):
    def test_gate_keeps_one_physical_occurrence_per_stream(self):
        queries = []
        for stream in MODULE.STREAMS:
            phase = 'warmup' if stream == 'warmup' else 'measured'
            for position in range(12400):
                text = f'SELECT * WHERE {{ <{stream}> <p> <{position}> }}'
                queries.append({
                    'query_id': f'{stream}-{position}',
                    'query': text,
                    'query_sha256': hashlib.sha256(text.encode()).hexdigest(),
                    'phase': phase,
                    'stream': stream,
                    'position': position,
                    'native_query_id': position + 1,
                })
        full = {
            'schema_version': 1,
            'workload': 'watdiv-stress-100',
            'dataset': 'watdiv-10m',
            'query_count': 74400,
            'stream_order': list(MODULE.STREAMS),
            'queries': queries,
        }
        with tempfile.TemporaryDirectory() as directory:
            original_gate = MODULE.GATE_MANIFEST
            original_full = MODULE.FULL_MANIFEST
            MODULE.GATE_MANIFEST = Path(directory) / 'gate.json'
            MODULE.FULL_MANIFEST = Path(directory) / 'source.json'
            try:
                MODULE.FULL_MANIFEST.write_text(json.dumps(full))
                gate = MODULE.build_gate_manifest(full)
            finally:
                MODULE.GATE_MANIFEST = original_gate
                MODULE.FULL_MANIFEST = original_full
        self.assertEqual(len(gate['queries']), 6)
        self.assertEqual([item['stream'] for item in gate['queries']], list(MODULE.STREAMS))
        self.assertEqual(
            [item['stream_position'] for item in gate['queries']], list(range(6))
        )
        self.assertEqual(
            [item['stream_phase'] for item in gate['queries']],
            ['warmup', 'measured', 'measured', 'measured', 'measured', 'measured'],
        )
        for item in gate['queries']:
            self.assertNotIn('benchmark', item)
            self.assertNotIn('dataset', item)
            self.assertNotIn('workload', item)
            self.assertNotIn('phase', item)
            self.assertNotIn('position', item)
        self.assertEqual(gate['gate_selection']['source_query_count'], 74400)

    def test_gate_loads_and_builds_records_without_reserved_collisions(self):
        import sys
        sys.path.insert(0, str(ROOT / 'execution-framework'))
        from bench_executor.rdf_query_benchmark import (
            _load_query_manifest, _RdfQueryBenchmark,
        )

        full = json.loads(MODULE.FULL_MANIFEST.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            original_gate = MODULE.GATE_MANIFEST
            MODULE.GATE_MANIFEST = Path(directory) / 'gate.json'
            try:
                MODULE.build_gate_manifest(full)
                manifest = _load_query_manifest(str(MODULE.GATE_MANIFEST))
            finally:
                MODULE.GATE_MANIFEST = original_gate
        benchmark = _RdfQueryBenchmark(
            adapter_factory=lambda: None,
            experiment_id='watdiv-gate-test',
            system='rdflib/default',
            manifest=manifest,
            warmup_runs=0,
            measured_runs=1,
        )
        records = [
            benchmark._base_record(
                query,
                query.metadata['stream_phase'],
                0,
                index,
                index,
            )
            for index, query in enumerate(manifest.queries)
        ]
        self.assertEqual(len(records), 6)
        self.assertEqual([item['stream_position'] for item in records], list(range(6)))
        self.assertTrue(all(item['dataset'] == 'watdiv-10m' for item in records))
        self.assertTrue(all(item['workload'] == 'watdiv-stress-100-rdflib-gate' for item in records))

    def test_gate_allows_large_rdflib_source_startup(self):
        self.assertEqual(MODULE.STARTUP_TIMEOUT_S, '900')

    def test_default_mode_prepares_without_executing(self):
        args = MODULE.parse_args([])
        self.assertFalse(args.execute_gate)


if __name__ == '__main__':
    unittest.main()
