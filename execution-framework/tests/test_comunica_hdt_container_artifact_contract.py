#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.comunica_hdt_system_adapter import (
    CONTAINER_ARTIFACT,
    ComunicaHdtSystemAdapter,
)


class ContainerArtifactContractTests(unittest.TestCase):
    def test_adapter_exposes_worker_mount_target(self):
        adapter = ComunicaHdtSystemAdapter()
        self.assertEqual(adapter.container_artifact, CONTAINER_ARTIFACT)
        self.assertEqual(adapter.container_artifact, "/data/dataset.hdt")

    def test_worker_command_uses_exposed_mount_target(self):
        adapter = ComunicaHdtSystemAdapter()
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "dataset.hdt"
            artifact.write_bytes(b"HDT")
            command = adapter.worker_command(
                host_artifact=artifact,
                container_name="KROWN-Comunica-contract",
            )
            self.assertIn(
                f"{artifact.resolve()}:{adapter.container_artifact}:ro",
                command,
            )
            self.assertEqual(command[-1], adapter.container_artifact)


if __name__ == "__main__":
    unittest.main()
