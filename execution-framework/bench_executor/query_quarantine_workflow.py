"""Run the controlled query-quarantine evidence workflow."""
from __future__ import annotations

import hashlib
import os
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bench_executor.query_quarantine_ingestion_output import (
    build_ingestion_document_from_paths,
)
from bench_executor.query_quarantine_ledger_build import (
    build_ledger_from_paths,
    validate_ledger_v2,
)
from bench_executor.query_quarantine_snapshot_build import (
    build_snapshot_from_paths,
)
from bench_executor.query_quarantine_resolver import validate_snapshot

WORKFLOW_SCHEMA = "rdf-query-quarantine-controlled-workflow-v1"
AUDIT_SCHEMA = "rdf-query-quarantine-controlled-workflow-audit-v1"
_PLAN_FIELDS = {
    "schema", "created_at_utc", "runs", "ledger", "policy", "snapshot",
    "audit",
}
_RUN_FIELDS = {
    "summary", "archive", "manifest", "declaration", "run_id", "system",
    "adapter_identity", "artifact_identity", "selector_kind",
    "summary_sha256", "archive_sha256", "exclusion_report", "output",
}
_OUTPUT_FIELDS = {"output", "created_at_utc"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(
            f"{field} must be non-empty text without surrounding whitespace"
        )
    return value


def _relative(value: Any, field: str) -> Path:
    text = _text(value, field)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a safe relative path")
    return path


def _resolve(root: Path, value: Any, field: str) -> Path:
    relative = _relative(value, field)
    result = (root / relative).resolve()
    try:
        result.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{field} leaves the workflow root") from error
    return result


def validate_workflow_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one explicit workflow plan without accessing source files."""
    if not isinstance(value, Mapping) or set(value) != _PLAN_FIELDS:
        raise ValueError("invalid controlled workflow fields")
    if value.get("schema") != WORKFLOW_SCHEMA:
        raise ValueError("unsupported controlled workflow schema")
    _text(value["created_at_utc"], "created_at_utc")
    runs = value.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("runs must be a non-empty array")
    normalized_runs = []
    run_ids = set()
    outputs = set()
    for index, raw in enumerate(runs):
        if not isinstance(raw, Mapping) or set(raw) != _RUN_FIELDS:
            raise ValueError(f"run {index} has invalid fields")
        run = dict(raw)
        run_id = _text(run["run_id"], f"run {index}.run_id")
        if run_id in run_ids:
            raise ValueError("duplicate workflow run_id")
        run_ids.add(run_id)
        for field in (
            "summary", "archive", "manifest", "declaration", "output"
        ):
            run[field] = _relative(
                run[field], f"run {index}.{field}"
            ).as_posix()
        if run["exclusion_report"] is not None:
            run["exclusion_report"] = _relative(
                run["exclusion_report"],
                f"run {index}.exclusion_report",
            ).as_posix()
        for field in (
            "system", "adapter_identity", "artifact_identity",
            "selector_kind", "summary_sha256", "archive_sha256",
        ):
            _text(run[field], f"run {index}.{field}")
        if run["output"] in outputs:
            raise ValueError("duplicate workflow output path")
        outputs.add(run["output"])
        normalized_runs.append(run)
    normalized = {
        "schema": WORKFLOW_SCHEMA,
        "created_at_utc": value["created_at_utc"],
        "runs": normalized_runs,
    }
    for section in ("ledger", "snapshot"):
        raw = value.get(section)
        if not isinstance(raw, Mapping) or set(raw) != _OUTPUT_FIELDS:
            raise ValueError(f"invalid {section} fields")
        normalized[section] = {
            "output": _relative(
                raw["output"], f"{section}.output"
            ).as_posix(),
            "created_at_utc": _text(
                raw["created_at_utc"], f"{section}.created_at_utc"
            ),
        }
        if normalized[section]["output"] in outputs:
            raise ValueError("duplicate workflow output path")
        outputs.add(normalized[section]["output"])
    normalized["policy"] = _relative(
        value["policy"], "policy"
    ).as_posix()
    normalized["audit"] = _relative(
        value["audit"], "audit"
    ).as_posix()
    if normalized["audit"] in outputs:
        raise ValueError("duplicate workflow output path")
    return normalized


def _audit_document(
    plan_path: Path,
    plan: Mapping[str, Any],
    evidence_paths: list[Path],
    ledger_path: Path,
    snapshot_path: Path,
) -> dict[str, Any]:
    ledger = validate_ledger_v2(json.loads(ledger_path.read_text()))
    snapshot = validate_snapshot(json.loads(snapshot_path.read_text()))
    body = {
        "schema": AUDIT_SCHEMA,
        "created_at_utc": plan["created_at_utc"],
        "workflow_plan_sha256": _sha256_file(plan_path),
        "evidence_documents": [
            {"path": str(path), "sha256": _sha256_file(path)}
            for path in evidence_paths
        ],
        "ledger": {
            "path": str(ledger_path),
            "file_sha256": _sha256_file(ledger_path),
            "ledger_sha256": ledger["ledger_sha256"],
            "entry_count": len(ledger["entries"]),
        },
        "snapshot": {
            "path": str(snapshot_path),
            "file_sha256": _sha256_file(snapshot_path),
            "snapshot_sha256": snapshot["snapshot_sha256"],
            "decision_count": len(snapshot["decisions"]),
            "quarantined_count": sum(
                item["decision"] == "quarantined"
                for item in snapshot["decisions"]
            ),
        },
    }
    return {**body, "audit_sha256": hashlib.sha256(
        json.dumps(
            body, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()}


def execute_controlled_workflow(
    plan_path: Path,
    root: Path,
) -> dict[str, Any]:
    """Execute all stages and remove every new output after any failure."""
    plan_path = Path(plan_path).resolve()
    root = Path(root).resolve()
    if not plan_path.is_file():
        raise FileNotFoundError(f"workflow plan is missing: {plan_path}")
    plan = validate_workflow_plan(
        json.loads(plan_path.read_text(encoding="utf-8"))
    )
    evidence_paths = [
        _resolve(root, item["output"], f"run {index}.output")
        for index, item in enumerate(plan["runs"])
    ]
    ledger_path = _resolve(root, plan["ledger"]["output"], "ledger.output")
    snapshot_path = _resolve(
        root, plan["snapshot"]["output"], "snapshot.output"
    )
    audit_path = _resolve(root, plan["audit"], "audit")
    policy_path = _resolve(root, plan["policy"], "policy")
    outputs = [*evidence_paths, ledger_path, snapshot_path, audit_path]
    existing = [path for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(
            "workflow output already exists: " + ", ".join(map(str, existing))
        )
    created: list[Path] = []
    try:
        for index, (run, output) in enumerate(
            zip(plan["runs"], evidence_paths)
        ):
            build_ingestion_document_from_paths(
                summary_path=_resolve(
                    root, run["summary"], f"run {index}.summary"
                ),
                archive_path=_resolve(
                    root, run["archive"], f"run {index}.archive"
                ),
                manifest_path=_resolve(
                    root, run["manifest"], f"run {index}.manifest"
                ),
                declaration_path=_resolve(
                    root, run["declaration"], f"run {index}.declaration"
                ),
                run_id=run["run_id"],
                system=run["system"],
                adapter_identity=run["adapter_identity"],
                artifact_identity=run["artifact_identity"],
                created_at_utc=plan["created_at_utc"],
                selector_kind=run["selector_kind"],
                expected_summary_sha256=run["summary_sha256"],
                expected_archive_sha256=run["archive_sha256"],
                exclusion_report_path=(
                    None if run["exclusion_report"] is None else _resolve(
                        root, run["exclusion_report"],
                        f"run {index}.exclusion_report",
                    )
                ),
                output_path=output,
            )
            created.append(output)
        build_ledger_from_paths(
            evidence_paths,
            ledger_path,
            plan["ledger"]["created_at_utc"],
        )
        created.append(ledger_path)
        build_snapshot_from_paths(
            ledger_path,
            policy_path,
            snapshot_path,
            plan["snapshot"]["created_at_utc"],
        )
        created.append(snapshot_path)
        audit = _audit_document(
            plan_path, plan, evidence_paths, ledger_path, snapshot_path
        )
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            audit_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(audit, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        created.append(audit_path)
        return audit
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        for parent in sorted(
            {path.parent for path in outputs},
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            try:
                parent.rmdir()
            except OSError:
                pass
        raise
