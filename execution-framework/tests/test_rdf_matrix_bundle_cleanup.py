#!/usr/bin/env python3
"""Test cleanup of stale RDF matrix result bundles."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_experiment_matrix_resource import (
    _remove_published_bundle,
)


class RdfMatrixBundleCleanupTests(unittest.TestCase):
    def test_removes_both_stale_bundle_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / 'old-summary.json'
            archive = root / 'old-results.tar.gz'
            summary.write_text('{}\n', encoding='utf-8')
            archive.write_bytes(b'archive')

            _remove_published_bundle(summary, archive)

            self.assertFalse(summary.exists())
            self.assertFalse(archive.exists())

    def test_missing_stale_bundle_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _remove_published_bundle(
                root / 'missing-summary.json',
                root / 'missing-results.tar.gz',
            )

    def test_cleanup_failure_is_not_silenced(self):
        summary = Path('/tmp/summary.json')
        archive = Path('/tmp/archive.tar.gz')
        with patch.object(Path, 'unlink', side_effect=OSError('denied')):
            with self.assertRaisesRegex(OSError, 'denied'):
                _remove_published_bundle(summary, archive)


if __name__ == '__main__':
    unittest.main()
