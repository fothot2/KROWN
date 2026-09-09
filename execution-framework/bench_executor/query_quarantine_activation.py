"""Run a controlled matrix activation from one immutable snapshot."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bench_executor.query_quarantine_contract import content_sha256
from bench_executor.query_quarantine_probe import validate_probe_policy
from bench_executor.query_quarantine_resolver import validate_snapshot

ACTIVATION_SCHEMA = "rdf-query-quarantine-activation-plan-v1"
AUDIT_SCHEMA = "rdf-query-quarantine-activation-audit-v1"
_PLAN_FIELDS = {
    "schema", "created_at_utc", "scenario", "declaration", "manifest",
    "systems", "snapshot", "probe_policy", "completed_compatible_runs",
    "matrix_run_id", "force_include", "outputs", "expectation", "audit",
}
_OUTPUT_FIELDS = {
    "summary", "archive", "failure_summary", "failure_archive",
}
_EXPECTATION_FIELDS = {
    "matrix_status", "selected_probe_count", "minimum_skipped_count",
    "require_success_bundle", "require_failure_bundle",
}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty text without surrounding whitespace")
    return value


def _relative(value: Any, field: str) -> str:
    text = _text(value, field)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a safe relative path")
    return path.as_posix()


def _resolve(root: Path, value: str, field: str) -> Path:
    path = (root / _relative(value, field)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{field} leaves the activation root") from error
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_activation_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one runtime activation plan."""
    if not isinstance(value, Mapping) or set(value) != _PLAN_FIELDS:
        raise ValueError("invalid activation plan fields")
    if value.get("schema") != ACTIVATION_SCHEMA:
        raise ValueError("unsupported activation plan schema")
    systems = value.get("systems")
    if (not isinstance(systems, list) or not systems
            or any(not isinstance(item, str) or not item.strip() or "/" not in item for item in systems)
            or len(systems) != len(set(systems))):
        raise ValueError("systems must be a non-empty unique system/configuration array")
    completed = value.get("completed_compatible_runs")
    if not isinstance(completed, int) or isinstance(completed, bool) or completed < 0:
        raise ValueError("completed_compatible_runs must be non-negative")
    if not isinstance(value.get("force_include"), bool):
        raise TypeError("force_include must be boolean")
    outputs = value.get("outputs")
    if not isinstance(outputs, Mapping) or set(outputs) != _OUTPUT_FIELDS:
        raise ValueError("invalid activation output fields")
    expectation = value.get("expectation")
    if not isinstance(expectation, Mapping) or set(expectation) != _EXPECTATION_FIELDS:
        raise ValueError("invalid activation expectation fields")
    if expectation["matrix_status"] not in {"ok", "completed_with_failures", "failed"}:
        raise ValueError("unsupported expected matrix status")
    for field in ("selected_probe_count", "minimum_skipped_count"):
        item = expectation[field]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise ValueError(f"expectation.{field} must be non-negative")
    for field in ("require_success_bundle", "require_failure_bundle"):
        if not isinstance(expectation[field], bool):
            raise TypeError(f"expectation.{field} must be boolean")
    normalized = dict(value)
    for field in ("created_at_utc", "matrix_run_id"):
        normalized[field] = _text(value[field], field)
    for field in ("scenario", "declaration", "manifest", "snapshot", "probe_policy", "audit"):
        normalized[field] = _relative(value[field], field)
    normalized["systems"] = list(systems)
    normalized["outputs"] = {
        key: _relative(item, f"outputs.{key}") for key, item in outputs.items()
    }
    normalized["expectation"] = dict(expectation)
    if len(set(normalized["outputs"].values())) != len(_OUTPUT_FIELDS):
        raise ValueError("activation output paths must be unique")
    return normalized


def preflight_activation(plan_path: Path, root: Path) -> dict[str, Any]:
    """Validate inputs and expected outputs without starting a matrix engine."""
    root = Path(root).resolve()
    plan_path = Path(plan_path).resolve()
    if not plan_path.is_file():
        raise FileNotFoundError(f"activation plan is missing: {plan_path}")
    plan = validate_activation_plan(json.loads(plan_path.read_text(encoding="utf-8")))
    scenario = _resolve(root, plan["scenario"], "scenario")
    declaration = _resolve(root, plan["declaration"], "declaration")
    if not scenario.is_dir():
        raise FileNotFoundError(f"scenario is missing: {scenario}")
    if not declaration.is_file():
        raise FileNotFoundError(f"declaration is missing: {declaration}")
    shared = scenario / "data/shared"
    if not shared.is_dir():
        raise FileNotFoundError(f"scenario shared directory is missing: {shared}")
    manifest = shared / plan["manifest"]
    snapshot_path = shared / plan["snapshot"]
    probe_policy_path = shared / plan["probe_policy"]
    for path, label in ((manifest, "manifest"), (snapshot_path, "snapshot"), (probe_policy_path, "probe policy")):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is missing: {path}")
    snapshot = validate_snapshot(json.loads(snapshot_path.read_text(encoding="utf-8")))
    probe_policy = validate_probe_policy(json.loads(probe_policy_path.read_text(encoding="utf-8")))
    outputs = {key: shared / value for key, value in plan["outputs"].items()}
    audit = _resolve(root, plan["audit"], "audit")
    existing = [path for path in [*outputs.values(), audit] if path.exists()]
    if existing:
        raise FileExistsError("activation output already exists: " + ", ".join(map(str, existing)))
    return {
        "plan": plan,
        "scenario": scenario,
        "declaration": declaration,
        "shared": shared,
        "snapshot": snapshot,
        "probe_policy": probe_policy,
        "outputs": outputs,
        "audit": audit,
        "snapshot_path": snapshot_path,
        "probe_policy_path": probe_policy_path,
        "plan_sha256": _sha256_file(plan_path),
    }


def _matrix_command(context: Mapping[str, Any]) -> list[str]:
    plan = context["plan"]
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "run_rdf_experiment_matrix.py"),
        "--scenario", str(context["scenario"]),
        "--declaration", str(context["declaration"]),
        "--manifest", plan["manifest"],
    ]
    for system in plan["systems"]:
        command.extend(["--system", system])
    command.extend([
        "--results", plan["outputs"]["summary"],
        "--output", plan["outputs"]["archive"],
        "--failure-results", plan["outputs"]["failure_summary"],
        "--failure-output", plan["outputs"]["failure_archive"],
        "--quarantine-snapshot", plan["snapshot"],
        "--quarantine-probe-policy", plan["probe_policy"],
        "--completed-compatible-runs", str(plan["completed_compatible_runs"]),
        "--matrix-run-id", plan["matrix_run_id"],
    ])
    if plan["force_include"]:
        command.append("--force-include")
    return command


def _validate_runtime_result(context: Mapping[str, Any], returncode: int) -> dict[str, Any]:
    plan = context["plan"]
    expectation = plan["expectation"]
    outputs = context["outputs"]
    success_present = outputs["summary"].is_file() and outputs["archive"].is_file()
    failure_present = outputs["failure_summary"].is_file() and outputs["failure_archive"].is_file()
    if success_present != expectation["require_success_bundle"]:
        raise RuntimeError("success bundle presence differs from activation expectation")
    if failure_present != expectation["require_failure_bundle"]:
        raise RuntimeError("failure bundle presence differs from activation expectation")
    selected_summary = outputs["summary"] if success_present else outputs["failure_summary"]
    if not selected_summary.is_file():
        raise RuntimeError("matrix did not publish an expected summary")
    summary = json.loads(selected_summary.read_text(encoding="utf-8"))
    if summary.get("status") != expectation["matrix_status"]:
        raise RuntimeError("matrix status differs from activation expectation")
    runtime = summary.get("runtime_orchestration")
    if not isinstance(runtime, Mapping):
        raise RuntimeError("matrix runtime provenance is missing")
    if runtime.get("matrix_run_id") != plan["matrix_run_id"]:
        raise RuntimeError("matrix run ID differs from activation plan")
    if runtime.get("quarantine_snapshot_sha256") != context["snapshot"]["snapshot_sha256"]:
        raise RuntimeError("matrix used a different quarantine snapshot")
    if runtime.get("probe_policy_sha256") != content_sha256(context["probe_policy"]):
        raise RuntimeError("matrix used a different probe policy")
    if runtime.get("completed_compatible_runs") != plan["completed_compatible_runs"]:
        raise RuntimeError("matrix used a different completed-run count")
    if runtime.get("force_include") != plan["force_include"]:
        raise RuntimeError("matrix force-include state differs")
    if runtime.get("selected_probe_count") != expectation["selected_probe_count"]:
        raise RuntimeError("selected probe count differs from activation expectation")
    experiments = summary.get("experiments")
    if not isinstance(experiments, list):
        raise RuntimeError("matrix experiments are missing")
    if [item.get("system") for item in experiments] != plan["systems"]:
        raise RuntimeError("matrix selected systems differ from activation plan")
    skipped = sum(item.get("skipped_count", 0) for item in experiments)
    if skipped < expectation["minimum_skipped_count"]:
        raise RuntimeError("matrix skipped-query count is below expectation")
    expected_returncode = 0 if expectation["matrix_status"] != "failed" else 1
    if returncode != expected_returncode:
        raise RuntimeError("matrix process return code differs from status")
    return {
        "summary": summary,
        "summary_path": selected_summary,
        "success_bundle_present": success_present,
        "failure_bundle_present": failure_present,
        "skipped_count": skipped,
    }


def execute_activation(plan_path: Path, root: Path, dry_run: bool = False) -> dict[str, Any]:
    """Validate or execute one controlled matrix activation."""
    context = preflight_activation(plan_path, root)
    command = _matrix_command(context)
    if dry_run:
        return {
            "schema": AUDIT_SCHEMA,
            "mode": "dry-run",
            "plan_sha256": context["plan_sha256"],
            "snapshot_sha256": context["snapshot"]["snapshot_sha256"],
            "probe_policy_sha256": content_sha256(context["probe_policy"]),
            "matrix_command": command,
            "validated": True,
        }
    created = []
    try:
        result = subprocess.run(command, cwd=Path(root).resolve(), text=True, capture_output=True, check=False)
        for path in context["outputs"].values():
            if path.exists():
                created.append(path)
        checked = _validate_runtime_result(context, result.returncode)
        body = {
            "schema": AUDIT_SCHEMA,
            "created_at_utc": context["plan"]["created_at_utc"],
            "mode": "execute",
            "plan_sha256": context["plan_sha256"],
            "matrix_run_id": context["plan"]["matrix_run_id"],
            "systems": context["plan"]["systems"],
            "snapshot_sha256": context["snapshot"]["snapshot_sha256"],
            "probe_policy_sha256": content_sha256(context["probe_policy"]),
            "completed_compatible_runs": context["plan"]["completed_compatible_runs"],
            "matrix_returncode": result.returncode,
            "matrix_stdout": result.stdout,
            "matrix_stderr": result.stderr,
            "summary_path": str(checked["summary_path"]),
            "summary_file_sha256": _sha256_file(checked["summary_path"]),
            "success_bundle_present": checked["success_bundle_present"],
            "failure_bundle_present": checked["failure_bundle_present"],
            "selected_probe_count": checked["summary"]["runtime_orchestration"]["selected_probe_count"],
            "skipped_count": checked["skipped_count"],
            "status": "ok",
        }
        audit = {**body, "audit_sha256": content_sha256(body)}
        context["audit"].parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(context["audit"], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(audit, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        created.append(context["audit"])
        return audit
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
