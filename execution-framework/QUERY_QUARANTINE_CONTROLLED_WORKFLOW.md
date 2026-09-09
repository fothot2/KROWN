# Controlled query quarantine workflow

The workflow uses one explicit plan.

```text
completed matrix files
  -> one evidence document per run
  -> one immutable ledger
  -> one immutable snapshot
  -> one audit report
```

- An **evidence document** stores query results from one run.
- A **ledger** stores evidence from many runs.
- A **snapshot** stores current skip decisions.
- An **audit report** lists all output hashes and counts.

Run:

```bash
python execution-framework/run_query_quarantine_workflow.py \
  --plan workflow.json \
  --root /absolute/workflow/root
```

The plan uses paths relative to `--root`. It includes every source hash, run ID, output path, ledger timestamp, policy path, and snapshot timestamp.

The workflow refuses existing outputs. If one stage fails, it removes all outputs that it created. It never removes source files.
