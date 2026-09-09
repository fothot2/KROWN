import io,json,sys,tarfile,tempfile,unittest,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.benchmark_result import sha256_text
from bench_executor.query_quarantine_resolver import POLICY_SCHEMA
from bench_executor.query_quarantine_workflow import WORKFLOW_SCHEMA,execute_controlled_workflow,validate_workflow_plan

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def fixture(root,bad_second=False):
 query='ASK { <urn:x> ?p ?o }';qsha=sha256_text(query);manifest={"schema_version":1,"workload":"w","dataset":"bsbm-explore-10k","queries":[{"query_id":"q1","query":query,"query_sha256":qsha,"bsbm_template_id":"1"}]};decl={"schema":"rdf-experiment-declaration-v1","benchmark":"bsbm","dataset":"explore-10k","workload":"w","bindings":[{"system":"pycottas/default","representation":"cottas/default"}],"execution_policy":{"timeout_s":60.0}};record={"query_id":"q1","query_sha256":qsha,"system":"pycottas/default","workload":"w","status":"timeout","bsbm_template_id":"1"};summary={"status":"completed_with_failures","experiments":[{"system":"pycottas/default","representation":"cottas/default","status":"completed_with_failures","result_file":"r.jsonl","record_count":1,"success_count":0,"skipped_count":0,"unsupported_count":0,"failure_count":1,"execution_mode":{"timeout_mode":"worker","lifecycle":"shared"}}]}
 for name,value in (("manifest.json",manifest),("declaration.json",decl),("summary.json",summary)):(root/name).write_text(json.dumps(value))
 data=json.dumps(record,separators=(",",":")).encode()+b'\n'
 with tarfile.open(root/'results.tar.gz','w:gz') as archive:info=tarfile.TarInfo('r.jsonl');info.size=len(data);archive.addfile(info,io.BytesIO(data))
 policy={"schema":POLICY_SCHEMA,"policy_id":"p","minimum_independent_completed_runs":2,"required_timeout_count":2,"window_kind":"latest-compatible-runs","window_size":2,"timeout_outcome":"timeout"};(root/'policy.json').write_text(json.dumps(policy))
 base={"summary":"summary.json","archive":"results.tar.gz","manifest":"manifest.json","declaration":"declaration.json","system":"pycottas/default","adapter_identity":"pycottas-1.1.0","artifact_identity":"bsbm/explore-10k/cottas/default","selector_kind":"bsbm_template_id","summary_sha256":sha(root/'summary.json'),"archive_sha256":sha(root/'results.tar.gz'),"exclusion_report":None}
 runs=[]
 for i in range(2):runs.append({**base,"run_id":f"run-{i}","output":f"evidence/run-{i}.json"})
 if bad_second:runs[1]["archive_sha256"]='0'*64
 plan={"schema":WORKFLOW_SCHEMA,"created_at_utc":"2026-09-09T18:00:00Z","runs":runs,"ledger":{"output":"ledger/ledger.json","created_at_utc":"2026-09-09T18:01:00Z"},"policy":"policy.json","snapshot":{"output":"snapshot/snapshot.json","created_at_utc":"2026-09-09T18:02:00Z"},"audit":"audit/audit.json"};(root/'plan.json').write_text(json.dumps(plan));return root/'plan.json'
class WorkflowTests(unittest.TestCase):
 def test_success_and_no_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);plan=fixture(root);audit=execute_controlled_workflow(plan,root);self.assertEqual(audit['ledger']['entry_count'],2);self.assertEqual(audit['snapshot']['quarantined_count'],1)
   with self.assertRaises(FileExistsError):execute_controlled_workflow(plan,root)
 def test_failure_rolls_back_all_outputs(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);plan=fixture(root,True)
   with self.assertRaises(ValueError):execute_controlled_workflow(plan,root)
   for name in ('evidence','ledger','snapshot','audit'):self.assertFalse((root/name).exists())
 def test_path_escape_and_duplicate_run_fail(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);plan=fixture(root);value=json.loads(plan.read_text());value['audit']='../audit.json'
   with self.assertRaises(ValueError):validate_workflow_plan(value)
   value=json.loads(plan.read_text());value['runs'][1]['run_id']=value['runs'][0]['run_id']
   with self.assertRaises(ValueError):validate_workflow_plan(value)
if __name__=='__main__':unittest.main()
