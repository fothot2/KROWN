#!/usr/bin/env python3
import json, subprocess, sys, tempfile, unittest
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
    def test_worker_source_reserves_stdout_and_uses_rdflib_classes(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "bench_executor/hdt_rdflib_jsonl_worker.py").read_text()
        self.assertIn("PROTOCOL = os.fdopen(os.dup(sys.stdout.fileno())", source)
        self.assertIn("os.dup2(sys.stderr.fileno(), sys.stdout.fileno())", source)
        self.assertIn("isinstance(value, URIRef)", source)
        self.assertIn("isinstance(value, BNode)", source)
        self.assertIn("isinstance(value, Literal)", source)
        self.assertNotIn("value.term_type", source)

    def test_worker_term_serializer_with_real_rdflib_terms(self):
        root = Path(__file__).resolve().parents[1]
        runtime = root.parent / ".runtime/rdflib-hdt-3.3/bin/python"
        worker = root / "bench_executor/hdt_rdflib_jsonl_worker.py"
        self.assertTrue(runtime.is_file(), runtime)
        self.assertTrue(worker.is_file(), worker)
        code = (
            "import importlib.util,json,sys; "
            "from rdflib import URIRef,BNode,Literal; "
            "s=importlib.util.spec_from_file_location('worker',sys.argv[1]); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(json.dumps([m.term(URIRef('urn:x')),m.term(BNode('b1')),"
            "m.term(Literal('hello',lang='en'))]))"
        )
        result = subprocess.run(
            [str(runtime), "-c", code, str(worker)],
            text=True, capture_output=True, check=True,
        )
        value = json.loads(result.stdout)
        self.assertEqual(value[0], {"type": "uri", "value": "urn:x"})
        self.assertEqual(value[1], {"type": "bnode", "value": "b1"})
        self.assertEqual(value[2]["type"], "literal")
        self.assertEqual(value[2]["language"], "en")

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
    def test_local_force_stop_terminates_the_live_worker(self):
        backend = HdtRdflibOptimizedSystemAdapter()
        process = MagicMock()
        process.poll.return_value = None
        backend.force_stop_process(process, "KROWN-HDT-RDFLib")
        process.terminate.assert_called_once_with()

    def test_transport_uses_direct_stop_without_shell_command(self):
        backend = MagicMock()
        backend.worker_identity.return_value = "worker"
        backend.force_stop_process = MagicMock()
        adapter = PersistentJsonlQueryAdapter(
            adapter=backend,
            artifact=Path("x"),
            timeout_s=1,
            normalizer=lambda document, query: document,
        )
        process = MagicMock()
        adapter._process = process
        adapter._force_stop()
        backend.force_stop_process.assert_called_once_with(process, "worker")
        backend.force_stop_command.assert_not_called()
        process.wait.assert_called_once_with(timeout=5)

    def test_transport_uses_backend_memory_hooks(self):
        backend=MagicMock(); backend.memory_scope="external-worker-process-tree"
        backend.worker_identity.return_value="worker"; backend.current_rss_bytes.return_value=7
        adapter=PersistentJsonlQueryAdapter(adapter=backend,artifact=Path("x"),timeout_s=1,normalizer=lambda d,q:d)
        process=MagicMock(); adapter._process=process
        self.assertEqual(adapter.memory_scope,"external-worker-process-tree")
        self.assertEqual(adapter.current_rss_bytes(),7)
        backend.current_rss_bytes.assert_called_once_with(process,"worker")

if __name__ == "__main__": unittest.main()
