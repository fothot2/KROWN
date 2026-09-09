#!/usr/bin/env python3
"""Validate the frozen experiment catalogue and write a coverage audit."""
from __future__ import annotations
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from bench_executor.experiment_catalogue import build_coverage_audit,load_catalogue,write_audit_outputs

def main(argv=None):
 parser=argparse.ArgumentParser();parser.add_argument("--catalogue",type=Path,required=True);parser.add_argument("--output-root",type=Path,required=True);parser.add_argument("--require-ready",action="store_true");args=parser.parse_args(argv)
 try:
  audit=build_coverage_audit(load_catalogue(args.catalogue));write_audit_outputs(audit,args.output_root)
  if args.require_ready and not audit["ready_for_bsbm_10k"]:raise RuntimeError("catalogue is not ready for BSBM 10k")
 except Exception as error:print(f"ERROR: {type(error).__name__}: {error}",file=sys.stderr);return 1
 print("EXPERIMENT CATALOGUE COVERAGE AUDIT: OK");print(f"Ready for BSBM 10k: {str(audit['ready_for_bsbm_10k']).lower()}");print(f"Missing required systems: {len(audit['missing_required_system_ids'])}");print(f"Blocking metric cells: {len(audit['blocking_cells'])}");return 0
if __name__=="__main__":raise SystemExit(main())
