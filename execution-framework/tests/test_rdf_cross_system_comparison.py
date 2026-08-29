#!/usr/bin/env python3
from __future__ import annotations
import json, sys, tarfile, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_cross_system_comparison import compare_archives, compare_results

MODES={'q1':'unordered_multiset_fingerprint','q8':'ordered_fingerprint','q9':'implementation_defined_describe','q10':'ordered_fingerprint'}
def record(query,status='ok',fingerprint='same',count=1):
 return {'query_id':query,'phase':'measured','run':0,'status':status,'elapsed_ns':1,'result_count':count if status=='ok' else None,'result_fingerprint':fingerprint if status=='ok' else None}
class Tests(unittest.TestCase):
 def systems(self):
  return {'rdflib/default':[record('q1'),record('q8'),record('q9','ok','describe-a',6),record('q10')], 'virtuoso/default':[record('q1'),record('q8','ok','different',2),record('q9','ok','describe-b',27),record('q10')], 'vortex-rdf/layout':[record('q1'),record('q8'),record('q9','ok','describe-a',6),record('q10','timeout')]}
 def test_classifies_match_mismatch_describe_and_deferred_timeout(self):
  policy={'schema':'rdf-cross-system-policy-v1','deferred_limitations':[{'system':'vortex-rdf/layout','query_id':'q10','status':'timeout','reason':'deferred overhaul'}]}
  report=compare_results(MODES,self.systems(),policy)
  by_query={item['query_id']:item for item in report['outcomes']}
  self.assertEqual(by_query['q1']['classification'],'strict_match')
  self.assertEqual(by_query['q8']['classification'],'strict_mismatch')
  self.assertEqual(by_query['q9']['classification'],'implementation_defined_describe')
  self.assertEqual(by_query['q10']['classification'],'deferred_limitation')
  self.assertTrue(report['structural_completeness']['complete'])
 def test_unapproved_timeout_is_execution_failure(self):
  report=compare_results(MODES,self.systems())
  self.assertEqual(next(x for x in report['outcomes'] if x['query_id']=='q10')['classification'],'execution_failure')
 def test_missing_record_is_incomplete(self):
  systems=self.systems(); systems['virtuoso/default'].pop()
  report=compare_results(MODES,systems)
  self.assertFalse(report['structural_completeness']['complete'])
  self.assertEqual(next(x for x in report['outcomes'] if x['query_id']=='q10')['classification'],'incomplete')
 def test_manifest_derives_absent_comparison_modes(self):
  with tempfile.TemporaryDirectory() as directory:
   manifest=Path(directory)/'manifest.json'
   manifest.write_text(json.dumps({'queries':[
    {'query_id':'select','query':'SELECT ?s WHERE { ?s ?p ?o }'},
    {'query_id':'describe','query':'DESCRIBE <http://example/s>'},
   ]}))
   from bench_executor.rdf_cross_system_comparison import load_manifest_modes
   modes,_=load_manifest_modes(manifest)
  self.assertEqual(modes['select'],'unordered_multiset_fingerprint')
  self.assertEqual(modes['describe'],'implementation_defined_describe')
 def test_manifest_keeps_explicit_comparison_mode(self):
  with tempfile.TemporaryDirectory() as directory:
   manifest=Path(directory)/'manifest.json'
   manifest.write_text(json.dumps({'queries':[{
    'query_id':'limited',
    'query':'SELECT ?s WHERE { ?s ?p ?o } LIMIT 1',
    'comparison_mode':'ordered_fingerprint',
   }]}))
   from bench_executor.rdf_cross_system_comparison import load_manifest_modes
   modes,_=load_manifest_modes(manifest)
  self.assertEqual(modes['limited'],'ordered_fingerprint')
 def test_duplicate_system_across_archives_is_rejected(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory); manifest=root/'manifest.json'; manifest.write_text(json.dumps({'queries':[{'query_id':'q1','comparison_mode':'unordered_multiset_fingerprint'}]}))
   archives=[]
   for index in (1,2):
    data=root/f'r{index}.jsonl'; data.write_text(json.dumps(record('q1'))+'\n')
    archive=root/f'a{index}.tar.gz'
    with tarfile.open(archive,'w:gz') as out: out.add(data,arcname='same--default.jsonl')
    archives.append(archive)
   with self.assertRaisesRegex(ValueError,'duplicate system'): compare_archives(manifest,archives)
if __name__=='__main__': unittest.main()
