#!/usr/bin/env python3
import unittest
from bench_executor.resource_profile import *
from bench_executor.rdf_campaign import scoped_matrix_command
class Tests(unittest.TestCase):
 def test_profile(self):
  self.assertEqual(SYSTEM_MEMORY_BYTES,58*1024**3);self.assertEqual(FUSEKI_HEAPS["memory"],("4g","54g"));self.assertEqual(FUSEKI_HEAPS["tdb2"],("4g","16g"));n,d=virtuoso_buffers();self.assertGreater(n,4_000_000);self.assertEqual(d,int(n*0.75))
 def test_scope(self):
  c=scoped_matrix_command(["python","x.py"],"unit");self.assertIn("MemoryMax=58G",c);self.assertIn("MemorySwapMax=0",c);self.assertEqual(c[-2:],["python","x.py"])
if __name__=="__main__":unittest.main()
