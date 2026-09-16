#!/usr/bin/env python3
"""Run the execution-grade BSBM Explore 100k matrix safely and resumably.

This runner creates a run-local declaration with timeout_s=20.0. It does not
modify the benchmark-owned declaration. Required systems run sequentially.
pycottas/default runs last. Query-level failures remain reportable outcomes;
structural failures do not stop later systems.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "krown-bsbm-100k-execution-run-v1"
EXPECTED_KROWN_HEAD = "a5e735a5eb49983b76a8cffd740c1e83aa0dd73b"
EXPECTED_BENCHMARKS_HEAD = "547cd461d897634aa96f5af980f4c70619936c5c"
EXPECTED_DECLARATION_SHA256 = "0ddf851b2bf1bbccee2c40c15b97f7621ca42413ea6d49c40a9c65d50c2bec34"
EXPECTED_MANIFEST_SHA256 = "8131689ca460889823538171331dc367995b1a41be6b9c8ad45e1b8fb7c371f1"
TIMEOUT_S = 20.0

KROWN_ROOT = Path("/users/u0182905/KROWN")
BENCHMARKS_ROOT = Path("/users/u0182905/benchmarks")
SCENARIO = KROWN_ROOT / "benchmark-integration/bsbm-100k"
SHARED = SCENARIO / "data/shared"
DECLARATION = BENCHMARKS_ROOT / "BSBM/experiments/explore-100k-full.json"
MANIFEST_REL = "manifests/bsbm-full.json"
MANIFEST = SHARED / MANIFEST_REL
CATALOGUE = KROWN_ROOT / "execution-framework/experiment-catalogue.json"
MATRIX_RUNNER = KROWN_ROOT / "execution-framework/run_rdf_experiment_matrix.py"
READINESS_RUNNER = KROWN_ROOT / "execution-framework/check_rdf_experiment_readiness.py"
REPORT_RUNNER = KROWN_ROOT / "execution-framework/summarize_rdf_experiment.py"
PYTHON = Path("/users/u0182905/miniconda3/envs/vortex-rdf/bin/python")

# Keep local stores before HTTP stores. Run COTTAS last as requested.
REQUIRED_SYSTEMS = (
    'rdflib/default',
    'vortex-rdf/dictionary-secondary-by-reference',
    'vortex-rdf/dictionary-secondary-by-reference-memory',
    'vortex-rdf/dictionary-secondary-by-copy',
    'vortex-rdf/dictionary-secondary-by-copy-memory',
    'oxigraph/memory',
    'oxigraph/rocksdb',
    'fuseki/memory',
    'fuseki/tdb2',
    'qlever/default',
    'virtuoso/default',
    'comunica/hdt',
)
OPTIONAL_SYSTEM = "comunica/hdt"
RECEIPTS = {
    'rdf/source': ('rdf-source-receipt.json', 'f54ad4595df88c3b7e5c8cd61ba7fa03a26c7a944cc3c81162f9587b36302124'),
    'hdt/default': ('hdt-default-receipt.json', 'cd3d14b00e2cf21b2331a25d52c5e2fa535b9ff3598057da16b3ce01a88bf070'),
    'vortex-rdf/dictionary-secondary-by-reference': ('vortex-rdf-dictionary-secondary-by-reference-receipt.json', '5987fd0a51a431065aa58482b131cff364ba8f2cd1ab3f39c0bdce8aa25dd3ec'),
    'vortex-rdf/dictionary-secondary-by-copy': ('vortex-rdf-dictionary-secondary-by-copy-receipt.json', 'd18ce900027414a20cf81178e5cde195015275c07642e2df7bca4064b3b71d89'),
}
DATASET_ROOT = BENCHMARKS_ROOT / "BSBM/data/explore-100k"
EXPECTED_IMAGES = (
    "kgconstruct/fuseki:v6.2.0",
    "kgconstruct/virtuoso:v7.2.17",
    "kgconstruct/qlever:v0.6.0",
    "dtaikg/oxigraph:0.5.9",
)
EXPECTED_PORTS = (3030, 1111, 8890, 7001, 7878)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def command(args: list[str], *, cwd: Path = KROWN_ROOT, log: Path | None = None) -> int:
    environment = dict(os.environ)
    environment["RUST_LOG"] = environment.get("RUST_LOG", "vortex_rdf_cli=debug,vortex_rdf_core=debug")
    environment["KROWN_IN_RUN_TIMEOUT_QUARANTINE_THRESHOLD"] = environment.get(
        "KROWN_IN_RUN_TIMEOUT_QUARANTINE_THRESHOLD", "20"
    )
    environment["PYTHONPATH"] = str(BENCHMARKS_ROOT) + (":" + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    if log is None:
        return subprocess.run(args, cwd=cwd, env=environment, check=False).returncode
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(f"[{utc_now()}] COMMAND {json.dumps(args)}\n")
        stream.flush()
        return subprocess.run(args, cwd=cwd, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False).returncode


def git_head(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"cannot read Git HEAD: {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def verify_receipt(path: Path, expected_hash: str) -> list[dict[str, Any]]:
    if sha256(path) != expected_hash:
        raise RuntimeError(f"receipt SHA-256 changed: {path}")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    verified = []
    for record in receipt["files"]:
        artifact = path.parent / record["path"]
        if not artifact.is_file() or artifact.stat().st_size != record["size_bytes"] or sha256(artifact) != record["sha256"]:
            raise RuntimeError(f"representation differs from receipt: {artifact}")
        verified.append({"path": str(artifact), "size_bytes": record["size_bytes"], "sha256": record["sha256"]})
    return verified


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def preflight(run_root: Path, systems: list[str]) -> dict[str, Any]:
    if Path.cwd().resolve() != KROWN_ROOT:
        raise RuntimeError(f"run from {KROWN_ROOT}")
    if git_head(KROWN_ROOT) != EXPECTED_KROWN_HEAD:
        raise RuntimeError("KROWN HEAD changed")
    if git_head(BENCHMARKS_ROOT) != EXPECTED_BENCHMARKS_HEAD:
        raise RuntimeError("benchmarks HEAD changed")
    if sha256(DECLARATION) != EXPECTED_DECLARATION_SHA256:
        raise RuntimeError("full declaration SHA-256 changed")
    if sha256(MANIFEST) != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError("full manifest SHA-256 changed")
    if not PYTHON.is_file():
        raise RuntimeError(f"Python executable is missing: {PYTHON}")

    declaration = json.loads(DECLARATION.read_text(encoding="utf-8"))
    if declaration.get("benchmark") != "bsbm" or declaration.get("dataset") != "explore-100k":
        raise RuntimeError("declaration is not BSBM Explore 100k")
    if "smoke" in str(declaration.get("workload", "")).lower():
        raise RuntimeError("refusing to run a smoke declaration")
    declared = {binding["system"] for binding in declaration["bindings"]}
    missing = sorted(set(systems) - declared)
    if missing:
        raise RuntimeError("systems missing from declaration: " + ", ".join(missing))

    files = {}
    for representation, (name, digest) in RECEIPTS.items():
        path = DATASET_ROOT / name
        files[representation] = {"receipt": str(path), "receipt_sha256": digest, "files": verify_receipt(path, digest)}

    atomic_json(run_root / "readiness.json", {"schema": SCHEMA, "ready": True, "systems": systems, "note": "100k-specific artifact and declaration preflight passed"})

    docker = shutil.which("docker")
    if docker is None or command([docker, "info"], log=run_root / "preflight-docker.log") != 0:
        raise RuntimeError("Docker is unavailable")
    missing_images = [image for image in EXPECTED_IMAGES if command([docker, "image", "inspect", image], log=run_root / "preflight-docker.log") != 0]
    if missing_images:
        raise RuntimeError("missing Docker images: " + ", ".join(missing_images))
    result = subprocess.run([docker, "ps", "--format", "{{.Names}}"], text=True, capture_output=True, check=False)
    stale = sorted(name for name in result.stdout.splitlines() if name.startswith(("Fuseki", "Virtuoso", "QLever", "Oxigraph-")))
    if stale:
        raise RuntimeError("matrix-owned containers are already running: " + ", ".join(stale))
    busy = [port for port in EXPECTED_PORTS if not port_available(port)]
    if busy:
        raise RuntimeError("required ports are busy: " + ", ".join(map(str, busy)))
    return {"schema": SCHEMA, "checked_at_utc": utc_now(), "systems": systems, "representations": files, "ports": list(EXPECTED_PORTS), "images": list(EXPECTED_IMAGES)}


def create_local_declaration(run_root: Path) -> Path:
    """Create a run-local benchmark shadow tree with contained hard-linked artifacts."""
    value = json.loads(DECLARATION.read_text(encoding="utf-8"))
    value["execution_policy"] = {
        "warmup_runs": 0,
        "measured_runs": 1,
        "timeout_s": TIMEOUT_S,
    }
    shadow = run_root / "benchmark-shadow"
    experiments = shadow / "experiments"
    shadow_data = shadow / "data/explore-100k"
    experiments.mkdir(parents=True, exist_ok=True)
    shadow_data.mkdir(parents=True, exist_ok=True)

    # The declaration loader resolves receipts from declaration.parents[1].
    # Preserve that contract without changing the benchmark repository.
    for receipt_name, _ in RECEIPTS.values():
        source_receipt = DATASET_ROOT / receipt_name
        target_receipt = shadow_data / receipt_name
        shutil.copy2(source_receipt, target_receipt)
        receipt = json.loads(source_receipt.read_text(encoding="utf-8"))
        for record in receipt["files"]:
            source_artifact = DATASET_ROOT / record["path"]
            target_artifact = shadow_data / record["path"]
            target_artifact.parent.mkdir(parents=True, exist_ok=True)
            if target_artifact.exists() or target_artifact.is_symlink():
                target_artifact.unlink()
            try:
                os.link(source_artifact, target_artifact)
            except OSError as error:
                raise RuntimeError(
                    "cannot create the required run-local hard link for "
                    f"{source_artifact}: {error}"
                ) from error
            if (
                target_artifact.stat().st_size != record["size_bytes"]
                or sha256(target_artifact) != record["sha256"]
            ):
                raise RuntimeError(
                    f"run-local hard link failed validation: {target_artifact}"
                )

    inventory_source = DATASET_ROOT / "dataset-inventory.json"
    if inventory_source.is_file():
        shutil.copy2(inventory_source, shadow_data / inventory_source.name)
    path = experiments / "execution-declaration.json"
    atomic_json(path, value)
    return path


def artifact_hashes(directory: Path) -> dict[str, Any]:
    result = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name not in {"artifact-hashes.json", "state.json"}:
            result[path.name] = {"size_bytes": path.stat().st_size, "sha256": sha256(path)}
    return result


def valid_completed(system_root: Path) -> bool:
    state_path = system_root / "state.json"
    hashes_path = system_root / "artifact-hashes.json"
    if not state_path.is_file() or not hashes_path.is_file():
        return False
    state = json.loads(state_path.read_text())
    if state.get("state") not in {"completed", "completed-with-failures"}:
        return False
    hashes = json.loads(hashes_path.read_text())
    required = ("summary.json", "results.tar.gz", "report.json", "report.csv", "report.md", "report.xlsx")
    for name in required:
        path = system_root / name
        record = hashes.get(name)
        if not path.is_file() or not record or path.stat().st_size != record["size_bytes"] or sha256(path) != record["sha256"]:
            return False
    return True


def preserve_attempt(system_root: Path) -> None:
    if not system_root.exists() or not any(system_root.iterdir()):
        return
    target = system_root.parent / f"{system_root.name}-preserved-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    suffix = 1
    while target.exists():
        target = target.with_name(f"{target.name}-{suffix}")
        suffix += 1
    system_root.rename(target)


def run_system(run_root: Path, declaration: Path, system: str, retry_failed: bool) -> dict[str, Any]:
    safe = system.replace("/", "--")
    system_root = run_root / "systems" / safe
    if valid_completed(system_root):
        return {"system": system, "state": "skipped-complete", "finished_at_utc": utc_now()}
    if system_root.exists():
        old = json.loads((system_root / "state.json").read_text()) if (system_root / "state.json").is_file() else {}
        if old.get("state") == "structural-failure" and not retry_failed:
            return {"system": system, "state": "skipped-failed", "finished_at_utc": utc_now()}
        preserve_attempt(system_root)
    system_root.mkdir(parents=True)
    started = utc_now()
    atomic_json(system_root / "state.json", {"schema": SCHEMA, "system": system, "state": "running", "started_at_utc": started})

    raw_rel = f"raw/bsbm-100k-execution/{run_root.name}/{safe}"
    raw_dir = SHARED / raw_rel
    raw_dir.mkdir(parents=True, exist_ok=True)
    summary_rel = f"{raw_rel}/summary.json"
    archive_rel = f"{raw_rel}/results.tar.gz"
    failure_summary_rel = f"{raw_rel}/failed-summary.json"
    failure_archive_rel = f"{raw_rel}/failed-results.tar.gz"
    matrix_run_id = f"{run_root.name}:{safe}"
    log = system_root / "stdout-stderr.log"
    start_ns = time.monotonic_ns()
    rc = command([
        str(PYTHON), str(MATRIX_RUNNER), "--scenario", str(SCENARIO),
        "--declaration", str(declaration), "--manifest", MANIFEST_REL,
        "--system", system, "--results", summary_rel, "--output", archive_rel,
        "--failure-results", failure_summary_rel, "--failure-output", failure_archive_rel,
        "--matrix-run-id", matrix_run_id,
    ], log=log)
    elapsed_ns = time.monotonic_ns() - start_ns

    summary_source = SHARED / summary_rel
    archive_source = SHARED / archive_rel
    failure_summary = SHARED / failure_summary_rel
    failure_archive = SHARED / failure_archive_rel
    if rc == 0 and summary_source.is_file() and archive_source.is_file():
        shutil.copy2(summary_source, system_root / "summary.json")
        shutil.copy2(archive_source, system_root / "results.tar.gz")
        summary = json.loads(summary_source.read_text())
        state = "completed-with-failures" if summary.get("status") == "completed_with_failures" else "completed"
        report_rc = command([
            str(PYTHON), str(REPORT_RUNNER), str(system_root / "summary.json"),
            "--json", str(system_root / "report.json"), "--csv", str(system_root / "report.csv"),
            "--markdown", str(system_root / "report.md"), "--xlsx", str(system_root / "report.xlsx"),
        ], log=log)
        if report_rc:
            state = "structural-failure"
            error = "automatic report generation failed"
        else:
            error = None
    else:
        state = "structural-failure"
        error = f"matrix command failed with exit code {rc}"
        if failure_summary.is_file():
            shutil.copy2(failure_summary, system_root / "failed-summary.json")
        if failure_archive.is_file():
            shutil.copy2(failure_archive, system_root / "failed-results.tar.gz")

    finished = utc_now()
    state_value = {"schema": SCHEMA, "system": system, "state": state, "exit_code": rc, "error": error, "started_at_utc": started, "finished_at_utc": finished, "elapsed_ns": elapsed_ns, "matrix_run_id": matrix_run_id}
    atomic_json(system_root / "state.json", state_value)
    atomic_json(system_root / "artifact-hashes.json", artifact_hashes(system_root))
    return state_value


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--include-comunica", action="store_true")
    parser.add_argument("--system", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("bsbm-100k-%Y%m%dT%H%M%SZ")
    if Path(run_id).name != run_id or not run_id:
        raise RuntimeError("run ID must be one safe path component")
    run_root = SHARED / "executions" / run_id
    if run_root.exists() and not args.resume:
        raise RuntimeError(f"run already exists; use --resume --run-id {run_id}")
    run_root.mkdir(parents=True, exist_ok=True)

    systems = list(REQUIRED_SYSTEMS)
    if args.system:
        unknown = sorted(set(args.system) - set(systems))
        if unknown:
            raise RuntimeError("selected systems are not enabled: " + ", ".join(unknown))
        selected = set(args.system)
        systems = [system for system in systems if system in selected]
        if "pycottas/default" in systems:
            systems = [system for system in systems if system != "pycottas/default"] + ["pycottas/default"]

    plan_path = run_root / "execution-plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        if plan["systems"] != systems or plan["timeout_s"] != TIMEOUT_S:
            raise RuntimeError("resume arguments differ from the immutable execution plan")
    else:
        checks = preflight(run_root, systems)
        declaration = create_local_declaration(run_root)
        plan = {"schema": SCHEMA, "run_id": run_id, "created_at_utc": utc_now(), "systems": systems, "timeout_s": TIMEOUT_S, "warmup_runs": 0, "measured_runs": 1, "source_declaration": str(DECLARATION), "source_declaration_sha256": EXPECTED_DECLARATION_SHA256, "local_declaration": str(declaration), "local_declaration_sha256": sha256(declaration), "manifest": str(MANIFEST), "manifest_sha256": EXPECTED_MANIFEST_SHA256, "krown_head": EXPECTED_KROWN_HEAD, "benchmarks_head": EXPECTED_BENCHMARKS_HEAD, "preflight": checks}
        atomic_json(plan_path, plan)
    declaration = Path(plan["local_declaration"])
    if not declaration.is_file() or sha256(declaration) != plan["local_declaration_sha256"]:
        raise RuntimeError("run-local declaration changed")

    ledger = run_root / "ledger.jsonl"
    outcomes = []
    for index, system in enumerate(systems, 1):
        print(f"BSBM100K start {index}/{len(systems)} system={system} timeout_s={TIMEOUT_S}", flush=True)
        result = run_system(run_root, declaration, system, args.retry_failed)
        outcomes.append(result)
        append_jsonl(ledger, result)
        print(f"BSBM100K done {index}/{len(systems)} system={system} state={result['state']}", flush=True)

    terminal = {"completed", "completed-with-failures", "skipped-complete"}
    failures = [result for result in outcomes if result["state"] not in terminal]
    final = {"schema": SCHEMA, "run_id": run_id, "finished_at_utc": utc_now(), "timeout_s": TIMEOUT_S, "system_count": len(systems), "structural_failure_count": len(failures), "systems": outcomes, "complete": not failures}
    atomic_json(run_root / "final-summary.json", final)
    lines = ["# BSBM Explore 100k execution", "", f"Run ID: `{run_id}`", f"Timeout: `{TIMEOUT_S}` seconds", f"Complete: `{str(not failures).lower()}`", "", "## Systems", ""]
    lines.extend(f"- `{row['system']}`: `{row['state']}`" for row in outcomes)
    (run_root / "final-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    atomic_json(run_root / "artifact-inventory.json", artifact_hashes(run_root))
    print(f"BSBM100K final run_id={run_id} complete={str(not failures).lower()} structural_failures={len(failures)}")
    print(f"output={run_root}")
    return 0 if not failures else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"BSBM100K EXECUTION FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(2)
