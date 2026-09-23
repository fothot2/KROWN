#!/usr/bin/env python3
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from bench_executor.experiment_matrix_contract import ArtifactFile,DatasetArtifact
from bench_executor.fuseki_system_adapter import FusekiSystemAdapter,REUSE_MODE
class Tests(unittest.TestCase):
 def test_reuse_never_resets_or_loads(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);shared=root/'shared';shared.mkdir();src=shared/'dataset.nt';src.write_bytes(b'x');digest=hashlib.sha256(b'x').hexdigest();store=root/'store';data=store/'Data-0001';data.mkdir(parents=True);(data/'SPO.dat').write_bytes(b'abc');receipt=root/'receipt.json';receipt.write_text(json.dumps({'schema':'fuseki-tdb2-store-receipt-v1','source_sha256':digest,'files':[{'path':'Data-0001/SPO.dat','size_bytes':3}],'allocated_bytes':4096}));artifact=DatasetArtifact('dbbench','dbpedia','ntriples',1,digest,'rdf/source',(ArtifactFile('dataset.nt',1,digest),))
   with patch('bench_executor.fuseki_system_adapter.Fuseki') as cls:
    runtime=cls.return_value;runtime.wait_until_ready.return_value=True;runtime.stop.return_value=True
    adapter=FusekiSystemAdapter(artifact,str(root),str(root),str(root),dataset_mode='tdb2',lifecycle_mode=REUSE_MODE,reuse_store_path=str(store),reuse_receipt_path=str(receipt));self.assertTrue(adapter.prepare());adapter.memory_sampler=MagicMock();self.assertTrue(adapter.start());self.assertTrue(adapter.ready());self.assertTrue(adapter.stop())
   runtime.reset_store.assert_not_called();runtime.load.assert_not_called();cls.assert_called_once();self.assertEqual(cls.call_args.kwargs['database_path'],str(store.resolve()))
if __name__=='__main__':unittest.main()
