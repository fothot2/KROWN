# RDFLib 7.6.0 baseline

The `dtaikg/rdflib:7.6.0` image provides `rdflib/default`.
KROWN parses the N-Triples source once when the persistent worker starts.
Parsing is outside each query measurement. Query timing includes SPARQL
execution and full result materialization.
