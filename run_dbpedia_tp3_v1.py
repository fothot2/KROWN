#!/usr/bin/env python3
"""Gold runner for phased DBpedia TP3 system benchmarking."""
from __future__ import annotations
import argparse, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path('/users/u0182905/KROWN')
BENCH=Path('/users/u0182905/benchmarks/DBBench')
PYTHON=Path('/users/u0182905/miniconda3/envs/vortex-rdf/bin/python')
CAMPAIGN=ROOT/'execution-framework/run_rdf_campaign.py'
SCENARIO=ROOT/'benchmark-integration/dbbench-dbpedia'
DECLARATION=BENCH/'experiments/dbpedia-en-all-full.json'
MANIFEST='manifests/dbbench-dbpedia-tp3-v1.json'
SYSTEMS=(
 'rdflib/default','pycottas/default',
 'vortex-rdf/dictionary-secondary-by-reference','vortex-rdf/dictionary-secondary-by-reference-memory',
 'vortex-rdf/dictionary-secondary-by-copy','vortex-rdf/dictionary-secondary-by-copy-memory',
 'oxigraph/memory','oxigraph/rocksdb','fuseki/memory','fuseki/tdb2','virtuoso/default','qlever/default',
)
SAFE=re.compile(r'^[A-Za-z0-9._-]+$')
REUSE = {
 'fuseki': (ROOT/'benchmark-integration/dbbench-dbpedia/data/fuseki-tdb2-preserved-20260922T162121Z', BENCH/'data/dbpedia-en-all/fuseki-tdb2-store-receipt.json'),
 'virtuoso': (ROOT/'benchmark-integration/dbbench-dbpedia/data/virtuoso-preserved-20260923T102207Z', BENCH/'data/dbpedia-en-all/virtuoso-store-receipt.json'),
 'qlever': (ROOT/'benchmark-integration/dbbench-dbpedia/data/qlever-index-preserved-20260923T150938Z', BENCH/'data/dbpedia-en-all/qlever-index-receipt.json'),
 'oxigraph': (ROOT/'benchmark-integration/dbbench-dbpedia/data/oxigraph-rocksdb', BENCH/'data/dbpedia-en-all/oxigraph-rocksdb-store-receipt.json'),
}
REUSE_ENV = {
 'fuseki': ('KROWN_FUSEKI_TDB2_MODE','KROWN_FUSEKI_TDB2_REUSE_PATH','KROWN_FUSEKI_TDB2_RECEIPT'),
 'virtuoso': ('KROWN_VIRTUOSO_MODE','KROWN_VIRTUOSO_REUSE_PATH','KROWN_VIRTUOSO_RECEIPT'),
 'qlever': ('KROWN_QLEVER_MODE','KROWN_QLEVER_REUSE_PATH','KROWN_QLEVER_RECEIPT'),
 'oxigraph': ('KROWN_OXIGRAPH_ROCKSDB_MODE','KROWN_OXIGRAPH_ROCKSDB_REUSE_PATH','KROWN_OXIGRAPH_ROCKSDB_RECEIPT'),
}
def validate_reuse_inputs():
 for name,(store,receipt) in REUSE.items():
  if not store.is_dir(): raise SystemExit(f'missing reusable {name} store: {store}')
  if not receipt.is_file(): raise SystemExit(f'missing reusable {name} receipt: {receipt}')
  value=__import__('json').loads(receipt.read_text())
  if not value.get('schema'): raise SystemExit(f'invalid reusable {name} receipt: {receipt}')
def apply_reuse_environment(env):
 for name,(store,receipt) in REUSE.items():
  mode,path_key,receipt_key=REUSE_ENV[name]
  env[mode]='reuse';env[path_key]=str(store);env[receipt_key]=str(receipt)
def parse_args():
 p=argparse.ArgumentParser()
 p.add_argument('--campaign-id',default=None);p.add_argument('--system',action='append',default=[])
 p.add_argument('--system-limit-s',type=int,default=21600);p.add_argument('--rdflib-startup-timeout-s',type=int,default=3600)
 p.add_argument('--resume',action='store_true');p.add_argument('--retry-failed',action='store_true');p.add_argument('--dry-run',action='store_true')
 a=p.parse_args();a.campaign_id=a.campaign_id or datetime.now(timezone.utc).strftime('dbpedia-tp3-gold-%Y%m%dT%H%M%SZ')
 if not SAFE.fullmatch(a.campaign_id):p.error('--campaign-id must be one safe path component')
 if a.system_limit_s<=0 or a.rdflib_startup_timeout_s<=0:p.error('timeouts must be positive')
 unknown=sorted(set(a.system)-set(SYSTEMS))
 if unknown:p.error('unknown systems: '+', '.join(unknown))
 return a
def main():
 a=parse_args();validate_reuse_inputs();selected=a.system or list(SYSTEMS)
 cmd=[str(PYTHON),str(CAMPAIGN),'--scenario',str(SCENARIO),'--declaration',str(DECLARATION),
      '--benchmark-root',str(BENCH),'--manifest',MANIFEST,'--repetitions','1','--system-limit-s',str(a.system_limit_s),'--campaign-id',a.campaign_id]
 for system in selected:cmd.extend(['--system',system])
 if a.resume:cmd.append('--resume')
 if a.retry_failed:cmd.append('--retry-failed')
 print(' '.join(cmd),flush=True)
 if a.dry_run:return 0
 env=dict(os.environ);env.setdefault('RUST_LOG','vortex_rdf_cli=debug,vortex_rdf_core=debug')
 env['KROWN_RDFLIB_STARTUP_TIMEOUT_S']=str(a.rdflib_startup_timeout_s);env['PYTHONUNBUFFERED']='1';apply_reuse_environment(env)
 return subprocess.run(cmd,cwd=ROOT,env=env,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
