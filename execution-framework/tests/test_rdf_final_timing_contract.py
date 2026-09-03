#!/usr/bin/env python3
import io, json, sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_executor.persistent_jsonl_query_adapter import PersistentJsonlQueryAdapter
from bench_executor.rdf_experiment_matrix_resource import _run_file_backed
from bench_executor.rdf_query_benchmark import _QueryManifest, _QuerySpec
from bench_executor.sparql_result import normalize_sparql_json_result

class FinalTimingContractTests(unittest.TestCase):
 def test_persistent_worker_reports_ipc_and_correctness(self):
  process=MagicMock(); process.stdin=io.StringIO(); process.stderr=io.StringIO()
  process.poll.return_value=None
  document={"kind":"select","variables":["x"],"rows":[]}
  lines=[json.dumps({"kind":"ready","protocol":"jsonl-v1"})+"\n",json.dumps({"kind":"result","request_id":0,"status":"ok","document":document})+"\n"]
  process.stdout=MagicMock(); process.stdout.readline.side_effect=lines
  backend=SimpleNamespace(worker_command=lambda **k:["worker"],force_stop_command=lambda n:["stop",n])
  with patch("bench_executor.persistent_jsonl_query_adapter.subprocess.Popen",return_value=process), patch("bench_executor.persistent_jsonl_query_adapter.select.select",side_effect=lambda r,w,e,t:(r,[],[])):
   adapter=PersistentJsonlQueryAdapter(adapter=backend,artifact=Path("a.hdt"),timeout_s=1,normalizer=normalize_sparql_json_result)
   adapter.open(); outcome=adapter.execute("SELECT ?x WHERE { ?x ?p ?o }")
  self.assertEqual(set(outcome.stage_timings_ns),{"ipc","correctness"})
  self.assertEqual(outcome.elapsed_ns,sum(outcome.stage_timings_ns.values()))
 def test_file_backed_runner_returns_reconciled_lifecycle(self):
  benchmark=SimpleNamespace(execution_policy={"timeout_s":1,"warmup_runs":0,"measured_runs":1},experiment_id="e")
  manifest=_QueryManifest("w","d",(_QuerySpec("q","ASK {}"),))
  lifecycle={"schema":"rdf-query-lifecycle-timing-v1","stages_ns":{"artifact_open_or_load":1,"warmup":0,"measured":2,"engine_shutdown":1,"unclassified":0},"total_wall_ns":4,"reconciled":True,"resource_metrics":{},"execution_mode":{}}
  fake=MagicMock(); fake.last_lifecycle_timing=lifecycle
  with patch("bench_executor.rdf_experiment_matrix_resource._load_query_manifest",return_value=manifest), patch("bench_executor.rdf_experiment_matrix_resource._RdfQueryBenchmark",return_value=fake):
   result=_run_file_backed(SimpleNamespace(),Path("a"),Path("m"),Path("o"),benchmark,"comunica/hdt")
  self.assertIs(result,lifecycle)
  fake.run.assert_called_once_with("o")
if __name__=="__main__": unittest.main()
