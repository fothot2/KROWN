#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from bench_executor.oxigraph import Oxigraph


class OxigraphCliLoaderTests(unittest.TestCase):
    def runtime(self, directory: str) -> Oxigraph:
        runtime = Oxigraph.__new__(Oxigraph)
        runtime._data_path = Path(directory).resolve()
        runtime._backend = 'rocksdb'
        runtime._build_timeout_s = 10800.0
        runtime._logger = MagicMock()
        runtime.last_load_error = None
        runtime.run_and_wait_for_exit = MagicMock(return_value=True)
        return runtime

    def test_cli_loader_uses_non_atomic_ntriples_load(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / 'shared' / 'rdf-matrix-artifacts'
            shared.mkdir(parents=True)
            source = shared / 'rdf--source--0.nt'
            source.write_bytes(b'<s> <p> <o> .\n')
            runtime = self.runtime(directory)
            self.assertTrue(
                runtime.load_rocksdb_file(
                    'rdf-matrix-artifacts/rdf--source--0.nt'
                )
            )
            runtime.run_and_wait_for_exit.assert_called_once_with(
                'load --location /store '
                '--file /data/rdf-matrix-artifacts/rdf--source--0.nt '
                '--format nt --non-atomic'
            )

    def test_cli_loader_retains_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory) / 'shared'
            shared.mkdir()
            (shared / 'dataset.nt').write_bytes(b'<s> <p> <o> .\n')
            runtime = self.runtime(directory)
            runtime.run_and_wait_for_exit.return_value = False
            self.assertFalse(runtime.load_rocksdb_file('dataset.nt'))
            self.assertEqual(
                runtime.last_load_error['error_type'],
                'OxigraphCliLoadError',
            )


if __name__ == '__main__':
    unittest.main()
