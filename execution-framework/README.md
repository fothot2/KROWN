# KROWN 👑's execution framework

KROWN's execution framework is a simple framework to **execute benchmarks
on systems which are running in Docker**, exposed a CLI interface `exectool`.

Any benchmark pipeline can be constructed as a list of steps in which a resource
performs a certain task e.g. loading a relational database, executing a system,
etc. Each task may have zero or multiple parameters to specify information such
as the location of the data or the mapping to execute. Each pipeline is stored
in a JSON file `metadata.json` which is automatically discovered from the root
folder (`--root` CLI argument). Each resource is executed as a Docker container
which makes incorporating the resource straightforward into the framework.
Thanks to these pipelines, we can **share the experiment setup easily**
without requiring additional setup.

KROWN's execution framework **automatically executes the pipeline several times**
(`--runs` CLI argument) to avoid outliers when **collecting metrics measurements**
e.g. execution time, CPU time, memory consumption, storage usage, etc.
By collecting these metrics automatically, we ease the reproducibility of the
experiments as the metrics are collected in the same way.

After execution, **statistics can be calculated automatically** using the `stats`
command. All runs will then be combined to calculate median, average, min/max,
standard deviation per metrics and summarize all measurements per step to use
the **measurements immediately for analysis**. This way, we avoid ad-hoc scripts
that are hard to re-use in different environments and experiment setups.

## How to use?

You can list all options and arguments with `--help`

```
usage: exectool [-h] [--version] [--root MAIN_DIRECTORY] [--runs NUMBER_OF_RUNS] [--interval INTERVAL] [--verbose] [--wait-for-user]
                command

Copyright by (c) Dylan Van Assche (2022-2024), available under the MIT license

positional arguments:
  command               Command to execute, available commands: "list", "run", "clean", "stats", "download-challenge-2023"

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --root MAIN_DIRECTORY
                        Root directory of all scenarios to execute, defaults to the current working directory
  --runs NUMBER_OF_RUNS
                        Number of runs to execute a scenario. The value must be uneven for generating stats. Default 3 runs
  --interval INTERVAL   Measurement sample interval for metrics, default 0.1s
  --verbose             Turn on verbose output
  --wait-for-user       Show a prompt when a step is executed before going to the next one
```

### Generating scenarios

Each scenario you want to execute expects the following structure:

```
/path/to/my/scenario
├── data
│   └── shared
│       ├── file1
│       ├── file2
│       └── file3
└── metadata.json
```

Data shared among resources should be stored under the `./data/shared` folder
of the scenario, the steps to execute should be stored in `./metadata.json`.

The steps are described as followed:

```
{
    "@id": "http://example.com/scenario/ID", # Unique IRI for your scenario
    "name": "Case X: Apple: Pie", # Readable name for your scenario
    "description": "Bananas", # Readable description for your scenario
    "steps": [
        {
            "@id": "http://example.com/scenario/ID#step1", # Unique IRI for your step
            "name": "My Step Description", # Readable name of your step
            "resource": "$RESOURCE", # Name of resource to execute, matching $RESOURCE.py
            "command": "$METHOD", # Method to execute of the resource, defined in $RESOURCE.py
            "parameters": { # Parameters to supply with the method to execute, defined in $RESOURCE.py
                "param1": "MyParameter",
                "param2": 5
            }
        },
        ... # Infinite number of steps allowed
    ]
}
```

Real examples can be found under [bench_executor/data/test-cases/](bench_executor/data/test-cases/).

### Listing all scenarios

You can list all scenarios from a certain root folder with:

```
exectool list
```

By default, the root directory is set to the current working directory.
If you want to set a different one, use the `--root` argument:

```
exectool list --root=/path/to/your/scenarios
```

### Running all scenarios

Running all scenarios under a root directory is similar to listing them:

```
exectool run
```

If you want to specify the number of runs, metrics collection interval, 
and the root directory:

```
exectool list --root=/path/to/your/scenarios --runs=5 --interval 1.0
```

This will execute all scenarios at `/path/to/your/scenarios`,
each scenario will be executed 5 times,
and the metrics will be collected every `1.0` seconds.

#### Additional features

If you want to pause the execution of your scenario after each step,
you can add the `--wait-for-user` argument when running the scenarios:

```
exectool run --wait-for-user
```

This way, you can debug resources when they are not working properly or testing
your setup.

### Cleaning all scenarios

Sometimes you want to start from a clean slate, you can clean all scenarios under 
the given root directory with:

```
exectool clean
```

All collected metrics and log files will be deleted, be careful!

### Calculate statistics

After execution, you can automatically calculate statistics across multiple
runs e.g. median, average, min/max, standard deviation for each measured
metric. Moreover, the metrics will also be summarized per step so you can
immediately see how long a step took, how much computing resources
were consumed during this step, etc.

```
exectool stats --root=/path/to/your/scenarios
```

### Docker containers

All supported systems have their own Docker container which is available
in the [dockers](./dockers) folder. For each system a directory is provided
with a `Dockerfile` and a script to build and push all images is available
as well (`build-all.sh`).

Currently, the following Dockers are officially supported:

**Materialization systems**

- Morph-KGC 2.2.0
- OntopM (Ontop in materialization mode) 5.0.0
- RMLMapper 6.0.0
- RMLStreamer 2.5.0
- SDM-RDFizer 4.6.6.5

**Relational databases**

- MySQL 8.0
- PostgreSQL 14.5

**Triplestores**

- Fuseki 4.6.1
- Virtuoso 7.2.7

**Tools**

- YARRRML parser/generator 1.3.6

### Knowledge Graph Construction Challenge

The Knowledge Graph Construction Challenge can be immediately downloaded
from Zenodo by the execution framework and be executed. This demonstrates
the shareability of our pipelines as the pipelines are generated upfront
by our data generator, uploaded to Zenodo and retrieved
by the execution framework for all participants in
the Knowledge Graph Construction Challenge.

**ESWC 2023 edition**

```
exectool download-challenge-2023
```

**ESWC 2024 edition**

*Coming Soon!*

You can find the execution framework for the ESWC 2024 edition
of Challenge [here](https://github.com/kg-construct/challenge-tool).
After ESWC 2024, support for downloading the new edition will be merged
into KROWN's execution framework.

## Current limitations

KROWN's execution framework has a lot of features and flexibility,
but some limitations still occur. The main limitations are:

1. Execution across multiple machines is unsupported (GitHub [Issue #1](https://github.com/kg-construct/KROWN/issues/1)).
You can only execute pipelines on one machine.
This would allow RMLStreamer to be benchmarked among multiple machines 
(`cluster` mode) instead of only on one machine (`standalone` mode).

2. Automatically execution of unittests
on each GitHub Pull Request (GitHub [Issue #2](https://github.com/kg-construct/KROWN/issues/2)).
This is currently not implemented yet in a Github CI/CD setup for KROWN's
execution framework because it requires running Docker containers
inside Docker containers.

3. Configuration files described as RDF (GitHub Issue [#3](https://github.com/kg-construct/KROWN/issues/3)) which would
allow querying the pipeline configurations using Semantic Web standards
e.g. SPARQL. The configuration files are already written in such a way that
they can be expanded with a JSON-LD context to overcome this limitation.

For a full list of missing features, limitations, etc.
see [GitHub Issues](https://github.com/kg-construct/KROWN/issues).
Issues related to the execution framework have a specific
label 'execution-framework'.

## Sustainability plan

KROWN's execution framework has been used widely among multiple editions
of the Knowledge Graph Construction Workshop Challenge 
and for benchmarking incremental mappings (IncRML, under review).
The community plans to keep developing KROWN's execution framework in the future
to add new features and solve the current limitations 
of KROWN's execution framework. The community is currently collecting more 
feedback from the Challenge participants of the 2024 edition to improve KROWN's
execution framework further for the next edition of the Challenge.

## Installation

**Ubuntu 22.04 LTS**

1. Install dependencies

```
sudo apt install zlib1g zlib1g-dev libpq-dev libjpeg-dev python3-pip docker.io
pip install --user -r requirements.txt
```

2. Configure Docker

```
# Add user to docker group
sudo groupadd docker
sudo usermod -aG docker $USER
```

Do not forget to logout so the user groups are properly updated!

3. Verify installation

Execute one of the unit tests:

```
cd tests
./unit_tests
```


## Standalone DBBench workflow

KROWN delegates DBBench query discovery, manifest preparation, and RDFLib execution to the public `vortex-rdf-bench` interface. KROWN owns scenario orchestration, external dataset staging, artifact collection, and baseline validation. This keeps benchmark semantics in the benchmarks package and keeps the KROWN resources thin.

The reference scenario is stored at:

```text
benchmark-integration/dbbench-manifest
```

It performs five steps:

1. Generate the canonical 3,642-query manifest.
2. Generate a deterministic six-query semantic smoke manifest.
3. Stage an external RDF dataset inside `data/shared`.
4. Execute the smoke manifest with RDFLib.
5. Validate the JSONL output against the committed DBpedia 10M baseline.

### Benchmark command mode

The default resources call an installed command:

```text
vortex-rdf-bench
```

For development, set the resource parameter `benchmark_root` to a benchmarks checkout. KROWN then invokes `python -m benchmark_core.cli` and extends `PYTHONPATH` for that process only.

### DBpedia 10M smoke run

The smoke baseline expects this dataset identity:

```text
logical name: dbpedia-10m
format: N-Triples
size: 1,642,607,409 bytes
SHA-256: 82684ef2080b2004a25066bed38292cf40d7da64dcd8130c5057ff15d9c5317a
```

Set the source dataset path through the environment. Do not copy the dataset into the repository.

```bash
KROWN_DBBENCH_DATASET=/path/to/dbpedia_10M.nt \
./execution-framework/exectool \
  --runs=1 \
  --root=/path/to/KROWN/benchmark-integration/dbbench-manifest \
  run
```

The scenario uses hard-link staging. The source and KROWN must therefore be on the same filesystem. Change the metadata staging mode to `copy` when a hard link is not possible. Copy mode can duplicate a large dataset, so use it explicitly.

The cleaner removes only the staged file and its private ownership marker. It does not remove the external source dataset.

### Semantic smoke baseline

The smoke selection contains six canonical queries:

- Three queries with observed non-empty results on the DBpedia 10M fragment.
- Three queries with intentional empty results.

The committed baseline checks:

- Dataset size and SHA-256.
- Manifest dataset, workload, query count, and SHA-256.
- Exact query IDs, phases, run numbers, statuses, counts, and fingerprints.
- Dataset and manifest provenance in every record.
- Duplicate execution keys.
- Three non-empty and three empty results.
- Four distinct result fingerprints.

Repeatability comparisons use semantic signatures. They ignore runtime-dependent fields such as `elapsed_ns`, `client_elapsed_ns`, and execution order.

### Full-workload guard

`DBBenchQueryResource` allows at most 100 queries by default. A larger manifest is rejected before RDFLib starts. To run the full 3,642-query manifest deliberately, set:

```bash
KROWN_DBBENCH_ALLOW_FULL=1
```

A full-run scenario must point `manifest_file` to `manifests/dbbench.json`. Keep explicit values for `timeout_s`, `warmup_runs`, and `measured_runs`. The existing reference scenario remains a six-query smoke run even when the environment variable is set.

### Artifacts and atomic output

`DBBenchQueryResource` is the sole owner of:

```text
raw/dbbench-smoke.jsonl
```

`DBBenchBaselineResource` consumes that path through `results_input_file`, so KROWN does not collect the same artifact twice. Successful artifacts are moved under:

```text
benchmark-integration/dbbench-manifest/results/run_N/
```

The query resource writes to a private sibling temporary file. It validates JSONL structure, the shared result contract, provenance, query IDs, record counts, and duplicate keys before atomically replacing the declared artifact. A command failure or validation failure preserves any existing final artifact and removes the temporary file.

### Common failures

- `Environment variable is not set: KROWN_DBBENCH_DATASET`: set the external dataset path.
- `External RDF dataset SHA-256 mismatch`: use the expected DBpedia 10M fragment or update the baseline deliberately.
- `Input path leaves the shared directory`: do not stage an external symbolic link. Use hard-link or copy mode.
- `DBBench manifest contains ... above the safe limit`: use the six-query smoke manifest, or set `KROWN_DBBENCH_ALLOW_FULL=1` for an intentional full run.
- `DBBench smoke semantic records differ from baseline`: the dataset, manifest, benchmark behavior, or expected baseline changed.
- `Artifact is not an existing file`: ensure only the producing resource uses a `results_file` or `output_file` parameter. Read-only consumers must use input-only parameter names.

### Focused validation

Run the DBBench regression tests from the repository root:

```bash
python execution-framework/tests/unit_tests \
  UnitTests.test_dbbench_query_resource_runs_public_cli \
  UnitTests.test_dbbench_query_resource_preserves_output_after_failures \
  UnitTests.test_dbbench_full_workload_guard_requires_explicit_opt_in \
  UnitTests.test_dbbench_semantic_signature_ignores_runtime_fields \
  UnitTests.test_external_rdf_dataset_resource_hardlinks_and_cleans \
  UnitTests.test_external_rdf_dataset_resource_rejects_hash_mismatch \
  -v
```

## Citation

See main [README](../README.md).

## License

Licensed under the [MIT license](./LICENSE)<br>
Written by Dylan Van Assche (dylan.vanassche@ugent.be)

### Generic RDF experiment configuration

RDF benchmark scenarios use benchmark-neutral environment variables:

- `KROWN_RDF_DATASET_FILE` selects the external RDF dataset file.
- `KROWN_RDF_ALLOW_LARGE_WORKLOAD=1` permits a workload above the configured query limit.

A benchmark scenario can override these parameter values explicitly. Benchmark adapters do not require benchmark-specific execution resources.

### BSBM adapter scenario

Generate BSBM outside KROWN. Store the ignored dataset, official Explore CSV stream, generation receipt, and test-driver data under the separate benchmarks repository. Set `KROWN_BSBM_QUERY_STREAM`, `KROWN_BSBM_GENERATION_RECEIPT`, and `KROWN_RDF_DATASET_FILE`. The smoke scenario imports the first measured instance of each BSBM query template. KROWN does not download, configure, or run the BSBM generator.
