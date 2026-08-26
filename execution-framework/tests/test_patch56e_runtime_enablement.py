#!/usr/bin/env python3
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.experiment_matrix_contract import ArtifactFile,DatasetArtifact
from bench_executor.qlever_system_adapter import QLeverSystemAdapter

class Patch56eRuntimeEnablementTests(unittest.TestCase):
 def test_oxigraph_builder_has_native_rocksdb_toolchain(self):
  root=Path(__file__).resolve().parents[1]; text=(root/'dockers/Oxigraph/Dockerfile').read_text()
  for value in ('clang','libclang-dev','cmake','pkg-config','cargo install --locked --version'):
   self.assertIn(value,text)
  self.assertIn('ENTRYPOINT ["oxigraph"]',text)
 def test_qlever_image_uses_required_data_workdir(self):
  root=Path(__file__).resolve().parents[1]; text=(root/'dockers/QLever/Dockerfile').read_text()
  self.assertIn('WORKDIR /data',text)
 def test_qlever_derives_direct_binary_commands(self):
  artifact=DatasetArtifact('sample','tiny','ntriples',1,'a'*64,'rdf/source',(ArtifactFile('rdf-matrix-artifacts/rdf--source--0.nt',1,'b'*64),))
  with tempfile.TemporaryDirectory() as directory, patch('bench_executor.qlever_system_adapter.QLever') as qlever:
   QLeverSystemAdapter(artifact,directory,directory)
  args=qlever.call_args.args
  self.assertEqual(args[3],'kgconstruct/qlever:v0.6.0')
  self.assertIn('/qlever/qlever-index',args[4]); self.assertIn('/data/shared/rdf-matrix-artifacts/rdf--source--0.nt',args[4])
  self.assertIn('/qlever/qlever-server',args[5]); self.assertIn('--port 7001',args[5])

if __name__=='__main__': unittest.main()
