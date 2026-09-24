#!/usr/bin/env python3
"""Load benchmark-owned RDF experiment declarations into KROWN contracts."""
from __future__ import annotations
import importlib,json
from pathlib import Path
from typing import Any, Sequence
from bench_executor.dataset_artifact_receipt import load_dataset_artifact_receipt
from bench_executor.experiment_matrix_contract import DatasetArtifact,ExperimentSpecification,SystemConfiguration
from bench_executor.sparql_http_system_adapter import sparql_http_system_specifications
from bench_executor.comunica_hdt_system_adapter import adapter_specification as comunica_specification
from bench_executor.hdt_rdflib_optimized_system_adapter import adapter_specification as hdt_rdflib_specification
from bench_executor.cottas_standalone_system_adapter import adapter_specification as cottas_specification
from bench_executor.vortex_rdf_system_adapter import VortexRdfRuntimeConfiguration
from bench_executor.rdflib_system_adapter import adapter_specification as rdflib_specification
from bench_executor.system_adapter_contract import SystemAdapterSpecification
SCHEMA="rdf-experiment-declaration-v1"
def _vortex_rdf_specifications()->tuple[SystemAdapterSpecification,...]:
 base=VortexRdfRuntimeConfiguration().adapter_specification()
 variants=(
  ("dictionary-secondary-by-reference","vortex-rdf/dictionary-secondary-by-reference","secondary-by-reference",False),
  ("dictionary-secondary-by-reference-memory","vortex-rdf/dictionary-secondary-by-reference","secondary-by-reference",True),
  ("dictionary-secondary-by-copy","vortex-rdf/dictionary-secondary-by-copy","secondary-by-copy",False),
  ("dictionary-secondary-by-copy-memory","vortex-rdf/dictionary-secondary-by-copy","secondary-by-copy",True),
 )
 result=[]
 for configuration,representation,index_type,in_memory in variants:
  storage_mode="in-memory" if in_memory else "file-backed"
  system_configuration=SystemConfiguration(system="vortex-rdf",configuration=configuration,kind="embedded",representation=representation,parameters={"layout":"dictionary","index_type":index_type,"storage_mode":storage_mode,"vortex_in_memory":in_memory})
  parameters=dict(base.parameters); parameters.pop("vortex_layout",None)
  parameters.update({"engine":"vortex","execution_strategy":"rdflib-worker","storage_mode":storage_mode,"vortex_in_memory":in_memory})
  result.append(SystemAdapterSpecification(configuration=system_configuration,adapter=base.adapter,capabilities=base.capabilities,parameters=parameters))
 return tuple(result)
def system_adapter_specifications()->tuple[SystemAdapterSpecification,...]:
 specifications=(*sparql_http_system_specifications(),comunica_specification(),hdt_rdflib_specification(),cottas_specification(),*_vortex_rdf_specifications(),rdflib_specification())
 if len({item.system_id for item in specifications})!=len(specifications): raise ValueError("system adapter IDs must be unique")
 return specifications
def _contained(root:Path,value:Any,field:str)->Path:
 if not isinstance(value,str) or not value or Path(value).is_absolute() or ".." in Path(value).parts: raise ValueError(f"{field} must be a contained relative path")
 path=(root/value).resolve()
 try:path.relative_to(root.resolve())
 except ValueError as error:raise ValueError(f"{field} escapes benchmark root") from error
 return path
def load_rdf_experiment_declaration(
    path: str | Path,
    benchmark_root: str | Path | None = None,
    selected_systems: Sequence[str] | None = None,
    verify_artifact_files: bool = True,
) -> tuple[tuple[ExperimentSpecification, ...], dict[str, DatasetArtifact]]:
    declaration_path = Path(path).expanduser().resolve()
    root = (
        declaration_path.parents[1]
        if benchmark_root is None
        else Path(benchmark_root).expanduser().resolve()
    )
    value = json.loads(declaration_path.read_text(encoding="utf-8"))
    if benchmark_root is not None and not root.is_dir():
        raise FileNotFoundError(f"benchmark root is missing: {root}")
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("unsupported RDF experiment declaration")
    required = {
        "schema", "experiment", "benchmark", "dataset", "workload",
        "inventory", "representations", "bindings", "execution_policy",
    }
    optional = {"semantic_baseline"}
    fields = set(value)
    if not required.issubset(fields) or fields.difference(required | optional):
        raise ValueError("RDF experiment declaration has unexpected fields")

    bindings = value["bindings"]
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("bindings must be a non-empty array")
    declared_systems = []
    seen = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != {"system", "representation"}:
            raise ValueError("binding has unexpected fields")
        system_id = binding["system"]
        representation = binding["representation"]
        if not isinstance(system_id, str) or not system_id:
            raise ValueError("binding system must be a non-empty string")
        if not isinstance(representation, str) or not representation:
            raise ValueError("binding representation must be a non-empty string")
        if system_id in seen:
            raise ValueError(f"duplicate system binding: {system_id}")
        seen.add(system_id)
        declared_systems.append(system_id)

    if selected_systems is None:
        selected_bindings = bindings
    else:
        if not isinstance(selected_systems, (list, tuple)) or not selected_systems:
            raise ValueError("selected_systems must be a non-empty array")
        normalized = []
        for system_id in selected_systems:
            if not isinstance(system_id, str) or not system_id.strip():
                raise ValueError("selected_systems entries must be non-empty strings")
            normalized.append(system_id.strip())
        if len(normalized) != len(set(normalized)):
            raise ValueError("selected_systems contains duplicate systems")
        unknown = sorted(set(normalized).difference(declared_systems))
        if unknown:
            raise ValueError(
                "selected_systems contains unknown systems: " + ", ".join(unknown)
            )
        selected = set(normalized)
        selected_bindings = [
            binding for binding in bindings if binding["system"] in selected
        ]

    representations = value["representations"]
    if not isinstance(representations, dict) or not representations:
        raise ValueError("representations must be a non-empty object")
    selected_representations = {
        binding["representation"] for binding in selected_bindings
    }
    unknown_representations = sorted(selected_representations.difference(representations))
    if unknown_representations:
        raise ValueError(
            "unknown representation binding: " + ", ".join(unknown_representations)
        )
    artifacts = {
        identifier: load_dataset_artifact_receipt(
            str(_contained(root, representations[identifier], "representation receipt")),
            verify_files=verify_artifact_files,
        )
        for identifier in representations
        if identifier in selected_representations
    }
    if any(
        identifier != artifact.representation
        for identifier, artifact in artifacts.items()
    ):
        raise ValueError("receipt representation differs from declaration")
    identities = {
        (
            artifact.benchmark,
            artifact.dataset,
            artifact.source_format,
            artifact.source_size_bytes,
            artifact.source_sha256,
        )
        for artifact in artifacts.values()
    }
    if (
        len(identities) != 1
        or next(iter(identities))[:2] != (value["benchmark"], value["dataset"])
    ):
        raise ValueError("representations do not share the declared logical source")

    registry = {item.system_id: item for item in system_adapter_specifications()}
    experiments = []
    for binding in selected_bindings:
        system_id = binding["system"]
        representation = binding["representation"]
        if system_id not in registry:
            raise ValueError(f"unknown system binding: {system_id}")
        artifact = artifacts[representation]
        if (
            system_id == "hdt-rdflib/optimized-in-memory"
            and [item.path for item in artifact.files]
            != ["dataset.hdt", "dataset.hdt.index.v1-1"]
        ):
            raise ValueError(
                "optimized HDT requires dataset.hdt and dataset.hdt.index.v1-1"
            )
        experiment = ExperimentSpecification(
            experiment_id=f'{value["experiment"]}/{system_id}',
            benchmark=value["benchmark"],
            dataset=value["dataset"],
            workload=value["workload"],
            dataset_artifact=artifact.artifact_id,
            system_configuration=system_id,
            execution_policy=value["execution_policy"],
        )
        experiment.validate_bindings(artifact, registry[system_id].configuration)
        experiments.append(experiment)
    return tuple(experiments), artifacts
def resolve_adapter_classes()->dict[str,type]:
 result={}
 for specification in system_adapter_specifications():
  module,separator,name=specification.adapter.partition(":")
  if not separator: raise ValueError(f"invalid adapter path: {specification.adapter}")
  cls=getattr(importlib.import_module(module),name)
  if not isinstance(cls,type): raise TypeError(f"adapter is not a class: {specification.adapter}")
  result[specification.system_id]=cls
 return result
