#!/usr/bin/env python3
"""Configure RDFLib SPARQL over a Vortex-RDF physical store."""
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

from bench_executor.experiment_matrix_contract import (
    DatasetArtifact,
    SystemConfiguration,
)
from bench_executor.system_adapter_contract import (
    LifecycleCapabilities,
    SystemAdapterSpecification,
)

DEFAULT_CONFIGURATION = "simple-dictionary-native-rdf-store"
DEFAULT_REPRESENTATION = f"vortex-rdf/{DEFAULT_CONFIGURATION}"
DEFAULT_STORE_LAYOUT = "cottas-native-ids"
DEFAULT_STORAGE_LAYOUT = "native-rdf-store"
DEFAULT_BACKEND = "native"
DEFAULT_IMAGE = "dtaikg/vortex-rdf:0.1.0-0a0e511"
DEFAULT_VORTEX_RDF_VERSION = "0.1.0"
DEFAULT_RDFLIB_VERSION = "7.6.0"
DEFAULT_COMMIT = "0a0e51171aa42e79defdcd322bc1a328a93fcd11"
CONTAINER_ARTIFACT = "/data/dataset.vortex"


@dataclasses.dataclass(frozen=True)
class VortexRdfRuntimeConfiguration:
    """Keep physical names and temporary binding aliases in one replaceable object."""

    configuration: str = DEFAULT_CONFIGURATION
    representation: str = DEFAULT_REPRESENTATION
    store_layout: str = DEFAULT_STORE_LAYOUT
    storage_layout: str = DEFAULT_STORAGE_LAYOUT
    backend: str = DEFAULT_BACKEND
    image: str = DEFAULT_IMAGE
    vortex_rdf_version: str = DEFAULT_VORTEX_RDF_VERSION
    rdflib_version: str = DEFAULT_RDFLIB_VERSION
    repository_commit: str = DEFAULT_COMMIT

    def __post_init__(self) -> None:
        required = dataclasses.asdict(self)
        for name, value in required.items():
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        expected = f"vortex-rdf/{self.configuration}"
        if self.representation != expected:
            raise ValueError(f"representation must equal {expected}")
        if self.backend != "native":
            raise ValueError("Patch 52 supports only the native backend")

    @property
    def system_id(self) -> str:
        return f"vortex-rdf/{self.configuration}"

    def system_configuration(self) -> SystemConfiguration:
        return SystemConfiguration(
            system="vortex-rdf",
            configuration=self.configuration,
            kind="embedded",
            representation=self.representation,
            parameters={
                "backend": self.backend,
                "store_layout": self.store_layout,
                "storage_layout": self.storage_layout,
                "image": self.image,
                "vortex_rdf_version": self.vortex_rdf_version,
                "rdflib_version": self.rdflib_version,
                "repository_commit": self.repository_commit,
            },
        )

    def adapter_specification(self) -> SystemAdapterSpecification:
        return SystemAdapterSpecification(
            configuration=self.system_configuration(),
            adapter=(
                "bench_executor.vortex_rdf_system_adapter:"
                "VortexRdfSystemAdapter"
            ),
            capabilities=LifecycleCapabilities.for_kind("embedded"),
            parameters={
                "engine": "vortex",
                "vortex_layout": self.store_layout,
                "backend": self.backend,
            },
        )


class VortexRdfSystemAdapter:
    """Verify one Vortex artifact and build its RDFLib worker parameters."""

    def __init__(
            self,
            artifact: DatasetArtifact,
            data_path: str | Path,
            runtime: VortexRdfRuntimeConfiguration | None = None):
        if not isinstance(artifact, DatasetArtifact):
            raise TypeError("artifact must be a DatasetArtifact")
        self.runtime = runtime or VortexRdfRuntimeConfiguration()
        if artifact.representation != self.runtime.representation:
            raise ValueError(
                "Vortex-RDF artifact representation differs from runtime configuration"
            )
        if len(artifact.files) != 1:
            raise ValueError("Vortex-RDF artifact must contain one file")
        if not artifact.files[0].path.endswith(".vortex"):
            raise ValueError("Vortex-RDF artifact file must end with .vortex")
        self.artifact = artifact
        self.data_path = Path(data_path).expanduser().resolve()
        self.artifact_path: Path | None = None

    @property
    def system_id(self) -> str:
        return self.runtime.system_id

    @property
    def representation(self) -> str:
        return self.runtime.representation

    @property
    def lifecycle(self) -> tuple[str, ...]:
        return ("prepare", "execute", "collect")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def prepare(self) -> bool:
        shared = (self.data_path / "shared").resolve()
        path = (shared / self.artifact.files[0].path).resolve()
        try:
            path.relative_to(shared)
        except ValueError:
            return False
        declared = self.artifact.files[0]
        if not path.is_file():
            return False
        if path.stat().st_size != declared.size_bytes:
            return False
        if self._sha256(path) != declared.sha256:
            return False
        self.artifact_path = path
        return True

    def query_parameters(self) -> dict[str, str]:
        if self.artifact_path is None:
            raise RuntimeError("Vortex-RDF artifact is not prepared")
        return {
            "engine": "vortex",
            "artifact_file": str(self.artifact_path),
            "system": self.system_id,
            "vortex_layout": self.runtime.store_layout,
        }

    def docker_smoke_command(
            self,
            sparql_query: str,
            container_artifact: str = CONTAINER_ARTIFACT) -> list[str]:
        if self.artifact_path is None:
            raise RuntimeError("Vortex-RDF artifact is not prepared")
        if not isinstance(sparql_query, str) or not sparql_query.strip():
            raise ValueError("sparql_query must not be empty")
        if not container_artifact.startswith("/") or not container_artifact.endswith(".vortex"):
            raise ValueError("container_artifact must be an absolute .vortex path")
        code = (
            "from rdflib import Graph; "
            "from vortex_rdflib import VortexStore; "
            f"g=Graph(store=VortexStore({container_artifact!r}, "
            f"layout={self.runtime.store_layout!r}, backend={self.runtime.backend!r})); "
            f"rows=list(g.query({sparql_query!r})); print(len(rows)); g.close()"
        )
        return [
            "docker", "run", "--rm", "--network", "none",
            "--volume", f"{self.artifact_path}:{container_artifact}:ro",
            self.runtime.image, "python", "-c", code,
        ]
