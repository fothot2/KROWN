"""Resolve immutable query-quarantine snapshots from validated evidence."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from bench_executor.query_quarantine_contract import content_sha256, validate_ledger

SNAPSHOT_SCHEMA = "rdf-query-quarantine-snapshot-v1"
POLICY_SCHEMA = "rdf-query-quarantine-policy-v1"
POLICY_FIELDS = {
    "schema",
    "policy_id",
    "minimum_independent_completed_runs",
    "required_timeout_count",
    "window_kind",
    "window_size",
    "timeout_outcome",
}


def validate_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one latest-compatible-run policy."""
    if not isinstance(value, Mapping):
        raise TypeError("quarantine policy must be an object")
    if set(value) != POLICY_FIELDS:
        raise ValueError("quarantine policy has unexpected or missing fields")
    if value.get("schema") != POLICY_SCHEMA:
        raise ValueError("unsupported quarantine policy schema")
    policy_id = value.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id or policy_id != policy_id.strip():
        raise ValueError("policy_id must be non-empty text without surrounding whitespace")
    if value.get("window_kind") != "latest-compatible-runs":
        raise ValueError("window_kind must be latest-compatible-runs")
    if value.get("timeout_outcome") != "timeout":
        raise ValueError("timeout_outcome must be timeout")
    numbers = {}
    for field in (
        "minimum_independent_completed_runs",
        "required_timeout_count",
        "window_size",
    ):
        item = value.get(field)
        if not isinstance(item, int) or isinstance(item, bool) or item < 1:
            raise ValueError(f"{field} must be a positive integer")
        numbers[field] = item
    if numbers["required_timeout_count"] > numbers["window_size"]:
        raise ValueError("required_timeout_count must not exceed window_size")
    if numbers["window_size"] < numbers["minimum_independent_completed_runs"]:
        raise ValueError(
            "window_size must be at least minimum_independent_completed_runs"
        )
    return dict(value)


def _decision(group: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    """Resolve one compatibility group with run_id as stable run order."""
    ordered = sorted(group, key=lambda item: (item["run_id"], item["evidence_id"]))
    window = ordered[-policy["window_size"]:]
    observed = len(window)
    timeout_count = sum(
        item["outcome"] == policy["timeout_outcome"] for item in window
    )
    qualifies = (
        observed >= policy["minimum_independent_completed_runs"]
        and observed == policy["window_size"]
        and timeout_count >= policy["required_timeout_count"]
    )
    compatibility = window[-1]["compatibility"]
    result = {
        "system": compatibility["system"],
        "selector_kind": compatibility["selector_kind"],
        "selector_value": compatibility["selector_value"],
        "compatibility_sha256": window[-1]["compatibility_sha256"],
        "decision": "quarantined" if qualifies else "not_quarantined",
        "reason": (
            "timeout-in-10-of-10-compatible-independent-completed-runs"
            if qualifies
            else "automatic-quarantine-threshold-not-met"
        ),
        "window_size": policy["window_size"],
        "observed_run_count": observed,
        "timeout_count": timeout_count,
        "evidence_ids": [item["evidence_id"] for item in window],
    }
    result["decision_sha256"] = content_sha256(result)
    return result


def resolve_snapshot(
    ledger: Mapping[str, Any],
    policy: Mapping[str, Any],
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    """Validate inputs and resolve all auditable compatibility decisions."""
    validated_ledger = validate_ledger(ledger)
    validated_policy = validate_policy(policy)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in validated_ledger["entries"]:
        groups[entry["compatibility_sha256"]].append(entry)
    decisions = [
        _decision(groups[key], validated_policy) for key in sorted(groups)
    ]
    decisions.sort(
        key=lambda item: (
            item["system"],
            item["selector_kind"],
            item["selector_value"],
            item["compatibility_sha256"],
        )
    )
    created = created_at_utc or datetime.now(timezone.utc).isoformat()
    if not isinstance(created, str) or not created or created != created.strip():
        raise ValueError("created_at_utc must be non-empty text")
    body = {
        "schema": SNAPSHOT_SCHEMA,
        "created_at_utc": created,
        "policy_id": validated_policy["policy_id"],
        "policy_sha256": content_sha256(validated_policy),
        "evidence_ledger_sha256": validated_ledger["ledger_sha256"],
        "decisions": decisions,
    }
    return {**body, "snapshot_sha256": content_sha256(body)}


def validate_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one immutable resolver snapshot for matrix execution."""
    if not isinstance(value, Mapping):
        raise TypeError("quarantine snapshot must be an object")
    required = {
        "schema", "created_at_utc", "policy_id", "policy_sha256",
        "evidence_ledger_sha256", "decisions", "snapshot_sha256",
    }
    if set(value) != required or value.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("invalid quarantine snapshot fields or schema")
    body = dict(value)
    snapshot_sha256 = body.pop("snapshot_sha256")
    if snapshot_sha256 != content_sha256(body):
        raise ValueError("snapshot_sha256 mismatch")
    if not isinstance(value["decisions"], list):
        raise TypeError("snapshot decisions must be an array")
    seen = set()
    decisions = []
    for raw in value["decisions"]:
        if not isinstance(raw, Mapping):
            raise TypeError("snapshot decision must be an object")
        decision = dict(raw)
        decision_sha256 = decision.pop("decision_sha256", None)
        if decision_sha256 != content_sha256(decision):
            raise ValueError("decision_sha256 mismatch")
        if decision.get("decision") not in {"quarantined", "not_quarantined"}:
            raise ValueError("unsupported quarantine decision")
        key = (
            decision.get("system"), decision.get("selector_kind"),
            decision.get("selector_value"), decision.get("compatibility_sha256"),
        )
        if key in seen:
            raise ValueError("duplicate quarantine snapshot decision")
        seen.add(key)
        decision["decision_sha256"] = decision_sha256
        decisions.append(decision)
    return {**body, "decisions": decisions, "snapshot_sha256": snapshot_sha256}
