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
