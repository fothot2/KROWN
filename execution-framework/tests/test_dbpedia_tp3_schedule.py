from __future__ import annotations
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/'benchmark-integration/dbbench-dbpedia/data/shared/manifests/dbbench-dbpedia-tp3-v1.json'
def find_records(value):
 found=[]
 def walk(x):
  if isinstance(x,list):
   if sum(isinstance(y,dict) and y.get('stream_phase') in {'warmup','measured'} for y in x)==15683:found.append(x)
   for y in x:walk(y)
  elif isinstance(x,dict):
   for y in x.values():walk(y)
 walk(value);assert len(found)==1;return found[0]
def tp(x):return '/TP/' in x.get('query_id','') or str(x.get('reporting_family') or x.get('query_family') or x.get('family') or '').startswith('TP/')
def join(x):return '/JOINS/' in x.get('query_id','') or str(x.get('reporting_family') or x.get('query_family') or x.get('family') or '').startswith('JOINS/')
def test_dbpedia_tp3_schedule_contract():
 records=find_records(json.loads(MANIFEST.read_text()));assert len(records)==15683
 assert [x['stream_position'] for x in records]==list(range(15683))
 warm=[x for x in records if x['stream_phase']=='warmup'];measured=[x for x in records if x['stream_phase']=='measured']
 assert len(warm)==3625 and all(tp(x) and x['set_repetition']==0 for x in warm)
 mtp=[x for x in measured if tp(x)];joins=[x for x in measured if join(x)]
 assert len(mtp)==10875 and len(joins)==1183
 assert {x['set_repetition'] for x in mtp}=={1,2,3}
 assert all(x['set_repetition']==1 for x in joins)
 assert max(x['stream_position'] for x in mtp)<min(x['stream_position'] for x in joins)
 for rep in (1,2,3):assert [x['source_query_index'] for x in mtp if x['set_repetition']==rep]==list(range(3625))
def test_runner_uses_expanded_schedule_and_long_rdflib_startup():
 text=(ROOT/'run_dbpedia_tp3_v1.py').read_text();assert "'--repetitions','1'" in text
 assert 'dbbench-dbpedia-tp3-v1.json' in text and 'default=3600' in text
