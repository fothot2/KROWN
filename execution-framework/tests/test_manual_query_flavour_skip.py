import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_experiment_matrix_resource import (  # noqa: E402
    _manual_skip_rules,
    _result_summary,
)
from bench_executor.rdf_query_benchmark import (  # noqa: E402
    _QueryManifest,
    _QueryOutcome,
    _QuerySpec,
    _RdfQueryAdapter,
    _RdfQueryBenchmark,
)


class Adapter(_RdfQueryAdapter):
    executions = 0

    def execute(self, query):
        type(self).executions += 1
        return _QueryOutcome(
            result_count=1,
            metadata={"measurement_boundary": "test-adapter"},
        )


class TestManualSkip(unittest.TestCase):
    def manifest(self):
        return _QueryManifest(
            "workload",
            "dataset",
            (
                _QuerySpec("q5", "ASK {}", {"bsbm_template_id": "5"}),
                _QuerySpec("q7", "ASK {}", {"bsbm_template_id": "7"}),
            ),
        )

    def rules(self):
        policy = {
            "manual_query_flavour_skips": [{
                "system": "pycottas/default",
                "bsbm_template_ids": ["5"],
                "policy_id": "p1",
                "reason": "known timeout",
            }]
        }
        return _manual_skip_rules(
            policy, self.manifest(), "pycottas/default"
        )

    def test_skip_is_visible_and_not_dispatched(self):
        Adapter.executions = 0
        benchmark = _RdfQueryBenchmark(
            Adapter,
            "experiment",
            "pycottas/default",
            self.manifest(),
            warmup_runs=0,
            measured_runs=1,
            progress=False,
            manual_skip_rules=self.rules(),
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            records = benchmark.run(str(output))
            summary = _result_summary(
                output,
                SimpleNamespace(system_configuration="pycottas/default"),
                "cottas/default",
            )
        skipped = records[0]
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["elapsed_ns"], 0)
        self.assertEqual(skipped["attempt_elapsed_ns"], 0)
        self.assertTrue(skipped["timing_reconciled"])
        self.assertEqual(
            skipped["measurement_boundary"],
            "query-skipped-before-adapter-dispatch",
        )
        self.assertEqual(skipped["skip_policy_id"], "p1")
        self.assertEqual(len(skipped["skip_policy_sha256"]), 64)
        self.assertEqual(Adapter.executions, 1)
        self.assertEqual(summary["success_count"], 1)
        self.assertEqual(summary["failure_count"], 0)
        self.assertEqual(summary["unsupported_count"], 0)
        self.assertEqual(summary["skipped_count"], 1)

    def test_force_include_dispatches_all_queries(self):
        Adapter.executions = 0
        benchmark = _RdfQueryBenchmark(
            Adapter,
            "experiment",
            "pycottas/default",
            self.manifest(),
            warmup_runs=0,
            measured_runs=1,
            progress=False,
            manual_skip_rules=self.rules(),
            force_include=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            records = benchmark.run(
                str(Path(directory) / "results.jsonl")
            )
        self.assertEqual(
            [record["status"] for record in records], ["ok", "ok"]
        )
        self.assertEqual(Adapter.executions, 2)

    def test_unknown_and_duplicate_selectors_fail(self):
        base = {
            "system": "pycottas/default",
            "bsbm_template_ids": ["99"],
            "policy_id": "p1",
            "reason": "known timeout",
        }
        with self.assertRaisesRegex(ValueError, "unknown"):
            _manual_skip_rules(
                {"manual_query_flavour_skips": [base]},
                self.manifest(),
                "pycottas/default",
            )
        duplicate = dict(base, bsbm_template_ids=["5", "5"])
        with self.assertRaisesRegex(ValueError, "unique"):
            _manual_skip_rules(
                {"manual_query_flavour_skips": [duplicate]},
                self.manifest(),
                "pycottas/default",
            )


if __name__ == "__main__":
    unittest.main()
