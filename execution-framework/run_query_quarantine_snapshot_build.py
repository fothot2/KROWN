#!/usr/bin/env python3
"""Build one immutable query-quarantine snapshot."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_executor.query_quarantine_snapshot_build import (
    build_snapshot_from_paths,
)


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Build one immutable query-quarantine snapshot."
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created-at-utc", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    arguments = parse_arguments(argv)
    try:
        snapshot = build_snapshot_from_paths(
            arguments.ledger,
            arguments.policy,
            arguments.output,
            arguments.created_at_utc,
        )
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("IMMUTABLE QUERY QUARANTINE SNAPSHOT BUILD: OK")
    print(f"Output: {arguments.output}")
    print(f"Decisions: {len(snapshot['decisions'])}")
    print(f"Snapshot SHA-256: {snapshot['snapshot_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
