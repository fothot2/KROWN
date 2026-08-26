#!/usr/bin/env python3
"""Run the real RDF matrix preflight without starting query systems."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bench_executor.rdf_experiment_matrix_resource import _runtime_preflight

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--declaration',required=True)
 parser.add_argument('--manifest',required=True)
 parser.add_argument('--output',required=True)
 parser.add_argument('--systems')
 args=parser.parse_args()
 selected=None if not args.systems else [x.strip() for x in args.systems.split(',')]
 report=_runtime_preflight(Path(args.declaration).resolve(),Path(args.manifest).resolve(),selected_systems=selected)
 output=Path(args.output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
 temporary=output.with_name('.'+output.name+'.tmp')
 temporary.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
 temporary.replace(output)
 print(f"Validated {len(report['experiments'])} systems")
 print(output)
if __name__=='__main__':main()
