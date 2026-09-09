"""Validate explicit query-quarantine runtime orchestration inputs."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bench_executor.query_quarantine_contract import content_sha256
from bench_executor.query_quarantine_probe import (
    select_probe_rules,
    validate_probe_policy,
)
from bench_executor.query_quarantine_resolver import validate_snapshot
from bench_executor.standalone_benchmark import input_file


def non_negative_integer(value: str) -> int:
    """Parse one non-negative integer for the matrix CLI."""
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "completed compatible runs must be an integer"
        ) from error
    if result < 0:
        raise ValueError("completed compatible runs must be non-negative")
    return result


def validate_runtime_arguments(
    snapshot_file: str | None,
    probe_policy_file: str | None,
    completed_compatible_runs: int | None,
    matrix_run_id: str | None,
) -> None:
    """Validate cross-field runtime requirements without reading files."""
    if probe_policy_file is not None and snapshot_file is None:
        raise ValueError("probe policy requires a quarantine snapshot")
    if completed_compatible_runs is not None and probe_policy_file is None:
        raise ValueError("completed compatible runs requires a probe policy")
    if probe_policy_file is not None and completed_compatible_runs is None:
        raise ValueError("probe policy requires completed compatible runs")
    if probe_policy_file is not None and (
        not isinstance(matrix_run_id, str) or not matrix_run_id.strip()
    ):
        raise ValueError("matrix run ID is required with a probe policy")
    if completed_compatible_runs is not None and (
        not isinstance(completed_compatible_runs, int)
        or isinstance(completed_compatible_runs, bool)
        or completed_compatible_runs < 0
    ):
        raise ValueError("completed compatible runs must be non-negative")
    if matrix_run_id is not None and (
        not isinstance(matrix_run_id, str)
        or not matrix_run_id.strip()
        or matrix_run_id != matrix_run_id.strip()
    ):
        raise ValueError(
            "matrix run ID must be non-empty without surrounding whitespace"
        )


def load_runtime_orchestration(
    shared: Path,
    snapshot_file: str | None,
    probe_policy_file: str | None,
    completed_compatible_runs: int | None,
    matrix_run_id: str | None,
    force_include: bool,
) -> dict[str, Any]:
    """Resolve and validate all runtime inputs before adapter startup."""
    validate_runtime_arguments(
        snapshot_file,
        probe_policy_file,
        completed_compatible_runs,
        matrix_run_id,
    )
    snapshot = None
    policy = None
    if snapshot_file is not None:
        path = input_file(str(shared), snapshot_file)
        snapshot = validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
    if probe_policy_file is not None:
        path = input_file(str(shared), probe_policy_file)
        policy = validate_probe_policy(json.loads(path.read_text(encoding="utf-8")))
    return {
        "matrix_run_id": matrix_run_id,
        "quarantine_snapshot": snapshot,
        "quarantine_snapshot_sha256": (
            None if snapshot is None else snapshot["snapshot_sha256"]
        ),
        "probe_policy": policy,
        "probe_policy_id": None if policy is None else policy["policy_id"],
        "probe_policy_sha256": (
            None if policy is None else content_sha256(policy)
        ),
        "completed_compatible_runs": completed_compatible_runs,
        "force_include": force_include,
    }


def runtime_probe_rules(runtime: Mapping[str, Any], system_id: str):
    """Select probe rules from one normalized runtime contract."""
    if runtime["force_include"] or runtime["probe_policy"] is None:
        return ()
    return select_probe_rules(
        runtime["quarantine_snapshot"],
        runtime["probe_policy"],
        runtime["completed_compatible_runs"],
        runtime["matrix_run_id"],
        system_id,
    )


def binding_runtime_provenance(
    runtime: Mapping[str, Any], probe_rules
) -> dict[str, Any]:
    """Build one normalized binding-level provenance object."""
    count = 0 if runtime["force_include"] else len(probe_rules)
    return {
        "matrix_run_id": runtime["matrix_run_id"],
        "quarantine_snapshot_sha256": runtime[
            "quarantine_snapshot_sha256"
        ],
        "probe_policy_id": runtime["probe_policy_id"],
        "probe_policy_sha256": runtime["probe_policy_sha256"],
        "completed_compatible_runs": runtime[
            "completed_compatible_runs"
        ],
        "probe_due": count > 0,
        "selected_probe_count": count,
        "force_include": runtime["force_include"],
    }


def matrix_runtime_provenance(
    runtime: Mapping[str, Any], summaries: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Aggregate normalized orchestration provenance for publication."""
    return {
        "matrix_run_id": runtime["matrix_run_id"],
        "quarantine_snapshot_sha256": runtime[
            "quarantine_snapshot_sha256"
        ],
        "probe_policy_id": runtime["probe_policy_id"],
        "probe_policy_sha256": runtime["probe_policy_sha256"],
        "completed_compatible_runs": runtime[
            "completed_compatible_runs"
        ],
        "selected_probe_count": sum(
            item.get("runtime_orchestration", {}).get(
                "selected_probe_count", 0
            )
            for item in summaries
        ),
        "force_include": runtime["force_include"],
    }
