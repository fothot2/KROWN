"""Build deterministic query-quarantine evidence ledgers."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from bench_executor.query_quarantine_contract import EvidenceObservation, LEDGER_SCHEMA, content_sha256

def deduplicate_independent_observations(observations: Iterable[EvidenceObservation]) -> tuple[EvidenceObservation, ...]:
    selected={}
    for observation in observations:
        if not isinstance(observation,EvidenceObservation): raise TypeError("observations must contain EvidenceObservation values")
        if not observation.run_completed: continue
        prior=selected.get(observation.independent_key)
        if prior is not None and prior.evidence_id != observation.evidence_id: raise ValueError("conflicting observations for one independent run and query pair")
        selected[observation.independent_key]=observation
    return tuple(sorted(selected.values(),key=lambda item:(item.run_id,item.compatibility_sha256,item.evidence_id)))

def build_ledger(observations: Iterable[EvidenceObservation], created_at_utc: str | None = None) -> dict[str, Any]:
    entries=[item.to_dict() for item in deduplicate_independent_observations(observations)]
    created=created_at_utc or datetime.now(timezone.utc).isoformat()
    body={"schema":LEDGER_SCHEMA,"created_at_utc":created,"entries":entries}
    return {**body,"ledger_sha256":content_sha256(body)}

def timeout_evidence_count(ledger: dict[str, Any], compatibility_sha256: str) -> int:
    return sum(entry["outcome"]=="timeout" for entry in ledger["entries"] if entry["compatibility_sha256"]==compatibility_sha256)
