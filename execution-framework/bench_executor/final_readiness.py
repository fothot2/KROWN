"""Final machine-readable readiness gate for RDF benchmark execution."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bench_executor.experiment_catalogue import build_coverage_audit
from bench_executor.outcome_contract import CATEGORIES
from bench_executor.rdf_inter_run_statistics import METHOD
from summarize_rdf_experiment import write_csv, write_json, write_markdown, write_xlsx

SCHEMA = "krown-rdf-final-readiness-v1"
EXPECTED_OUTCOMES = frozenset({
    "completed", "timeout", "skipped", "engine-error",
    "semantic-mismatch", "confirmed-oom",
})
EXPECTED_OUTPUTS = ["json", "csv", "markdown", "xlsx"]
EXPECTED_BENCHMARK_ORDER = ["bsbm", "krown-synthetic", "dbbench"]
EXPECTED_FIRST_EXECUTION = "bsbm/10k"
EXPECTED_OOM_RULE = "confirmed-process-memory-exhaustion-only"
EXPECTED_PERCENTILE_METHOD = "linear-interpolation-r7"


def build_final_readiness(catalogue: Mapping[str, Any]) -> dict[str, Any]:
    """Recalculate every non-runtime gate from current source contracts."""
    audit = build_coverage_audit(catalogue)
    scope = catalogue.get("scope")
    dataset_scales = scope.get("dataset_scales") if isinstance(scope, Mapping) else None
    required_rows = [row for row in audit["rows"] if row["required"]]
    required_metric_statuses_ready = all(
        row["status"] in {"validated", "not-applicable"}
        for row in required_rows
    )
    try:
        import openpyxl  # noqa: F401
        xlsx_dependency_ready = True
    except ImportError:
        xlsx_dependency_ready = False
    report_writers = (write_json, write_csv, write_markdown, write_xlsx)
    checks = {
        "catalogue_schema_ready": catalogue.get("schema") == "krown-experiment-catalogue-v1",
        "missing_required_systems_ready": not audit["missing_required_system_ids"],
        "metric_coverage_ready": not audit["blocking_cells"] and required_metric_statuses_ready,
        "outcome_contract_ready": CATEGORIES == EXPECTED_OUTCOMES,
        "partial_outcome_ready": {"timeout", "skipped", "engine-error", "semantic-mismatch", "confirmed-oom"}.issubset(CATEGORIES),
        "automatic_reporting_ready": catalogue.get("required_outputs") == EXPECTED_OUTPUTS and all(callable(writer) for writer in report_writers),
        "xlsx_dependency_ready": xlsx_dependency_ready,
        "inter_run_statistics_ready": METHOD == EXPECTED_PERCENTILE_METHOD,
        "strict_oom_rule_ready": catalogue.get("oom_rule") == EXPECTED_OOM_RULE,
        "benchmark_order_ready": isinstance(scope, Mapping) and scope.get("blocking_benchmarks") == EXPECTED_BENCHMARK_ORDER,
        "first_execution_ready": isinstance(dataset_scales, Mapping) and dataset_scales.get("first_execution") == EXPECTED_FIRST_EXECUTION,
    }
    ready = all(checks.values())
    return {
        "schema": SCHEMA,
        "catalogue_id": catalogue.get("catalogue_id"),
        "first_execution": dataset_scales.get("first_execution") if isinstance(dataset_scales, Mapping) else None,
        "blocking_benchmarks": scope.get("blocking_benchmarks") if isinstance(scope, Mapping) else None,
        "required_outputs": catalogue.get("required_outputs"),
        "oom_rule": catalogue.get("oom_rule"),
        "percentile_method": METHOD,
        "outcome_categories": sorted(CATEGORIES),
        "registered_system_ids": audit["registered_system_ids"],
        "missing_required_system_ids": audit["missing_required_system_ids"],
        "missing_required_system_count": len(audit["missing_required_system_ids"]),
        "blocking_metric_cells": audit["blocking_cells"],
        "blocking_metric_cell_count": len(audit["blocking_cells"]),
        "checks": checks,
        "ready_for_bsbm_10k": ready,
    }
