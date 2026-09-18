#!/usr/bin/env python3
import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_campaign import CampaignSpecification,RdfCampaign,atomic_json,retain
class CampaignTests(unittest.TestCase):
 def test_specification_rejects_unsafe_manifest_and_duplicate_systems(self):
  with self.assertRaises(ValueError):CampaignSpecification('/tmp/s','/tmp/d','../m',systems=('a/b',))
  with self.assertRaises(ValueError):CampaignSpecification('/tmp/s','/tmp/d','m',systems=('a/b','a/b'))
 def test_atomic_json_and_retention(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'a';target=root/'b';source.write_text('x');retain(source,target);self.assertFalse(source.exists());self.assertEqual(target.read_text(),'x');atomic_json(root/'v.json',{'x':1});self.assertEqual(json.loads((root/'v.json').read_text()),{'x':1})
 def test_matrix_command_passes_explicit_benchmark_root(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);spec=CampaignSpecification(root/'scenario',root/'decl.json','manifest.json',root/'bench',systems=('rdflib/default',));c=RdfCampaign(spec,root/'matrix.py',root/'report.py',root/'inter.py');command=c._matrix_command('run','rdflib/default','raw/x');self.assertEqual(command[command.index('--benchmark-root')+1],str((root/'bench').resolve()))
if __name__=='__main__':unittest.main()
