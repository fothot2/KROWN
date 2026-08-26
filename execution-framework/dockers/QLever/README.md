# QLever 0.6.0

This context pins the official QLever 0.6.0 image by digest. The local image is
`kgconstruct/qlever:v0.6.0`. It sets `WORKDIR /data`, as required by the upstream
entrypoint.

KROWN mounts the scenario data directory at `/data`. The standard adapter derives
commands from the verified staged N-Triples artifact:

- `/qlever/qlever-index` builds `/data/qlever-index/bsbm-explore-1k`.
- `/qlever/qlever-server` serves that index on port 7001.

Explicit image, index command, and server command options still override these
defaults. KROWN does not use Docker Compose for experiment execution.
