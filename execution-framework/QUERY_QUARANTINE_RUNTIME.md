# Query quarantine runtime setup

This guide lists the supported experiment modes for query quarantine and probes.
All file arguments are paths relative to the selected scenario's `data/shared`
directory.

## 1. Normal experiment

Use no quarantine arguments. Manual skips from the experiment declaration still
apply.

```bash
python execution-framework/run_rdf_experiment_matrix.py \
  --scenario benchmark-integration/bsbm-10k \
  --declaration /users/u0182905/benchmarks/BSBM/experiments/explore-10k-smoke.json \
  --manifest manifests/bsbm.json \
  --system pycottas/default \
  --results results/summary.json \
  --output results/results.tar.gz \
  --failure-results results/failure-summary.json \
  --failure-output results/failure-results.tar.gz
```

## 2. Force all queries to run

Add `--force-include`. This bypasses manual skips, automatic quarantine skips,
and scheduled probes. The summary still records that force-include was active
when runtime orchestration inputs are present.

```bash
... --force-include
```

## 3. Automatic quarantine only

Place a validated immutable snapshot under `data/shared`. Add only
`--quarantine-snapshot`. Quarantined queries are skipped. No probes are
scheduled.

```bash
... \
  --quarantine-snapshot quarantine/snapshot.json
```

## 4. Automatic quarantine with a non-due probe policy

Place the snapshot and probe policy under `data/shared`. Supply all four runtime
inputs. If the completed compatible-run count is not a policy interval, no probe
runs. Automatic quarantine still applies.

```bash
... \
  --quarantine-snapshot quarantine/snapshot.json \
  --quarantine-probe-policy quarantine/probe-policy.json \
  --completed-compatible-runs 19 \
  --matrix-run-id bsbm-cottas-20260909T160000Z
```

## 5. Automatic quarantine with a due probe

Use a completed compatible-run count that is an exact policy interval. For a
policy with an interval of 10, counts 10, 20, and 30 are due. The scheduler
selects at most one quarantined query per binding.

```bash
... \
  --quarantine-snapshot quarantine/snapshot.json \
  --quarantine-probe-policy quarantine/probe-policy.json \
  --completed-compatible-runs 20 \
  --matrix-run-id bsbm-cottas-20260909T160000Z
```

The execution precedence is:

```text
--force-include
scheduled quarantine probe
manual query-flavour skip
automatic quarantine
normal execution
```

## 6. Snapshot and probe inputs with force-include

This mode validates and records the supplied runtime inputs, but executes every
query. It does not mark a query as a probe.

```bash
... \
  --quarantine-snapshot quarantine/snapshot.json \
  --quarantine-probe-policy quarantine/probe-policy.json \
  --completed-compatible-runs 20 \
  --matrix-run-id bsbm-cottas-20260909T160000Z \
  --force-include
```

## Probe policy format

```json
{
  "schema": "rdf-query-quarantine-probe-policy-v1",
  "policy_id": "probe-every-10-compatible-runs-v1",
  "probe_every_completed_compatible_runs": 10,
  "maximum_probes_per_binding": 1
}
```

## Required combinations

Valid combinations:

```text
no runtime arguments
snapshot only
snapshot + probe policy + completed count + matrix run ID
snapshot + probe policy + completed count + matrix run ID + force-include
```

Invalid combinations:

```text
probe policy without snapshot
probe policy without completed count
probe policy without matrix run ID
completed count without probe policy
negative completed count
absolute paths or paths that leave data/shared
```

## Evidence boundary

The completed compatible-run count is an explicit orchestration input. KROWN
does not derive it from directory names or artifact counts. A scheduled probe is
execution intent only. Only a final preserved result can become evidence in a
later immutable evidence-ledger build.
