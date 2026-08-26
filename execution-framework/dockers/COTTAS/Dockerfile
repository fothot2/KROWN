FROM python:3.12-slim-bookworm
ARG PYCOTTAS_VERSION=1.1.0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt && python -c 'from importlib.metadata import version; assert version("pycottas")=="1.1.0"; assert version("rdflib")=="7.6.0"'
WORKDIR /work
ENTRYPOINT []
CMD ["python","-m","pycottas","--help"]
