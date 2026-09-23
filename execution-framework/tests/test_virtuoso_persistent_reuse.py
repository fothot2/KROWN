#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from bench_executor.experiment_matrix_contract import ArtifactFile,DatasetArtifact
from bench_executor.virtuoso_system_adapter import VirtuosoSystemAdapter,REUSE_MODE

class VirtuosoPersistentReuseTests(unittest.TestCase):
 def test_reuse_never_hashes_resets_or_loads(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); shared=root/'shared'; shared.mkdir(); src=shared/'dataset.nt'; src.write_bytes(b'x'); digest=hashlib.sha256(b'x').hexdigest(); store=root/'store'; store.mkdir(); (store/'virtuoso.db').write_bytes(b'durable'); receipt=root/'receipt.json'; receipt.write_text(json.dumps({'schema':'virtuoso-store-receipt-v1','source_sha256':digest,'store_path':str(store.resolve()),'files':[{'path':'virtuoso.db','size_bytes':7}],'allocated_bytes':4096})); artifact=DatasetArtifact('dbbench','dbpedia','ntriples',1,digest,'rdf/source',(ArtifactFile('dataset.nt',1,digest),))
   with patch('bench_executor.virtuoso_system_adapter.Virtuoso') as cls, patch('bench_executor.virtuoso_system_adapter._sha256',side_effect=AssertionError('source hash must not run')):
    runtime=cls.return_value; runtime.wait_until_ready.return_value=True; runtime.stop.return_value=True
    adapter=VirtuosoSystemAdapter(artifact,str(root),str(root),str(root),lifecycle_mode=REUSE_MODE,reuse_store_path=str(store),reuse_receipt_path=str(receipt)); self.assertTrue(adapter.prepare()); adapter.memory_sampler=MagicMock(); self.assertTrue(adapter.start()); self.assertTrue(adapter.ready()); self.assertTrue(adapter.stop())
   runtime.reset_store.assert_not_called(); runtime.load_parallel.assert_not_called(); self.assertEqual(cls.call_args.kwargs['database_path'],str(store.resolve())); self.assertEqual(adapter.build_metrics['boundary'],'prebuilt-representation-reuse')
 def test_reuse_accepts_expected_database_growth(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); shared=root/'shared'; shared.mkdir(); src=shared/'dataset.nt'; src.write_bytes(b'x'); digest=hashlib.sha256(b'x').hexdigest(); store=root/'store'; store.mkdir(); db=store/'virtuoso.db'; db.write_bytes(b'durable'); receipt=root/'receipt.json'; receipt.write_text(json.dumps({'schema':'virtuoso-store-receipt-v1','source_sha256':digest,'store_path':str(store.resolve()),'files':[{'path':'virtuoso.db','size_bytes':7}]})); artifact=DatasetArtifact('dbbench','dbpedia','ntriples',1,digest,'rdf/source',(ArtifactFile('dataset.nt',1,digest),)); db.write_bytes(b'durable-after-checkpoint')
   with patch('bench_executor.virtuoso_system_adapter.Virtuoso'):
    adapter=VirtuosoSystemAdapter(artifact,str(root),str(root),str(root),lifecycle_mode=REUSE_MODE,reuse_store_path=str(store),reuse_receipt_path=str(receipt)); self.assertTrue(adapter.prepare()); self.assertEqual(adapter.representation_size['logical_bytes'],len(b'durable-after-checkpoint'))

 def test_reuse_fails_closed_when_stable_file_is_missing(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); shared=root/'shared'; shared.mkdir(); src=shared/'dataset.nt'; src.write_bytes(b'x'); digest=hashlib.sha256(b'x').hexdigest(); store=root/'store'; store.mkdir(); receipt=root/'receipt.json'; receipt.write_text(json.dumps({'schema':'virtuoso-store-receipt-v1','source_sha256':digest,'store_path':str(store.resolve()),'files':[{'path':'virtuoso.db','size_bytes':7}]})); artifact=DatasetArtifact('dbbench','dbpedia','ntriples',1,digest,'rdf/source',(ArtifactFile('dataset.nt',1,digest),))
   with patch('bench_executor.virtuoso_system_adapter.Virtuoso'):
    adapter=VirtuosoSystemAdapter(artifact,str(root),str(root),str(root),lifecycle_mode=REUSE_MODE,reuse_store_path=str(store),reuse_receipt_path=str(receipt)); self.assertFalse(adapter.prepare())
 def test_reuse_ready_does_not_require_build_sampler(self):
  adapter=VirtuosoSystemAdapter.__new__(VirtuosoSystemAdapter)
  adapter._virtuoso=MagicMock()
  adapter._lifecycle_mode=REUSE_MODE
  adapter.memory_sampler=None
  self.assertTrue(adapter.ready())

 def test_lock_file_is_excluded_from_stable_inventory(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d); shared=root/'shared'; shared.mkdir(); src=shared/'dataset.nt'; src.write_bytes(b'x'); digest=hashlib.sha256(b'x').hexdigest(); store=root/'store'; store.mkdir(); (store/'virtuoso.db').write_bytes(b'durable'); (store/'virtuoso.lck').write_bytes(b'lock'); receipt=root/'receipt.json'; receipt.write_text(json.dumps({'schema':'virtuoso-store-receipt-v1','source_sha256':digest,'store_path':str(store.resolve()),'files':[{'path':'virtuoso.db','size_bytes':7}]})); artifact=DatasetArtifact('dbbench','dbpedia','ntriples',1,digest,'rdf/source',(ArtifactFile('dataset.nt',1,digest),))
   with patch('bench_executor.virtuoso_system_adapter.Virtuoso'):
    adapter=VirtuosoSystemAdapter(artifact,str(root),str(root),str(root),lifecycle_mode=REUSE_MODE,reuse_store_path=str(store),reuse_receipt_path=str(receipt)); self.assertTrue(adapter.prepare())

if __name__=='__main__':unittest.main()
