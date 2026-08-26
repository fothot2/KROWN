FROM python:3.12-slim-bookworm
ARG RDFLIB_VERSION=7.6.0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN python -m pip install --no-cache-dir "rdflib==${RDFLIB_VERSION}" "psutil==7.0.0" \
 && python -c 'from importlib.metadata import version; assert version("rdflib")=="7.6.0"'
WORKDIR /work
ENTRYPOINT []
CMD ["python","-c","from rdflib import Graph; print(type(Graph().store).__name__)"]
