#!/usr/bin/env python3
"""Run canonical staged WatDiv 10M campaigns with a five-hour system budget."""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,os,subprocess,time
from pathlib import Path
ROOT=Path('/users/u0182905/KROWN');BENCH=Path('/users/u0182905/benchmarks')
SCENARIO=ROOT/'benchmark-integration/watdiv-10m';SHARED=SCENARIO/'data/shared'
SOURCE=SHARED/'manifests/watdiv-10m-smoke.json';DECL=BENCH/'WatDiv/experiments/watdiv-10m-smoke.json';BROOT=BENCH/'WatDiv';MATRIX=ROOT/'execution-framework/run_rdf_experiment_matrix.py';PY=Path('/users/u0182905/miniconda3/envs/vortex-rdf/bin/python')
SYSTEMS=('vortex-rdf/dictionary-secondary-by-reference','pycottas/default','comunica/hdt','hdt-rdflib/optimized-in-memory','fuseki/tdb2','qlever/default')
STAGES={'primary':('test.1',),'extension':('test.2','test.3','test.4','test.5'),'all':('test.1','test.2','test.3','test.4','test.5')}
ACTUAL_BUDGET_S=18000

def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name('.'+path.name+'.tmp');tmp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');os.replace(tmp,path)
def stage_paths(stage):
 return (SHARED/f'manifests/watdiv-10m-{stage}-campaign.json',f'raw/{stage}-campaign')
def prepare(stage):
 streams=STAGES[stage];source=json.loads(SOURCE.read_text());selected=[]
 for stream in streams:
  rows=sorted((q for q in source['queries'] if q.get('stream')==stream),key=lambda q:q['position'])
  if len(rows)!=12400 or [q['position'] for q in rows]!=list(range(12400)):raise RuntimeError(f'{stream} is not contiguous')
  selected.extend(rows)
 queries=[]
 for index,query in enumerate(selected):
  value={key:item for key,item in query.items() if key not in {'benchmark','dataset','workload','phase','position'}};value['stream_phase']='measured';value['stream_position']=index
  if hashlib.sha256(value['query'].encode()).hexdigest()!=value['query_sha256']:raise RuntimeError(f'query hash mismatch at {index}')
  queries.append(value)
 target,_=stage_paths(stage);result={key:item for key,item in source.items() if key not in {'queries','query_count','catalog','stream_order'}}
 result.update({'workload':f'watdiv-stress-100-{stage}-campaign','query_count':len(queries),'stream_order':list(streams),'schedule':{'schema':'rdf-preexpanded-stream-schedule-v1','mode':'preexpanded','phase_field':'stream_phase'},'campaign_selection':{'schema':'watdiv-canonical-staged-campaign-v1','stage':stage,'source_manifest_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest()},'queries':queries});atomic(target,result);return target,result
def smoke():
 path=ROOT/'run_watdiv_10m_multisystem_smoke_v1.py';spec=importlib.util.spec_from_file_location(path.stem,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def primary_summary(system):
 _,base=stage_paths('primary');return SHARED/base/(system.replace('/','--')+'-summary.json')
def extension_eligible(system):
 path=primary_summary(system)
 if not path.is_file():return False,'primary summary is missing'
 value=json.loads(path.read_text());experiments=value.get('experiments',[])
 if value.get('status') not in {'ok','completed_with_failures'}:return False,f"primary status is {value.get('status')}"
 if len(experiments)!=1 or experiments[0].get('record_count')!=12400:return False,'primary stream is incomplete'
 return True,'complete primary stream'
def existing_complete(stage,system,expected):
 _,base=stage_paths(stage);path=SHARED/base/(system.replace('/','--')+'-summary.json')
 if not path.is_file():return None
 value=json.loads(path.read_text());experiments=value.get('experiments',[])
 if value.get('status') in {'ok','completed_with_failures'} and len(experiments)==1 and experiments[0].get('record_count')==expected:return path
 return None
def run_one(stage,system,manifest):
 streams=STAGES[stage];expected=12400*len(streams);prior=existing_complete(stage,system,expected)
 if prior:return {'system':system,'stage':stage,'status':'skipped-complete','returncode':0,'summary':str(prior)}
 if stage=='extension':
  eligible,reason=extension_eligible(system)
  if not eligible:return {'system':system,'stage':stage,'status':'ineligible','returncode':0,'reason':reason,'summary':None}
 _,base=stage_paths(stage);slug=system.replace('/','--');prefix=f'{base}/{slug}';command=[str(PY),str(MATRIX),'--scenario',str(SCENARIO),'--declaration',str(DECL),'--benchmark-root',str(BROOT),'--manifest',str(manifest.relative_to(SHARED)),'--system',system,'--results',prefix+'-summary.json','--output',prefix+'-results.tar.gz','--failure-results',prefix+'-failed-summary.json','--failure-output',prefix+'-failed-results.tar.gz']
 env=smoke().env_for(system);env.setdefault('RUST_LOG','vortex_rdf_cli=debug,vortex_rdf_core=debug');env['KROWN_IN_RUN_TIMEOUT_QUARANTINE_THRESHOLD']='2';env['KROWN_RDF_BUDGET_MIN_ATTEMPTS']='0';env['KROWN_RDF_BUDGET_MAX_PROJECTED_WALL_S']='0';env['KROWN_RDF_BUDGET_MAX_ACTUAL_WALL_S']=str(ACTUAL_BUDGET_S);env.setdefault('KROWN_RDFLIB_STARTUP_TIMEOUT_S','900')
 started=time.perf_counter_ns();completed=subprocess.run(command,cwd=ROOT,env=env,check=False);elapsed=time.perf_counter_ns()-started
 success=SHARED/(prefix+'-summary.json');failure=SHARED/(prefix+'-failed-summary.json');summary=success if success.is_file() else failure;status='failed'
 if summary.is_file():status=json.loads(summary.read_text()).get('status','failed')
 return {'system':system,'stage':stage,'status':status,'returncode':completed.returncode,'elapsed_ns':elapsed,'summary':str(summary) if summary.is_file() else None}
def publish(stage,rows):
 _,base=stage_paths(stage);path=SHARED/base/f'watdiv-10m-{stage}-campaign-ledger.json';existing={}
 if path.is_file():existing={row['system']:row for row in json.loads(path.read_text()).get('systems',[])}
 existing.update({row['system']:row for row in rows});atomic(path,{'schema':'watdiv-staged-campaign-ledger-v1','stage':stage,'streams':list(STAGES[stage]),'actual_budget_s':ACTUAL_BUDGET_S,'projected_budget_enabled':False,'systems':[existing[s] for s in SYSTEMS if s in existing]});return path
def parse(argv=None):
 parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=tuple(STAGES),default='primary');parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--system',action='append',choices=SYSTEMS);return parser.parse_args(argv)
def main(argv=None):
 args=parse(argv);manifest,value=prepare(args.stage);print(f'WATDIV {args.stage.upper()} CAMPAIGN MANIFEST READY queries={len(value["queries"])} path={manifest}')
 if args.prepare_only:return 0
 rows=[]
 for system in args.system or list(SYSTEMS):
  print('WATDIV CAMPAIGN SYSTEM START',args.stage,system,flush=True)
  try:rows.append(run_one(args.stage,system,manifest))
  except KeyboardInterrupt:raise
  except Exception as error:rows.append({'system':system,'stage':args.stage,'status':'failed','returncode':None,'error':f'{type(error).__name__}: {error}'})
  print('WATDIV CAMPAIGN SYSTEM DONE',args.stage,system,rows[-1]['status'],flush=True)
 print('WATDIV CAMPAIGN LEDGER',publish(args.stage,rows));accepted={'ok','completed_with_failures','budget_exhausted','skipped-complete','ineligible'};return 0 if all(row['status'] in accepted for row in rows) else 1
if __name__=='__main__':raise SystemExit(main())
