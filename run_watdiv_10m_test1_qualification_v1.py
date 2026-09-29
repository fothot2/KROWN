#!/usr/bin/env python3
"""Prepare and independently run the WatDiv 10M test.1 qualification stream."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, os, subprocess, time
from pathlib import Path
ROOT=Path('/users/u0182905/KROWN'); BENCH=Path('/users/u0182905/benchmarks')
SCENARIO=ROOT/'benchmark-integration/watdiv-10m'; SHARED=SCENARIO/'data/shared'
SOURCE=SHARED/'manifests/watdiv-10m-smoke.json'; TARGET=SHARED/'manifests/watdiv-10m-test.1-qualification.json'
DECL=BENCH/'WatDiv/experiments/watdiv-10m-smoke.json'; BROOT=BENCH/'WatDiv'; MATRIX=ROOT/'execution-framework/run_rdf_experiment_matrix.py'; PY=Path('/users/u0182905/miniconda3/envs/vortex-rdf/bin/python')
SYSTEMS=('vortex-rdf/dictionary-secondary-by-reference','pycottas/default','comunica/hdt','hdt-rdflib/optimized-in-memory','fuseki/tdb2','qlever/default')
def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name('.'+path.name+'.tmp'); tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n'); os.replace(tmp,path)
def prepare():
 source=json.loads(SOURCE.read_text()); selected=sorted((q for q in source['queries'] if q.get('stream')=='test.1'),key=lambda q:q['position'])
 if len(selected)!=12400 or [q['position'] for q in selected]!=list(range(12400)): raise RuntimeError('test.1 is not a contiguous 12,400-occurrence stream')
 queries=[]
 for i,q in enumerate(selected):
  value={k:v for k,v in q.items() if k not in {'benchmark','dataset','workload','phase','position'}}; value['stream_phase']='measured'; value['stream_position']=i
  if hashlib.sha256(value['query'].encode()).hexdigest()!=value['query_sha256']: raise RuntimeError(f'query hash mismatch at {i}')
  queries.append(value)
 result={k:v for k,v in source.items() if k not in {'queries','query_count','catalog','stream_order'}}; result.update({'workload':'watdiv-stress-100-test.1-qualification','query_count':12400,'stream_order':['test.1'],'qualification_selection':{'schema':'watdiv-krown-stream-qualification-v1','stream':'test.1','source_manifest_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'source_query_count':source['query_count']},'queries':queries}); atomic(TARGET,result); return result
def smoke():
 path=ROOT/'run_watdiv_10m_multisystem_smoke_v1.py'; spec=importlib.util.spec_from_file_location(path.stem,path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
def run_one(system):
 slug=system.replace('/','--'); base=f'raw/test.1/{slug}'; command=[str(PY),str(MATRIX),'--scenario',str(SCENARIO),'--declaration',str(DECL),'--benchmark-root',str(BROOT),'--manifest','manifests/watdiv-10m-test.1-qualification.json','--system',system,'--results',base+'-summary.json','--output',base+'-results.tar.gz','--failure-results',base+'-failed-summary.json','--failure-output',base+'-failed-results.tar.gz']
 env=smoke().env_for(system); env.setdefault('RUST_LOG','vortex_rdf_cli=debug,vortex_rdf_core=debug'); env.setdefault('KROWN_RDFLIB_STARTUP_TIMEOUT_S','900'); env.setdefault('KROWN_IN_RUN_TIMEOUT_QUARANTINE_THRESHOLD','2'); started=time.perf_counter_ns(); completed=subprocess.run(command,cwd=ROOT,env=env,check=False); elapsed=time.perf_counter_ns()-started
 success=SHARED/(base+'-summary.json'); failure=SHARED/(base+'-failed-summary.json'); summary=success if success.is_file() else failure
 return {'system':system,'status':'completed' if completed.returncode==0 else 'failed','returncode':completed.returncode,'elapsed_ns':elapsed,'summary':str(summary) if summary.is_file() else None}
def publish(rows):
 path=SHARED/'raw/test.1/watdiv-10m-test.1-qualification-ledger.json'; current={}
 if path.is_file(): current={r['system']:r for r in json.loads(path.read_text()).get('systems',[])}
 current.update({r['system']:r for r in rows}); atomic(path,{'schema':'watdiv-stream-qualification-ledger-v1','stream':'test.1','systems':[current[s] for s in SYSTEMS if s in current]}); return path
def main(argv=None):
 parser=argparse.ArgumentParser(); parser.add_argument('--prepare-only',action='store_true'); parser.add_argument('--system',action='append',choices=SYSTEMS); args=parser.parse_args(argv); manifest=prepare(); print(f'WATDIV TEST.1 MANIFEST READY queries={len(manifest["queries"])} path={TARGET}')
 if args.prepare_only:return 0
 rows=[]
 for system in args.system or list(SYSTEMS):
  print('WATDIV TEST.1 SYSTEM START',system,flush=True)
  try: rows.append(run_one(system))
  except Exception as error: rows.append({'system':system,'status':'failed','returncode':None,'summary':None,'error':f'{type(error).__name__}: {error}'})
  print('WATDIV TEST.1 SYSTEM DONE',system,rows[-1]['status'],flush=True)
 print('WATDIV TEST.1 QUALIFICATION LEDGER',publish(rows)); return 0 if all(r['status']=='completed' for r in rows) else 1
if __name__=='__main__':raise SystemExit(main())
