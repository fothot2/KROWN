import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.query_quarantine_contract import EvidenceObservation, compatibility_sha256, validate_ledger
from bench_executor.query_quarantine_evidence import build_ledger

def compatibility(**changes):
    value={"benchmark":"bsbm","dataset":"explore-10k","workload":"bsbm-explore-10k-smoke","system":"pycottas/default","selector_kind":"bsbm_template_id","selector_value":"5","query_sha256":"a"*64,"timeout_s":60.0,"timeout_mode":"worker","lifecycle":"shared","correctness_mode":"fingerprint","artifact_identity":"bsbm/explore-10k/cottas/default","adapter_identity":"pycottas-1.1.0","policy_schema":"rdf-experiment-declaration-v1"}
    value.update(changes); return value

def observation(run="run-1",outcome="timeout",completed=True,**changes):
    return EvidenceObservation(run,completed,"completed_with_failures",compatibility(**changes),outcome,1,"b"*64,"c"*64,"d"*64)

class ContractTests(unittest.TestCase):
    def test_compatibility_changes_with_query_timeout_and_system(self):
        base=compatibility_sha256(compatibility())
        for changes in ({"query_sha256":"e"*64},{"timeout_s":30.0},{"system":"other/default"}): self.assertNotEqual(base,compatibility_sha256(compatibility(**changes)))
    def test_evidence_id_is_deterministic(self):
        self.assertEqual(observation().evidence_id,observation().evidence_id)
    def test_ledger_hash_detects_change(self):
        ledger=build_ledger([observation()],"2026-09-09T00:00:00+00:00"); validate_ledger(ledger)
        changed=copy.deepcopy(ledger); changed["entries"][0]["outcome"]="ok"
        with self.assertRaisesRegex(ValueError,"evidence_id mismatch"): validate_ledger(changed)
    def test_invalid_outcome_fails(self):
        with self.assertRaisesRegex(ValueError,"unsupported"): observation(outcome="invented")
