#!/usr/bin/env python3
"""Configure the isolated optimized rdflib-hdt JSONL worker."""
from __future__ import annotations
import os
import signal
from pathlib import Path
import psutil

SYSTEM_ID = "hdt-rdflib/optimized-in-memory"
REPRESENTATION = "hdt/default"
RUNTIME_PYTHON = Path("/users/u0182905/KROWN/.runtime/rdflib-hdt-3.3/bin/python")
WORKER = Path(__file__).with_name("hdt_rdflib_jsonl_worker.py")

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
    def worker_command(self, *, host_artifact, container_name=None):
        artifact = self.prepare(host_artifact)
        if not RUNTIME_PYTHON.is_file() or not WORKER.is_file():
            raise FileNotFoundError("optimized HDT runtime or worker is missing")
        return [str(RUNTIME_PYTHON), str(WORKER), str(artifact)]
    def ready_response_contract(self):
        artifact = self._prepared
        return {"kind":"ready","protocol":"jsonl-v1","source_open":True,
                "source_type":"hdt-rdflib","source_boundary":"rdflib-hdt-optimized-bgp",
                "source_reference":str(artifact),"mapped":False,"indexed":True,
                "safe_mode":True,"optimize_sparql_calls":1}
    def worker_command(self, *, host_artifact, container_name=None):
        self._prepared = self.prepare(host_artifact)
        return [str(RUNTIME_PYTHON), str(WORKER), str(self._prepared)]
    def current_rss_bytes(self, process, worker_name):
        if process is None or process.poll() is not None:
            return None
        try:
            parent = psutil.Process(process.pid)
            return sum(item.memory_info().rss for item in [parent, *parent.children(recursive=True)])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
    def force_stop_command(self, worker_name):
        return ["true"]
