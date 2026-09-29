#!/usr/bin/env python3
"""Prepare and run one continuous five-stream WatDiv 10M campaign."""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,os,subprocess,time
from pathlib import Path
ROOT=Path('/users/u0182905/KROWN');BENCH=Path('/users/u0182905/benchmarks');SCENARIO=ROOT/'benchmark-integration/watdiv-10m';SHARED=SCENARIO/'data/shared'
SOURCE=SHARED/'manifests/watdiv-10m-smoke.json';TARGET=SHARED/'manifests/watdiv-10m-measured-campaign.json';DECL=BENCH/'WatDiv/experiments/watdiv-10m-smoke.json';BROOT=BENCH/'WatDiv';MATRIX=ROOT/'execution-framework/run_rdf_experiment_matrix.py';PY=Path('/users/u0182905/miniconda3/envs/vortex-rdf/bin/python')
STREAMS=tuple(f'test.{i}' for i in range(1,6));SYSTEMS=('vortex-rdf/dictionary-secondary-by-reference','pycottas/default','comunica/hdt','hdt-rdflib/optimized-in-memory','fuseki/tdb2','qlever/default')
def atomic(p,v):p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name('.'+p.name+'.tmp');t.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n');os.replace(t,p)
def prepare():
 source=json.loads(SOURCE.read_text()); selected=[]
 for stream in STREAMS:
  rows=sorted((q for q in source['queries'] if q.get('stream')==stream),key=lambda q:q['position'])
  if len(rows)!=12400 or [q['position'] for q in rows]!=list(range(12400)):raise RuntimeError(f'{stream} is not contiguous')
  selected.extend(rows)
 queries=[]
 for i,q in enumerate(selected):
  v={k:x for k,x in q.items() if k not in {'benchmark','dataset','workload','phase','position'}};v['stream_phase']='measured';v['stream_position']=i
  if hashlib.sha256(v['query'].encode()).hexdigest()!=v['query_sha256']:raise RuntimeError(f'query hash mismatch at {i}')
  queries.append(v)
 result={k:v for k,v in source.items() if k not in {'queries','query_count','catalog','stream_order'}};result.update({'workload':'watdiv-stress-100-five-stream-measured-campaign','query_count':62000,'stream_order':list(STREAMS),'schedule':{'schema':'rdf-preexpanded-stream-schedule-v1','mode':'preexpanded','phase_field':'stream_phase'},'campaign_selection':{'schema':'watdiv-five-stream-measured-campaign-v1','source_manifest_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest()},'queries':queries});atomic(TARGET,result);return result
def smoke():
 p=ROOT/'run_watdiv_10m_multisystem_smoke_v1.py';s=importlib.util.spec_from_file_location(p.stem,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def run_one(system):
 slug=system.replace('/','--');base=f'raw/measured-campaign/{slug}';cmd=[str(PY),str(MATRIX),'--scenario',str(SCENARIO),'--declaration',str(DECL),'--benchmark-root',str(BROOT),'--manifest','manifests/watdiv-10m-measured-campaign.json','--system',system,'--results',base+'-summary.json','--output',base+'-results.tar.gz','--failure-results',base+'-failed-summary.json','--failure-output',base+'-failed-results.tar.gz']
 env=smoke().env_for(system);env.setdefault('RUST_LOG','vortex_rdf_cli=debug,vortex_rdf_core=debug');env['KROWN_IN_RUN_TIMEOUT_QUARANTINE_THRESHOLD']='2';env['KROWN_RDF_BUDGET_MIN_ATTEMPTS']='500';env['KROWN_RDF_BUDGET_MAX_PROJECTED_WALL_S']='28800';env['KROWN_RDF_BUDGET_MAX_ACTUAL_WALL_S']='14400';env.setdefault('KROWN_RDFLIB_STARTUP_TIMEOUT_S','900')
 started=time.perf_counter_ns();p=subprocess.run(cmd,cwd=ROOT,env=env,check=False);elapsed=time.perf_counter_ns()-started
 success=SHARED/(base+'-summary.json');failure=SHARED/(base+'-failed-summary.json');summary=success if success.is_file() else failure;status='failed'
 if summary.is_file():status=json.loads(summary.read_text()).get('status','failed')
 return {'system':system,'status':status,'returncode':p.returncode,'elapsed_ns':elapsed,'summary':str(summary) if summary.is_file() else None}
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--prepare-only',action='store_true');p.add_argument('--system',action='append',choices=SYSTEMS);a=p.parse_args(argv);m=prepare();print(f'WATDIV MEASURED CAMPAIGN MANIFEST READY queries={len(m["queries"])} path={TARGET}')
 if a.prepare_only:return 0
 rows=[]
 for system in a.system or list(SYSTEMS):
  print('WATDIV CAMPAIGN SYSTEM START',system,flush=True)
  try:rows.append(run_one(system))
  except Exception as e:rows.append({'system':system,'status':'failed','returncode':None,'error':f'{type(e).__name__}: {e}'})
  print('WATDIV CAMPAIGN SYSTEM DONE',system,rows[-1]['status'],flush=True)
 ledger=SHARED/'raw/measured-campaign/watdiv-10m-measured-campaign-ledger.json';atomic(ledger,{'schema':'watdiv-measured-campaign-ledger-v1','streams':list(STREAMS),'systems':rows});print('WATDIV CAMPAIGN LEDGER',ledger)
 return 0 if all(r['status'] in {'ok','completed_with_failures','budget_exhausted'} for r in rows) else 1
if __name__=='__main__':raise SystemExit(main())
