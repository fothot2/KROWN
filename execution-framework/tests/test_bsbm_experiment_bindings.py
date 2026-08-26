#!/usr/bin/env python3
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.bsbm_experiment_bindings import DEFAULT_EXECUTION_POLICY,RECEIPT_FILES,SYSTEM_REPRESENTATIONS,bsbm_explore_1k_experiments,load_bsbm_explore_1k_artifacts,resolve_adapter_classes,system_adapter_specifications
class BsbmExperimentBindingsTests(unittest.TestCase):
 def setUp(self):
  self.temporary=tempfile.TemporaryDirectory(); self.root=Path(self.temporary.name); data=self.root/"BSBM/data/explore-1k"; data.mkdir(parents=True)
  source=b"<http://example.org/s> <http://example.org/p> <http://example.org/o> .\n"; source_sha=hashlib.sha256(source).hexdigest()
  for index,(representation,receipt_name) in enumerate(RECEIPT_FILES.items()):
   suffix={"rdf/source":".nt","hdt/default":".hdt","cottas/default":".cottas"}.get(representation,".vortex"); filename=f"artifact-{index}{suffix}"; payload=source+representation.encode(); (data/filename).write_bytes(payload)
   receipt={"schema":"rdf-representation-receipt-v1","benchmark":"bsbm","dataset":"explore-1k","created_at_utc":"2026-08-26T00:00:00+00:00","source":{"format":"ntriples","size_bytes":len(source),"sha256":source_sha},"representation":representation,"files":[{"path":filename,"size_bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest()}],"producer":{"test":True}}
   (data/receipt_name).write_text(json.dumps(receipt,sort_keys=True),encoding="utf-8")
 def tearDown(self): self.temporary.cleanup()
 def test_all_receipts_share_one_logical_source(self):
  artifacts=load_bsbm_explore_1k_artifacts(self.root); self.assertEqual(tuple(artifacts),tuple(RECEIPT_FILES)); self.assertEqual(len({x.source_sha256 for x in artifacts.values()}),1)
 def test_matrix_has_unique_binding_for_every_system(self):
  experiments=bsbm_explore_1k_experiments(self.root); self.assertEqual([x.system_configuration for x in experiments],list(SYSTEM_REPRESENTATIONS)); self.assertEqual(len({x.experiment_id for x in experiments}),9); self.assertTrue(all(dict(x.execution_policy)==DEFAULT_EXECUTION_POLICY for x in experiments))
 def test_registry_and_adapter_resolution(self):
  specifications=system_adapter_specifications(); self.assertEqual({x.system_id:x.configuration.representation for x in specifications},SYSTEM_REPRESENTATIONS); self.assertEqual(set(resolve_adapter_classes()),set(SYSTEM_REPRESENTATIONS))
 def test_source_identity_mismatch_is_rejected(self):
  receipt=self.root/"BSBM/data/explore-1k/hdt-default-receipt.json"; value=json.loads(receipt.read_text()); value["source"]["sha256"]="0"*64; receipt.write_text(json.dumps(value))
  with self.assertRaisesRegex(ValueError,"do not share one source identity"): bsbm_explore_1k_experiments(self.root)
if __name__=="__main__": unittest.main()
