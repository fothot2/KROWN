"""Define immutable query-quarantine evidence contracts."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

LEDGER_SCHEMA = "rdf-query-quarantine-evidence-ledger-v1"
EVIDENCE_SCHEMA = "rdf-query-quarantine-evidence-v1"
OUTCOMES = frozenset({"ok", "timeout", "engine_error", "unsupported", "oom", "cancelled", "skipped_manual", "skipped_automatic", "missing"})
COMPATIBILITY_FIELDS = ("benchmark", "dataset", "workload", "system", "selector_kind", "selector_value", "query_sha256", "timeout_s", "timeout_mode", "lifecycle", "correctness_mode", "artifact_identity", "adapter_identity", "policy_schema")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()

def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip(): raise ValueError(f"{field} must be non-empty text without surrounding whitespace")
    return value

def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value): raise ValueError(f"{field} must be a lowercase SHA-256 value")
    return value

def compatibility_document(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping): raise TypeError("compatibility must be an object")
    if set(value) != set(COMPATIBILITY_FIELDS): raise ValueError("compatibility has unexpected or missing fields")
    result=dict(value)
    for field in COMPATIBILITY_FIELDS:
        if field == "timeout_s":
            timeout=result[field]
            if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or timeout <= 0: raise ValueError("timeout_s must be positive")
            result[field]=float(timeout)
        elif field == "query_sha256": _sha(result[field], field)
        else: _text(result[field], field)
    return result

def compatibility_sha256(value: Mapping[str, Any]) -> str:
    return content_sha256(compatibility_document(value))

@dataclasses.dataclass(frozen=True)
class EvidenceObservation:
    run_id: str
    run_completed: bool
    matrix_status: str
    compatibility: Mapping[str, Any]
    outcome: str
    attempt_count_in_run: int
    source_summary_sha256: str
    source_archive_sha256: str
    source_record_sha256: str
    schema: str = EVIDENCE_SCHEMA

    def __post_init__(self):
        if self.schema != EVIDENCE_SCHEMA: raise ValueError("unsupported evidence schema")
        _text(self.run_id,"run_id"); _text(self.matrix_status,"matrix_status")
        if not isinstance(self.run_completed,bool): raise TypeError("run_completed must be boolean")
        if self.outcome not in OUTCOMES: raise ValueError(f"unsupported evidence outcome: {self.outcome}")
        if not isinstance(self.attempt_count_in_run,int) or isinstance(self.attempt_count_in_run,bool) or self.attempt_count_in_run < 1: raise ValueError("attempt_count_in_run must be positive")
        for field in ("source_summary_sha256","source_archive_sha256","source_record_sha256"): _sha(getattr(self,field),field)
        object.__setattr__(self,"compatibility",compatibility_document(self.compatibility))

    @property
    def compatibility_sha256(self): return compatibility_sha256(self.compatibility)
    @property
    def evidence_id(self):
        return content_sha256(self.to_dict(include_evidence_id=False))
    @property
    def independent_key(self):
        return (self.run_id,self.compatibility["system"],self.compatibility["selector_kind"],self.compatibility["selector_value"],self.compatibility["query_sha256"])
    def to_dict(self, include_evidence_id=True):
        value={"schema":self.schema,"run_id":self.run_id,"run_completed":self.run_completed,"matrix_status":self.matrix_status,"compatibility":dict(self.compatibility),"compatibility_sha256":self.compatibility_sha256,"outcome":self.outcome,"attempt_count_in_run":self.attempt_count_in_run,"source_summary_sha256":self.source_summary_sha256,"source_archive_sha256":self.source_archive_sha256,"source_record_sha256":self.source_record_sha256}
        if include_evidence_id: value["evidence_id"]=self.evidence_id
        return value

def validate_ledger(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value,Mapping): raise TypeError("ledger must be an object")
    required={"schema","created_at_utc","entries","ledger_sha256"}
    if set(value)!=required or value.get("schema")!=LEDGER_SCHEMA: raise ValueError("invalid evidence ledger fields or schema")
    _text(value["created_at_utc"],"created_at_utc")
    if not isinstance(value["entries"],list): raise TypeError("entries must be an array")
    entries=[]
    for raw in value["entries"]:
        if not isinstance(raw,Mapping): raise TypeError("ledger entry must be an object")
        supplied=dict(raw); eid=supplied.pop("evidence_id",None); supplied.pop("compatibility_sha256",None)
        observation=EvidenceObservation(**supplied)
        if eid != observation.evidence_id: raise ValueError("evidence_id mismatch")
        entries.append(observation.to_dict())
    body={"schema":LEDGER_SCHEMA,"created_at_utc":value["created_at_utc"],"entries":entries}
    if value["ledger_sha256"] != content_sha256(body): raise ValueError("ledger_sha256 mismatch")
    return {**body,"ledger_sha256":value["ledger_sha256"]}
