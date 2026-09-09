#!/usr/bin/env python3
"""Persistent JSONL SPARQL worker for optimized rdflib-hdt."""
from __future__ import annotations
import contextlib
import json
import os
import sys
import traceback
from pathlib import Path
from rdflib_hdt import HDTStore, optimize_sparql
from rdflib import BNode, Graph, Literal, URIRef

# Keep one duplicate of the original stdout pipe for JSONL protocol output.
# Query diagnostics are redirected at the file-descriptor boundary.
PROTOCOL = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)


@contextlib.contextmanager
def query_diagnostics_to_stderr():
    """Reserve stdout for JSONL even when dependencies print diagnostics."""
    sys.stdout.flush()
    saved_stdout = os.dup(sys.stdout.fileno())
    try:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved_stdout, sys.stdout.fileno())
        os.close(saved_stdout)


def emit(value):
    PROTOCOL.write(json.dumps(value, separators=(",", ":")) + "\n")
    PROTOCOL.flush()


def term(value):
    if value is None:
        return None
    if isinstance(value, URIRef):
        return {"type": "uri", "value": str(value)}
    if isinstance(value, BNode):
        return {"type": "bnode", "value": str(value)}
    if isinstance(value, Literal):
        return {"type": "literal", "value": str(value),
                "language": value.language or None,
                "datatype": str(value.datatype) if value.datatype else None}
    raise TypeError(f"unsupported RDF term class: {type(value).__name__}")


def document(result):
    kind = str(getattr(result, "type", "")).upper()
    if kind == "ASK":
        return {"kind": "ask", "boolean": bool(result.askAnswer)}
    if kind in {"CONSTRUCT", "DESCRIBE"}:
        return {"kind": "graph", "triples": [
            [term(s), term(p), term(o)] for s, p, o in result.graph
        ]}
    variables = [str(value) for value in result.vars]
    rows = []
    for row in result:
        rows.append({name: term(row[index]) for index, name in enumerate(variables)
                     if row[index] is not None})
    return {"kind": "select", "variables": variables, "rows": rows}


def main():
    if len(sys.argv) != 2:
        raise SystemExit("one absolute dataset.hdt path is required")
    artifact = Path(sys.argv[1]).resolve()
    index = Path(str(artifact) + ".index.v1-1")
    if artifact.name != "dataset.hdt" or not artifact.is_file() or not index.is_file():
        raise RuntimeError("query-ready HDT pair is missing or has invalid basenames")
    optimize_sparql()
    store = HDTStore(str(artifact), mapped=False, indexed=True, safe_mode=True)
    graph = Graph(store=store)
    emit({"kind":"ready","protocol":"jsonl-v1","source_open":True,
        "source_type":"hdt-rdflib","source_boundary":"rdflib-hdt-optimized-bgp",
        "source_reference":str(artifact),"mapped":False,"indexed":True,
        "safe_mode":True,"optimize_sparql_calls":1})
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if request.get("kind") == "shutdown":
                emit({"kind":"stopped"})
                return
            request_id = request.get("request_id")
            try:
                with query_diagnostics_to_stderr():
                    result = graph.query(request["query"])
                    result_document = document(result)
                emit({"kind":"result","request_id":request_id,
                      "status":"ok","document":result_document})
            except BaseException as error:
                emit({"kind":"result","request_id":request_id,
                      "status":"error","error_type":type(error).__name__,
                      "error_message":str(error)})
    finally:
        graph.close()

if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc(file=sys.stderr)
        raise
