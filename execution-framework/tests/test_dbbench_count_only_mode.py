#!/usr/bin/env python3
import unittest
from unittest.mock import patch
from bench_executor.rdf_experiment_matrix_resource import _correctness_mode
from bench_executor.sparql_result import CORRECTNESS_MODES
class Manifest:
 workload='dbbench-dbpedia-full'
class Tests(unittest.TestCase):
 def test_mode(self):
  self.assertIn('count-only',CORRECTNESS_MODES);self.assertEqual(_correctness_mode(Manifest()),'count-only')
 def test_other_workload(self):
  value=Manifest();value.workload='bsbm';self.assertEqual(_correctness_mode(value),'fingerprint')
if __name__=='__main__':unittest.main()
