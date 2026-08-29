# RDF benchmark execution architecture

KROWN orchestrates RDF benchmark experiments. It does not own benchmark semantics.

## Responsibility boundary

### External benchmark tools

External tools generate datasets and native workload inputs. Their outputs stay outside KROWN. The separate benchmarks repository documents the required local placement and keeps generated assets under ignored `data/` directories.

### Benchmarks repository

Benchmark adapters own input discovery, native-format validation, query identity, and conversion to the common RDF workload manifest. The shared execution runner owns the JSONL result contract and provenance fields.

### KROWN

KROWN owns orchestration, measurement, external dataset staging, artifact collection, large-workload protection, and semantic baseline validation. Its RDF resources are benchmark-neutral:

1. `RdfManifestResource` invokes a benchmark adapter.
2. `ExternalRdfDatasetResource` stages an external RDF dataset.
3. `RdfQueryResource` executes the common manifest.
4. `RdfBaselineResource` validates semantic results and provenance.

DBBench uses a compatibility manifest resource for its canonical inventory, but it uses the same generic staging, query, and baseline resources. BSBM composes all four generic resources directly.

## Enforced invariants

The cross-repository audit checks resource composition, shared baseline schemas, neutral workload protection, stage and consumer path consistency, benchmark-side contracts, and the absence of generator or download steps in these KROWN scenarios.

Run the focused audit with:

```bash
python execution-framework/tests/unit_tests \
  UnitTests.test_cross_benchmark_rdf_architecture_audit \
  -v
```
## Experiment matrix and comparison

`RdfExperimentMatrixResource` executes an external benchmark-owned experiment
declaration. It publishes compact result archives. Separate matrix runs can
publish separate archives for different system groups.

`RdfCrossSystemComparisonResource` is a downstream consumer. It combines two or
more compact archives and publishes one atomic comparison report. It does not
execute queries and it does not change matrix results.

KROWN owns the generic comparison implementation and workflow resource. The
benchmark repository owns query selection and optional limitation policy. A
policy can classify an exact observed failure as a deferred limitation. KROWN
must not hard-code benchmark names, query IDs, or system exceptions.

The workload manifest controls comparison semantics. Strict query modes compare
result counts and fingerprints. `DESCRIBE` remains implementation-defined.
Runtime archives, policies for temporary local limitations, and generated
comparison reports remain outside tracked KROWN source.
