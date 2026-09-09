# Controlled runtime activation

An activation plan runs one matrix with one fixed snapshot.

- The ledger stores past query results.
- The snapshot stores current skip decisions.
- The activation plan tells KROWN which snapshot to use now.

Validate without an engine:

```bash
python execution-framework/run_query_quarantine_activation.py --plan activation.json --root /workflow/root --dry-run
```

Run the matrix:

```bash
python execution-framework/run_query_quarantine_activation.py --plan activation.json --root /workflow/root
```

The plan declares the scenario, systems, snapshot, probe policy, completed-run count, matrix run ID, output files, and expected counts. The command verifies the published summary. It removes new outputs if validation fails.
