#!/usr/bin/env python3
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_query_benchmark import _QueryManifest,_QueryOutcome,_QuerySpec,_QueryTimeoutError,_RdfQueryAdapter,_RdfQueryBenchmark
from bench_executor.rdf_experiment_matrix_resource import _compact_result_record,_result_summary
from types import SimpleNamespace
class Adapter(_RdfQueryAdapter):
 def execute(self,query):
  if query=='SLOW':raise _QueryTimeoutError('timeout')
  return _QueryOutcome(1,metadata={'measurement_boundary':'test'})
class Tests(unittest.TestCase):
 def run_manifest(self,queries):
  manifest=_QueryManifest('w','d',tuple(queries))
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'r.jsonl';records=_RdfQueryBenchmark(Adapter,'e','s',manifest,warmup_runs=0,measured_runs=1,progress=False,in_run_timeout_quarantine_threshold=2).run(str(path));summary=_result_summary(path,SimpleNamespace(system_configuration='s'),'r')
  return records,summary
 def test_watdiv_native_query_quarantines_after_two_measured_timeouts(self):
  queries=[]
  for stream in range(5):
   queries.append(_QuerySpec(f'q-{stream}','SLOW',{'native_query_id':17,'stream':f'test.{stream+1}'}))
   queries.append(_QuerySpec(f'fast-{stream}','FAST',{'native_query_id':18,'stream':f'test.{stream+1}'}))
  records,summary=self.run_manifest(queries);slow=records[::2]
  self.assertEqual([r['status'] for r in slow],['timeout','timeout','skipped','skipped','skipped'])
  self.assertEqual(slow[2]['skip_kind'],'in-run-selector-timeout-quarantine')
  self.assertEqual(slow[2]['skip_selector_kind'],'native_query_id')
  self.assertEqual(slow[2]['skip_selector_value'],'17')
  self.assertEqual(summary['in_run_timeout_quarantine_skipped_count'],3)
  compact=_compact_result_record(slow[2]);self.assertEqual(compact['skip_selector_value'],'17')
 def test_bsbm_template_behavior_is_preserved(self):
  queries=[_QuerySpec(f'q{i}','SLOW',{'bsbm_template_id':'10'}) for i in range(4)]
  records,_=self.run_manifest(queries)
  self.assertEqual([r['status'] for r in records],['timeout','timeout','skipped','skipped'])
  self.assertEqual(records[2]['skip_kind'],'in-run-template-timeout-quarantine')
  self.assertEqual(records[2]['skip_template_id'],'10')
  self.assertEqual(records[2]['skip_selector_kind'],'bsbm_template_id')
 def test_warmup_timeout_does_not_increment_measured_selector_counter(self):
  manifest=_QueryManifest('w','d',(_QuerySpec('q','SLOW',{'native_query_id':17}),))
  with tempfile.TemporaryDirectory() as d:
   records=_RdfQueryBenchmark(Adapter,'e','s',manifest,warmup_runs=1,measured_runs=2,progress=False,skip_after_warmup_timeout=False,in_run_timeout_quarantine_threshold=2).run(str(Path(d)/'r.jsonl'))
  self.assertEqual([r['status'] for r in records],['timeout','timeout','timeout'])
if __name__=='__main__':unittest.main()
