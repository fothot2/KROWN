from __future__ import annotations
import importlib.util, os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def load():
 spec=importlib.util.spec_from_file_location('dbpedia_runner',ROOT/'run_dbpedia_tp3_v1.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def test_reuse_inputs_exist_and_validate():
 m=load();m.validate_reuse_inputs()
def test_reuse_environment_is_fail_closed_and_complete():
 m=load();env={};m.apply_reuse_environment(env)
 expected={'KROWN_FUSEKI_TDB2_MODE','KROWN_VIRTUOSO_MODE','KROWN_QLEVER_MODE','KROWN_OXIGRAPH_ROCKSDB_MODE'}
 assert all(env[k]=='reuse' for k in expected)
 for name,(store,receipt) in m.REUSE.items():
  mode,path_key,receipt_key=m.REUSE_ENV[name];assert env[path_key]==str(store) and env[receipt_key]==str(receipt)
def test_known_fuseki_memory_failure_can_be_excluded_from_resume():
 m=load();assert 'fuseki/memory' in m.SYSTEMS and 'fuseki/tdb2' in m.SYSTEMS
