#!/usr/bin/env python3
import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];P=ROOT/'run_watdiv_10m_measured_campaign_v1.py';S=importlib.util.spec_from_file_location(P.stem,P);M=importlib.util.module_from_spec(S);S.loader.exec_module(M)
class Tests(unittest.TestCase):
 def test_contract(self):self.assertEqual(M.STREAMS,('test.1','test.2','test.3','test.4','test.5'));self.assertEqual(len(M.SYSTEMS),6);self.assertEqual(M.TARGET.name,'watdiv-10m-measured-campaign.json')
 def test_launcher_declares_budgets(self):
  source=P.read_text();self.assertIn("KROWN_RDF_BUDGET_MIN_ATTEMPTS']='500'",source);self.assertIn("KROWN_RDF_BUDGET_MAX_PROJECTED_WALL_S']='28800'",source);self.assertIn("KROWN_RDF_BUDGET_MAX_ACTUAL_WALL_S']='14400'",source)
if __name__=='__main__':unittest.main()
