#!/usr/bin/env python3
"""Load benchmark-owned RDF experiment declarations into KROWN contracts."""
from __future__ import annotations
import importlib,json
from pathlib import Path
from typing import Any
from bench_executor.dataset_artifact_receipt import load_dataset_artifact_receipt
from bench_executor.experiment_matrix_contract import DatasetArtifact,ExperimentSpecification
from bench_executor.sparql_http_system_adapter import sparql_http_system_specifications
from bench_executor.comunica_hdt_system_adapter import adapter_specification as comunica_specification
from bench_executor.cottas_standalone_system_adapter import adapter_specification as cottas_specification
from bench_executor.vortex_rdf_system_adapter import VortexRdfRuntimeConfiguration
from bench_executor.rdflib_system_adapter import adapter_specification as rdflib_specification
from bench_executor.system_adapter_contract import SystemAdapterSpecification
SCHEMA="rdf-experiment-declaration-v1"
def system_adapter_specifications()->tuple[SystemAdapterSpecification,...]:
 specifications=(*sparql_http_system_specifications(),comunica_specification(),cottas_specification(),VortexRdfRuntimeConfiguration().adapter_specification(),rdflib_specification())
 if len({item.system_id for item in specifications})!=len(specifications): raise ValueError("system adapter IDs must be unique")
 return specifications
def _contained(root:Path,value:Any,field:str)->Path:
 if not isinstance(value,str) or not value or Path(value).is_absolute() or ".." in Path(value).parts: raise ValueError(f"{field} must be a contained relative path")
 path=(root/value).resolve()
 try:path.relative_to(root.resolve())
 except ValueError as error:raise ValueError(f"{field} escapes benchmark root") from error
 return path
def load_rdf_experiment_declaration(path:str|Path)->tuple[tuple[ExperimentSpecification,...],dict[str,DatasetArtifact]]:
 declaration_path=Path(path).expanduser().resolve(); root=declaration_path.parents[1]; value=json.loads(declaration_path.read_text(encoding="utf-8"))
 if not isinstance(value,dict) or value.get("schema")!=SCHEMA: raise ValueError("unsupported RDF experiment declaration")
 required={"schema","experiment","benchmark","dataset","workload","inventory","representations","bindings","execution_policy","semantic_baseline"}
 if set(value)!=required: raise ValueError("RDF experiment declaration has unexpected fields")
 representations=value["representations"]
 if not isinstance(representations,dict) or not representations: raise ValueError("representations must be a non-empty object")
 artifacts={identifier:load_dataset_artifact_receipt(str(_contained(root,receipt,"representation receipt"))) for identifier,receipt in representations.items()}
 if any(identifier!=artifact.representation for identifier,artifact in artifacts.items()): raise ValueError("receipt representation differs from declaration")
 identities={(a.benchmark,a.dataset,a.source_format,a.source_size_bytes,a.source_sha256) for a in artifacts.values()}
 if len(identities)!=1 or next(iter(identities))[:2]!=(value["benchmark"],value["dataset"]): raise ValueError("representations do not share the declared logical source")
 registry={item.system_id:item for item in system_adapter_specifications()}; experiments=[]; seen=set()
 for binding in value["bindings"]:
  if not isinstance(binding,dict) or set(binding)!={"system","representation"}: raise ValueError("binding has unexpected fields")
  system_id=binding["system"]; representation=binding["representation"]
  if system_id in seen: raise ValueError(f"duplicate system binding: {system_id}")
  if system_id not in registry: raise ValueError(f"unknown system binding: {system_id}")
  if representation not in artifacts: raise ValueError(f"unknown representation binding: {representation}")
  artifact=artifacts[representation]; experiment=ExperimentSpecification(experiment_id=f'{value["experiment"]}/{system_id}',benchmark=value["benchmark"],dataset=value["dataset"],workload=value["workload"],dataset_artifact=artifact.artifact_id,system_configuration=system_id,execution_policy=value["execution_policy"])
  experiment.validate_bindings(artifact,registry[system_id].configuration); experiments.append(experiment); seen.add(system_id)
 return tuple(experiments),artifacts
def resolve_adapter_classes()->dict[str,type]:
 result={}
 for specification in system_adapter_specifications():
  module,separator,name=specification.adapter.partition(":")
  if not separator: raise ValueError(f"invalid adapter path: {specification.adapter}")
  cls=getattr(importlib.import_module(module),name)
  if not isinstance(cls,type): raise TypeError(f"adapter is not a class: {specification.adapter}")
  result[specification.system_id]=cls
 return result
