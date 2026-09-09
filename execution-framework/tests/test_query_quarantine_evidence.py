import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.query_quarantine_contract import EvidenceObservation
from bench_executor.query_quarantine_evidence import build_ledger, deduplicate_independent_observations, timeout_evidence_count

def compatibility(**changes):
    value = {
        "benchmark": "bsbm",
        "dataset": "explore-10k",
        "workload": "bsbm-explore-10k-smoke",
        "system": "pycottas/default",
        "selector_kind": "bsbm_template_id",
        "selector_value": "5",
        "query_sha256": "a" * 64,
        "timeout_s": 60.0,
        "timeout_mode": "worker",
        "lifecycle": "shared",
        "correctness_mode": "fingerprint",
        "artifact_identity": "bsbm/explore-10k/cottas/default",
        "adapter_identity": "pycottas-1.1.0",
        "policy_schema": "rdf-experiment-declaration-v1",
    }
    value.update(changes)
    return value

def obs(run,outcome="timeout",completed=True,record="d"):
    return EvidenceObservation(run,completed,"completed_with_failures",compatibility(),outcome,1,"b"*64,"c"*64,record*64)
class EvidenceTests(unittest.TestCase):
    def test_ten_independent_runs_count_ten(self):
        ledger=build_ledger([obs(f"run-{i:02d}") for i in range(10)],"2026-09-09T00:00:00+00:00")
        key=ledger["entries"][0]["compatibility_sha256"]
        self.assertEqual(timeout_evidence_count(ledger,key),10)
    def test_duplicate_reference_counts_once(self):
        item=obs("run-1"); self.assertEqual(len(deduplicate_independent_observations([item,item])),1)
    def test_conflicting_same_run_fails(self):
        with self.assertRaisesRegex(ValueError,"conflicting"): deduplicate_independent_observations([obs("run-1"),obs("run-1",outcome="ok",record="e")])
    def test_incomplete_run_does_not_count(self):
        self.assertEqual(build_ledger([obs("run-1",completed=False)],"2026-09-09T00:00:00+00:00")["entries"],[])
    def test_only_timeout_increments_timeout_count(self):
        values=[obs(f"run-{i}",outcome) for i,outcome in enumerate(("timeout","ok","engine_error","oom","skipped_manual","skipped_automatic","missing"))]
        ledger=build_ledger(values,"2026-09-09T00:00:00+00:00"); key=ledger["entries"][0]["compatibility_sha256"]
        self.assertEqual(timeout_evidence_count(ledger,key),1)
