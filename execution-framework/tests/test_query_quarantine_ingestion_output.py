import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.benchmark_result import sha256_text
from bench_executor.query_quarantine_ingestion_output import (
    build_ingestion_document,
    build_ingestion_document_from_paths,
)
from bench_executor.query_quarantine_ledger_build import (
    load_ingestion_document,
)


def source(root):
    query = "ASK { <urn:x> ?p ?o }"; sha = sha256_text(query)
    manifest={"schema_version":1,"workload":"w","dataset":"bsbm-explore-10k","queries":[{"query_id":"q1","query":query,"query_sha256":sha,"bsbm_template_id":"1"}]}
    declaration={"schema":"rdf-experiment-declaration-v1","benchmark":"bsbm","dataset":"explore-10k","workload":"w","bindings":[{"system":"pycottas/default","representation":"cottas/default"}],"execution_policy":{"timeout_s":60.0}}
    record={"query_id":"q1","query_sha256":sha,"system":"pycottas/default","workload":"w","status":"ok","bsbm_template_id":"1"}
    summary={"status":"ok","experiments":[{"system":"pycottas/default","representation":"cottas/default","status":"ok","result_file":"r.jsonl","record_count":1,"success_count":1,"skipped_count":0,"unsupported_count":0,"failure_count":0,"execution_mode":{"timeout_mode":"worker","lifecycle":"shared"}}]}
    for name,value in (("manifest.json",manifest),("declaration.json",declaration),("summary.json",summary)):(root/name).write_text(json.dumps(value))
    data=json.dumps(record,separators=(",",":")).encode()+b"\n"
    with tarfile.open(root/"results.tar.gz","w:gz") as archive:
        info=tarfile.TarInfo("r.jsonl");info.size=len(data);archive.addfile(info,io.BytesIO(data))
    return {"summary_path":root/"summary.json","archive_path":root/"results.tar.gz","manifest_path":root/"manifest.json","declaration_path":root/"declaration.json","run_id":"run-1","system":"pycottas/default","adapter_identity":"pycottas-1.1.0","artifact_identity":"bsbm/explore-10k/cottas/default","created_at_utc":"2026-09-09T17:00:00Z"}


class OutputTests(unittest.TestCase):
    def test_build_publish_and_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);arguments=source(root);document=build_ingestion_document(**arguments);output=root/"evidence.json"
            built=build_ingestion_document_from_paths(output_path=output,**arguments)
            digest,observations=load_ingestion_document(output)
            self.assertEqual(built,document);self.assertEqual(digest,document["document_sha256"]);self.assertEqual(len(observations),1)

    def test_no_overwrite_and_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);arguments=source(root);output=root/"evidence.json";output.write_bytes(b"old\n")
            with self.assertRaises(FileExistsError):build_ingestion_document_from_paths(output_path=output,**arguments)
            self.assertEqual(output.read_bytes(),b"old\n");self.assertFalse(list(root.glob(".*.tmp")))
            report=root/"report.json";report.write_text(json.dumps({"classification":"instrumentation-validation-not-historical-evidence"}));arguments["exclusion_report_path"]=report
            with self.assertRaisesRegex(ValueError,"excluded"):build_ingestion_document(**arguments)


if __name__=="__main__":unittest.main()
