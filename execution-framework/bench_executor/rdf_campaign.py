"""Resumable, benchmark-neutral RDF campaign execution."""
from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

SCHEMA = "rdf-campaign-specification-v2"
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REPORTABLE = frozenset({"completed", "completed-with-failures"})
FAILED = frozenset({"structural-failure", "timed-out", "interrupted", "infrastructure-blocked"})
MATRIX_CONTAINER_PREFIXES = ("Fuseki", "Virtuoso", "QLever", "qlever_", "Oxigraph-")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: str | Path, value: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        json.loads(temporary.read_text())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def append_jsonl(path: str | Path, value: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def retain(source: str | Path, target: str | Path) -> None:
    source_path = Path(source)
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.unlink(missing_ok=True)
    try:
        source_path.replace(target_path)
    except OSError:
        shutil.copy2(source_path, target_path)
        source_path.unlink()


def _safe(value: str, field: str) -> str:
    if not isinstance(value, str) or not SAFE.fullmatch(value):
        raise ValueError(f"{field} must be one safe path component")
    return value


def _positive(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be positive")
    return value


def matrix_owned_containers() -> tuple[str, ...]:
    """Return running containers with names reserved by RDF matrix adapters."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("cannot inspect running Docker containers")
    return tuple(sorted(
        name for name in result.stdout.splitlines()
        if name.startswith(MATRIX_CONTAINER_PREFIXES)
    ))


def require_clean_matrix_environment(stage: str) -> None:
    """Reject infrastructure contamination without deleting foreign state."""
    containers = matrix_owned_containers()
    if containers:
        raise RuntimeError(
            f"matrix infrastructure is blocked during {stage}: "
            + ", ".join(containers)
        )


def declaration_systems(path: str | Path) -> tuple[str, ...]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    bindings = value.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("declaration bindings must be a non-empty array")
    systems = []
    for index, binding in enumerate(bindings):
        if not isinstance(binding, Mapping) or not isinstance(binding.get("system"), str):
            raise ValueError(f"declaration binding {index} has no system")
        systems.append(binding["system"])
    if len(systems) != len(set(systems)):
        raise ValueError("declaration system bindings must be unique")
    return tuple(systems)


@dataclasses.dataclass(frozen=True)
class CampaignSpecification:
    scenario: Path
    declaration: Path
    manifest: str
    benchmark_root: Path | None = None
    repetitions: int = 3
    systems: tuple[str, ...] = ()
    system_limit_s: int = 7200
    campaign_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario", Path(self.scenario).expanduser().resolve())
        object.__setattr__(self, "declaration", Path(self.declaration).expanduser().resolve())
        if self.benchmark_root is not None:
            object.__setattr__(self, "benchmark_root", Path(self.benchmark_root).expanduser().resolve())
        _positive(self.repetitions, "repetitions")
        _positive(self.system_limit_s, "system_limit_s")
        manifest = Path(self.manifest)
        if manifest.is_absolute() or ".." in manifest.parts:
            raise ValueError("manifest must be relative to data/shared")
        if self.campaign_id is not None:
            _safe(self.campaign_id, "campaign_id")
        if len(self.systems) != len(set(self.systems)):
            raise ValueError("systems must be unique")

    def resolved_id(self) -> str:
        return self.campaign_id or datetime.now(timezone.utc).strftime("rdf-campaign-%Y%m%dT%H%M%SZ")

    def selected_systems(self) -> tuple[str, ...]:
        declared = declaration_systems(self.declaration)
        if not self.systems:
            return declared
        unknown = [system for system in self.systems if system not in declared]
        if unknown:
            raise ValueError(f"systems are not declared: {', '.join(unknown)}")
        requested = set(self.systems)
        return tuple(system for system in declared if system in requested)

    def to_dict(self, systems: Sequence[str]) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "scenario": str(self.scenario),
            "declaration": str(self.declaration),
            "benchmark_root": None if self.benchmark_root is None else str(self.benchmark_root),
            "manifest": self.manifest,
            "repetitions": self.repetitions,
            "systems": list(systems),
            "system_limit_s": self.system_limit_s,
            "campaign_id": self.campaign_id,
        }


class RdfCampaign:
    def __init__(
        self,
        spec: CampaignSpecification,
        matrix_runner: Path,
        report_runner: Path,
        inter_run_runner: Path,
        python: Path | None = None,
        executor: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self.spec = spec
        self.python = Path(python or sys.executable)
        self.matrix_runner = Path(matrix_runner).resolve()
        self.report_runner = Path(report_runner).resolve()
        self.inter_run_runner = Path(inter_run_runner).resolve()
        self.executor = executor or subprocess.run
        self.shared = spec.scenario / "data/shared"
        self.campaigns = self.shared / "campaigns"
        self.executions = self.shared / "executions"

    def _plan_identity(self, campaign_id: str, systems: Sequence[str]) -> dict[str, object]:
        manifest = self.shared / self.spec.manifest
        for path in (self.spec.declaration, manifest, self.matrix_runner, self.report_runner, self.inter_run_runner):
            if not path.is_file():
                raise FileNotFoundError(path)
        if self.spec.benchmark_root is not None and not self.spec.benchmark_root.is_dir():
            raise FileNotFoundError(self.spec.benchmark_root)
        return {
            "schema": SCHEMA,
            "campaign_id": campaign_id,
            "specification": self.spec.to_dict(systems),
            "inputs": {
                "declaration_sha256": sha256(self.spec.declaration),
                "manifest_sha256": sha256(manifest),
                "matrix_runner_sha256": sha256(self.matrix_runner),
                "report_runner_sha256": sha256(self.report_runner),
                "inter_run_runner_sha256": sha256(self.inter_run_runner),
            },
        }

    def _matrix_command(self, run_id: str, system: str, raw: str) -> list[str]:
        command = [
            str(self.python), str(self.matrix_runner),
            "--scenario", str(self.spec.scenario),
            "--declaration", str(self.spec.declaration),
            "--manifest", self.spec.manifest,
            "--system", system,
            "--results", f"{raw}/summary.json",
            "--output", f"{raw}/results.tar.gz",
            "--failure-results", f"{raw}/failed-summary.json",
            "--failure-output", f"{raw}/failed-results.tar.gz",
            "--matrix-run-id", f"{run_id}:{system.replace('/', '--')}",
        ]
        if self.spec.benchmark_root is not None:
            command.extend(["--benchmark-root", str(self.spec.benchmark_root)])
        return command

    @staticmethod
    def _hashes(root: Path) -> dict[str, dict[str, object]]:
        return {
            path.name: {"size_bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in root.iterdir()
            if path.is_file() and path.name not in {"state.json", "artifact-hashes.json"}
        }

    @staticmethod
    def _artifacts_valid(root: Path) -> bool:
        hashes_path = root / "artifact-hashes.json"
        state_path = root / "state.json"
        if not hashes_path.is_file() or not state_path.is_file():
            return False
        try:
            hashes = json.loads(hashes_path.read_text())
            state = json.loads(state_path.read_text())
        except (OSError, ValueError):
            return False
        if state.get("state") not in REPORTABLE:
            return False
        for name, identity in hashes.items():
            path = root / name
            if not path.is_file() or path.stat().st_size != identity.get("size_bytes") or sha256(path) != identity.get("sha256"):
                return False
        return True

    def _run_system(self, run_root: Path, run_id: str, system: str, environment: Mapping[str, str], retry_failed: bool) -> dict[str, object]:
        safe = system.replace("/", "--")
        root = run_root / "systems" / safe
        state_path = root / "state.json"
        hashes_path = root / "artifact-hashes.json"
        if self._artifacts_valid(root):
            previous = json.loads(state_path.read_text())
            return {**previous, "resume_action": "skipped-verified"}
        if state_path.is_file():
            previous = json.loads(state_path.read_text())
            if previous.get("state") in FAILED and not retry_failed:
                return {**previous, "resume_action": "failed-not-retried"}
        root.mkdir(parents=True, exist_ok=True)
        started = now()
        atomic_json(state_path, {"system": system, "state": "running", "started_at_utc": started})
        raw = f"raw/rdf-campaign/{run_id}/{safe}"
        shared_raw = self.shared / raw
        log = root / "stdout-stderr.log"
        status = "structural-failure"
        exit_code = None
        detail = None
        try:
            with log.open("a", encoding="utf-8") as stream:
                result = self.executor(
                    self._matrix_command(run_id, system, raw), cwd=Path('/users/u0182905/KROWN'), env=dict(environment),
                    stdout=stream, stderr=subprocess.STDOUT, timeout=self.spec.system_limit_s, check=False,
                )
            exit_code = result.returncode
            remaining_containers = matrix_owned_containers()
            if remaining_containers:
                status = "infrastructure-blocked"
                detail = (
                    "matrix-owned containers remain after system execution: "
                    + ", ".join(remaining_containers)
                )
                success = False
            else:
                success = exit_code == 0 and (shared_raw / "summary.json").is_file() and (shared_raw / "results.tar.gz").is_file()
            if success:
                retain(shared_raw / "summary.json", root / "summary.json")
                retain(shared_raw / "results.tar.gz", root / "results.tar.gz")
                summary = json.loads((root / "summary.json").read_text())
                status = "completed-with-failures" if summary.get("status") == "completed_with_failures" else "completed"
                report = self.executor([
                    str(self.python), str(self.report_runner), str(root / "summary.json"),
                    "--json", str(root / "report.json"), "--csv", str(root / "report.csv"),
                    "--markdown", str(root / "report.md"), "--xlsx", str(root / "report.xlsx"),
                ], cwd=Path('/users/u0182905/KROWN'), env=dict(environment), check=False)
                if report.returncode:
                    status = "structural-failure"
                    detail = "report generation failed"
            else:
                if detail is None:
                    detail = "matrix process failed or did not publish its success bundle"
                for name in ("failed-summary.json", "failed-results.tar.gz"):
                    if (shared_raw / name).is_file():
                        retain(shared_raw / name, root / name)
        except subprocess.TimeoutExpired:
            status = "timed-out"
            detail = f"system limit exceeded: {self.spec.system_limit_s}s"
        except KeyboardInterrupt:
            status = "interrupted"
            detail = "campaign received an interrupt"
        row = {"system": system, "state": status, "exit_code": exit_code, "detail": detail, "started_at_utc": started, "finished_at_utc": now()}
        atomic_json(hashes_path, self._hashes(root))
        atomic_json(state_path, row)
        return row


    @staticmethod
    def _outcome_counts(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
        """Count terminal campaign outcomes without changing query semantics."""
        return {
            "reportable_count": sum(row.get("state") in REPORTABLE for row in rows),
            "structural_failure_count": sum(
                row.get("state") == "structural-failure" for row in rows
            ),
            "timed_out_count": sum(row.get("state") == "timed-out" for row in rows),
            "interrupted_count": sum(row.get("state") == "interrupted" for row in rows),
            "infrastructure_blocked_count": sum(
                row.get("state") == "infrastructure-blocked" for row in rows
            ),
        }

    def _inter_run(self, campaign_root: Path, systems: Sequence[str], outcomes: Sequence[Mapping[str, object]], environment: Mapping[str, str]) -> dict[str, object]:
        result = {"state": "not-run"}
        for system in systems:
            safe = system.replace("/", "--")
            records = []
            for outcome in outcomes:
                run_id = str(outcome["run_id"])
                summary = self.executions / run_id / "systems" / safe / "summary.json"
                if summary.is_file():
                    records.append(summary)
            if len(records) < 2:
                continue
            output = campaign_root / "inter-run" / safe
            output.mkdir(parents=True, exist_ok=True)
            completed = self.executor([
                str(self.python), str(self.inter_run_runner), *map(str, records),
                "--json", str(output / "statistics.json"), "--csv", str(output / "statistics.csv"),
                "--markdown", str(output / "statistics.md"), "--xlsx", str(output / "statistics.xlsx"),
            ], cwd=Path('/users/u0182905/KROWN'), env=dict(environment), check=False)
            result[system] = {"state": "completed" if completed.returncode == 0 else "failed", "exit_code": completed.returncode}
        if len(result) > 1:
            result["state"] = "completed" if all(value.get("state") == "completed" for key, value in result.items() if key != "state") else "failed"
        return result

    def run(self, resume: bool = False, retry_failed: bool = False) -> dict[str, object]:
        campaign_id = self.spec.resolved_id()
        systems = self.spec.selected_systems()
        campaign_root = self.campaigns / campaign_id
        lock_path = self.campaigns / ".rdf-campaign.lock"
        self.campaigns.mkdir(parents=True, exist_ok=True)
        if campaign_root.exists() and not resume:
            raise FileExistsError(campaign_root)
        campaign_root.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            identity = self._plan_identity(campaign_id, systems)
            plan_path = campaign_root / "campaign-plan.json"
            if plan_path.exists():
                previous = json.loads(plan_path.read_text())
                if {key: previous[key] for key in identity} != identity:
                    raise RuntimeError(
                        "resume differs from immutable campaign plan or its input hashes"
                    )
            else:
                atomic_json(plan_path, {**identity, "created_at_utc": now()})

            try:
                require_clean_matrix_environment("campaign preflight")
            except RuntimeError as error:
                final = {
                    "campaign_id": campaign_id,
                    "expected_repetitions": self.spec.repetitions,
                    "completed_repetitions": 0,
                    "reportable_repetitions": 0,
                    "systems": list(systems),
                    "outcomes": [],
                    "inter_run": {"state": "not-run"},
                    "execution_complete": False,
                    "all_systems_reportable": False,
                    "complete": False,
                    "reportable_count": 0,
                    "structural_failure_count": 0,
                    "timed_out_count": 0,
                    "interrupted_count": 0,
                    "infrastructure_blocked_count": 1,
                    "state": "infrastructure-blocked",
                    "detail": str(error),
                    "finished_at_utc": now(),
                }
                atomic_json(campaign_root / "final-summary.json", final)
                append_jsonl(campaign_root / "campaign-ledger.jsonl", final)
                return final

            environment = os.environ.copy()
            environment.setdefault(
                "RUST_LOG",
                "vortex_rdf_cli=debug,vortex_rdf_core=debug",
            )
            environment["PYTHONUNBUFFERED"] = "1"
            outcomes = []
            interrupted = False
            infrastructure_blocked = False
            for repetition in range(1, self.spec.repetitions + 1):
                run_id = f"{campaign_id}-r{repetition:02d}"
                run_root = self.executions / run_id
                run_root.mkdir(parents=True, exist_ok=True)
                rows = []
                for system in systems:
                    row = self._run_system(
                        run_root,
                        run_id,
                        system,
                        environment,
                        retry_failed,
                    )
                    rows.append(row)
                    append_jsonl(run_root / "ledger.jsonl", row)
                    if row["state"] in {"interrupted", "infrastructure-blocked"}:
                        interrupted = row["state"] == "interrupted"
                        infrastructure_blocked = row["state"] == "infrastructure-blocked"
                        break

                terminal_complete = (
                    len(rows) == len(systems)
                    and all(row["state"] in REPORTABLE | FAILED for row in rows)
                )
                all_reportable = (
                    terminal_complete
                    and all(row["state"] in REPORTABLE for row in rows)
                )
                counts = self._outcome_counts(rows)
                final = {
                    "run_id": run_id,
                    "repetition": repetition,
                    "systems": rows,
                    "execution_complete": terminal_complete,
                    "all_systems_reportable": all_reportable,
                    "complete": terminal_complete,
                    **counts,
                    "finished_at_utc": now(),
                }
                atomic_json(run_root / "final-summary.json", final)
                outcomes.append(final)
                append_jsonl(campaign_root / "campaign-ledger.jsonl", final)
                if interrupted or infrastructure_blocked:
                    break

            execution_complete = (
                len(outcomes) == self.spec.repetitions
                and all(outcome["execution_complete"] for outcome in outcomes)
            )
            all_systems_reportable = (
                execution_complete
                and all(outcome["all_systems_reportable"] for outcome in outcomes)
            )
            inter_run = (
                self._inter_run(campaign_root, systems, outcomes, environment)
                if execution_complete
                else {"state": "not-run"}
            )
            rows = [
                row
                for outcome in outcomes
                for row in outcome["systems"]
            ]
            counts = self._outcome_counts(rows)
            final = {
                "campaign_id": campaign_id,
                "expected_repetitions": self.spec.repetitions,
                "completed_repetitions": sum(
                    bool(outcome["execution_complete"])
                    for outcome in outcomes
                ),
                "reportable_repetitions": sum(
                    bool(outcome["all_systems_reportable"])
                    for outcome in outcomes
                ),
                "systems": list(systems),
                "outcomes": outcomes,
                "inter_run": inter_run,
                "execution_complete": execution_complete,
                "all_systems_reportable": all_systems_reportable,
                "complete": execution_complete,
                **counts,
                "finished_at_utc": now(),
            }
            atomic_json(campaign_root / "final-summary.json", final)
            return final
