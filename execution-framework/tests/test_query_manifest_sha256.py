#!/usr/bin/env python3
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.rdf_query_benchmark import (  # noqa: E402
    _load_query_manifest,
    _QueryOutcome,
    _RdfQueryAdapter,
    _RdfQueryBenchmark,
)


class QueryManifestSha256Tests(unittest.TestCase):
    QUERY = 'ASK { ?s ?p ?o }'

    def write_manifest(self, directory, declared_hash):
        query = {
            'query_id': 'q1',
            'query': self.QUERY,
            'query_result_type': 'ASK',
            'comparison_mode': 'boolean',
        }
        if declared_hash is not None:
            query['query_sha256'] = declared_hash
        path = Path(directory) / 'manifest.json'
        path.write_text(json.dumps({
            'schema_version': 1,
            'workload': 'sample-smoke',
            'dataset': 'tiny',
            'query_count': 1,
            'queries': [query],
        }), encoding='utf-8')
        return path

    def test_matching_declared_hash_is_validated_and_not_metadata(self):
        digest = hashlib.sha256(self.QUERY.encode('utf-8')).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            manifest = _load_query_manifest(str(
                self.write_manifest(directory, digest)
            ))
        query = manifest.queries[0]
        self.assertEqual(query.query_sha256, digest)
        self.assertNotIn('query_sha256', query.metadata)
        self.assertEqual(query.metadata['query_result_type'], 'ASK')

    def test_mismatching_declared_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_manifest(directory, '0' * 64)
            with self.assertRaisesRegex(
                    ValueError, 'query_sha256 differs from query text'):
                _load_query_manifest(str(path))

    def test_invalid_declared_hash_shape_is_rejected(self):
        for value in ('not-a-hash', 'A' * 64, 123):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = self.write_manifest(directory, value)
                with self.assertRaisesRegex(
                        ValueError, 'must be a lowercase SHA-256'):
                    _load_query_manifest(str(path))

    def test_matching_hash_writes_one_reserved_record_field(self):
        class Adapter(_RdfQueryAdapter):
            def execute(self, query):
                return _QueryOutcome(
                    result_count=1,
                    result_fingerprint='a' * 64,
                )

        digest = hashlib.sha256(self.QUERY.encode('utf-8')).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            manifest = _load_query_manifest(str(
                self.write_manifest(directory, digest)
            ))
            output = Path(directory) / 'results.jsonl'
            records = _RdfQueryBenchmark(
                adapter_factory=Adapter,
                experiment_id='sample/run',
                system='sample/default',
                manifest=manifest,
                warmup_runs=0,
                measured_runs=1,
            ).run(str(output))
            persisted = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['query_sha256'], digest)
        self.assertEqual(persisted['query_sha256'], digest)
        self.assertEqual(records[0]['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
