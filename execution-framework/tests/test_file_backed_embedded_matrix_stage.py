#!/usr/bin/env python3
"""Focused tests for explicit file-backed and embedded matrix routing."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest

FRAMEWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK))

from bench_executor.comunica_hdt_system_adapter import adapter_specification as comunica_specification
from bench_executor.cottas_standalone_system_adapter import adapter_specification as cottas_specification
from bench_executor.rdflib_system_adapter import adapter_specification as rdflib_specification
from bench_executor.rdf_experiment_matrix_resource import _execution_strategy
from bench_executor.vortex_rdf_system_adapter import VortexRdfRuntimeConfiguration


class FileBackedEmbeddedMatrixStageTests(unittest.TestCase):
    def test_registered_runtime_routes_are_explicit(self):
        specifications = (
            comunica_specification(),
            cottas_specification(),
            rdflib_specification(),
            VortexRdfRuntimeConfiguration().adapter_specification(),
        )
        self.assertEqual(
            {item.system_id: _execution_strategy(item) for item in specifications},
            {
                "comunica/hdt": "persistent-jsonl",
                "pycottas/default": "rdflib-worker",
                "rdflib/default": "rdflib-worker",
                "vortex-rdf/simple-dictionary-native-rdf-store": "rdflib-worker",
            },
        )

    def test_cottas_does_not_claim_persistent_jsonl_protocol(self):
        specification = cottas_specification()
        self.assertEqual(specification.configuration.kind, "file-backed")
        self.assertEqual(specification.parameters["engine"], "cottas")
        self.assertEqual(
            specification.parameters["execution_strategy"], "rdflib-worker"
        )

    def test_comunica_uses_persistent_jsonl_protocol(self):
        specification = comunica_specification()
        self.assertEqual(
            specification.parameters["execution_strategy"], "persistent-jsonl"
        )


if __name__ == "__main__":
    unittest.main()
