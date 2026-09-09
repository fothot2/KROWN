#!/usr/bin/env python3
"""Run one controlled query-quarantine runtime activation."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_executor.query_quarantine_activation import execute_activation

def main(argv=None):
    parser=argparse.ArgumentParser(description="Validate or run one controlled quarantine activation.")
    parser.add_argument("--plan",type=Path,required=True);parser.add_argument("--root",type=Path,required=True);parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args(argv)
    try:audit=execute_activation(args.plan,args.root,args.dry_run)
    except Exception as error:print(f"ERROR: {type(error).__name__}: {error}",file=sys.stderr);return 1
    if args.dry_run:print("CONTROLLED QUARANTINE ACTIVATION DRY RUN: OK");print(json.dumps(audit,indent=2))
    else:print("CONTROLLED QUARANTINE ACTIVATION: OK");print(f"Audit SHA-256: {audit['audit_sha256']}")
    return 0
if __name__=="__main__":raise SystemExit(main())
