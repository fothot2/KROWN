"""Fixed single-system resource policy for RDF evaluation."""
from __future__ import annotations

SYSTEM_MEMORY_GIB=58
SYSTEM_MEMORY_BYTES=SYSTEM_MEMORY_GIB*1024**3
DOCKER_MEMORY="58g"
DOCKER_MEMORY_SWAP="58g"
FUSEKI_HEAPS={"memory":("4g","54g"),"tdb2":("4g","16g")}
VIRTUOSO_EFFECTIVE_FRACTION=0.85
VIRTUOSO_BUFFER_FRACTION=0.66
VIRTUOSO_DIRTY_FRACTION=0.75
VIRTUOSO_LOADER_CORES=6
QLEVER_QUERY_MEMORY="42G"
QLEVER_CACHE_MEMORY="8G"
QLEVER_SIMULTANEOUS_QUERIES=1
QLEVER_THREADS=6

def virtuoso_buffers():
 effective=SYSTEM_MEMORY_BYTES*VIRTUOSO_EFFECTIVE_FRACTION
 number=int(effective*VIRTUOSO_BUFFER_FRACTION/8000)
 return number,int(number*VIRTUOSO_DIRTY_FRACTION)

def provenance():
 number,dirty=virtuoso_buffers()
 return {"schema":"rdf-system-resource-profile-v1","memory_high_bytes":SYSTEM_MEMORY_BYTES,"memory_max_bytes":SYSTEM_MEMORY_BYTES,"memory_swap_max_bytes":0,"docker_memory":DOCKER_MEMORY,"docker_memory_swap":DOCKER_MEMORY_SWAP,"fuseki_heaps":{k:{"xms":v[0],"xmx":v[1]} for k,v in FUSEKI_HEAPS.items()},"virtuoso":{"number_of_buffers":number,"max_dirty_buffers":dirty,"loader_cores":VIRTUOSO_LOADER_CORES},"qlever":{"memory_max_size":QLEVER_QUERY_MEMORY,"cache_max_size":QLEVER_CACHE_MEMORY,"num_simultaneous_queries":QLEVER_SIMULTANEOUS_QUERIES,"threads":QLEVER_THREADS}}
