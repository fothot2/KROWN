# Vortex-RDF RDFLib Store container

This image runs RDFLib SPARQL over `vortex_rdflib.VortexStore`.
RDFLib supplies SPARQL processing.
Vortex-RDF supplies physical triple-pattern access.

The build uses a local Vortex-RDF checkout because the alpha release is not final.
The build rejects a checkout with the wrong commit or a dirty worktree.

```bash
VORTEX_RDF_SOURCE=/path/to/vortex-rdf ./build.sh
```

All runtime names are configurable in
`bench_executor/vortex_rdf_system_adapter.py` through
`VortexRdfRuntimeConfiguration`.
The current Python binding uses `cottas-native-ids` as its Store layout alias.
The physical representation and CLI storage layout remain `native-rdf-store`.
When the binding adopts the final name, change only `store_layout`.
