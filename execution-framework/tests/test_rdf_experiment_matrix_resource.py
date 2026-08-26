#!/usr/bin/env python3
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.experiment_matrix_contract import ArtifactFile,DatasetArtifact,SystemConfiguration
from bench_executor.rdf_experiment_matrix_resource import _constructor_arguments,_result_summary,_stage_artifacts
class RdfExperimentMatrixResourceTests(unittest.TestCase):
 def test_constructor_requires_explicit_unknown_runtime_values(self):
  class Adapter:
   def __init__(self,artifact,data_path,directory,image,index_command):pass
  artifact=DatasetArtifact('sample','tiny','ntriples',1,'a'*64,'rdf/source',(ArtifactFile('x.nt',1,'b'*64),))
  configuration=SystemConfiguration('engine','default','server','rdf/source')
  with self.assertRaisesRegex(ValueError,'image, index_command'):_constructor_arguments(Adapter,artifact,'data','config','log',False,configuration,{})
 def test_constructor_derives_backend_from_configuration(self):
  class Adapter:
   def __init__(self,artifact,data_path,directory,backend):pass
  artifact=DatasetArtifact('sample','tiny','ntriples',1,'a'*64,'rdf/source',(ArtifactFile('x.nt',1,'b'*64),))
  configuration=SystemConfiguration('oxigraph','memory','server','rdf/source')
  arguments=_constructor_arguments(Adapter,artifact,'data','config','log',False,configuration,{})
  self.assertEqual(arguments['backend'],'memory')
 def test_stage_artifacts_keeps_external_source_and_verifies_hash(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)/'Suite'; experiments=root/'experiments'; data=root/'data'; shared=Path(directory)/'shared'; experiments.mkdir(parents=True);data.mkdir();shared.mkdir()
   source=data/'artifact.bin';source.write_bytes(b'payload');digest=hashlib.sha256(b'payload').hexdigest()
   receipt={'files':[{'path':'artifact.bin'}]};(data/'receipt.json').write_text(json.dumps(receipt))
   declaration={'representations':{'custom/default':'data/receipt.json'}};path=experiments/'run.json';path.write_text(json.dumps(declaration))
   artifact=DatasetArtifact('sample','tiny','binary',7,'a'*64,'custom/default',(ArtifactFile('artifact.bin',7,digest),))
   staged=_stage_artifacts(path,{'custom/default':artifact},shared)['custom/default'];target=shared/staged.files[0].path
   self.assertTrue(target.is_file());self.assertEqual(target.read_bytes(),b'payload');self.assertTrue(source.is_file())
 def test_result_summary_reports_failures_and_hash(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'results.jsonl';path.write_text(json.dumps({'status':'ok'})+'\n'+json.dumps({'status':'engine_error'})+'\n')
   experiment=SimpleNamespace(experiment_id='sample/run/system',system_configuration='system/default')
   summary=_result_summary(path,experiment,'custom/default');self.assertEqual(summary['record_count'],2);self.assertEqual(summary['failure_count'],1);self.assertEqual(len(summary['sha256']),64)
if __name__=='__main__':unittest.main()
