# Oxigraph 0.5.9

This context builds `dtaikg/oxigraph:0.5.9` from the locked `oxigraph-cli` crate.
The builder installs Clang, libclang, CMake, and pkg-config. The Oxigraph RocksDB
bindings require this native build toolchain.

KROWN exposes two configurations:

- `oxigraph/memory` omits `--location` and uses memory only.
- `oxigraph/rocksdb` uses `--location /store` and a persistent host mount.

Both configurations read the verified `rdf/source` N-Triples artifact. Loading
occurs before query timing. The SPARQL endpoint is `/query`. This integration
does not require Docker Compose.

Build the pinned image explicitly:

```bash
docker build --build-arg OXIGRAPH_VERSION=0.5.9 -t dtaikg/oxigraph:0.5.9 .
```
