#!/usr/bin/env python3
"""Create compact timing and resource reports from an RDF matrix summary."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping


def _number(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _validate_timing(value: Mapping[str, Any], schema: str, field: str) -> None:
    if not isinstance(value, Mapping) or value.get("schema") != schema:
        raise ValueError(f"{field} has an invalid schema")
    stages = value.get("stages_ns")
    total = _number(value.get("total_wall_ns"), f"{field}.total_wall_ns")
    if not isinstance(stages, Mapping):
        raise ValueError(f"{field}.stages_ns must be an object")
    stage_sum = sum(_number(item, f"{field}.stages_ns") for item in stages.values())
    if stage_sum != total or value.get("stages_sum_ns", stage_sum) != stage_sum:
        raise ValueError(f"{field} does not reconcile")
    if value.get("reconciled") is not True:
        raise ValueError(f"{field} is not marked reconciled")


def _milliseconds(value: int | None) -> float | None:
    return None if value is None else round(value / 1_000_000, 3)


def _phase(workload: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    phases = workload.get("phases", {})
    value = phases.get(name, {})
    return value if isinstance(value, Mapping) else {}


def build_report(summary: Mapping[str, Any]) -> dict[str, Any]:
    experiments = summary.get("experiments")
    if not isinstance(experiments, list):
        raise ValueError("summary experiments must be an array")
    rows = []
    for index, experiment in enumerate(experiments):
        if not isinstance(experiment, Mapping):
            raise ValueError(f"experiment {index} must be an object")
        timing = experiment.get("system_timing")
        _validate_timing(timing, "rdf-system-timing-v1", f"experiment {index}.system_timing")
        workload = experiment.get("workload_timing")
        if not isinstance(workload, Mapping) or workload.get("schema") != "rdf-workload-timing-v1":
            raise ValueError(f"experiment {index} has invalid workload timing")
        warmup = _phase(workload, "warmup")
        measured = _phase(workload, "measured")
        measured_count = _number(measured.get("attempt_count", 0), "measured.attempt_count")
        measured_total = _number(measured.get("attempt_total_ns", 0), "measured.attempt_total_ns")
        metrics = experiment.get("resource_metrics") or {}
        mode = experiment.get("execution_mode") or {}
        stages = timing["stages_ns"]
        rows.append({
            "system": experiment.get("system"),
            "representation": experiment.get("representation"),
            "status": experiment.get("status"),
            "record_count": experiment.get("record_count"),
            "failure_count": experiment.get("failure_count"),
            "storage": mode.get("storage"),
            "process_temperature": mode.get("process_temperature"),
            "lifecycle": mode.get("lifecycle"),
            "warmup_total_ms": _milliseconds(warmup.get("attempt_total_ns", 0)),
            "measured_total_ms": _milliseconds(measured_total),
            "measured_attempt_count": measured_count,
            "measured_mean_ms": (
                None if measured_count == 0
                else round(measured_total / measured_count / 1_000_000, 3)
            ),
            "system_total_ms": _milliseconds(timing["total_wall_ns"]),
            "open_or_load_ms": _milliseconds(stages.get("artifact_open_or_load", 0)),
            "startup_ms": _milliseconds(stages.get("engine_startup", 0)),
            "shutdown_ms": _milliseconds(stages.get("engine_shutdown", 0)),
            "validation_ms": _milliseconds(stages.get("validation", 0)),
            "unclassified_ms": _milliseconds(stages.get("unclassified", 0)),
            "max_rss_mib": (
                None if metrics.get("max_rss_kib") is None
                else round(_number(metrics["max_rss_kib"], "max_rss_kib") / 1024, 3)
            ),
            "user_cpu_ms": _milliseconds(metrics.get("user_cpu_ns")),
            "system_cpu_ms": _milliseconds(metrics.get("system_cpu_ns")),
            "major_page_faults": metrics.get("major_page_faults"),
            "minor_page_faults": metrics.get("minor_page_faults"),
            "input_blocks": metrics.get("input_blocks"),
            "output_blocks": metrics.get("output_blocks"),
        })
    measured_values = [row["measured_total_ms"] for row in rows]
    return {
        "schema": "rdf-experiment-report-v1",
        "status": summary.get("status"),
        "matrix_timing": summary.get("matrix_timing"),
        "experiment_count": len(rows),
        "measured_total_ms": round(sum(measured_values), 3),
        "measured_median_ms": (
            None if not measured_values
            else round(statistics.median(measured_values), 3)
        ),
        "experiments": rows,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--csv", dest="csv_path", type=Path)
    args = parser.parse_args(argv)
    report = build_report(json.loads(args.summary.read_text(encoding="utf-8")))
    if args.json_path:
        args.json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.csv_path:
        write_csv(args.csv_path, report["experiments"])
    if not args.json_path and not args.csv_path:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
