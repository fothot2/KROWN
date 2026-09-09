#!/usr/bin/env python3
from __future__ import annotations
import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_experiment_manifest import system_adapter_specifications
from bench_executor.rdflib_query_benchmark import _make_rdflib_graph

class VortexStorageModesTests(unittest.TestCase):
 def test_registry_contains_four_modes_with_shared_representations(self):
  registry={item.system_id:item for item in system_adapter_specifications()}
  expected={
   'vortex-rdf/dictionary-secondary-by-reference':('vortex-rdf/dictionary-secondary-by-reference',False,'file-backed'),
   'vortex-rdf/dictionary-secondary-by-reference-memory':('vortex-rdf/dictionary-secondary-by-reference',True,'in-memory'),
   'vortex-rdf/dictionary-secondary-by-copy':('vortex-rdf/dictionary-secondary-by-copy',False,'file-backed'),
   'vortex-rdf/dictionary-secondary-by-copy-memory':('vortex-rdf/dictionary-secondary-by-copy',True,'in-memory'),
  }
  for system,(representation,in_memory,storage) in expected.items():
   item=registry[system]
   self.assertEqual(item.configuration.representation,representation)
   self.assertIs(item.parameters['vortex_in_memory'],in_memory)
   self.assertEqual(item.parameters['storage_mode'],storage)

 def test_graph_constructor_receives_explicit_residency(self):
  calls=[]
  class Store:
   def __init__(self,*args,**kwargs):calls.append((args,kwargs))
  class Graph:
   def __init__(self,*,store):self.store=store
  with patch('vortex_rdflib.VortexRdflibStore',Store),patch('bench_executor.rdflib_query_benchmark.Graph',Graph):
   _make_rdflib_graph('vortex','/tmp/data.vortex','unused',False)
   _make_rdflib_graph('vortex','/tmp/data.vortex','unused',True)
  self.assertEqual(calls,[ ((),{'path':'/tmp/data.vortex','in_memory':False}), ((),{'path':'/tmp/data.vortex','in_memory':True}) ])

if __name__=='__main__':unittest.main()
