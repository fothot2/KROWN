#!/usr/bin/env python3
import importlib.util,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'run_rdf_campaign.py';S=importlib.util.spec_from_file_location('run_rdf_campaign',P);M=importlib.util.module_from_spec(S);S.loader.exec_module(M)
class CliTests(unittest.TestCase):
 def test_parser_accepts_generic_inputs(self):
  a=M.parse_arguments(['--scenario','s','--declaration','d','--benchmark-root','b','--manifest','m','--system','rdflib/default']);self.assertEqual(a.system,['rdflib/default']);self.assertEqual(a.repetitions,3)
if __name__=='__main__':unittest.main()
