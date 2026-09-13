#!/usr/bin/env python3
"""Recalculate and publish the final RDF experiment readiness decision."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from bench_executor.experiment_catalogue import load_catalogue
from bench_executor.final_readiness import build_final_readiness


def write_atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = build_final_readiness(load_catalogue(arguments.catalogue))
    write_atomic_json(arguments.output, report)
    return 0 if report["ready_for_bsbm_10k"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
