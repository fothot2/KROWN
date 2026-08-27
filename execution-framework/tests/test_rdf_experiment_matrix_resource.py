#!/usr/bin/env python3
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact, SystemConfiguration
from bench_executor.rdf_experiment_matrix_resource import (
    _compact_result_file,
    _compact_result_record,
    _constructor_arguments,
    _environment_adapter_options,
    _require_concrete_runtime_value,
    _environment_system_selection,
    _result_summary,
    _runtime_preflight,
    _selected_experiments,
    _stage_artifacts,
)


class RdfExperimentMatrixResourceTests(unittest.TestCase):
    def test_constructor_requires_explicit_unknown_runtime_values(self):
        class Adapter:
            def __init__(self, artifact, data_path, directory, image, index_command): pass
        artifact = DatasetArtifact('sample','tiny','ntriples',1,'a'*64,'rdf/source',(ArtifactFile('x.nt',1,'b'*64),))
        configuration = SystemConfiguration('engine','default','server','rdf/source')
        with self.assertRaisesRegex(ValueError, 'image, index_command'):
            _constructor_arguments(Adapter, artifact, 'data', 'config', 'log', False, configuration, {})

    def test_constructor_derives_backend_from_configuration(self):
        class Adapter:
            def __init__(self, artifact, data_path, directory, backend): pass
        artifact = DatasetArtifact('sample','tiny','ntriples',1,'a'*64,'rdf/source',(ArtifactFile('x.nt',1,'b'*64),))
        configuration = SystemConfiguration('oxigraph','memory','server','rdf/source')
        arguments = _constructor_arguments(Adapter, artifact, 'data', 'config', 'log', False, configuration, {})
        self.assertEqual(arguments['backend'], 'memory')

    def test_stage_artifacts_keeps_external_source_and_verifies_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'Suite'; experiments=root/'experiments'; data=root/'data'; shared=Path(directory)/'shared'; experiments.mkdir(parents=True); data.mkdir(); shared.mkdir()
            source=data/'artifact.bin'; source.write_bytes(b'payload'); digest=hashlib.sha256(b'payload').hexdigest()
            (data/'receipt.json').write_text(json.dumps({'files':[{'path':'artifact.bin'}]}))
            path=experiments/'run.json'; path.write_text(json.dumps({'representations':{'custom/default':'data/receipt.json'}}))
            artifact=DatasetArtifact('sample','tiny','binary',7,'a'*64,'custom/default',(ArtifactFile('artifact.bin',7,digest),))
            staged=_stage_artifacts(path,{'custom/default':artifact},shared)['custom/default']; target=shared/staged.files[0].path
            self.assertEqual(target.read_bytes(),b'payload'); self.assertTrue(source.is_file())

    def test_compact_result_keeps_only_useful_fields(self):
        record = {
            "query_id": "q1", "phase": "measured", "run": 0,
            "status": "ok", "elapsed_ns": 7, "result_count": 2,
            "result_fingerprint": "f", "query_sha256": "x" * 64,
            "client_elapsed_ns": 9, "result_variables": ["x"],
        }
        self.assertEqual(set(_compact_result_record(record)), {
            "query_id", "phase", "run", "status", "elapsed_ns",
            "result_count", "result_fingerprint",
        })

    def test_compact_result_keeps_errors_only_on_failure(self):
        record = {
            "query_id": "q1", "phase": "measured", "run": 0,
            "status": "engine_error", "elapsed_ns": 7, "result_count": None,
            "result_fingerprint": None, "error_type": "RuntimeError",
            "error_message": "failed",
        }
        compact = _compact_result_record(record)
        self.assertEqual(compact["error_type"], "RuntimeError")
        self.assertEqual(compact["error_message"], "failed")

    def test_result_summary_reports_failures_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'results.jsonl'; path.write_text(json.dumps({'status':'ok'})+'\n'+json.dumps({'status':'engine_error'})+'\n')
            experiment=SimpleNamespace(experiment_id='sample/run/system',system_configuration='system/default')
            summary=_result_summary(path,experiment,'custom/default')
            self.assertEqual(summary['record_count'],2); self.assertEqual(summary['failure_count'],1); self.assertNotIn('sha256',summary); self.assertNotIn('experiment_id',summary)

    def test_environment_options_reject_placeholders(self):
        self.assertEqual(_require_concrete_runtime_value('qlever index', 'command'), 'qlever index')
        for value in ('<validated command>', 'TODO', 'replace-me'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'placeholder'):
                _require_concrete_runtime_value(value, 'command')

    def test_preflight_builds_plan_without_starting_systems(self):
        experiment=SimpleNamespace(experiment_id='sample/run/rdflib',system_configuration='rdflib/default')
        artifact=DatasetArtifact('sample','tiny','ntriples',1,'a'*64,'rdf/source',(ArtifactFile('x.nt',1,'b'*64),))
        configuration=SystemConfiguration('rdflib','default','embedded','rdf/source',parameters={'image':'dtaikg/rdflib:7.6.0'})
        specification=SimpleNamespace(system_id='rdflib/default', configuration=configuration, adapter='bench_executor.rdflib_system_adapter:RdfLibSystemAdapter', parameters={'engine':'default'})
        with tempfile.TemporaryDirectory() as directory:
            declaration=Path(directory)/'declaration.json'; manifest=Path(directory)/'manifest.json'
            declaration.write_text('{}'); manifest.write_text(json.dumps({'schema_version':1,'workload':'sample-smoke','dataset':'tiny','query_count':1,'queries':[{'query_id':'q1','query':'ASK { ?s ?p ?o }'}]}))
            daemon=SimpleNamespace(returncode=0,stdout='"29.1.3"',stderr='')
            with patch('bench_executor.rdf_experiment_matrix_resource.load_rdf_experiment_declaration',return_value=((experiment,),{'rdf/source':artifact})), patch('bench_executor.rdf_experiment_matrix_resource.system_adapter_specifications',return_value=(specification,)), patch('bench_executor.rdf_experiment_matrix_resource.shutil.which',return_value='/usr/bin/docker'), patch('bench_executor.rdf_experiment_matrix_resource.subprocess.run',return_value=daemon), patch('bench_executor.rdf_experiment_matrix_resource.importlib.util.find_spec',return_value=object()), patch('bench_executor.rdf_experiment_matrix_resource._docker_image_available',return_value=True), patch('bench_executor.rdf_experiment_matrix_resource._port_available',return_value=True):
                report=_runtime_preflight(declaration,manifest)
        self.assertEqual(report['schema'],'rdf-experiment-matrix-preflight-v1')
        self.assertEqual(report['experiments'][0]['system'],'rdflib/default')

    def test_preflight_rejects_missing_local_image(self):
        experiment=SimpleNamespace(experiment_id='sample/run/comunica',system_configuration='comunica/hdt')
        artifact=DatasetArtifact('sample','tiny','binary',1,'a'*64,'hdt/default',(ArtifactFile('x.hdt',1,'b'*64),))
        configuration=SystemConfiguration('comunica','hdt','file-backed','hdt/default',parameters={'image':'dtaikg/comunica-hdt:v5.0.1'})
        specification=SimpleNamespace(system_id='comunica/hdt',configuration=configuration,adapter='bench_executor.comunica_hdt_system_adapter:ComunicaHdtSystemAdapter',parameters={'engine':'comunica-hdt'})
        with tempfile.TemporaryDirectory() as directory:
            declaration=Path(directory)/'declaration.json'; manifest=Path(directory)/'manifest.json'; declaration.write_text('{}'); manifest.write_text(json.dumps({'schema_version':1,'workload':'sample-smoke','dataset':'tiny','query_count':1,'queries':[{'query_id':'q1','query':'ASK { ?s ?p ?o }'}]}))
            daemon=SimpleNamespace(returncode=0,stdout='"29.1.3"',stderr='')
            with patch('bench_executor.rdf_experiment_matrix_resource.load_rdf_experiment_declaration',return_value=((experiment,),{'hdt/default':artifact})), patch('bench_executor.rdf_experiment_matrix_resource.system_adapter_specifications',return_value=(specification,)), patch('bench_executor.rdf_experiment_matrix_resource.shutil.which',return_value='/usr/bin/docker'), patch('bench_executor.rdf_experiment_matrix_resource.subprocess.run',return_value=daemon), patch('bench_executor.rdf_experiment_matrix_resource._docker_image_available',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'missing local Docker images'):
                    _runtime_preflight(declaration,manifest)

    def test_qlever_preflight_uses_local_default_image(self):
        experiment=SimpleNamespace(experiment_id='sample/run/qlever',system_configuration='qlever/default')
        artifact=DatasetArtifact('sample','tiny','ntriples',1,'a'*64,'rdf/source',(ArtifactFile('x.nt',1,'b'*64),))
        configuration=SystemConfiguration('qlever','default','server','rdf/source')
        specification=SimpleNamespace(system_id='qlever/default',configuration=configuration,adapter='bench_executor.qlever_system_adapter:QLeverSystemAdapter',parameters={})
        with tempfile.TemporaryDirectory() as directory:
            declaration=Path(directory)/'declaration.json'; manifest=Path(directory)/'manifest.json'; declaration.write_text('{}'); manifest.write_text(json.dumps({'schema_version':1,'workload':'sample-smoke','dataset':'tiny','query_count':1,'queries':[{'query_id':'q1','query':'ASK { ?s ?p ?o }'}]}))
            daemon=SimpleNamespace(returncode=0,stdout='"29.1.3"',stderr='')
            with patch('bench_executor.rdf_experiment_matrix_resource.load_rdf_experiment_declaration',return_value=((experiment,),{'rdf/source':artifact})), patch('bench_executor.rdf_experiment_matrix_resource.system_adapter_specifications',return_value=(specification,)), patch('bench_executor.rdf_experiment_matrix_resource.shutil.which',return_value='/usr/bin/docker'), patch('bench_executor.rdf_experiment_matrix_resource.subprocess.run',return_value=daemon), patch('bench_executor.rdf_experiment_matrix_resource._docker_image_available',return_value=True), patch('bench_executor.rdf_experiment_matrix_resource._port_available',return_value=True):
                report=_runtime_preflight(declaration,manifest)
        self.assertIn('kgconstruct/qlever:v0.6.0',report['required_images'])

    def test_system_selection_preserves_declaration_order(self):
        experiments = tuple(
            SimpleNamespace(system_configuration=value)
            for value in ("a/one", "b/two", "c/three")
        )
        selected = _selected_experiments(
            experiments, ["c/three", "a/one"]
        )
        self.assertEqual(
            [item.system_configuration for item in selected],
            ["a/one", "c/three"],
        )

    def test_system_selection_rejects_unknown_and_duplicates(self):
        experiments = (SimpleNamespace(system_configuration="a/one"),)
        with self.assertRaisesRegex(ValueError, "unknown systems"):
            _selected_experiments(experiments, ["missing/default"])
        with self.assertRaisesRegex(ValueError, "duplicate systems"):
            _selected_experiments(experiments, ["a/one", "a/one"])

    def test_environment_system_selection_is_optional(self):
        self.assertIsNone(_environment_system_selection("TEST_SYSTEMS", {}))
        self.assertEqual(
            _environment_system_selection(
                "TEST_SYSTEMS", {"TEST_SYSTEMS": "c/three, a/one"}
            ),
            ["c/three", "a/one"],
        )


if __name__ == '__main__':
    unittest.main()
