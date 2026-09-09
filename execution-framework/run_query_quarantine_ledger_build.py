#!/usr/bin/env python3
"""Build one immutable query-quarantine evidence ledger."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_executor.query_quarantine_ledger_build import build_ledger_from_paths

def parse_arguments(argv=None):
    parser=argparse.ArgumentParser(description="Build one immutable query-quarantine evidence ledger.")
    parser.add_argument("--input",dest="inputs",type=Path,action="append",required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--created-at-utc",required=True)
    return parser.parse_args(argv)

def main(argv=None):
    args=parse_arguments(argv)
    try:
        ledger=build_ledger_from_paths(args.inputs,args.output,args.created_at_utc)
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}",file=sys.stderr)
        return 1
    print("IMMUTABLE QUERY QUARANTINE LEDGER BUILD: OK")
    print(f"Output: {args.output}")
    print(f"Entries: {len(ledger['entries'])}")
    print(f"Ledger SHA-256: {ledger['ledger_sha256']}")
    return 0
if __name__=="__main__":raise SystemExit(main())
