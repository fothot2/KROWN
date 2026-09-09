import copy
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.query_quarantine_contract import (  # noqa: E402
    EvidenceObservation,
    content_sha256,
)
from bench_executor.query_quarantine_evidence import build_ledger  # noqa: E402
from bench_executor.query_quarantine_resolver import (  # noqa: E402
    POLICY_SCHEMA,
    resolve_snapshot,
    validate_policy,
)

CREATED = "2026-09-09T00:00:00+00:00"


def compatibility(selector="5"):
    return {
        "benchmark": "bsbm",
        "dataset": "explore-10k",
        "workload": "bsbm-explore-10k-smoke",
        "system": "pycottas/default",
        "selector_kind": "bsbm_template_id",
        "selector_value": selector,
        "query_sha256": ("a" if selector == "5" else "f") * 64,
        "timeout_s": 60.0,
        "timeout_mode": "worker",
        "lifecycle": "shared",
        "correctness_mode": "fingerprint",
        "artifact_identity": "bsbm/explore-10k/cottas/default",
        "adapter_identity": "pycottas-1.1.0",
        "policy_schema": "rdf-experiment-declaration-v1",
    }


def observation(index, outcome="timeout", selector="5", record=None):
    marker = record or format(index % 16, "x")
    return EvidenceObservation(
        f"run-{index:02d}",
        True,
        "completed_with_failures",
        compatibility(selector),
        outcome,
        1,
        "b" * 64,
        "c" * 64,
        marker * 64,
    )


def policy(**changes):
    value = {
        "schema": POLICY_SCHEMA,
        "policy_id": "bsbm-independent-timeout-quarantine-v1",
        "minimum_independent_completed_runs": 10,
        "required_timeout_count": 10,
        "window_kind": "latest-compatible-runs",
        "window_size": 10,
        "timeout_outcome": "timeout",
    }
    value.update(changes)
    return value


def snapshot(observations, rule=None):
    ledger = build_ledger(observations, CREATED)
    return resolve_snapshot(ledger, rule or policy(), CREATED)


class ResolverTests(unittest.TestCase):
    def test_ten_of_ten_quarantines_and_lists_exact_evidence(self):
        observations = [observation(index) for index in range(10)]
        ledger = build_ledger(observations, CREATED)
        result = resolve_snapshot(ledger, policy(), CREATED)
        decision = result["decisions"][0]
        self.assertEqual(decision["decision"], "quarantined")
        self.assertEqual(decision["timeout_count"], 10)
        self.assertEqual(decision["observed_run_count"], 10)
        self.assertEqual(
            decision["evidence_ids"],
            [entry["evidence_id"] for entry in ledger["entries"]],
        )

    def test_nine_timeouts_and_one_success_do_not_quarantine(self):
        values = [observation(index) for index in range(9)]
        values.append(observation(9, "ok"))
        self.assertEqual(
            snapshot(values)["decisions"][0]["decision"], "not_quarantined"
        )

    def test_nine_timeouts_and_one_engine_error_do_not_quarantine(self):
        values = [observation(index) for index in range(9)]
        values.append(observation(9, "engine_error"))
        self.assertEqual(
            snapshot(values)["decisions"][0]["decision"], "not_quarantined"
        )

    def test_latest_window_of_ten_is_used(self):
        values = [observation(0, "ok")]
        values.extend(observation(index) for index in range(1, 11))
        decision = snapshot(values)["decisions"][0]
        self.assertEqual(decision["decision"], "quarantined")
        self.assertEqual(decision["timeout_count"], 10)
        self.assertNotIn(values[0].evidence_id, decision["evidence_ids"])

    def test_compatibility_groups_remain_separate(self):
        values = [observation(index) for index in range(10)]
        values.extend(observation(index, selector="10") for index in range(10))
        result = snapshot(values)
        self.assertEqual(len(result["decisions"]), 2)
        self.assertEqual(
            {item["selector_value"] for item in result["decisions"]},
            {"5", "10"},
        )

    def test_input_order_does_not_change_snapshot(self):
        values = [observation(index) for index in range(10)]
        shuffled = list(values)
        random.Random(42).shuffle(shuffled)
        self.assertEqual(snapshot(values), snapshot(shuffled))

    def test_changed_selected_evidence_changes_decision_hash(self):
        first = snapshot([observation(index) for index in range(10)])
        changed = [observation(index) for index in range(9)]
        changed.append(observation(9, record="e"))
        second = snapshot(changed)
        self.assertNotEqual(
            first["decisions"][0]["decision_sha256"],
            second["decisions"][0]["decision_sha256"],
        )

    def test_invalid_thresholds_fail(self):
        for changes in (
            {"window_size": 0},
            {"required_timeout_count": 11},
            {"minimum_independent_completed_runs": 11},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_policy(policy(**changes))

    def test_ledger_hash_mismatch_fails_before_resolution(self):
        ledger = build_ledger([observation(index) for index in range(10)], CREATED)
        ledger["ledger_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "ledger_sha256 mismatch"):
            resolve_snapshot(ledger, policy(), CREATED)

    def test_non_quarantined_decision_remains_visible(self):
        result = snapshot([observation(index) for index in range(9)])
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(result["decisions"][0]["decision"], "not_quarantined")
        body = dict(result)
        snapshot_hash = body.pop("snapshot_sha256")
        self.assertEqual(snapshot_hash, content_sha256(body))


if __name__ == "__main__":
    unittest.main()
