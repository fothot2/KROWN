import random,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.query_quarantine_contract import content_sha256
from bench_executor.query_quarantine_probe import PROBE_POLICY_SCHEMA,select_probe_rules,validate_probe_policy
from bench_executor.query_quarantine_resolver import SNAPSHOT_SCHEMA
from bench_executor.rdf_experiment_matrix_resource import _compact_result_record,_result_summary
from bench_executor.rdf_query_benchmark import _QueryManifest,_QueryOutcome,_QuerySpec,_QueryTimeoutError,_RdfQueryAdapter,_RdfQueryBenchmark

def policy(**changes):
 v={"schema":PROBE_POLICY_SCHEMA,"policy_id":"probe-v1","probe_every_completed_compatible_runs":10,"maximum_probes_per_binding":1};v.update(changes);return v
def decision(selector,state="quarantined"):
 v={"system":"pycottas/default","selector_kind":"bsbm_template_id","selector_value":selector,"compatibility_sha256":selector.zfill(64),"decision":state,"reason":"timeout-in-10-of-10-compatible-independent-completed-runs","window_size":10,"observed_run_count":10,"timeout_count":10,"evidence_ids":[str(i)*64 for i in range(10)]};v["decision_sha256"]=content_sha256(v);return v
def snapshot(decisions):
 body={"schema":SNAPSHOT_SCHEMA,"created_at_utc":"2026-09-09T00:00:00Z","policy_id":"q-v1","policy_sha256":"a"*64,"evidence_ledger_sha256":"b"*64,"decisions":decisions};return {**body,"snapshot_sha256":content_sha256(body)}
def manifest():return _QueryManifest("w","d",(_QuerySpec("q5","ASK {}",{"bsbm_template_id":"5"}),_QuerySpec("q7","ASK { ?s ?p ?o }",{"bsbm_template_id":"7"})))
class Adapter(_RdfQueryAdapter):
 executions=[];mode="ok"
 def execute(self,q):
  type(self).executions.append(q)
  if q=="ASK {}" and type(self).mode=="timeout":raise _QueryTimeoutError("probe timeout")
  if q=="ASK {}" and type(self).mode=="error":raise RuntimeError("probe error")
  return _QueryOutcome(1,metadata={"measurement_boundary":"test"})
class ProbeTests(unittest.TestCase):
 def test_due_interval_eligibility_and_determinism(self):
  values=[decision("7"),decision("5")];a=select_probe_rules(snapshot(values),policy(),10,"run-10","pycottas/default")
  random.Random(1).shuffle(values);b=select_probe_rules(snapshot(values),policy(),10,"run-10","pycottas/default")
  self.assertEqual(len(a),1);self.assertEqual(len(b),1)
  self.assertEqual(a[0]["selector_value"],"5");self.assertEqual(b[0]["selector_value"],"5")
  self.assertEqual(a[0]["source_decision_sha256"],b[0]["source_decision_sha256"])
  self.assertEqual(select_probe_rules(snapshot(values),policy(),9,"run-9","pycottas/default"),())
  self.assertEqual(select_probe_rules(snapshot([decision("5","not_quarantined")]),policy(),10,"r","pycottas/default"),())
 def test_policy_validation(self):
  for changes in ({"probe_every_completed_compatible_runs":0},{"maximum_probes_per_binding":2}):
   with self.assertRaises(ValueError):validate_probe_policy(policy(**changes))
 def run_case(self,mode="ok",force=False):
  Adapter.executions=[];Adapter.mode=mode
  auto=({"selector_kind":"bsbm_template_id","selector_value":"5","query_sha256":manifest().queries[0].query_sha256,"reason":"q","policy_id":"q","policy_sha256":"a"*64,"evidence_ledger_sha256":"b"*64,"snapshot_sha256":"c"*64,"decision_sha256":"d"*64,"evidence_count":10,"timeout_count":10},)
  manual=({"selector_values":["5"],"policy_id":"m","reason":"m","policy_sha256":"e"*64},)
  probe=({"selector_kind":"bsbm_template_id","selector_value":"5","source_decision_sha256":"d"*64,"source_snapshot_sha256":"c"*64,"policy_id":"p","policy_sha256":"f"*64,"reason":"scheduled-quarantine-revalidation","ordinal":1,"run_id":"r","probe_decision_sha256":"1"*64},)
  bench=_RdfQueryBenchmark(Adapter,"e","pycottas/default",manifest(),warmup_runs=0,measured_runs=1,progress=False,manual_skip_rules=manual,automatic_quarantine_rules=auto,probe_rules=probe,force_include=force)
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/"r.jsonl";records=bench.run(str(path));summary=_result_summary(path,SimpleNamespace(system_configuration="pycottas/default"),"cottas/default")
  return records,summary
 def test_probe_precedence_provenance_and_summary(self):
  records,summary=self.run_case();q5=records[0]
  self.assertEqual(q5["status"],"ok");self.assertTrue(q5["quarantine_probe"]);self.assertEqual(len(Adapter.executions),2)
  self.assertEqual(summary["quarantine_probe_count"],1)
  for f in ("probe_policy_id","probe_policy_sha256","probe_decision_sha256","probe_reason","probe_ordinal","probe_source_snapshot_sha256"):
   self.assertEqual(_compact_result_record(q5)[f],q5[f])
 def test_probe_timeout_and_error_keep_native_status(self):
  records,summary=self.run_case("timeout");self.assertEqual(records[0]["status"],"timeout");self.assertEqual(summary["failure_count"],1)
  records,_=self.run_case("error");self.assertEqual(records[0]["status"],"engine_error")
 def test_force_include_highest_precedence(self):
  records,summary=self.run_case(force=True);self.assertTrue(all(r["status"]=="ok" for r in records));self.assertEqual(summary["quarantine_probe_count"],0)
if __name__=="__main__":unittest.main()
