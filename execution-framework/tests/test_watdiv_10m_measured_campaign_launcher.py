#!/usr/bin/env python3
import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];PATH=ROOT/'run_watdiv_10m_measured_campaign_v1.py';SPEC=importlib.util.spec_from_file_location(PATH.stem,PATH);MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)
class Tests(unittest.TestCase):
 def test_all_fourteen_systems_are_available(self):
  self.assertEqual(MODULE.SYSTEMS, ('rdflib/default', 'hdt-rdflib/optimized-in-memory', 'comunica/hdt', 'pycottas/default', 'vortex-rdf/dictionary-secondary-by-reference', 'vortex-rdf/dictionary-secondary-by-reference-memory', 'vortex-rdf/dictionary-secondary-by-copy', 'vortex-rdf/dictionary-secondary-by-copy-memory', 'oxigraph/memory', 'fuseki/memory', 'oxigraph/rocksdb', 'fuseki/tdb2', 'virtuoso/default', 'qlever/default'))
 def test_stage_contract(self):
  self.assertEqual(MODULE.STAGES['primary'],('test.1',));self.assertEqual(MODULE.STAGES['extension'],('test.2','test.3','test.4','test.5'));self.assertEqual(MODULE.ACTUAL_BUDGET_S,18000)
 def test_projected_budget_is_disabled(self):
  source=PATH.read_text();self.assertIn("KROWN_RDF_BUDGET_MIN_ATTEMPTS']='0'",source);self.assertIn("KROWN_RDF_BUDGET_MAX_PROJECTED_WALL_S']='0'",source);self.assertIn("KROWN_RDF_BUDGET_MAX_ACTUAL_WALL_S']=str(ACTUAL_BUDGET_S)",source)
 def test_extension_requires_complete_primary(self):
  with tempfile.TemporaryDirectory() as directory:
   old=MODULE.SHARED;MODULE.SHARED=Path(directory)
   try:
    eligible,reason=MODULE.extension_eligible('qlever/default');self.assertFalse(eligible)
    path=MODULE.primary_summary('qlever/default');path.parent.mkdir(parents=True);path.write_text(json.dumps({'status':'ok','experiments':[{'record_count':12400}]}));eligible,reason=MODULE.extension_eligible('qlever/default');self.assertTrue(eligible)
   finally:MODULE.SHARED=old
 def test_canonical_order_is_not_interleaved(self):
  self.assertEqual(MODULE.STAGES['all'],('test.1','test.2','test.3','test.4','test.5'))
if __name__=='__main__':unittest.main()
