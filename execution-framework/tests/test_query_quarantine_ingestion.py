import io,json,sys,tarfile,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.query_quarantine_ingestion import ingest_matrix_bundle
from bench_executor.benchmark_result import sha256_text

class IngestionTests(unittest.TestCase):
 def bundle(self,statuses=("ok","timeout","skipped","unsupported"),skip="manual-query-flavour-policy"):
  root=tempfile.TemporaryDirectory();p=Path(root.name);queries=[];records=[]
  for i,status in enumerate(statuses,1):
   text=f"ASK {{ <urn:{i}> ?p ?o }}";qid=f"q{i}";sha=sha256_text(text)
   queries.append({"query_id":qid,"query":text,"query_sha256":sha,"bsbm_template_id":str(i)})
   record={"query_id":qid,"query_sha256":sha,"system":"pycottas/default","workload":"w","status":status,"bsbm_template_id":str(i)}
   if status=="skipped":record["skip_kind"]=skip
   records.append(record)
  manifest={"schema_version":1,"workload":"w","dataset":"bsbm-explore-10k","queries":queries};(p/"manifest.json").write_text(json.dumps(manifest))
  decl={"schema":"rdf-experiment-declaration-v1","benchmark":"bsbm","dataset":"explore-10k","workload":"w","bindings":[{"system":"pycottas/default","representation":"cottas/default"}],"execution_policy":{"timeout_s":60.0}};(p/"decl.json").write_text(json.dumps(decl))
  counts={x:sum(r["status"]==x for r in records) for x in ("ok","skipped","unsupported")};fail=sum(r["status"] not in {"ok","skipped","unsupported"} for r in records)
  binding={"system":"pycottas/default","representation":"cottas/default","status":"ok" if not fail else "completed_with_failures","result_file":"r.jsonl","record_count":len(records),"success_count":counts["ok"],"skipped_count":counts["skipped"],"unsupported_count":counts["unsupported"],"failure_count":fail,"execution_mode":{"timeout_mode":"worker","lifecycle":"shared"}}
  summary={"status":"ok" if not fail else "completed_with_failures","experiments":[binding]};(p/"summary.json").write_text(json.dumps(summary))
  with tarfile.open(p/"results.tar.gz","w:gz") as a:
   data=b"".join(json.dumps(r,separators=(",",":")).encode()+b"\n" for r in records);info=tarfile.TarInfo("r.jsonl");info.size=len(data);a.addfile(info,io.BytesIO(data))
  return root,p,records
 def ingest(self,p,**kw):return ingest_matrix_bundle(summary_path=p/"summary.json",archive_path=p/"results.tar.gz",manifest_path=p/"manifest.json",declaration_path=p/"decl.json",run_id="run-1",system="pycottas/default",adapter_identity="pycottas-1.1.0",artifact_identity="bsbm/explore-10k/cottas/default",**kw)
 def test_outcome_mapping_and_determinism(self):
  root,p,_=self.bundle();
  try:
   a=self.ingest(p);b=self.ingest(p);self.assertEqual([x.to_dict() for x in a],[x.to_dict() for x in b]);self.assertEqual({x.outcome for x in a},{"ok","timeout","skipped_manual","unsupported"})
  finally:root.cleanup()
 def test_engine_failures_and_automatic_skip(self):
  root,p,_=self.bundle(("engine_error","connection_error","parse_error","result_error","validation_mismatch","skipped"),"automatic-query-flavour-quarantine")
  try:self.assertEqual([x.outcome for x in self.ingest(p)].count("engine_error"),5);self.assertIn("skipped_automatic",[x.outcome for x in self.ingest(p)])
  finally:root.cleanup()
 def test_hash_and_count_tampering_fail(self):
  root,p,_=self.bundle(("ok",))
  try:
   with self.assertRaises(ValueError):self.ingest(p,expected_archive_sha256="0"*64)
   s=json.loads((p/"summary.json").read_text());s["experiments"][0]["record_count"]=2;(p/"summary.json").write_text(json.dumps(s))
   with self.assertRaises(ValueError):self.ingest(p)
  finally:root.cleanup()
 def test_manifest_mismatch_and_exclusion_fail(self):
  root,p,_=self.bundle(("ok",))
  try:
   m=json.loads((p/"manifest.json").read_text());m["queries"][0]["query_sha256"]="0"*64;(p/"manifest.json").write_text(json.dumps(m))
   with self.assertRaises(ValueError):self.ingest(p)
   report=p/"validation.json";report.write_text(json.dumps({"classification":"instrumentation-validation-not-historical-evidence"}))
   with self.assertRaises(ValueError):self.ingest(p,exclusion_report_path=report)
  finally:root.cleanup()
 def test_oom_requires_confirmation(self):
  root,p,records=self.bundle(("oom",))
  try:
   with self.assertRaises(ValueError):self.ingest(p)
   records[0].update({"oom_confirmed":True,"oom_reason":"memory-exhaustion"})
   with tarfile.open(p/"results.tar.gz","w:gz") as a:
    data=json.dumps(records[0],separators=(",",":")).encode()+b"\n";info=tarfile.TarInfo("r.jsonl");info.size=len(data);a.addfile(info,io.BytesIO(data))
   self.assertEqual(self.ingest(p)[0].outcome,"oom")
  finally:root.cleanup()
 def test_unsafe_archive_fails(self):
  root,p,_=self.bundle(("ok",))
  try:
   with tarfile.open(p/"results.tar.gz","w:gz") as a:
    data=b"{}\n";info=tarfile.TarInfo("../r.jsonl");info.size=len(data);a.addfile(info,io.BytesIO(data))
   with self.assertRaises(ValueError):self.ingest(p)
  finally:root.cleanup()
if __name__=="__main__":unittest.main()
