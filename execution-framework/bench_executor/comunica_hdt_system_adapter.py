#!/usr/bin/env python3
"""Define the persistent Comunica HDT system adapter."""
from __future__ import annotations
import dataclasses
from pathlib import Path
SYSTEM_ID="comunica/hdt";REPRESENTATION="hdt/default";IMAGE="dtaikg/comunica-hdt:v5.0.1"
PACKAGE="@comunica/query-sparql-hdt";PACKAGE_VERSION="5.0.1";NODE_VERSION="24.19.0"
WORKER="/opt/comunica-hdt/persistent-worker.js";CONTAINER_ARTIFACT="/data/dataset.hdt"
@dataclasses.dataclass(frozen=True)
class ComunicaHdtSystemAdapter:
    """Build one persistent, network-isolated Comunica worker command."""
    image:str=IMAGE
    @property
    def system_id(self):return SYSTEM_ID
    @property
    def representation(self):return REPRESENTATION
    @property
    def lifecycle(self):return ("prepare","execute","collect")
    def prepare(self,artifact):
        path=Path(artifact).expanduser().resolve()
        if not path.is_file():raise FileNotFoundError(f"HDT artifact is missing: {path}")
        if path.suffix.lower()!=".hdt":raise ValueError("Comunica HDT requires one .hdt artifact")
        return path
    def worker_command(self,*,host_artifact,container_name,container_artifact=CONTAINER_ARTIFACT):
        artifact=self.prepare(host_artifact)
        if not isinstance(container_name,str) or not container_name.startswith("KROWN-Comunica-"):
            raise ValueError("container_name must use the KROWN-Comunica- prefix")
        return ["docker","run","--rm","--interactive","--network","none","--name",container_name,
                "--volume",f"{artifact}:{container_artifact}:ro","--entrypoint","node",self.image,
                WORKER,container_artifact]
    def force_stop_command(self,container_name):return ["docker","rm","--force",container_name]
def system_configuration():
    from bench_executor.experiment_matrix_contract import SystemConfiguration
    return SystemConfiguration(system="comunica",configuration="hdt",kind="file-backed",representation=REPRESENTATION,parameters={"image":IMAGE,"package":PACKAGE,"package_version":PACKAGE_VERSION,"node_version":NODE_VERSION,"worker_protocol":"jsonl-v1"})
def adapter_specification():
    from bench_executor.system_adapter_contract import LifecycleCapabilities,SystemAdapterSpecification
    return SystemAdapterSpecification(configuration=system_configuration(),adapter="bench_executor.comunica_hdt_system_adapter:ComunicaHdtSystemAdapter",capabilities=LifecycleCapabilities.for_kind("file-backed"),parameters={"engine":"persistent-jsonl","execution_strategy":"persistent-jsonl"})
