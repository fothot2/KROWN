import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.query_quarantine_contract import content_sha256
from bench_executor.query_quarantine_probe import PROBE_POLICY_SCHEMA
from bench_executor.query_quarantine_resolver import SNAPSHOT_SCHEMA
from bench_executor.query_quarantine_runtime import (
    binding_runtime_provenance,
    load_runtime_orchestration,
    matrix_runtime_provenance,
    non_negative_integer,
    runtime_probe_rules,
    validate_runtime_arguments,
)


def policy():
    return {
        "schema": PROBE_POLICY_SCHEMA,
        "policy_id": "probe-v1",
        "probe_every_completed_compatible_runs": 10,
        "maximum_probes_per_binding": 1,
    }


def snapshot():
    decision = {
        "system": "pycottas/default",
        "selector_kind": "bsbm_template_id",
        "selector_value": "5",
        "compatibility_sha256": "a" * 64,
        "decision": "quarantined",
        "reason": "timeout-in-10-of-10-compatible-independent-completed-runs",
        "window_size": 10,
        "observed_run_count": 10,
        "timeout_count": 10,
        "evidence_ids": [str(index) * 64 for index in range(10)],
    }
    decision["decision_sha256"] = content_sha256(decision)
    body = {
        "schema": SNAPSHOT_SCHEMA,
        "created_at_utc": "2026-09-09T00:00:00Z",
        "policy_id": "quarantine-v1",
        "policy_sha256": "b" * 64,
        "evidence_ledger_sha256": "c" * 64,
        "decisions": [decision],
    }
    return {**body, "snapshot_sha256": content_sha256(body)}


class RuntimeTests(unittest.TestCase):
    def test_cross_field_validation(self):
        invalid = (
            (None, "policy.json", 10, "run-10"),
            ("snapshot.json", None, 10, "run-10"),
            ("snapshot.json", "policy.json", None, "run-10"),
            ("snapshot.json", "policy.json", 10, None),
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_runtime_arguments(*values)
        validate_runtime_arguments("snapshot.json", None, None, None)

    def test_non_negative_integer(self):
        self.assertEqual(non_negative_integer("10"), 10)
        with self.assertRaises(ValueError):
            non_negative_integer("-1")

    def test_snapshot_only_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "snapshot.json").write_text(json.dumps(snapshot()))
            runtime = load_runtime_orchestration(
                root, "snapshot.json", None, None, None, False
            )
        self.assertIsNotNone(runtime["quarantine_snapshot"])
        self.assertIsNone(runtime["probe_policy"])

    def test_due_non_due_and_force_include(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "snapshot.json").write_text(json.dumps(snapshot()))
            (root / "policy.json").write_text(json.dumps(policy()))
            due = load_runtime_orchestration(
                root, "snapshot.json", "policy.json", 20, "run-20", False
            )
            not_due = load_runtime_orchestration(
                root, "snapshot.json", "policy.json", 19, "run-19", False
            )
            forced = load_runtime_orchestration(
                root, "snapshot.json", "policy.json", 20, "run-20", True
            )
        due_rules = runtime_probe_rules(due, "pycottas/default")
        self.assertEqual(len(due_rules), 1)
        self.assertEqual(runtime_probe_rules(not_due, "pycottas/default"), ())
        self.assertEqual(runtime_probe_rules(forced, "pycottas/default"), ())
        binding = binding_runtime_provenance(due, due_rules)
        self.assertTrue(binding["probe_due"])
        matrix = matrix_runtime_provenance(
            due, [{"runtime_orchestration": binding}]
        )
        self.assertEqual(matrix["selected_probe_count"], 1)
        self.assertEqual(matrix["matrix_run_id"], "run-20")

    def test_shared_path_escape_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                load_runtime_orchestration(
                    Path(directory), "../snapshot.json", None, None, None, False
                )


if __name__ == "__main__":
    unittest.main()
