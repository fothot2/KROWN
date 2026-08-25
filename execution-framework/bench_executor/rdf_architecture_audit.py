#!/usr/bin/env python3
"""Audit generic RDF resource composition across KROWN scenarios."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GENERIC_RESOURCES = (
    'RdfManifestResource', 'ExternalRdfDatasetResource',
    'RdfQueryResource', 'RdfBaselineResource',
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'JSON root must be an object: {path}')
    return value


def audit_repository(root: Path, benchmarks_root: Path) -> dict[str, Any]:
    """Return a cross-repository report or raise on an architecture drift."""
    root = root.resolve()
    benchmarks_root = benchmarks_root.resolve()
    scenarios = {
        'dbbench': root / 'benchmark-integration/dbbench-manifest/metadata.json',
        'bsbm': root / 'benchmark-integration/bsbm-smoke/metadata.json',
    }
    metadata = {name: _load(path) for name, path in scenarios.items()}

    expected = set(GENERIC_RESOURCES)
    bsbm_resources = [step['resource'] for step in metadata['bsbm']['steps']]
    if bsbm_resources != list(GENERIC_RESOURCES):
        raise ValueError('BSBM must compose the four generic RDF resources in order')

    dbbench_resources = {step['resource'] for step in metadata['dbbench']['steps']}
    required_dbbench = {
        'ExternalRdfDatasetResource', 'RdfQueryResource', 'RdfBaselineResource',
    }
    if not required_dbbench.issubset(dbbench_resources):
        raise ValueError('DBBench misses generic staging, query, or baseline resources')
    if 'DBBenchQueryResource' in dbbench_resources or 'DBBenchBaselineResource' in dbbench_resources:
        raise ValueError('DBBench still uses a benchmark-specific execution resource')

    for name, document in metadata.items():
        for step in document['steps']:
            resource = step['resource']
            if resource in {'RdfQueryResource', 'RdfBaselineResource'} and resource not in expected:
                raise ValueError(f'{name} uses an unknown RDF resource: {resource}')
            lowered = resource.lower()
            if 'generator' in lowered or 'download' in lowered:
                raise ValueError(f'{name} embeds generation or download in KROWN')

    bsbm = metadata['bsbm']['steps']
    staged = bsbm[1]['parameters']['destination_file']
    if bsbm[2]['parameters']['dataset_file'] != staged or bsbm[3]['parameters']['dataset_file'] != staged:
        raise ValueError('BSBM stage, execute, and validate paths differ')
    if bsbm[2]['parameters']['large_workload_env'] != 'KROWN_RDF_ALLOW_LARGE_WORKLOAD':
        raise ValueError('BSBM does not use the neutral large-workload guard')

    dbbench_execute = next(step for step in metadata['dbbench']['steps']
                           if step['resource'] == 'RdfQueryResource')
    if dbbench_execute['parameters']['large_workload_env'] != 'KROWN_RDF_ALLOW_LARGE_WORKLOAD':
        raise ValueError('DBBench does not use the neutral large-workload guard')

    for relative in (
        'execution-framework/bench_executor/rdf_workload_contract.py',
        'execution-framework/bench_executor/rdf_manifest_resource.py',
        'execution-framework/bench_executor/external_rdf_dataset_resource.py',
        'execution-framework/bench_executor/rdf_query_resource.py',
        'execution-framework/bench_executor/rdf_baseline_resource.py',
    ):
        if not (root / relative).is_file():
            raise ValueError(f'Missing generic KROWN resource: {relative}')

    for relative in (
        'benchmark_core/manifest.py', 'benchmark_core/result.py',
        'benchmark_core/rdf_execution.py', 'DBBench/manifest.py', 'BSBM/manifest.py',
    ):
        if not (benchmarks_root / relative).is_file():
            raise ValueError(f'Missing benchmark-side contract: {relative}')

    baselines = {
        'dbbench': _load(root / 'benchmark-integration/dbbench-manifest/data/shared/dbbench/dbpedia-10m-baseline.json'),
        'bsbm': _load(root / 'benchmark-integration/bsbm-smoke/data/shared/bsbm/explore-1k-baseline.json'),
    }
    if any(value.get('schema') != 'rdf-query-baseline-v1' for value in baselines.values()):
        raise ValueError('All semantic baselines must use rdf-query-baseline-v1')

    return {
        'schema': 'krown-rdf-architecture-audit-v1',
        'repository_role': 'orchestration-measurement-validation',
        'benchmarks': ['dbbench', 'bsbm'],
        'generic_resources': list(GENERIC_RESOURCES),
        'shared_baseline_schema': 'rdf-query-baseline-v1',
        'large_workload_env': 'KROWN_RDF_ALLOW_LARGE_WORKLOAD',
        'generation_inside_krown': False,
    }
