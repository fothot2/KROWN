# Apache Jena Fuseki 6.2.0 container

This Docker context builds the Fuseki server used by KROWN. It downloads the official Apache Jena Fuseki 6.2.0 binary distribution and verifies its SHA-512 value before extraction.

## Requirements

- Docker with the `docker build` command.
- Docker Compose is optional. KROWN does not depend on it.

## Build

```bash
docker build \
  --build-arg JENA_VERSION=6.2.0 \
  --build-arg FUSEKI_SHA512=ba65f5867d2d4741b2ed9e2af5a0d4fbb447909894ab2a0c6bc4dac8997f4fe339c87b13c48d45d054977769f0f8bf763ea346b1f7792d5cdc458041bd43a132 \
  --tag kgconstruct/fuseki:v6.2.0 .
```

The image uses Java 21. It does not use the host Java runtime.

## Run

```bash
docker run --rm --publish 3030:3030 \
  --volume "$PWD/databases:/fuseki/databases" \
  kgconstruct/fuseki:v6.2.0 \
  --tdb2 --update --loc /fuseki/databases/DB /ds
```

The SPARQL query endpoint is `http://localhost:3030/ds/sparql`. The Graph Store Protocol endpoint is `http://localhost:3030/ds`.

## Compose

The tracked `docker-compose.yaml` provides the same version, image name, command, ports, and volumes. Compose is a manual development path. The KROWN executor uses its own Docker abstraction.

## Source policy

Do not commit an unpacked Apache Jena distribution. The Docker build verifies the official archive and then extracts it inside the image.
