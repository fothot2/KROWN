import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.query_quarantine_contract import EvidenceObservation,content_sha256
from bench_executor.query_quarantine_ledger_build import INGESTION_CLASSIFICATION,INGESTION_SCHEMA,build_ledger_from_paths,build_ledger_v2,load_ingestion_document,validate_ledger_v2

def compatibility(selector="5"):
 return {"benchmark":"bsbm","dataset":"explore-10k","workload":"w","system":"pycottas/default","selector_kind":"bsbm_template_id","selector_value":selector,"query_sha256":selector.zfill(64),"timeout_s":60.0,"timeout_mode":"worker","lifecycle":"shared","correctness_mode":"fingerprint","artifact_identity":"a","adapter_identity":"p","policy_schema":"rdf-experiment-declaration-v1"}
def observation(run="run-1",outcome="timeout",selector="5",record="d",completed=True):return EvidenceObservation(run,completed,"completed_with_failures",compatibility(selector),outcome,1,"a"*64,"b"*64,record*64)
def document(values,classification=INGESTION_CLASSIFICATION):
 body={"schema":INGESTION_SCHEMA,"created_at_utc":"2026-09-09T00:00:00Z","classification":classification,"source_bundle":{"summary_sha256":"a"*64,"archive_sha256":"b"*64,"manifest_sha256":"c"*64,"declaration_sha256":"e"*64,"run_id":values[0].run_id},"observations":[v.to_dict() for v in values]};return {**body,"document_sha256":content_sha256(body)}
def write(path,value):path.write_text(json.dumps(value));return path
class LedgerBuildTests(unittest.TestCase):
 def test_one_document_build_and_validate(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=write(root/"i.json",document([observation()]));out=root/"ledger.json";ledger=build_ledger_from_paths([source],out,"2026-09-09T01:00:00Z");self.assertEqual(validate_ledger_v2(json.loads(out.read_text())),ledger);self.assertEqual(len(ledger["entries"]),1)
 def test_input_order_is_deterministic_and_identical_observation_deduplicates(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);a=write(root/"a.json",document([observation("run-1")]));b=write(root/"b.json",document([observation("run-2",record="e")]))
   docs1=[load_ingestion_document(a),load_ingestion_document(b)];docs2=list(reversed(docs1));self.assertEqual(build_ledger_v2(docs1,"t"),build_ledger_v2(docs2,"t"))
   duplicate=build_ledger_v2([load_ingestion_document(a),load_ingestion_document(a)],"t");self.assertEqual(len(duplicate["entries"]),1)
 def test_conflicting_observations_fail(self):
  a=observation();b=observation(outcome="ok",record="e")
  with self.assertRaisesRegex(ValueError,"conflicting"):build_ledger_v2([(content_sha256(document([a])),(a,)),(content_sha256(document([b])),(b,))],"t")
 def test_document_hash_identity_and_source_mismatch_fail(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);value=document([observation()]);value["document_sha256"]="0"*64
   with self.assertRaisesRegex(ValueError,"document_sha256"):load_ingestion_document(write(root/"bad.json",value))
   value=document([observation()]);value["observations"][0]["evidence_id"]="0"*64;body=dict(value);body.pop("document_sha256");value["document_sha256"]=content_sha256(body)
   with self.assertRaisesRegex(ValueError,"evidence_id"):load_ingestion_document(write(root/"bad2.json",value))
   value=document([observation()]);value["source_bundle"]["summary_sha256"]="f"*64;body=dict(value);body.pop("document_sha256");value["document_sha256"]=content_sha256(body)
   with self.assertRaisesRegex(ValueError,"provenance"):load_ingestion_document(write(root/"bad3.json",value))
 def test_mixed_duplicate_and_excluded_documents_fail(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);first=observation("run-1");second=observation("run-2",record="e");value=document([first,second]);body=dict(value);body.pop("document_sha256");value["document_sha256"]=content_sha256(body)
   with self.assertRaisesRegex(ValueError,"mixed run IDs"):load_ingestion_document(write(root/"mixed.json",value))
   value=document([first,first]);body=dict(value);body.pop("document_sha256");value["document_sha256"]=content_sha256(body)
   with self.assertRaisesRegex(ValueError,"duplicate observation"):load_ingestion_document(write(root/"dup.json",value))
   value=document([first],"genuine-format-fixture-not-historical-evidence");
   with self.assertRaisesRegex(ValueError,"classification"):load_ingestion_document(write(root/"excluded.json",value))
 def test_duplicate_path_existing_output_and_cleanup(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=write(root/"i.json",document([observation()]));out=write(root/"ledger.json",{"old":True});before=out.read_bytes()
   with self.assertRaisesRegex(ValueError,"duplicate"):build_ledger_from_paths([source,source],root/"new.json","t")
   with self.assertRaises(FileExistsError):build_ledger_from_paths([source],out,"t")
   self.assertEqual(out.read_bytes(),before);self.assertFalse(list(root.glob(".*.tmp")))
if __name__=="__main__":unittest.main()
