#!/usr/bin/env python3
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.cottas_standalone_system_adapter import CottasStandaloneSystemAdapter as A
class Tests(unittest.TestCase):
 def test_contract_and_command(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"dataset.cottas"; p.write_bytes(b"x"); a=A()
   self.assertEqual(a.system_id,"pycottas/default"); self.assertEqual(a.representation,"cottas/default")
   self.assertEqual(a.lifecycle,("prepare","execute","collect"))
   c=a.docker_command(p,"SELECT * WHERE { ?s ?p ?o } LIMIT 1")
   self.assertEqual(c[-3:-1],["python","-c"])
   self.assertIn("COTTASStore",c[-1]); self.assertIn("graph.query".replace("graph.","g."),c[-1])
 def test_rejections(self):
  a=A()
  with self.assertRaises(FileNotFoundError): a.prepare("missing.cottas")
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.hdt"; p.write_bytes(b"x")
   with self.assertRaises(ValueError): a.prepare(p)
if __name__=="__main__": unittest.main()
