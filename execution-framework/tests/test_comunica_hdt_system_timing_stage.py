#!/usr/bin/env python3
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ComunicaSystemTimingStageTests(unittest.TestCase):
    def test_persistent_jsonl_maps_verified_open_to_artifact_stage(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "bench_executor/rdf_experiment_matrix_resource.py"
        ).read_text()
        tree = ast.parse(source)
        assignments = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name)
                and target.id == "lifecycle_stages_ns"
                for target in node.targets
            ):
                continue
            segment = ast.get_source_segment(source, node.value)
            if segment and 'query_stages["artifact_open_or_load"]' in segment:
                assignments.append(segment)
        persistent = [
            segment for segment in assignments
            if '"engine_startup": 0' in segment
            and '"artifact_open_or_load": query_stages["artifact_open_or_load"]' in segment
        ]
        self.assertGreaterEqual(len(persistent), 2)
        self.assertNotIn(
            '"engine_startup": query_stages["artifact_open_or_load"]',
            source,
        )


if __name__ == "__main__":
    unittest.main()
