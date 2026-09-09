#!/usr/bin/env python3
"""Configure the isolated optimized rdflib-hdt JSONL worker."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import psutil

SYSTEM_ID = "hdt-rdflib/optimized-in-memory"
REPRESENTATION = "hdt/default"
RUNTIME_PYTHON = Path("/users/u0182905/KROWN/.runtime/rdflib-hdt-3.3/bin/python")
WORKER = Path(__file__).with_name("hdt_rdflib_jsonl_worker.py")
RUNTIME_MANIFEST = RUNTIME_PYTHON.parents[1] / "runtime-manifest.json"
RUNTIME_MANIFEST_SHA256 = "4cba12c81e006c6fa2f7e7e7c2827c4661f46561d09ba3562f1b12ec0d650404"


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_runtime():
    if not RUNTIME_PYTHON.is_file() or not WORKER.is_file() or not RUNTIME_MANIFEST.is_file():
        raise FileNotFoundError("optimized HDT runtime, manifest, or worker is missing")
    if _sha256(RUNTIME_MANIFEST) != RUNTIME_MANIFEST_SHA256:
        raise RuntimeError("optimized HDT runtime manifest SHA-256 differs")
    value = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    if value.get("packages") != {"rdflib": "7.6.0", "rdflib-hdt": "3.3"}:
        raise RuntimeError("optimized HDT runtime package versions differ")
    return value

class HdtRdflibOptimizedSystemAdapter:
    @property
    def system_id(self): return SYSTEM_ID
    @property
    def representation(self): return REPRESENTATION
    @property
    def memory_scope(self): return "external-worker-process-tree"
    @property
    def lifecycle(self): return ("prepare", "execute", "collect")
    def worker_identity(self): return "KROWN-HDT-RDFLib"
    def prepare(self, artifact):
        path = Path(artifact).expanduser().resolve()
        index = Path(str(path) + ".index.v1-1")
        if path.name != "dataset.hdt" or not path.is_file() or not index.is_file():
            raise FileNotFoundError("query-ready dataset.hdt pair is required")
        return path
    def ready_response_contract(self):
        artifact = self._prepared
        return {"kind":"ready","protocol":"jsonl-v1","source_open":True,
                "source_type":"hdt-rdflib","source_boundary":"rdflib-hdt-optimized-bgp",
                "source_reference":str(artifact),"mapped":False,"indexed":True,
                "safe_mode":True,"optimize_sparql_calls":1}
    def worker_command(self, *, host_artifact, container_name=None):
        validate_runtime()
        self._prepared = self.prepare(host_artifact)
        return [str(RUNTIME_PYTHON), str(WORKER), str(self._prepared)]
    @property
    def execution_mode_provenance(self):
        return {"storage":"in-memory","engine":"rdflib-hdt",
                "query_interface":"rdflib",
                "query_evaluator":"rdflib-hdt-optimized-bgp",
                "mapped":False,"indexed":True,"safe_mode":True,
                "runtime_manifest_sha256":RUNTIME_MANIFEST_SHA256}
    def current_rss_bytes(self, process, worker_name):
        if process is None or process.poll() is not None:
            return None
        try:
            parent = psutil.Process(process.pid)
            return sum(item.memory_info().rss for item in [parent, *parent.children(recursive=True)])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
    def force_stop_process(self, process, worker_name):
        if process is not None and process.poll() is None:
            process.terminate()


def system_configuration():
    from bench_executor.experiment_matrix_contract import SystemConfiguration
    return SystemConfiguration(
        system="hdt-rdflib", configuration="optimized-in-memory",
        kind="file-backed", representation=REPRESENTATION,
        parameters={"rdflib":"7.6.0","rdflib_hdt":"3.3",
                    "storage_mode":"in-memory","mapped":False,
                    "indexed":True,"safe_mode":True,
                    "query_evaluator":"rdflib-hdt-optimized-bgp"},
    )


def adapter_specification():
    from bench_executor.system_adapter_contract import (
        LifecycleCapabilities, SystemAdapterSpecification,
    )
    return SystemAdapterSpecification(
        configuration=system_configuration(),
        adapter="bench_executor.hdt_rdflib_optimized_system_adapter:HdtRdflibOptimizedSystemAdapter",
        capabilities=LifecycleCapabilities.for_kind("file-backed"),
        parameters={"engine":"rdflib-hdt-optimized",
                    "execution_strategy":"persistent-jsonl"},
    )
