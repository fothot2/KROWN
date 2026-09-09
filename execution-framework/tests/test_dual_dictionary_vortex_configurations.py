#!/usr/bin/env python3
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_experiment_manifest import system_adapter_specifications
from bench_executor.rdf_experiment_matrix_resource import _execution_strategy
class DualDictionaryVortexConfigurationsTests(unittest.TestCase):
 def test_dual_dictionary_configurations_are_generic_and_explicit(self):
  registry={item.system_id:item for item in system_adapter_specifications()}
  expected={
   "vortex-rdf/dictionary-secondary-by-reference":("vortex-rdf/dictionary-secondary-by-reference","secondary-by-reference"),
   "vortex-rdf/dictionary-secondary-by-reference-memory":("vortex-rdf/dictionary-secondary-by-reference","secondary-by-reference"),
   "vortex-rdf/dictionary-secondary-by-copy":("vortex-rdf/dictionary-secondary-by-copy","secondary-by-copy"),
   "vortex-rdf/dictionary-secondary-by-copy-memory":("vortex-rdf/dictionary-secondary-by-copy","secondary-by-copy"),
  }
  for system_id,(representation,index_type) in expected.items():
   item=registry[system_id]
   self.assertEqual(item.configuration.representation,representation)
   self.assertEqual(item.configuration.parameters["layout"],"dictionary")
   self.assertEqual(item.configuration.parameters["index_type"],index_type)
   self.assertEqual(_execution_strategy(item),"rdflib-worker")
   self.assertNotIn("vortex_layout",item.parameters)
if __name__=="__main__": unittest.main()
