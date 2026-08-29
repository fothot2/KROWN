#!/usr/bin/env python3
'''Compare RDF result archives without benchmark-specific rules.'''
from __future__ import annotations
import argparse, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_executor.rdf_cross_system_comparison import compare_archives

def arguments(argv=None):
    parser=argparse.ArgumentParser(description='Compare independent RDF matrix result archives.')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--archive', type=Path, action='append', required=True)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    return parser.parse_args(argv)

def main(argv=None):
    args=arguments(argv)
    report=compare_archives(args.manifest.resolve(), [p.resolve() for p in args.archive], None if args.policy is None else args.policy.resolve())
    target=args.output.resolve(); target.parent.mkdir(parents=True, exist_ok=True)
    handle=tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=target.parent,prefix=f'.{target.name}.',suffix='.tmp',delete=False)
    temporary=Path(handle.name)
    try:
        with handle: json.dump(report,handle,indent=2,sort_keys=True,allow_nan=False); handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,target)
    finally: temporary.unlink(missing_ok=True)
    return 0
if __name__=='__main__': raise SystemExit(main())
