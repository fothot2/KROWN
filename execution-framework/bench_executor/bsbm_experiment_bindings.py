#!/usr/bin/env python3
"""Build declarative BSBM Explore 1K experiment bindings."""
from __future__ import annotations
import importlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from bench_executor.comunica_hdt_system_adapter import adapter_specification as comunica_adapter_specification
from bench_executor.cottas_standalone_system_adapter import adapter_specification as cottas_adapter_specification
from bench_executor.dataset_artifact_receipt import load_dataset_artifact_receipt
from bench_executor.experiment_matrix_contract import DatasetArtifact,ExperimentSpecification
from bench_executor.rdflib_system_adapter import adapter_specification as rdflib_adapter_specification
from bench_executor.sparql_http_system_adapter import sparql_http_system_specifications
from bench_executor.system_adapter_contract import SystemAdapterSpecification
from bench_executor.vortex_rdf_system_adapter import VortexRdfRuntimeConfiguration
BENCHMARK="bsbm"; DATASET="explore-1k"; WORKLOAD="bsbm-explore-smoke"
DEFAULT_EXECUTION_POLICY={"warmup_runs":0,"measured_runs":1,"timeout_s":60.0}
SYSTEM_REPRESENTATIONS={
 "fuseki/default":"rdf/source","virtuoso/default":"rdf/source","qlever/default":"rdf/source",
 "oxigraph/memory":"rdf/source","oxigraph/rocksdb":"rdf/source","comunica/hdt":"hdt/default",
 "pycottas/default":"cottas/default","vortex-rdf/simple-dictionary-native-rdf-store":"vortex-rdf/simple-dictionary-native-rdf-store",
 "rdflib/default":"rdf/source"}
RECEIPT_FILES={"rdf/source":"rdf-source-receipt.json","hdt/default":"hdt-default-receipt.json","cottas/default":"cottas-default-receipt.json","vortex-rdf/simple-dictionary-native-rdf-store":"vortex-rdf-bootstrap-receipt.json"}
def system_adapter_specifications()->tuple[SystemAdapterSpecification,...]:
 specifications=(*sparql_http_system_specifications(),comunica_adapter_specification(),cottas_adapter_specification(),VortexRdfRuntimeConfiguration().adapter_specification(),rdflib_adapter_specification())
 by_id={item.system_id:item for item in specifications}
 if len(by_id)!=len(specifications): raise ValueError("system adapter IDs must be unique")
 if tuple(by_id)!=tuple(SYSTEM_REPRESENTATIONS): raise ValueError("system adapter registry differs from the BSBM matrix")
 for system_id,representation in SYSTEM_REPRESENTATIONS.items():
  if by_id[system_id].configuration.representation!=representation: raise ValueError(f"unexpected representation for {system_id}")
 return specifications
def load_bsbm_explore_1k_artifacts(benchmark_root:str|Path)->dict[str,DatasetArtifact]:
 data_root=Path(benchmark_root).expanduser().resolve()/"BSBM/data/explore-1k"
 artifacts={representation:load_dataset_artifact_receipt(str(data_root/filename)) for representation,filename in RECEIPT_FILES.items()}
 identities={(item.benchmark,item.dataset,item.source_format,item.source_size_bytes,item.source_sha256) for item in artifacts.values()}
 if len(identities)!=1: raise ValueError("BSBM representations do not share one source identity")
 if identities.pop()[:2]!=(BENCHMARK,DATASET): raise ValueError("representation receipts describe another logical dataset")
 return artifacts
def bsbm_explore_1k_experiments(benchmark_root:str|Path,execution_policy:Mapping[str,Any]|None=None)->tuple[ExperimentSpecification,...]:
 policy=dict(DEFAULT_EXECUTION_POLICY if execution_policy is None else execution_policy); artifacts=load_bsbm_explore_1k_artifacts(benchmark_root)
 systems={item.system_id:item.configuration for item in system_adapter_specifications()}; experiments=[]
 for system_id,representation in SYSTEM_REPRESENTATIONS.items():
  artifact=artifacts[representation]; experiment=ExperimentSpecification(experiment_id=f"{BENCHMARK}/{DATASET}/{WORKLOAD}/{system_id}",benchmark=BENCHMARK,dataset=DATASET,workload=WORKLOAD,dataset_artifact=artifact.artifact_id,system_configuration=system_id,execution_policy=policy)
  experiment.validate_bindings(artifact,systems[system_id]); experiments.append(experiment)
 if len({item.experiment_id for item in experiments})!=len(experiments): raise ValueError("experiment IDs must be unique")
 return tuple(experiments)
def resolve_adapter_classes()->dict[str,type]:
 resolved={}
 for specification in system_adapter_specifications():
  module_name,separator,class_name=specification.adapter.partition(":")
  if not separator: raise ValueError(f"invalid adapter path: {specification.adapter}")
  adapter_class=getattr(importlib.import_module(module_name),class_name)
  if not isinstance(adapter_class,type): raise TypeError(f"adapter is not a class: {specification.adapter}")
  resolved[specification.system_id]=adapter_class
 return resolved
