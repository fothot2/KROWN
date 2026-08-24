#!/usr/bin/env python3
"""Keep the DBBench query resource as a compatibility wrapper."""
from __future__ import annotations

from bench_executor.rdf_query_resource import (
    RdfQueryResource, _require_full_workload_opt_in,
)


class DBBenchQueryResource(RdfQueryResource):
    """Apply DBBench defaults to the generic RDF query resource."""

    def execute(self, manifest_file: str, dataset_file: str,
                results_file: str, experiment_id: str,
                warmup_runs: int = 1, measured_runs: int = 5,
                timeout_s: float = 60.0, resume: bool = False,
                benchmark_command: str = 'vortex-rdf-bench',
                benchmark_root: str | None = None,
                max_query_count: int = 100,
                allow_full_env: str = 'KROWN_DBBENCH_ALLOW_FULL') -> bool:
        return super().execute(
            manifest_file=manifest_file,
            dataset_file=dataset_file,
            results_file=results_file,
            experiment_id=experiment_id,
            warmup_runs=warmup_runs,
            measured_runs=measured_runs,
            timeout_s=timeout_s,
            resume=resume,
            benchmark_command=benchmark_command,
            benchmark_root=benchmark_root,
            max_query_count=max_query_count,
            allow_full_env=allow_full_env,
            benchmark='dbbench',
            system='rdflib',
        )
