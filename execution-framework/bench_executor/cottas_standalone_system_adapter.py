#!/usr/bin/env python3
"File-backed adapter for SPARQL execution through RDFLib over COTTASStore."
from dataclasses import dataclass
from pathlib import Path
SYSTEM_ID="pycottas/default"; REPRESENTATION="cottas/default"
IMAGE="dtaikg/cottas:v1.1.0"; CONTAINER_ARTIFACT="/data/dataset.cottas"
@dataclass(frozen=True)
class CottasStandaloneSystemAdapter:
 image:str=IMAGE
 @property
 def system_id(self): return SYSTEM_ID
 @property
 def representation(self): return REPRESENTATION
 @property
 def lifecycle(self): return ("prepare","execute","collect")
 def prepare(self,artifact):
  path=Path(artifact).expanduser().resolve()
  if not path.is_file(): raise FileNotFoundError(f"COTTAS artifact is missing: {path}")
  if path.suffix.lower()!=".cottas": raise ValueError("Standalone COTTAS requires one .cottas artifact")
  return path
 def query_command(self,container_artifact,sparql_query):
  if not container_artifact.startswith("/") or not container_artifact.endswith(".cottas"): raise ValueError("container_artifact must be an absolute .cottas path")
  if not isinstance(sparql_query,str) or not sparql_query.strip(): raise ValueError("sparql_query must not be empty")
  code="from rdflib import Graph; from pycottas.cottas_store import COTTASStore; g=Graph(store=COTTASStore(%r)); rows=list(g.query(%r)); print(len(rows))"%(container_artifact,sparql_query)
  return ["python","-c",code]
 def docker_command(self,host_artifact,sparql_query,container_artifact=CONTAINER_ARTIFACT):
  artifact=self.prepare(host_artifact)
  return ["docker","run","--rm","--network","none","--volume",f"{artifact}:{container_artifact}:ro",self.image,*self.query_command(container_artifact,sparql_query)]

def system_configuration():
 from bench_executor.experiment_matrix_contract import SystemConfiguration
 return SystemConfiguration(system="pycottas",configuration="default",kind="file-backed",representation=REPRESENTATION,parameters={"image":IMAGE,"package":"pycottas","package_version":"1.1.0","sparql_engine":"rdflib"})
def adapter_specification():
 from bench_executor.system_adapter_contract import LifecycleCapabilities,SystemAdapterSpecification
 return SystemAdapterSpecification(configuration=system_configuration(),adapter="bench_executor.cottas_standalone_system_adapter:CottasStandaloneSystemAdapter",capabilities=LifecycleCapabilities.for_kind("file-backed"),parameters={"engine":"cottas","sparql_engine":"rdflib","execution_strategy":"rdflib-worker"})
