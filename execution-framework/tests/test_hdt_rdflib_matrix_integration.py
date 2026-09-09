#!/usr/bin/env python3
import hashlib, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
from bench_executor.hdt_rdflib_optimized_system_adapter import adapter_specification
from bench_executor.rdf_experiment_manifest import system_adapter_specifications
from bench_executor.rdf_experiment_matrix_resource import _stage_artifacts, _verify_staged_artifact

class Tests(unittest.TestCase):
    def test_registry_contains_optimized_hdt_once(self):
        ids=[item.system_id for item in system_adapter_specifications()]
        self.assertEqual(ids.count("hdt-rdflib/optimized-in-memory"),1)
        spec=adapter_specification()
        self.assertEqual(spec.configuration.kind,"file-backed")
        self.assertEqual(spec.parameters["execution_strategy"],"persistent-jsonl")
    def test_hdt_pair_keeps_exact_basenames_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); suite=root/"BSBM"; exp=suite/"experiments"; data=suite/"data"; shared=root/"shared"
            exp.mkdir(parents=True); data.mkdir(); shared.mkdir()
            files=[]
            for name,payload in (("dataset.hdt",b"hdt"),("dataset.hdt.index.v1-1",b"index")):
                (data/name).write_bytes(payload); files.append({"path":name})
            (data/"receipt.json").write_text(json.dumps({"files":files}))
            declaration=exp/"run.json"; declaration.write_text(json.dumps({"representations":{"hdt/default":"data/receipt.json"}}))
            artifact=DatasetArtifact("bsbm","tiny","ntriples",1,"a"*64,"hdt/default",tuple(
                ArtifactFile(item["path"],(data/item["path"]).stat().st_size,hashlib.sha256((data/item["path"]).read_bytes()).hexdigest()) for item in files),
                producer={"build_metrics":{"status":"ok"},"representation_size":{"logical_bytes":8}})
            staged=_stage_artifacts(declaration,{"hdt/default":artifact},shared)["hdt/default"]
            self.assertEqual([Path(item.path).name for item in staged.files],["dataset.hdt","dataset.hdt.index.v1-1"])
            self.assertEqual({Path(item.path).parent for item in staged.files},{Path("rdf-matrix-artifacts/hdt--default")})
            _verify_staged_artifact(staged,shared)
            (shared/staged.files[1].path).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError,"changed"):_verify_staged_artifact(staged,shared)
    def test_query_ready_rule_is_binding_specific(self):
        root=Path(__file__).resolve().parents[1]
        receipt=(root/"bench_executor/dataset_artifact_receipt.py").read_text()
        manifest=(root/"bench_executor/rdf_experiment_manifest.py").read_text()
        self.assertNotIn("hdt/default must declare dataset.hdt",receipt)
        self.assertIn('system_id=="hdt-rdflib/optimized-in-memory"',manifest)
        self.assertIn('"dataset.hdt","dataset.hdt.index.v1-1"',manifest)
    def test_comunica_one_file_hdt_contract_remains_supported(self):
        root=Path(__file__).resolve().parents[1]
        adapter=(root/"bench_executor/comunica_hdt_system_adapter.py").read_text()
        self.assertIn('source_type":"hdt"',adapter)
        self.assertIn('container_artifact',adapter)

if __name__=="__main__": unittest.main()
