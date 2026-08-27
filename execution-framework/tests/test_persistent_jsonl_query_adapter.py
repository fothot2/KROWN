#!/usr/bin/env python3
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.persistent_jsonl_query_adapter import (  # noqa: E402
    PersistentJsonlQueryAdapter,
)
from bench_executor.rdf_query_benchmark import _QueryTimeoutError  # noqa: E402
from bench_executor.sparql_result import normalize_sparql_json_result  # noqa: E402


class PersistentJsonlTests(unittest.TestCase):
    def process(self, lines, returncode=None, stderr=""):
        process = MagicMock()
        process.stdin = io.StringIO()
        process.stdout = MagicMock()
        process.stdout.readline.side_effect = lines
        process.stderr = io.StringIO(stderr)
        process.poll.return_value = returncode
        process.wait.return_value = 0
        return process

    @staticmethod
    def adapter():
        return SimpleNamespace(
            worker_command=lambda **kwargs: ["docker", "run"],
            force_stop_command=lambda name: [
                "docker", "rm", "--force", name
            ],
        )

    def query_adapter(self, process, timeout=1.0):
        return PersistentJsonlQueryAdapter(
            adapter=self.adapter(), artifact=Path("/tmp/a.hdt"),
            timeout_s=timeout, normalizer=normalize_sparql_json_result,
        )

    def test_one_process_handles_two_queries(self):
        document = {"kind": "select", "variables": ["x"], "rows": []}
        process = self.process([
            json.dumps({"kind": "ready", "protocol": "jsonl-v1"}) + "\n",
            json.dumps({"kind": "result", "request_id": 0,
                        "status": "ok", "document": document}) + "\n",
            json.dumps({"kind": "result", "request_id": 1,
                        "status": "ok", "document": document}) + "\n",
        ])
        with patch(
            "bench_executor.persistent_jsonl_query_adapter.subprocess.Popen",
            return_value=process,
        ) as popen, patch(
            "bench_executor.persistent_jsonl_query_adapter.select.select",
            side_effect=lambda readers, writers, errors, timeout:
                (readers, [], []),
        ):
            adapter = self.query_adapter(process)
            adapter.open()
            adapter.execute("SELECT ?x WHERE { ?x ?p ?o }")
            adapter.execute("SELECT ?x WHERE { ?x ?p ?o }")
            adapter.close()
        popen.assert_called_once()
        self.assertEqual(process.stdin.getvalue().count('"kind":"query"'), 2)

    def test_timeout_forces_container_removal(self):
        process = self.process([
            json.dumps({"kind": "ready", "protocol": "jsonl-v1"}) + "\n"
        ])
        with patch(
            "bench_executor.persistent_jsonl_query_adapter.subprocess.Popen",
            return_value=process,
        ), patch(
            "bench_executor.persistent_jsonl_query_adapter.select.select",
            side_effect=[([process.stdout], [], []), ([], [], [])],
        ), patch(
            "bench_executor.persistent_jsonl_query_adapter.subprocess.run"
        ) as run:
            adapter = self.query_adapter(process, 0.01)
            adapter.open()
            with self.assertRaises(_QueryTimeoutError):
                adapter.execute("ASK { ?s ?p ?o }")
        run.assert_called_once_with(
            ["docker", "rm", "--force", adapter._container_name],
            stdout=-3, stderr=-3, check=False,
        )

    def test_eof_reports_worker_stderr_and_forces_cleanup(self):
        process = self.process([
            json.dumps({"kind": "ready", "protocol": "jsonl-v1"}) + "\n",
            "",
        ], returncode=1, stderr="TypeError: queryBindings failed")
        with patch(
            "bench_executor.persistent_jsonl_query_adapter.subprocess.Popen",
            return_value=process,
        ), patch(
            "bench_executor.persistent_jsonl_query_adapter.select.select",
            side_effect=lambda readers, writers, errors, timeout:
                (readers, [], []),
        ), patch(
            "bench_executor.persistent_jsonl_query_adapter.subprocess.run"
        ) as run:
            adapter = self.query_adapter(process)
            adapter.open()
            with self.assertRaisesRegex(
                RuntimeError, "TypeError: queryBindings failed"
            ):
                adapter.execute("SELECT ?x WHERE { ?x ?p ?o }")
        run.assert_called_once()

    def test_worker_uses_explicit_hdt_api_source_descriptor(self):
        worker = (
            Path(__file__).resolve().parents[1]
            / "dockers/ComunicaHDT/persistent-worker.js"
        ).read_text(encoding="utf-8")
        self.assertIn('type: "hdt"', worker)
        self.assertIn('value: artifact', worker)
        self.assertNotIn('`hdt@${artifact}`', worker)
        self.assertEqual(worker.count("new QueryEngine()"), 1)

    def test_worker_recognizes_prefixed_query_forms(self):
        worker = (Path(__file__).resolve().parents[1] / "dockers/ComunicaHDT/persistent-worker.js").read_text()
        self.assertIn("function withoutComments(query)", worker)
        self.assertIn("withoutComments(query).match", worker)
        self.assertNotIn("query.replace(/#[^\\r\\n]*/g", worker)

    def test_worker_graph_document_uses_shared_fingerprint(self):
        result = normalize_sparql_json_result({
            "kind": "graph",
            "triples": [[
                {"type": "uri", "value": "x"},
                {"type": "uri", "value": "p"},
                {"type": "uri", "value": "y"},
            ]],
        }, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(len(result["result_fingerprint"]), 64)


if __name__ == "__main__":
    unittest.main()
