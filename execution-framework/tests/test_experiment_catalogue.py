import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.experiment_catalogue import build_coverage_audit,load_catalogue,write_audit_outputs

class Spec:
 def __init__(self,value):self.system_id=value
class CatalogueTests(unittest.TestCase):
 def catalogue(self):return load_catalogue(Path(__file__).resolve().parents[1]/"experiment-catalogue.json")
 def test_supervisor_scope_is_frozen(self):
  value=self.catalogue();self.assertEqual(value["scope"]["blocking_benchmarks"],["bsbm","krown-synthetic","dbbench"]);self.assertEqual(value["required_outputs"], ["json","csv","markdown","xlsx"]);self.assertEqual(value["oom_rule"],"confirmed-process-memory-exhaustion-only")
  systems={item["system_id"] for item in value["setups"]};self.assertIn("fuseki/memory",systems);self.assertIn("fuseki/tdb2",systems);self.assertIn("hdt-rdflib/default",systems);self.assertIn("pyoxigraph-rdflib/memory",systems);self.assertIn("vortex-rdf/dictionary-secondary-by-reference-memory",systems)
 def test_missing_systems_and_cells_block_readiness(self):
  value=self.catalogue()
  with patch("bench_executor.experiment_catalogue.system_adapter_specifications",lambda:[Spec("pycottas/default")]):audit=build_coverage_audit(value)
  self.assertFalse(audit["ready_for_bsbm_10k"]);self.assertIn("fuseki/memory",audit["missing_required_system_ids"]);self.assertTrue(audit["blocking_cells"])
 def test_outputs_are_written(self):
  value=self.catalogue()
  with patch("bench_executor.experiment_catalogue.system_adapter_specifications",lambda:[Spec(item["system_id"]) for item in value["setups"]]):audit=build_coverage_audit(value)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);write_audit_outputs(audit,root)
   for name in ("coverage-audit.json","coverage-audit.csv","coverage-audit.md","coverage-audit-xlsx-rows.json"):self.assertTrue((root/name).is_file())
if __name__=="__main__":unittest.main()
