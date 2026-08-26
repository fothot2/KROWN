# Oxigraph 0.5.9

This context builds `dtaikg/oxigraph:0.5.9` from the locked `oxigraph-cli` crate.

KROWN exposes two configurations:

- `oxigraph/memory` omits `--location` and uses memory only.
- `oxigraph/rocksdb` uses `--location /store` and a persistent host mount.

Both configurations read the verified `rdf/source` N-Triples artifact. Loading occurs before query timing. The SPARQL endpoint is `/query`. This integration does not require Docker Compose.
