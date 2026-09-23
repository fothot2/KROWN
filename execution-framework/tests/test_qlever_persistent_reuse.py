#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from bench_executor.experiment_matrix_contract import ArtifactFile,DatasetArtifact
from bench_executor.qlever_system_adapter import QLeverSystemAdapter,REUSE_MODE

class QLeverPersistentReuseTests(unittest.TestCase):
 def test_reuse_never_hashes_or_builds_index(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); shared=root/'shared'; shared.mkdir(); src=shared/'dataset.nt'; src.write_bytes(b'x'); digest=hashlib.sha256(b'x').hexdigest(); index=root/'index'; index.mkdir(); (index/'dataset.index.spo').write_bytes(b'abc'); receipt=root/'receipt.json'; receipt.write_text(json.dumps({'schema':'qlever-index-receipt-v1','source_sha256':digest,'index_path':str(index.resolve()),'files':[{'path':'dataset.index.spo','size_bytes':3}]})); artifact=DatasetArtifact('dbbench','dbpedia','ntriples',1,digest,'rdf/source',(ArtifactFile('dataset.nt',1,digest),))
   with patch('bench_executor.qlever_system_adapter.QLever') as cls, patch('bench_executor.qlever_system_adapter._sha256',side_effect=AssertionError('source hash must not run')):
    runtime=cls.return_value; runtime.endpoint='http://localhost:7001'; runtime.start.return_value=True; runtime.wait_until_ready.return_value=True; runtime.stop.return_value=True
    adapter=QLeverSystemAdapter(artifact,str(root),str(root),lifecycle_mode=REUSE_MODE,reuse_index_path=str(index),reuse_receipt_path=str(receipt)); self.assertTrue(adapter.prepare()); self.assertTrue(adapter.start()); self.assertTrue(adapter.ready()); self.assertTrue(adapter.stop())
   runtime.build_index.assert_not_called(); self.assertEqual(cls.call_args.kwargs['index_path'],str(index.resolve())); self.assertEqual(adapter.build_metrics['boundary'],'prebuilt-representation-reuse')
 def test_reuse_fails_when_stable_index_changes(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); shared=root/'shared'; shared.mkdir(); src=shared/'dataset.nt'; src.write_bytes(b'x'); digest=hashlib.sha256(b'x').hexdigest(); index=root/'index'; index.mkdir(); (index/'dataset.index.spo').write_bytes(b'changed'); receipt=root/'receipt.json'; receipt.write_text(json.dumps({'schema':'qlever-index-receipt-v1','source_sha256':digest,'index_path':str(index.resolve()),'files':[{'path':'dataset.index.spo','size_bytes':3}]})); artifact=DatasetArtifact('dbbench','dbpedia','ntriples',1,digest,'rdf/source',(ArtifactFile('dataset.nt',1,digest),))
   with patch('bench_executor.qlever_system_adapter.QLever'):
    adapter=QLeverSystemAdapter(artifact,str(root),str(root),lifecycle_mode=REUSE_MODE,reuse_index_path=str(index),reuse_receipt_path=str(receipt)); self.assertFalse(adapter.prepare())
if __name__=='__main__':unittest.main()
