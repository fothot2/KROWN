#!/usr/bin/env python3
"""Execute any declared RDF experiment-matrix system selection."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_executor.rdf_experiment_matrix_resource import (
    RdfExperimentMatrixResource,
)


def _relative_shared_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or not value.strip() or ".." in path.parts:
        raise argparse.ArgumentTypeError(
            "artifact paths must be non-empty paths relative to data/shared"
        )
    return path.as_posix()


def parse_systems(values: list[str]) -> list[str]:
    systems: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value.split(","):
            system = item.strip()
            if not system or "/" not in system:
                raise ValueError(
                    "each selected system must use system/configuration syntax"
                )
            if system in seen:
                raise ValueError(f"duplicate selected system: {system}")
            seen.add(system)
            systems.append(system)
    if not systems:
        raise ValueError("at least one system must be selected")
    return systems


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute a generic RDF experiment-matrix selection."
    )
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--manifest", type=_relative_shared_path, required=True)
    parser.add_argument(
        "--system", dest="systems", action="append", required=True,
        help="system/configuration; repeat or use comma-separated values",
    )
    parser.add_argument("--results", type=_relative_shared_path, required=True)
    parser.add_argument("--output", type=_relative_shared_path, required=True)
    parser.add_argument(
        "--failure-results", type=_relative_shared_path, required=True
    )
    parser.add_argument(
        "--failure-output", type=_relative_shared_path, required=True
    )
    parser.add_argument("--quiet", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        arguments.systems = parse_systems(arguments.systems)
    except ValueError as error:
        parser.error(str(error))
    return arguments


def execute_matrix(
    scenario: Path,
    declaration: Path,
    manifest: str,
    systems: list[str],
    results: str,
    output: str,
    failure_results: str,
    failure_output: str,
    verbose: bool = True,
) -> bool:
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
        manifest_file=manifest,
        results_file=results,
        output_file=output,
        selected_systems=list(systems),
        failure_results_file=failure_results,
        failure_output_file=failure_output,
    )


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    success = execute_matrix(
        scenario=arguments.scenario,
        declaration=arguments.declaration,
        manifest=arguments.manifest,
        systems=arguments.systems,
        results=arguments.results,
        output=arguments.output,
        failure_results=arguments.failure_results,
        failure_output=arguments.failure_output,
        verbose=not arguments.quiet,
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
