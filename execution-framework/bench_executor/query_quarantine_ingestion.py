"""Ingest one explicit completed matrix bundle into evidence observations."""
from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bench_executor.query_quarantine_contract import EvidenceObservation

_COMPLETED = frozenset({"ok", "completed_with_failures"})
_ENGINE_ERRORS = frozenset({
    "engine_error", "connection_error", "parse_error", "result_error",
    "validation_mismatch",
})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EXCLUDED_MARKERS = (
    "instrumentation-validation", "synthetic", "must not enter",
    "does not create evidence",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: str | None, actual: str, field: str) -> None:
    if value is not None and (not _SHA256.fullmatch(value) or value != actual):
        raise ValueError(f"{field} mismatch")


def _load_manifest(path: Path) -> tuple[dict[str, dict[str, Any]], str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    queries = value.get("queries")
    if not isinstance(queries, list) or not queries:
        raise ValueError("manifest queries must be a non-empty array")
    result = {}
    for item in queries:
        query_id = item.get("query_id")
        query_sha256 = item.get("query_sha256")
        if not isinstance(query_id, str) or not _SHA256.fullmatch(str(query_sha256)):
            raise ValueError("manifest query identity is invalid")
        if query_id in result:
            raise ValueError("duplicate manifest query_id")
        result[query_id] = dict(item)
    return result, value["workload"], value["dataset"]


def _load_declaration(path: Path, system: str) -> tuple[dict[str, Any], str, str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    bindings = [item for item in value.get("bindings", []) if item.get("system") == system]
    if len(bindings) != 1:
        raise ValueError("declaration must contain exactly one selected system binding")
    policy = value.get("execution_policy")
    if not isinstance(policy, Mapping):
        raise ValueError("declaration execution_policy is missing")
    return dict(policy), bindings[0]["representation"], value["benchmark"], value["schema"]


def _safe_member(archive: tarfile.TarFile, expected: str) -> bytes:
    members = archive.getmembers()
    names = [item.name for item in members]
    if len(names) != len(set(names)):
        raise ValueError("archive contains duplicate members")
    if names.count(expected) != 1:
        raise ValueError("result_file must exist exactly once in archive")
    for member in members:
        path = Path(member.name)
        if (not member.isfile() or path.is_absolute() or len(path.parts) != 1
                or ".." in path.parts or not member.name.endswith(".jsonl")):
            raise ValueError("archive contains an unsafe member")
    stream = archive.extractfile(expected)
    if stream is None:
        raise ValueError("cannot read result_file from archive")
    return stream.read()


def _outcome(record: Mapping[str, Any]) -> str:
    status = record.get("status")
    if status == "ok":
        return "ok"
    if status == "timeout":
        return "timeout"
    if status in _ENGINE_ERRORS:
        return "engine_error"
    if status == "unsupported":
        return "unsupported"
    if status == "skipped":
        kind = record.get("skip_kind")
        if kind == "manual-query-flavour-policy":
            return "skipped_manual"
        if kind == "automatic-query-flavour-quarantine":
            return "skipped_automatic"
        raise ValueError("skipped record has unsupported skip_kind")
    if status == "oom":
        if record.get("oom_confirmed") is not True or record.get("oom_reason") != "memory-exhaustion":
            raise ValueError("OOM requires explicit confirmed memory-exhaustion provenance")
        return "oom"
    if status == "cancelled":
        return "cancelled"
    raise ValueError(f"unsupported evidence source status: {status}")


def ingest_matrix_bundle(
    *, summary_path: Path, archive_path: Path, manifest_path: Path,
    declaration_path: Path, run_id: str, system: str, adapter_identity: str,
    artifact_identity: str, selector_kind: str = "bsbm_template_id",
    expected_summary_sha256: str | None = None,
    expected_archive_sha256: str | None = None,
    exclusion_report_path: Path | None = None,
) -> tuple[EvidenceObservation, ...]:
    """Validate one source bundle and return deterministic immutable observations."""
    paths = (summary_path, archive_path, manifest_path, declaration_path)
    if any(not Path(path).is_file() for path in paths):
        raise FileNotFoundError("all ingestion inputs must be existing files")
    if not isinstance(run_id, str) or not run_id.strip() or run_id != run_id.strip():
        raise ValueError("run_id must be non-empty without surrounding whitespace")
    for field, value in (("system", system), ("adapter_identity", adapter_identity),
                         ("artifact_identity", artifact_identity), ("selector_kind", selector_kind)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be non-empty")

    if exclusion_report_path is not None:
        report = json.loads(Path(exclusion_report_path).read_text(encoding="utf-8"))
        text = json.dumps(report, sort_keys=True).lower()
        if any(marker in text for marker in _EXCLUDED_MARKERS):
            raise ValueError("source is explicitly excluded from evidence ingestion")

    summary_bytes = Path(summary_path).read_bytes()
    archive_sha256 = _sha256_file(Path(archive_path))
    summary_sha256 = _sha256_bytes(summary_bytes)
    _require_sha(expected_summary_sha256, summary_sha256, "summary SHA-256")
    _require_sha(expected_archive_sha256, archive_sha256, "archive SHA-256")
    summary = json.loads(summary_bytes.decode("utf-8"))
    if summary.get("status") not in _COMPLETED:
        raise ValueError("matrix summary is not completed")
    text = json.dumps(summary, sort_keys=True).lower()
    if any(marker in text for marker in _EXCLUDED_MARKERS):
        raise ValueError("matrix summary is synthetic or validation-only")
    bindings = [item for item in summary.get("experiments", []) if item.get("system") == system]
    if len(bindings) != 1:
        raise ValueError("summary must contain exactly one selected system binding")
    binding = bindings[0]
    if binding.get("status") not in _COMPLETED:
        raise ValueError("selected binding is not completed")

    manifest, workload, manifest_dataset = _load_manifest(Path(manifest_path))
    policy, representation, benchmark, policy_schema = _load_declaration(Path(declaration_path), system)
    if binding.get("representation") != representation:
        raise ValueError("summary representation differs from declaration")
    if not manifest_dataset.endswith(str(json.loads(Path(declaration_path).read_text())["dataset"])):
        raise ValueError("manifest dataset differs from declaration")
    result_file = binding.get("result_file")
    if not isinstance(result_file, str):
        raise ValueError("binding result_file is missing")
    with tarfile.open(archive_path, "r:gz") as archive:
        record_bytes = _safe_member(archive, result_file)
    lines = [line for line in record_bytes.splitlines() if line.strip()]
    records = [json.loads(line.decode("utf-8")) for line in lines]
    if len(records) != binding.get("record_count"):
        raise ValueError("record count differs from summary")

    counts = Counter(record.get("status") for record in records)
    failures = sum(value for key, value in counts.items() if key not in {"ok", "skipped", "unsupported"})
    if (counts["ok"] != binding.get("success_count")
            or counts["skipped"] != binding.get("skipped_count")
            or counts["unsupported"] != binding.get("unsupported_count")
            or failures != binding.get("failure_count")):
        raise ValueError("record status counts differ from summary")

    observations = []
    seen = set()
    for raw, line in zip(records, lines):
        query_id = raw.get("query_id")
        if query_id not in manifest:
            raise ValueError("result query_id is not in manifest")
        declared = manifest[query_id]
        if raw.get("query_sha256") != declared["query_sha256"]:
            raise ValueError("result query_sha256 differs from manifest")
        if raw.get("system") != system or raw.get("workload") != workload:
            raise ValueError("result system or workload identity differs")
        selector_value = raw.get(selector_kind)
        if selector_value is None or str(selector_value) != str(declared.get(selector_kind)):
            raise ValueError("result selector differs from manifest")
        key = (str(selector_value), raw["query_sha256"])
        if key in seen:
            raise ValueError("duplicate independent observation in one run")
        seen.add(key)
        compatibility = {
            "benchmark": benchmark,
            "dataset": json.loads(Path(declaration_path).read_text())["dataset"],
            "workload": workload,
            "system": system,
            "selector_kind": selector_kind,
            "selector_value": str(selector_value),
            "query_sha256": raw["query_sha256"],
            "timeout_s": float(policy["timeout_s"]),
            "timeout_mode": str(binding.get("execution_mode", {}).get("timeout_mode", "none")),
            "lifecycle": str(binding.get("execution_mode", {}).get("lifecycle", "shared")),
            "correctness_mode": "fingerprint",
            "artifact_identity": artifact_identity,
            "adapter_identity": adapter_identity,
            "policy_schema": policy_schema,
        }
        observations.append(EvidenceObservation(
            run_id=run_id,
            run_completed=True,
            matrix_status=summary["status"],
            compatibility=compatibility,
            outcome=_outcome(raw),
            attempt_count_in_run=1,
            source_summary_sha256=summary_sha256,
            source_archive_sha256=archive_sha256,
            source_record_sha256=_sha256_bytes(line),
        ))
    return tuple(sorted(observations, key=lambda item: (item.compatibility_sha256, item.evidence_id)))
