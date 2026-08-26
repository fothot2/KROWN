ARG RUST_VERSION=1.96.1
FROM rust:${RUST_VERSION}-bookworm AS builder
ARG VORTEX_RDF_COMMIT
ARG MATURIN_VERSION=1.14.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-dev \
        python3-pip \
        patchelf \
        git \
        build-essential \
        clang \
        libclang-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install \
        --break-system-packages \
        --no-cache-dir \
        maturin==${MATURIN_VERSION}
WORKDIR /source
COPY . .
LABEL org.opencontainers.image.revision=${VORTEX_RDF_COMMIT}

RUN cd python \
    && maturin build \
        --release \
        --locked \
        --interpreter python3 \
        --out /wheels

FROM python:3.11-slim-bookworm
ARG VORTEX_RDF_VERSION=0.1.0
ARG RDFLIB_VERSION=7.6.0
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl "rdflib==${RDFLIB_VERSION}" "psutil==7.0.0" \
    && python -c 'from importlib.metadata import version; assert version("vortex-rdflib")=="0.1.0"; assert version("rdflib")=="7.6.0"'
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work
ENTRYPOINT []
CMD ["python", "-c", "from vortex_rdflib import VortexStore; print('vortex-rdflib-ready')"]
