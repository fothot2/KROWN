#!/usr/bin/env python3
"""Execute the BSBM HTTP-server matrix stage."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_executor.rdf_experiment_matrix_resource import (
    RdfExperimentMatrixResource,
)

HTTP_SYSTEMS = (
    "fuseki/default",
    "virtuoso/default",
    "oxigraph/memory",
    "oxigraph/rocksdb",
)
DECLARATION = Path(
    "/users/u0182905/benchmarks/BSBM/experiments/explore-1k-smoke.json"
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the four BSBM SPARQL HTTP systems."
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=Path(
            "/users/u0182905/KROWN/benchmark-integration/bsbm-smoke"
        ),
    )
    parser.add_argument("--declaration", type=Path, default=DECLARATION)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def execute_http_stage(
    scenario: Path,
    declaration: Path,
    verbose: bool = True,
) -> bool:
    """Execute all HTTP systems through the generic matrix resource."""
    scenario = scenario.expanduser().resolve()
    declaration = declaration.expanduser().resolve()
    resource = RdfExperimentMatrixResource(
        data_path=str(scenario / "data"),
        config_path=str(scenario / "config"),
        directory=str(scenario / "log"),
        verbose=verbose,
    )
    return resource.execute(
        declaration_file=str(declaration),
        manifest_file="manifests/bsbm.json",
        results_file="raw/bsbm-http-summary.json",
        output_file="raw/bsbm-http-results.tar.gz",
        selected_systems=list(HTTP_SYSTEMS),
        failure_results_file="raw/bsbm-http-failed-summary.json",
        failure_output_file="raw/bsbm-http-failed-results.tar.gz",
    )


def main() -> int:
    arguments = parse_arguments()
    success = execute_http_stage(
        arguments.scenario,
        arguments.declaration,
        verbose=not arguments.quiet,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
