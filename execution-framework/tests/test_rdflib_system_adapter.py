#!/usr/bin/env python3
import hashlib,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.experiment_matrix_contract import ArtifactFile,DatasetArtifact
from bench_executor.rdflib_system_adapter import RdfLibSystemAdapter,adapter_specification
class Tests(unittest.TestCase):
 def test_contract_prepare_and_command(self):
  with tempfile.TemporaryDirectory() as d:
   shared=Path(d)/"shared"; shared.mkdir(); p=shared/"dataset.nt"; p.write_text("<http://example.org/s> <http://example.org/p> <http://example.org/o> .\n"); payload=p.read_bytes(); h=hashlib.sha256(payload).hexdigest()
   artifact=DatasetArtifact(benchmark="bsbm",dataset="explore-1k",source_format="ntriples",source_size_bytes=len(payload),source_sha256=h,representation="rdf/source",files=(ArtifactFile(p.name,len(payload),h),))
   a=RdfLibSystemAdapter(artifact,d); self.assertEqual(a.system_id,"rdflib/default"); self.assertTrue(a.prepare()); self.assertEqual(a.query_parameters()["engine"],"default"); self.assertIn("g.parse",a.docker_smoke_command("SELECT * WHERE { ?s ?p ?o } LIMIT 1")[-1])
 def test_specification(self):
  s=adapter_specification(); self.assertEqual(s.system_id,"rdflib/default"); self.assertEqual(s.configuration.kind,"embedded"); self.assertEqual(s.configuration.representation,"rdf/source")
if __name__=="__main__": unittest.main()
