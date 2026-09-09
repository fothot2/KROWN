#!/usr/bin/env python3
"""Run one controlled query-quarantine evidence workflow."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_executor.query_quarantine_workflow import execute_controlled_workflow

def main(argv=None):
    parser=argparse.ArgumentParser(description="Run the controlled evidence, ledger, and snapshot workflow.")
    parser.add_argument("--plan",type=Path,required=True)
    parser.add_argument("--root",type=Path,required=True)
    arguments=parser.parse_args(argv)
    try:audit=execute_controlled_workflow(arguments.plan,arguments.root)
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}",file=sys.stderr);return 1
    print("CONTROLLED QUERY QUARANTINE WORKFLOW: OK")
    print(f"Evidence documents: {len(audit['evidence_documents'])}")
    print(f"Ledger entries: {audit['ledger']['entry_count']}")
    print(f"Snapshot decisions: {audit['snapshot']['decision_count']}")
    print(f"Quarantined: {audit['snapshot']['quarantined_count']}")
    print(f"Audit SHA-256: {audit['audit_sha256']}")
    return 0
if __name__=="__main__":raise SystemExit(main())
