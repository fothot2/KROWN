#!/usr/bin/env python3
from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_query_benchmark import _QueryManifest,_QueryOutcome,_QuerySpec,_QueryTimeoutError,_RdfQueryBenchmark
class Adapter:
    supports_load_temperature = False
    def open(self): pass
    def close(self): pass
    def prepare_for_attempt(self): return False
    def execute(self, query):
        if query == "SLOW": raise _QueryTimeoutError("timeout")
        return _QueryOutcome(result_count=1,result_fingerprint="ok")
class InRunQuarantineTests(unittest.TestCase):
    def test_twentieth_timeout_activates_template_quarantine(self):
        queries=[]
        for i in range(25):
            queries.append(_QuerySpec(f"slow-{i}","SLOW",{"bsbm_template_id":"10"}))
            queries.append(_QuerySpec(f"fast-{i}","FAST",{"bsbm_template_id":"1"}))
        manifest=_QueryManifest("w","d",tuple(queries))
        with tempfile.TemporaryDirectory() as d:
            records=_RdfQueryBenchmark(Adapter,"e","s",manifest,warmup_runs=0,measured_runs=1,in_run_timeout_quarantine_threshold=20).run(str(Path(d)/"r.jsonl"))
        slow=[r for r in records if r["bsbm_template_id"]=="10"]
        self.assertEqual(sum(r["status"]=="timeout" for r in slow),20)
        skipped=[r for r in slow if r["status"]=="skipped"]
        self.assertEqual(len(skipped),5)
        self.assertTrue(all(r["skip_kind"]=="in-run-template-timeout-quarantine" for r in skipped))
        self.assertTrue(all(r["attempt_elapsed_ns"]==0 for r in skipped))
        self.assertEqual(sum(r["status"]=="ok" for r in records),25)
        self.assertEqual(len(records),50)
    def test_real_stream_query_ids_activate_without_template_metadata(self):
        queries=[]
        for i in range(25):
            queries.append(_QuerySpec(f"explore/stream-{i:06d}/query-10","SLOW",{}))
            queries.append(_QuerySpec(f"explore/stream-{i:06d}/query-01","FAST",{}))
        manifest=_QueryManifest("w","d",tuple(queries))
        with tempfile.TemporaryDirectory() as d:
            records=_RdfQueryBenchmark(Adapter,"e","s",manifest,warmup_runs=0,measured_runs=1,in_run_timeout_quarantine_threshold=20).run(str(Path(d)/"r.jsonl"))
        q10=[r for r in records if r["query_id"].endswith("/query-10")]
        self.assertEqual(sum(r["status"]=="timeout" for r in q10),20)
        skipped=[r for r in q10 if r["status"]=="skipped"]
        self.assertEqual(len(skipped),5)
        self.assertTrue(all(r["skip_template_id"]=="10" for r in skipped))
        self.assertEqual(sum(r["status"]=="ok" for r in records),25)
        self.assertEqual(len(records),50)
    def test_explicit_template_metadata_has_priority(self):
        query=_QuerySpec("explore/stream-000000/query-10","SLOW",{"bsbm_template_id":"7"})
        manifest=_QueryManifest("w","d",tuple([query]*2))
        with tempfile.TemporaryDirectory() as d:
            records=_RdfQueryBenchmark(Adapter,"e","s",manifest,warmup_runs=0,measured_runs=1,in_run_timeout_quarantine_threshold=1).run(str(Path(d)/"r.jsonl"))
        self.assertEqual(records[0]["status"],"timeout")
        self.assertEqual(records[1]["skip_template_id"],"7")
    def test_zero_threshold_disables_quarantine(self):
        manifest=_QueryManifest("w","d",tuple(_QuerySpec(f"q{i}","SLOW",{"bsbm_template_id":"10"}) for i in range(21)))
        with tempfile.TemporaryDirectory() as d:
            records=_RdfQueryBenchmark(Adapter,"e","s",manifest,warmup_runs=0,measured_runs=1).run(str(Path(d)/"r.jsonl"))
        self.assertEqual(sum(r["status"]=="timeout" for r in records),21)
        self.assertFalse(any(r["status"]=="skipped" for r in records))
if __name__=="__main__": unittest.main()
