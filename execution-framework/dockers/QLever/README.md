# QLever 0.6.0

This context pins the official QLever 0.6.0 image by its multi-platform digest.
The KROWN executor uses `kgconstruct/qlever:v0.6.0` through its stock Docker abstraction.

The upstream image provides the `qlever` command through `/qlever/docker-entrypoint.sh`.
It does not expose `IndexBuilderMain` or `ServerMain` in `PATH`.
Therefore, experiment configuration must pass explicit QLever CLI commands to
`QLeverSystemAdapter`. KROWN does not guess index names, input files, memory limits,
or server options.

Build the local image:

```sh
docker build -t kgconstruct/qlever:v0.6.0 .
```

The tracked `docker-compose.yaml` is a manual development template. Set
`QLEVER_COMMAND` to one complete command before you start it. The KROWN executor
does not use Compose.
