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
 a=parse_args();selected=a.system or list(SYSTEMS)
 cmd=[str(PYTHON),str(CAMPAIGN),'--scenario',str(SCENARIO),'--declaration',str(DECLARATION),
      '--benchmark-root',str(BENCH),'--manifest',MANIFEST,'--repetitions','1','--system-limit-s',str(a.system_limit_s),'--campaign-id',a.campaign_id]
 for system in selected:cmd.extend(['--system',system])
 if a.resume:cmd.append('--resume')
 if a.retry_failed:cmd.append('--retry-failed')
 print(' '.join(cmd),flush=True)
 if a.dry_run:return 0
 env=dict(os.environ);env.setdefault('RUST_LOG','vortex_rdf_cli=debug,vortex_rdf_core=debug')
 env['KROWN_RDFLIB_STARTUP_TIMEOUT_S']=str(a.rdflib_startup_timeout_s);env['PYTHONUNBUFFERED']='1'
 return subprocess.run(cmd,cwd=ROOT,env=env,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
