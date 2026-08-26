#!/bin/sh
set -eu

VORTEX_RDF_SOURCE=${VORTEX_RDF_SOURCE:?Set VORTEX_RDF_SOURCE to the pinned Vortex-RDF checkout}
VORTEX_RDF_COMMIT=${VORTEX_RDF_COMMIT:-0a0e51171aa42e79defdcd322bc1a328a93fcd11}
VORTEX_RDF_VERSION=${VORTEX_RDF_VERSION:-0.1.0}
RDFLIB_VERSION=${RDFLIB_VERSION:-7.6.0}
RUST_VERSION=${RUST_VERSION:-1.96.1}
MATURIN_VERSION=${MATURIN_VERSION:-1.14.1}
IMAGE=${VORTEX_RDF_IMAGE:-dtaikg/vortex-rdf:0.1.0-0a0e511}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

ACTUAL_COMMIT=$(git -C "$VORTEX_RDF_SOURCE" rev-parse HEAD)
[ "$ACTUAL_COMMIT" = "$VORTEX_RDF_COMMIT" ] || {
    echo "Expected Vortex-RDF commit $VORTEX_RDF_COMMIT, found $ACTUAL_COMMIT" >&2
    exit 1
}
[ -z "$(git -C "$VORTEX_RDF_SOURCE" status --porcelain=v1 --untracked-files=all)" ] || {
    echo "Vortex-RDF worktree must be clean" >&2
    exit 1
}

CONTEXT=$(mktemp -d)
trap 'rm -rf "$CONTEXT"' EXIT HUP INT TERM

git -C "$VORTEX_RDF_SOURCE" archive --format=tar HEAD \
    | tar -xf - -C "$CONTEXT"

cp "$SCRIPT_DIR/Dockerfile" "$CONTEXT/Dockerfile.krown"

docker build \
    --file "$CONTEXT/Dockerfile.krown" \
    --build-arg "VORTEX_RDF_COMMIT=$VORTEX_RDF_COMMIT" \
    --build-arg "VORTEX_RDF_VERSION=$VORTEX_RDF_VERSION" \
    --build-arg "RDFLIB_VERSION=$RDFLIB_VERSION" \
    --build-arg "RUST_VERSION=$RUST_VERSION" \
    --build-arg "MATURIN_VERSION=$MATURIN_VERSION" \
    --tag "$IMAGE" \
    "$CONTEXT"
