#!/usr/bin/env python3
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_experiment_manifest import load_rdf_experiment_declaration,resolve_adapter_classes
REP={"rdf/source":"rdf.json","hdt/default":"hdt.json","cottas/default":"cottas.json","vortex-rdf/simple-dictionary-native-rdf-store":"vortex.json"}
SYS=[("fuseki/default","rdf/source"),("virtuoso/default","rdf/source"),("qlever/default","rdf/source"),("oxigraph/memory","rdf/source"),("oxigraph/rocksdb","rdf/source"),("comunica/hdt","hdt/default"),("pycottas/default","cottas/default"),("vortex-rdf/simple-dictionary-native-rdf-store","vortex-rdf/simple-dictionary-native-rdf-store"),("rdflib/default","rdf/source")]
class RdfExperimentManifestTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)/"BSBM"; exp=root/"experiments"; data=root/"data"; exp.mkdir(parents=True); data.mkdir()
  source=b"source"; source_hash=hashlib.sha256(source).hexdigest()
  for i,(representation,receipt) in enumerate(REP.items()):
   name=f"artifact-{i}.bin"; payload=representation.encode(); (data/name).write_bytes(payload)
   value={"schema":"rdf-representation-receipt-v1","benchmark":"bsbm","dataset":"explore-1k","created_at_utc":"2026-08-26T00:00:00Z","source":{"format":"ntriples","size_bytes":len(source),"sha256":source_hash},"representation":representation,"files":[{"path":name,"size_bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest()}],"producer":{}}
   (data/receipt).write_text(json.dumps(value))
  declaration={"schema":"rdf-experiment-declaration-v1","experiment":"bsbm/explore-1k/explore-smoke","benchmark":"bsbm","dataset":"explore-1k","workload":"bsbm-explore-smoke","inventory":"data/inventory.json","representations":{k:f"data/{v}" for k,v in REP.items()},"bindings":[{"system":s,"representation":r} for s,r in SYS],"execution_policy":{"warmup_runs":0,"measured_runs":1,"timeout_s":60.0},"semantic_baseline":"baselines/smoke.json"}
  self.path=exp/"smoke.json"; self.path.write_text(json.dumps(declaration))
 def tearDown(self):self.tmp.cleanup()
 def test_loads_all_bindings_without_benchmark_constants_in_core(self):
  experiments,artifacts=load_rdf_experiment_declaration(self.path); self.assertEqual([e.system_configuration for e in experiments],[s for s,_ in SYS]); self.assertEqual(set(artifacts),set(REP))
 def test_adapter_classes_resolve(self):self.assertEqual(set(resolve_adapter_classes()),{s for s,_ in SYS})
 def test_representation_mismatch_is_rejected(self):
  value=json.loads(self.path.read_text()); value["bindings"][0]["representation"]="hdt/default"; self.path.write_text(json.dumps(value))
  with self.assertRaisesRegex(ValueError,"representations differ"):load_rdf_experiment_declaration(self.path)
if __name__=="__main__":unittest.main()
