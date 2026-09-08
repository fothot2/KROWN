#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.sparql_http_benchmark import _SparqlHttpAdapter
from bench_executor.sparql_http_system_adapter import SparqlHttpRunResult


class HttpOxigraphMemoryTests(unittest.TestCase):
    def test_http_adapter_assigns_warmup_and_measured_phases(self):
        sampler=MagicMock()
        adapter=_SparqlHttpAdapter('http://localhost:1',1.0,memory_sampler=sampler,warmup_attempt_count=1)
        adapter._session=MagicMock()
        response=MagicMock(status_code=200,content=b'{"boolean":true}',headers={'Content-Type':'application/sparql-results+json'})
        response.json.return_value={'boolean':True}; adapter._session.post.return_value=response
        adapter.execute('ASK {}'); adapter.execute('ASK {}')
        self.assertEqual(sampler.set_phase.call_args_list[0].args,('warmup',))
        self.assertEqual(sampler.set_phase.call_args_list[1].args,('measured',))

    def test_oxigraph_adapter_declares_stable_memory_container(self):
        source=(Path(__file__).resolve().parents[1]/'bench_executor/oxigraph_system_adapter.py').read_text()
        self.assertIn('return f"Oxigraph-{self._backend}"',source)

    def test_matrix_publishes_server_lifecycle_memory(self):
        source=(Path(__file__).resolve().parents[1]/'bench_executor/rdf_experiment_matrix_resource.py').read_text()
        self.assertIn('memory_sampler=adapter.memory_sampler,',source)
        self.assertIn('phase_memory_metrics = lifecycle.phase_memory_metrics',source)

    def test_run_result_accepts_phase_memory(self):
        value={'schema':'rdf-phase-memory-metrics-v1'}
        result=SparqlHttpRunResult('oxigraph/memory',MagicMock(),(),phase_memory_metrics=value)
        self.assertIs(result.phase_memory_metrics,value)
if __name__=='__main__': unittest.main()
