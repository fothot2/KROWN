#!/usr/bin/env python3
"""Keep the DBBench baseline resource as a compatibility wrapper."""
from bench_executor.rdf_baseline_resource import (
    RdfBaselineResource, semantic_signature,
)


class DBBenchBaselineResource(RdfBaselineResource):
    """Use the generic RDF baseline validator for DBBench."""
