#!/bin/sh
set -eu

version="${1:-6.2.0}"
archive="apache-jena-fuseki-${version}.tar.gz"
url="https://dlcdn.apache.org/jena/binaries/${archive}"
sha_url="${url}.sha512"

curl --fail --location --retry 5 --retry-all-errors --output "${archive}" "${url}"
curl --fail --location --retry 5 --retry-all-errors --output "${archive}.sha512" "${sha_url}"
sha512sum --check --strict "${archive}.sha512"
