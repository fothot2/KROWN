import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.query_quarantine_contract import EvidenceObservation
from bench_executor.query_quarantine_evidence import build_ledger
from bench_executor.query_quarantine_ledger_build import build_ledger_v2
from bench_executor.query_quarantine_resolver import (
    POLICY_SCHEMA,
    SNAPSHOT_SCHEMA,
    SNAPSHOT_V2_SCHEMA,
    resolve_snapshot,
    validate_ledger_dispatch,
    validate_snapshot,
)
from bench_executor.query_quarantine_snapshot_build import build_snapshot_from_paths

CREATED = "2026-09-09T16:00:00+00:00"


def compatibility():
    return {"benchmark":"bsbm","dataset":"explore-10k","workload":"w","system":"pycottas/default","selector_kind":"bsbm_template_id","selector_value":"5","query_sha256":"a"*64,"timeout_s":60.0,"timeout_mode":"worker","lifecycle":"shared","correctness_mode":"fingerprint","artifact_identity":"a","adapter_identity":"p","policy_schema":"rdf-experiment-declaration-v1"}


def observation(index, outcome="timeout"):
    marker = format(index % 16, "x")
    return EvidenceObservation(f"run-{index:02d}",True,"completed_with_failures",compatibility(),outcome,1,"b"*64,"c"*64,marker*64)


def policy():
    return {"schema":POLICY_SCHEMA,"policy_id":"p","minimum_independent_completed_runs":10,"required_timeout_count":10,"window_kind":"latest-compatible-runs","window_size":10,"timeout_outcome":"timeout"}


def ledgers(values):
    v1 = build_ledger(values, CREATED)
    documents = [(format(index + 1, "064x"), (value,)) for index, value in enumerate(values)]
    v2 = build_ledger_v2(documents, CREATED)
    return v1, v2


class SnapshotBuildTests(unittest.TestCase):
    def test_v1_and_v2_dispatch_and_equivalent_decisions(self):
        v1, v2 = ledgers([observation(index) for index in range(10)])
        self.assertEqual(validate_ledger_dispatch(v1)["schema"], v1["schema"])
        self.assertEqual(validate_ledger_dispatch(v2)["schema"], v2["schema"])
        first = resolve_snapshot(v1, policy(), CREATED)
        second = resolve_snapshot(v2, policy(), CREATED)
        self.assertEqual(first["schema"], SNAPSHOT_SCHEMA)
        self.assertEqual(second["schema"], SNAPSHOT_V2_SCHEMA)
        self.assertEqual(first["decisions"], second["decisions"])
        self.assertEqual(second["evidence_ledger_schema"], v2["schema"])
        self.assertEqual(second["source_ingestion_document_sha256s"], v2["source_ingestion_document_sha256s"])
        validate_snapshot(first); validate_snapshot(second)

    def test_threshold_is_unchanged(self):
        _, v2 = ledgers([observation(index) for index in range(9)] + [observation(9, "ok")])
        self.assertEqual(resolve_snapshot(v2, policy(), CREATED)["decisions"][0]["decision"], "not_quarantined")

    def test_unknown_and_tampered_v2_ledgers_fail(self):
        _, v2 = ledgers([observation(index) for index in range(10)])
        unknown = dict(v2); unknown["schema"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unsupported evidence ledger schema"):
            validate_ledger_dispatch(unknown)
        tampered = copy.deepcopy(v2); tampered["source_ingestion_document_sha256s"][0] = "f" * 64
        with self.assertRaises(ValueError):
            resolve_snapshot(tampered, policy(), CREATED)

    def test_atomic_cli_boundary_and_no_overwrite(self):
        _, v2 = ledgers([observation(index) for index in range(10)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); ledger = root/"ledger.json"; rule = root/"policy.json"; output = root/"snapshot.json"
            ledger.write_text(json.dumps(v2)); rule.write_text(json.dumps(policy()))
            first = build_snapshot_from_paths(ledger, rule, output, CREATED)
            self.assertEqual(validate_snapshot(json.loads(output.read_text())), first)
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                build_snapshot_from_paths(ledger, rule, output, CREATED)
            self.assertEqual(output.read_bytes(), before)
            self.assertFalse(list(root.glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
