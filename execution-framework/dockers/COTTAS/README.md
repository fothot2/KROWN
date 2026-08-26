# COTTAS 1.1.0 container

This image runs RDFLib SPARQL over the pycottas COTTASStore. COTTAS remains the physical RDF store.

```bash
docker build -t dtaikg/cottas:v1.1.0 COTTAS
docker run --rm --network none -v /path/dataset.cottas:/data/dataset.cottas:ro dtaikg/cottas:v1.1.0 python -c 'from rdflib import Graph; from pycottas.cottas_store import COTTASStore; print(len(list(Graph(store=COTTASStore("/data/dataset.cottas")).query("SELECT * WHERE { ?s ?p ?o } LIMIT 1"))))'
```
