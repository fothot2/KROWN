#!/usr/bin/env python3
import sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_query_benchmark import _QueryManifest,_QueryOutcome,_QuerySpec,_RdfQueryAdapter,_RdfQueryBenchmark
class A(_RdfQueryAdapter):
 def execute(self,q):time.sleep(0.002);return _QueryOutcome(1,metadata={'measurement_boundary':'test'})
class Tests(unittest.TestCase):
 def test_projected_budget_preserves_partial_records_and_closes(self):
  m=_QueryManifest('w','d',tuple(_QuerySpec(str(i),'ASK{}') for i in range(20)))
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'r.jsonl';b=_RdfQueryBenchmark(A,'e','s',m,warmup_runs=0,measured_runs=1,progress=False,budget_min_attempts=2,budget_max_projected_wall_s=.001);records=b.run(str(p))
   self.assertGreaterEqual(len(records),2);self.assertLess(len(records),20);self.assertEqual(b.last_budget_status['status'],'budget_exhausted');self.assertEqual(len(p.read_text().splitlines()),len(records));self.assertEqual(b.last_lifecycle_timing['budget'],b.last_budget_status)
 def test_disabled_budget_completes(self):
  m=_QueryManifest('w','d',(_QuerySpec('q','ASK{}'),));
  with tempfile.TemporaryDirectory() as d:
   b=_RdfQueryBenchmark(A,'e','s',m,warmup_runs=0,measured_runs=1,progress=False);self.assertEqual(len(b.run(str(Path(d)/'r.jsonl'))),1);self.assertIsNone(b.last_budget_status)
if __name__=='__main__':unittest.main()
