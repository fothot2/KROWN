import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bench_executor.experiment_catalogue import KNOWN_COVERAGE, load_catalogue
from bench_executor.final_readiness import build_final_readiness
from check_rdf_experiment_readiness import main


class FinalReadinessTests(unittest.TestCase):
    def catalogue_path(self):
        return Path(__file__).resolve().parents[1] / "experiment-catalogue.json"

    def test_current_platform_is_ready(self):
        report = build_final_readiness(load_catalogue(self.catalogue_path()))
        self.assertTrue(report["ready_for_bsbm_10k"])
        self.assertEqual(report["missing_required_system_count"], 0)
        self.assertEqual(report["blocking_metric_cell_count"], 0)
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(report["first_execution"], "bsbm/10k")
        self.assertEqual(report["blocking_benchmarks"], ["bsbm", "krown-synthetic", "dbbench"])

    def test_unresolved_metric_blocks_final_gate(self):
        with patch.dict(
            KNOWN_COVERAGE["qlever/default"],
            {"result_correctness": "implemented-unvalidated"},
        ):
            report = build_final_readiness(load_catalogue(self.catalogue_path()))
        self.assertFalse(report["ready_for_bsbm_10k"])
        self.assertFalse(report["checks"]["metric_coverage_ready"])
        self.assertEqual(report["blocking_metric_cell_count"], 1)

    def test_cli_publishes_machine_readable_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "readiness.json"
            self.assertEqual(main(["--catalogue", str(self.catalogue_path()), "--output", str(output)]), 0)
            report = json.loads(output.read_text())
        self.assertEqual(report["schema"], "krown-rdf-final-readiness-v1")
        self.assertTrue(report["ready_for_bsbm_10k"])


if __name__ == "__main__":
    unittest.main()
