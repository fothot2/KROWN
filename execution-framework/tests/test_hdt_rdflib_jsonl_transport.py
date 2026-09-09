#!/usr/bin/env python3
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_executor.hdt_rdflib_optimized_system_adapter import HdtRdflibOptimizedSystemAdapter
from bench_executor.persistent_jsonl_query_adapter import PersistentJsonlQueryAdapter

class Tests(unittest.TestCase):
    def pair(self, root):
        hdt=root/"dataset.hdt"; hdt.write_bytes(b"hdt")
        Path(str(hdt)+".index.v1-1").write_bytes(b"index")
        return hdt
    def test_local_backend_uses_isolated_worker_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=HdtRdflibOptimizedSystemAdapter(); hdt=self.pair(Path(directory))
            command=backend.worker_command(host_artifact=hdt)
            self.assertTrue(command[0].endswith(".runtime/rdflib-hdt-3.3/bin/python"))
            ready=backend.ready_response_contract()
            self.assertEqual(ready["source_boundary"], "rdflib-hdt-optimized-bgp")
            self.assertEqual(ready["optimize_sparql_calls"], 1)
    def test_missing_side_index_fails_before_worker_start(self):
        with tempfile.TemporaryDirectory() as directory:
            hdt=Path(directory)/"dataset.hdt"; hdt.write_bytes(b"hdt")
            with self.assertRaises(FileNotFoundError):
                HdtRdflibOptimizedSystemAdapter().worker_command(host_artifact=hdt)
    def test_transport_uses_backend_memory_hooks(self):
        backend=MagicMock(); backend.memory_scope="external-worker-process-tree"
        backend.worker_identity.return_value="worker"; backend.current_rss_bytes.return_value=7
        adapter=PersistentJsonlQueryAdapter(adapter=backend,artifact=Path("x"),timeout_s=1,normalizer=lambda d,q:d)
        process=MagicMock(); adapter._process=process
        self.assertEqual(adapter.memory_scope,"external-worker-process-tree")
        self.assertEqual(adapter.current_rss_bytes(),7)
        backend.current_rss_bytes.assert_called_once_with(process,"worker")

if __name__ == "__main__": unittest.main()
