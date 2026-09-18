#!/usr/bin/env python3
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_experiment_manifest import load_rdf_experiment_declaration,resolve_adapter_classes
REP={"rdf/source":"rdf.json","hdt/default":"hdt.json","cottas/default":"cottas.json","vortex-rdf/dictionary-secondary-by-reference":"vortex-reference.json","vortex-rdf/dictionary-secondary-by-copy":"vortex-copy.json"}
SYS=[("fuseki/memory","rdf/source"),("fuseki/tdb2","rdf/source"),("virtuoso/default","rdf/source"),("qlever/default","rdf/source"),("oxigraph/memory","rdf/source"),("oxigraph/rocksdb","rdf/source"),("comunica/hdt","hdt/default"),("pycottas/default","cottas/default"),("rdflib/default","rdf/source"),("vortex-rdf/dictionary-secondary-by-reference","vortex-rdf/dictionary-secondary-by-reference"),("vortex-rdf/dictionary-secondary-by-reference-memory","vortex-rdf/dictionary-secondary-by-reference"),("vortex-rdf/dictionary-secondary-by-copy","vortex-rdf/dictionary-secondary-by-copy"),("vortex-rdf/dictionary-secondary-by-copy-memory","vortex-rdf/dictionary-secondary-by-copy")]
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
 def test_adapter_classes_resolve(self):self.assertEqual(set(resolve_adapter_classes()),{"fuseki/memory","fuseki/tdb2","virtuoso/default","qlever/default","oxigraph/memory","oxigraph/rocksdb","hdt-rdflib/optimized-in-memory","comunica/hdt","pycottas/default","rdflib/default","vortex-rdf/dictionary-secondary-by-reference","vortex-rdf/dictionary-secondary-by-reference-memory","vortex-rdf/dictionary-secondary-by-copy","vortex-rdf/dictionary-secondary-by-copy-memory"})
 def test_representation_mismatch_is_rejected(self):
  value=json.loads(self.path.read_text()); value["bindings"][0]["representation"]="hdt/default"; self.path.write_text(json.dumps(value))
  with self.assertRaisesRegex(ValueError,"representations differ"):load_rdf_experiment_declaration(self.path)
 def test_explicit_benchmark_root_supports_run_local_declaration(self):
  local=Path(self.tmp.name)/"run-local.json"; local.write_text(self.path.read_text())
  experiments,artifacts=load_rdf_experiment_declaration(local,benchmark_root=self.path.parents[1])
  self.assertEqual(len(experiments),len(SYS)); self.assertEqual(set(artifacts),set(REP))

 def test_selected_system_ignores_invalid_unselected_receipt(self):
  value=json.loads(self.path.read_text()); hdt=self.path.parents[1]/value["representations"]["hdt/default"]; receipt=json.loads(hdt.read_text()); receipt["files"][0]["sha256"]="0"*64; hdt.write_text(json.dumps(receipt))
  experiments,artifacts=load_rdf_experiment_declaration(self.path,selected_systems=["rdflib/default"])
  self.assertEqual([item.system_configuration for item in experiments],["rdflib/default"]); self.assertEqual(set(artifacts),{"rdf/source"})
 def test_selected_system_still_validates_its_receipt(self):
  value=json.loads(self.path.read_text()); hdt=self.path.parents[1]/value["representations"]["hdt/default"]; receipt=json.loads(hdt.read_text()); receipt["files"][0]["sha256"]="0"*64; hdt.write_text(json.dumps(receipt))
  with self.assertRaises(ValueError):load_rdf_experiment_declaration(self.path,selected_systems=["comunica/hdt"])
 def test_unfiltered_load_still_validates_all_receipts(self):
  value=json.loads(self.path.read_text()); hdt=self.path.parents[1]/value["representations"]["hdt/default"]; receipt=json.loads(hdt.read_text()); receipt["files"][0]["sha256"]="0"*64; hdt.write_text(json.dumps(receipt))
  with self.assertRaises(ValueError):load_rdf_experiment_declaration(self.path)
 def test_selected_system_rejects_unknown_system(self):
  with self.assertRaisesRegex(ValueError,"unknown systems"):
   load_rdf_experiment_declaration(self.path,selected_systems=["missing/default"])

if __name__=="__main__":unittest.main()
