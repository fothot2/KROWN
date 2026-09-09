import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.query_quarantine_contract import content_sha256
from bench_executor.query_quarantine_probe import PROBE_POLICY_SCHEMA
from bench_executor.query_quarantine_resolver import SNAPSHOT_SCHEMA
from bench_executor.query_quarantine_activation import ACTIVATION_SCHEMA,execute_activation,validate_activation_plan

def snapshot():
 d={"system":"pycottas/default","selector_kind":"bsbm_template_id","selector_value":"5","compatibility_sha256":"a"*64,"decision":"quarantined","reason":"timeout-in-10-of-10-compatible-independent-completed-runs","window_size":10,"observed_run_count":10,"timeout_count":10,"evidence_ids":[str(i)*64 for i in range(10)]};d["decision_sha256"]=content_sha256(d);b={"schema":SNAPSHOT_SCHEMA,"created_at_utc":"t","policy_id":"q","policy_sha256":"b"*64,"evidence_ledger_sha256":"c"*64,"decisions":[d]};return {**b,"snapshot_sha256":content_sha256(b)}
def fixture(root,status="ok"):
 scenario=root/"scenario";shared=scenario/"data/shared";shared.mkdir(parents=True);(scenario/"config").mkdir();(scenario/"log").mkdir();(shared/"manifest.json").write_text('{}');(root/"declaration.json").write_text('{}');(shared/"snapshot.json").write_text(json.dumps(snapshot()));policy={"schema":PROBE_POLICY_SCHEMA,"policy_id":"p","probe_every_completed_compatible_runs":10,"maximum_probes_per_binding":1};(shared/"probe.json").write_text(json.dumps(policy));plan={"schema":ACTIVATION_SCHEMA,"created_at_utc":"t","scenario":"scenario","declaration":"declaration.json","manifest":"manifest.json","systems":["pycottas/default"],"snapshot":"snapshot.json","probe_policy":"probe.json","completed_compatible_runs":10,"matrix_run_id":"run-10","force_include":False,"outputs":{"summary":"out/summary.json","archive":"out/results.tar.gz","failure_summary":"out/failure.json","failure_archive":"out/failure.tar.gz"},"expectation":{"matrix_status":status,"selected_probe_count":1,"minimum_skipped_count":0,"require_success_bundle":status!="failed","require_failure_bundle":status=="failed"},"audit":"audit.json"};path=root/"plan.json";path.write_text(json.dumps(plan));return path,shared,policy
class ActivationTests(unittest.TestCase):
 def test_dry_run_and_invalid_plan(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);plan,_,_=fixture(root);audit=execute_activation(plan,root,True);self.assertTrue(audit["validated"])
   value=json.loads(plan.read_text());value["systems"]*=2
   with self.assertRaises(ValueError):validate_activation_plan(value)
 def test_success_validation_and_audit(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);plan,shared,policy=fixture(root);summary={"status":"ok","runtime_orchestration":{"matrix_run_id":"run-10","quarantine_snapshot_sha256":snapshot()["snapshot_sha256"],"probe_policy_sha256":content_sha256(policy),"completed_compatible_runs":10,"selected_probe_count":1,"force_include":False},"experiments":[{"system":"pycottas/default","skipped_count":0}]}
   def fake(*args,**kwargs):(shared/"out").mkdir();(shared/"out/summary.json").write_text(json.dumps(summary));(shared/"out/results.tar.gz").write_bytes(b'x');return type("R",(),{"returncode":0,"stdout":"ok","stderr":""})()
   with patch("bench_executor.query_quarantine_activation.subprocess.run",fake):audit=execute_activation(plan,root)
   self.assertEqual(audit["status"],"ok");self.assertTrue((root/"audit.json").is_file())
 def test_mismatch_rolls_back_matrix_outputs(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);plan,shared,_=fixture(root)
   def fake(*args,**kwargs):(shared/"out").mkdir();(shared/"out/summary.json").write_text(json.dumps({"status":"failed"}));(shared/"out/results.tar.gz").write_bytes(b'x');return type("R",(),{"returncode":1,"stdout":"","stderr":"bad"})()
   with patch("bench_executor.query_quarantine_activation.subprocess.run",fake):
    with self.assertRaises(RuntimeError):execute_activation(plan,root)
   self.assertFalse((shared/"out/summary.json").exists());self.assertFalse((shared/"out/results.tar.gz").exists())
if __name__=="__main__":unittest.main()
