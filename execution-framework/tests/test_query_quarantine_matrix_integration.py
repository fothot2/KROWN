import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_executor.query_quarantine_contract import content_sha256
from bench_executor.query_quarantine_resolver import SNAPSHOT_SCHEMA, validate_snapshot
from bench_executor.rdf_experiment_matrix_resource import _automatic_quarantine_rules, _compact_result_record, _result_summary
from bench_executor.rdf_query_benchmark import _QueryManifest, _QueryOutcome, _QuerySpec, _RdfQueryAdapter, _RdfQueryBenchmark

class Adapter(_RdfQueryAdapter):
    executions = 0
    def execute(self, query):
        type(self).executions += 1
        return _QueryOutcome(1, metadata={"measurement_boundary":"test"})

def manifest():
    return _QueryManifest("workload","dataset",(_QuerySpec("q5","ASK {}",{"bsbm_template_id":"5"}),_QuerySpec("q7","ASK {}",{"bsbm_template_id":"7"})))

def snapshot(decision="quarantined", selector="5"):
    item={"system":"pycottas/default","selector_kind":"bsbm_template_id","selector_value":selector,"compatibility_sha256":"a"*64,"decision":decision,"reason":"timeout-in-10-of-10-compatible-independent-completed-runs" if decision=="quarantined" else "automatic-quarantine-threshold-not-met","window_size":10,"observed_run_count":10,"timeout_count":10 if decision=="quarantined" else 9,"evidence_ids":[str(i)*64 for i in range(10)]}
    item["decision_sha256"]=content_sha256(item)
    body={"schema":SNAPSHOT_SCHEMA,"created_at_utc":"2026-09-09T00:00:00+00:00","policy_id":"p1","policy_sha256":"b"*64,"evidence_ledger_sha256":"c"*64,"decisions":[item]}
    return {**body,"snapshot_sha256":content_sha256(body)}

def rules(value):
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/"snapshot.json"; path.write_text(json.dumps(value))
        return _automatic_quarantine_rules(path,manifest(),"pycottas/default")

class IntegrationTests(unittest.TestCase):
    def run_benchmark(self, automatic=(), manual=(), force=False):
        Adapter.executions=0
        benchmark=_RdfQueryBenchmark(Adapter,"e","pycottas/default",manifest(),warmup_runs=0,measured_runs=1,progress=False,manual_skip_rules=manual,automatic_quarantine_rules=automatic,force_include=force)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"r.jsonl"; records=benchmark.run(str(path)); summary=_result_summary(path,SimpleNamespace(system_configuration="pycottas/default"),"cottas/default")
        return records,summary
    def test_automatic_skip_is_visible_not_dispatched_and_compactable(self):
        records,summary=self.run_benchmark(rules(snapshot()))
        record=records[0]
        self.assertEqual(record["skip_kind"],"automatic-query-flavour-quarantine")
        self.assertEqual(record["attempt_elapsed_ns"],0); self.assertTrue(record["timing_reconciled"])
        self.assertEqual(Adapter.executions,1)
        for field in ("skip_evidence_ledger_sha256","skip_quarantine_snapshot_sha256","skip_decision_sha256","skip_evidence_count","skip_timeout_count"):
            self.assertEqual(_compact_result_record(record)[field],record[field])
        self.assertEqual(summary["automatic_quarantine_skipped_count"],1); self.assertEqual(summary["manual_skipped_count"],0)
    def test_manual_precedence_and_force_include(self):
        manual=({"selector_values":["5"],"policy_id":"manual","reason":"manual","policy_sha256":"d"*64},)
        records,summary=self.run_benchmark(rules(snapshot()),manual)
        self.assertEqual(records[0]["skip_kind"],"manual-query-flavour-policy"); self.assertEqual(summary["manual_skipped_count"],1)
        records,_=self.run_benchmark(rules(snapshot()),manual,True)
        self.assertEqual([r["status"] for r in records],["ok","ok"]); self.assertEqual(Adapter.executions,2)
    def test_not_quarantined_and_other_system_do_not_skip(self):
        records,_=self.run_benchmark(rules(snapshot("not_quarantined")))
        self.assertEqual([r["status"] for r in records],["ok","ok"])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"s.json"; path.write_text(json.dumps(snapshot()))
            self.assertEqual(_automatic_quarantine_rules(path,manifest(),"other/default"),())
    def test_unknown_duplicate_and_tampered_hashes_fail(self):
        with self.assertRaisesRegex(ValueError,"unknown"):
            rules(snapshot(selector="99"))
        duplicate=snapshot(); duplicate["decisions"].append(copy.deepcopy(duplicate["decisions"][0])); body=dict(duplicate); body.pop("snapshot_sha256"); duplicate["snapshot_sha256"]=content_sha256(body)
        with self.assertRaisesRegex(ValueError,"duplicate"):
            validate_snapshot(duplicate)
        tampered=snapshot(); tampered["snapshot_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"snapshot_sha256"):
            validate_snapshot(tampered)
        tampered=snapshot(); tampered["decisions"][0]["timeout_count"]=9; body=dict(tampered); body.pop("snapshot_sha256"); tampered["snapshot_sha256"]=content_sha256(body)
        with self.assertRaisesRegex(ValueError,"decision_sha256"):
            validate_snapshot(tampered)

if __name__ == "__main__": unittest.main()
