#!/usr/bin/env python3
"""Define the file-backed Comunica HDT system adapter."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Sequence

SYSTEM_ID = "comunica/hdt"
REPRESENTATION = "hdt/default"
IMAGE = "dtaikg/comunica-hdt:v5.0.1"
PACKAGE = "@comunica/query-sparql-hdt"
PACKAGE_VERSION = "5.0.1"
NODE_VERSION = "24.19.0"
OUTPUT_TYPE = "application/sparql-results+json"

@dataclasses.dataclass(frozen=True)
class ComunicaHdtSystemAdapter:
    """Build a reproducible Comunica command for one verified HDT artifact."""
    image: str = IMAGE

    @property
    def system_id(self) -> str:
        return SYSTEM_ID

    @property
    def representation(self) -> str:
        return REPRESENTATION

    @property
    def lifecycle(self) -> tuple[str, ...]:
        return ("prepare", "execute", "collect")

    def prepare(self, artifact: str | Path) -> Path:
        path = Path(artifact).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"HDT artifact is missing: {path}")
        if path.suffix.lower() != ".hdt":
            raise ValueError("Comunica HDT requires one .hdt artifact")
        return path

    def query_command(self, *, container_artifact: str, query: str) -> list[str]:
        if not container_artifact.startswith("/") or not container_artifact.endswith(".hdt"):
            raise ValueError("container_artifact must be an absolute .hdt path")
        if not query.strip():
            raise ValueError("query must not be empty")
        return ["comunica-sparql-hdt", f"hdt@{container_artifact}", "-q", query, "-t", OUTPUT_TYPE]

    def docker_command(self, *, host_artifact: str | Path, query: str, container_artifact: str = "/data/dataset.hdt") -> list[str]:
        artifact = self.prepare(host_artifact)
        return ["docker", "run", "--rm", "--network", "none", "--volume", f"{artifact}:{container_artifact}:ro", self.image, *self.query_command(container_artifact=container_artifact, query=query)]

def system_configuration():
    from bench_executor.experiment_matrix_contract import SystemConfiguration
    return SystemConfiguration(system="comunica",configuration="hdt",kind="file-backed",representation=REPRESENTATION,parameters={"image":IMAGE,"package":PACKAGE,"package_version":PACKAGE_VERSION,"node_version":NODE_VERSION})
def adapter_specification():
    from bench_executor.system_adapter_contract import LifecycleCapabilities,SystemAdapterSpecification
    return SystemAdapterSpecification(configuration=system_configuration(),adapter="bench_executor.comunica_hdt_system_adapter:ComunicaHdtSystemAdapter",capabilities=LifecycleCapabilities.for_kind("file-backed"),parameters={"engine":"comunica-hdt"})
