import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_experiment_matrix_resource import (  # noqa: E402
    _compact_result_record,
)


class ManualSkipCompactionProvenanceTests(unittest.TestCase):
    def test_manual_skip_provenance_survives_compaction(self):
        record = {
            "query_id": "q10",
            "phase": "measured",
            "run": 0,
            "status": "skipped",
            "elapsed_ns": 0,
            "result_count": None,
            "result_fingerprint": None,
            "client_elapsed_ns": 0,
            "attempt_elapsed_ns": 0,
            "timing_clock": "perf_counter_ns",
            "timing_schema": "rdf-attempt-timing-v1",
            "timing_stages_ns": {"dispatch": 0},
            "timing_stages_sum_ns": 0,
            "timing_reconciled": True,
            "measurement_boundary": "query-skipped-before-adapter-dispatch",
            "bsbm_template_id": "10",
            "skip_kind": "manual-query-flavour-policy",
            "skip_reason": "known timeout",
            "skip_policy_id": "policy-v1",
            "skip_policy_sha256": "a" * 64,
        }
        compact = _compact_result_record(record)
        for name in (
            "skip_kind",
            "skip_reason",
            "skip_policy_id",
            "skip_policy_sha256",
        ):
            self.assertEqual(compact[name], record[name])


if __name__ == "__main__":
    unittest.main()
