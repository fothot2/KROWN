# Query quarantine evidence workflow

Use three fixed files.

1. **Evidence document**: Results from one completed matrix run.
2. **Ledger**: Evidence documents merged across runs.
3. **Snapshot**: Current skip decisions from one ledger and one policy.

## 1. Create one evidence document

```bash
python execution-framework/run_query_quarantine_ingestion.py \
  --summary path/to/summary.json \
  --archive path/to/results.tar.gz \
  --manifest path/to/manifest.json \
  --declaration path/to/declaration.json \
  --run-id run-001 \
  --system pycottas/default \
  --adapter-identity pycottas-1.1.0 \
  --artifact-identity bsbm/explore-10k/cottas/default \
  --created-at-utc 2026-09-09T17:00:00+00:00 \
  --summary-sha256 EXPECTED_SUMMARY_SHA256 \
  --archive-sha256 EXPECTED_ARCHIVE_SHA256 \
  --output evidence/run-001.json
```

Use `--exclusion-report` when a run has a separate validation report. The command rejects synthetic or instrumentation runs.

## 2. Build a ledger

```bash
python execution-framework/run_query_quarantine_ledger_build.py \
  --input evidence/run-001.json \
  --input evidence/run-002.json \
  --output ledgers/ledger.json \
  --created-at-utc 2026-09-09T18:00:00+00:00
```

A ledger is immutable. Create a new file when evidence changes.

## 3. Build a snapshot

```bash
python execution-framework/run_query_quarantine_snapshot_build.py \
  --ledger ledgers/ledger.json \
  --policy policies/quarantine-policy.json \
  --output snapshots/snapshot.json \
  --created-at-utc 2026-09-09T18:05:00+00:00
```

A snapshot is immutable. It contains current quarantine decisions.

## 4. Run experiments

Use the snapshot with the matrix runtime options documented in `QUERY_QUARANTINE_RUNTIME.md`.

## Rules

- Never overwrite evidence documents, ledgers, or snapshots.
- Never use synthetic validation runs as evidence.
- A timeout must be explicit in the result record.
- OOM means a confirmed process crash from memory exhaustion.
- A large file or high memory use is not OOM.
