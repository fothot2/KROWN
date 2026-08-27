#!/usr/bin/env python3
"""Execute the four non-server BSBM Stage 1 systems."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_executor.rdf_experiment_matrix_resource import RdfExperimentMatrixResource

STAGE1 = [
    "comunica/hdt",
    "pycottas/default",
    "vortex-rdf/simple-dictionary-native-rdf-store",
    "rdflib/default",
]

def main() -> int:
    scenario = Path(__file__).resolve().parents[1] / "benchmark-integration/bsbm-smoke"
    resource = RdfExperimentMatrixResource(
        str(scenario / "data"), str(scenario / "config"),
        str(scenario / "log"), True,
    )
    success = resource.execute(
        declaration_file="/users/u0182905/benchmarks/BSBM/experiments/explore-1k-smoke.json",
        manifest_file="manifests/bsbm.json",
        results_file="raw/bsbm-stage1-summary.json",
        output_file="raw/bsbm-stage1-results.tar.gz",
        selected_systems=STAGE1,
        failure_results_file="raw/bsbm-stage1-failed-summary.json",
        failure_output_file="raw/bsbm-stage1-failed-results.tar.gz",
    )
    return 0 if success else 1

if __name__ == "__main__":
    raise SystemExit(main())
