#!/usr/bin/env python3
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_experiment_matrix_resource import _environment_adapter_options
class BsbmSmokeMatrixScenarioTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(__file__).resolve().parents[2]
  self.metadata=json.loads((self.root/'benchmark-integration/bsbm-smoke/metadata.json').read_text(encoding='utf-8'))
 def test_scenario_prepares_then_executes_external_matrix(self):
  self.assertEqual([step['resource'] for step in self.metadata['steps']],['RdfManifestResource','RdfExperimentMatrixResource'])
  matrix=self.metadata['steps'][1]['parameters']
  self.assertEqual(matrix['declaration_file'],'/users/u0182905/benchmarks/BSBM/experiments/explore-1k-smoke.json')
  self.assertEqual(matrix['manifest_file'],'manifests/bsbm.json')
  self.assertEqual(matrix['results_file'],'raw/bsbm-matrix-summary.json')
  self.assertEqual(matrix['output_file'],'raw/bsbm-matrix-results.tar.gz')
 def test_scenario_does_not_duplicate_experiment_bindings(self):
  text=json.dumps(self.metadata,sort_keys=True)
  self.assertNotIn('representations',text);self.assertNotIn('bindings',text)
  self.assertNotIn('RdfQueryResource',text);self.assertNotIn('RdfBaselineResource',text)
 def test_qlever_runtime_values_are_environment_driven(self):
  mapping=self.metadata['steps'][1]['parameters']['adapter_option_env']
  environment={'KROWN_QLEVER_IMAGE':'kgconstruct/qlever:v0.6.0','KROWN_QLEVER_INDEX_COMMAND':'index explicit','KROWN_QLEVER_SERVER_COMMAND':'server explicit'}
  self.assertEqual(_environment_adapter_options(mapping,environment)['qlever/default'],{'image':'kgconstruct/qlever:v0.6.0','index_command':'index explicit','server_command':'server explicit'})
 def test_missing_runtime_environment_is_rejected(self):
  mapping=self.metadata['steps'][1]['parameters']['adapter_option_env']
  with self.assertRaisesRegex(ValueError,'KROWN_QLEVER_IMAGE'):_environment_adapter_options(mapping,{})
if __name__=='__main__':unittest.main()
