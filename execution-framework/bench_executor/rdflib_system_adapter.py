#!/usr/bin/env python3
"""Configure the RDFLib default in-memory Store baseline."""
from __future__ import annotations
import hashlib
from pathlib import Path
from bench_executor.experiment_matrix_contract import DatasetArtifact, SystemConfiguration
from bench_executor.system_adapter_contract import LifecycleCapabilities, SystemAdapterSpecification
SYSTEM_ID="rdflib/default"; REPRESENTATION="rdf/source"
IMAGE="dtaikg/rdflib:7.6.0"; RDFLIB_VERSION="7.6.0"

def system_configuration():
 return SystemConfiguration(system="rdflib",configuration="default",kind="embedded",representation=REPRESENTATION,parameters={"image":IMAGE,"rdflib_version":RDFLIB_VERSION,"store":"default"})

def adapter_specification():
 return SystemAdapterSpecification(configuration=system_configuration(),adapter="bench_executor.rdflib_system_adapter:RdfLibSystemAdapter",capabilities=LifecycleCapabilities.for_kind("embedded"),parameters={"engine":"default","execution_strategy":"rdflib-worker"})

class RdfLibSystemAdapter:
 def __init__(self,artifact:DatasetArtifact,data_path:str|Path):
  if not isinstance(artifact,DatasetArtifact): raise TypeError("artifact must be a DatasetArtifact")
  if artifact.representation!=REPRESENTATION: raise ValueError("RDFLib default Store requires rdf/source")
  if artifact.source_format!="ntriples" or len(artifact.files)!=1: raise ValueError("RDFLib default Store requires one N-Triples source file")
  self.artifact=artifact; self.data_path=Path(data_path).expanduser().resolve(); self.artifact_path=None
 @property
 def system_id(self): return SYSTEM_ID
 @property
 def representation(self): return REPRESENTATION
 @property
 def lifecycle(self): return ("prepare","execute","collect")
 @staticmethod
 def _sha256(path):
  h=hashlib.sha256()
  with path.open("rb") as f:
   for b in iter(lambda:f.read(1048576),b""): h.update(b)
  return h.hexdigest()
 def prepare(self):
  shared=(self.data_path/"shared").resolve(); path=(shared/self.artifact.files[0].path).resolve()
  try: path.relative_to(shared)
  except ValueError: return False
  declared=self.artifact.files[0]
  if not path.is_file() or path.stat().st_size!=declared.size_bytes or self._sha256(path)!=declared.sha256: return False
  self.artifact_path=path; return True
 def query_parameters(self):
  if self.artifact_path is None: raise RuntimeError("RDFLib source artifact is not prepared")
  return {"engine":"default","artifact_file":str(self.artifact_path),"system":SYSTEM_ID}
 def docker_smoke_command(self,query):
  if self.artifact_path is None: raise RuntimeError("RDFLib source artifact is not prepared")
  if not isinstance(query,str) or not query.strip(): raise ValueError("query must not be empty")
  code="from rdflib import Graph; g=Graph(); g.parse('/data/dataset.nt',format='nt'); rows=list(g.query(%r)); print(len(rows)); g.close()"%query
  return ["docker","run","--rm","--network","none","--volume",f"{self.artifact_path}:/data/dataset.nt:ro",IMAGE,"python","-c",code]
