"""Schedule deterministic revalidation probes for quarantined queries."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from bench_executor.query_quarantine_contract import content_sha256
from bench_executor.query_quarantine_resolver import validate_snapshot

PROBE_POLICY_SCHEMA = "rdf-query-quarantine-probe-policy-v1"
PROBE_REASON = "scheduled-quarantine-revalidation"
_FIELDS={"schema","policy_id","probe_every_completed_compatible_runs","maximum_probes_per_binding"}

def validate_probe_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value,Mapping): raise TypeError("probe policy must be an object")
    if set(value)!=_FIELDS or value.get("schema")!=PROBE_POLICY_SCHEMA: raise ValueError("invalid probe policy fields or schema")
    if not isinstance(value["policy_id"],str) or not value["policy_id"].strip(): raise ValueError("probe policy_id must be non-empty")
    interval=value["probe_every_completed_compatible_runs"]
    if not isinstance(interval,int) or isinstance(interval,bool) or interval<1: raise ValueError("probe interval must be positive")
    if value["maximum_probes_per_binding"]!=1: raise ValueError("maximum_probes_per_binding must be 1")
    return dict(value)

def select_probe_rules(snapshot_value, policy_value, completed_compatible_runs: int, run_id: str, system_id: str):
    snapshot=validate_snapshot(snapshot_value); policy=validate_probe_policy(policy_value)
    if not isinstance(completed_compatible_runs,int) or isinstance(completed_compatible_runs,bool) or completed_compatible_runs<0: raise ValueError("completed_compatible_runs must be non-negative")
    if not isinstance(run_id,str) or not run_id.strip(): raise ValueError("run_id must be non-empty")
    interval=policy["probe_every_completed_compatible_runs"]
    if completed_compatible_runs==0 or completed_compatible_runs%interval: return ()
    eligible=[item for item in snapshot["decisions"] if item["system"]==system_id and item["decision"]=="quarantined"]
    if not eligible: return ()
    selected=sorted(eligible,key=lambda item:(item["selector_kind"],str(item["selector_value"]),item["decision_sha256"]))[0]
    base={"system":system_id,"selector_kind":selected["selector_kind"],"selector_value":str(selected["selector_value"]),"source_decision_sha256":selected["decision_sha256"],"source_snapshot_sha256":snapshot["snapshot_sha256"],"policy_id":policy["policy_id"],"policy_sha256":content_sha256(policy),"reason":PROBE_REASON,"ordinal":completed_compatible_runs//interval,"run_id":run_id}
    return ({**base,"probe_decision_sha256":content_sha256(base)},)
