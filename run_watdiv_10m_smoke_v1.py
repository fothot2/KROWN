#!/usr/bin/env python3
"""Prepare and optionally execute the WatDiv 10M RDFLib smoke gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path('/users/u0182905/KROWN')
BENCHMARKS = Path('/users/u0182905/benchmarks')
SCENARIO = ROOT / 'benchmark-integration/watdiv-10m'
SHARED = SCENARIO / 'data/shared'
FULL_MANIFEST = SHARED / 'manifests/watdiv-10m-smoke.json'
GATE_MANIFEST = SHARED / 'manifests/watdiv-10m-rdflib-gate.json'
DECLARATION = BENCHMARKS / 'WatDiv/experiments/watdiv-10m-smoke.json'
MATRIX = ROOT / 'execution-framework/run_rdf_experiment_matrix.py'
PYTHON = Path('/users/u0182905/miniconda3/envs/vortex-rdf/bin/python')
EXPECTED_KROWN_HEAD = '629a907ef989f7bc19d66662737b64ff63045013'
EXPECTED_BENCHMARKS_HEAD = 'c273ecc48aebb01f6bda986b057b9fd0197511dc'
EXPECTED_DATASET_SIZE = 1542624409
EXPECTED_DATASET_SHA256 = '7cfe0341d578a677d3b5d562eaaf94d67aff8587d9e0ef3d83cc82765b77cddd'
EXPECTED_CATALOG_SHA256 = '67a59f1e00dfc39bb237a959e5fb671dde11b5bc908c7f8a63bc0bb81cbb603c'
STREAMS = ('warmup', 'test.1', 'test.2', 'test.3', 'test.4', 'test.5')
STARTUP_TIMEOUT_S = '900'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def git_head(root: Path) -> str:
    return subprocess.run(
        ['git', '-C', str(root), 'rev-parse', 'HEAD'],
        text=True, capture_output=True, check=True,
    ).stdout.strip()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n',
            encoding='utf-8',
        )
        json.loads(temporary.read_text(encoding='utf-8'))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_full_manifest(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    queries = value.get('queries')
    if value.get('dataset') != 'watdiv-10m':
        raise RuntimeError('manifest dataset is not watdiv-10m')
    if value.get('query_count') != 74400 or not isinstance(queries, list) or len(queries) != 74400:
        raise RuntimeError('manifest does not contain 74,400 query occurrences')
    if value.get('stream_order') != list(STREAMS):
        raise RuntimeError('manifest stream order differs from the frozen contract')
    catalog = value.get('catalog', {})
    if catalog.get('query_count') != 12400 or catalog.get('digest') != EXPECTED_CATALOG_SHA256:
        raise RuntimeError('manifest catalog identity differs from the frozen contract')
    for stream_index, stream_name in enumerate(STREAMS):
        start = stream_index * 12400
        block = queries[start:start + 12400]
        if len(block) != 12400:
            raise RuntimeError(f'incomplete stream block: {stream_name}')
        for position, query in enumerate(block):
            expected_phase = 'warmup' if stream_name == 'warmup' else 'measured'
            if query.get('stream') != stream_name or query.get('position') != position:
                raise RuntimeError(f'native order mismatch in {stream_name} at {position}')
            if query.get('phase') != expected_phase:
                raise RuntimeError(f'phase mismatch in {stream_name} at {position}')
            native_id = query.get('native_query_id')
            if not isinstance(native_id, int) or not 1 <= native_id <= 12400:
                raise RuntimeError(f'invalid native query ID in {stream_name} at {position}')
            text = query.get('query')
            declared = query.get('query_sha256')
            if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != declared:
                raise RuntimeError(f'query SHA-256 mismatch in {stream_name} at {position}')
        if sorted(item['native_query_id'] for item in block) != list(range(1, 12401)):
            raise RuntimeError(f'native IDs are not a permutation in {stream_name}')
    return value


def prepare_full_manifest() -> dict:
    if git_head(ROOT) != EXPECTED_KROWN_HEAD:
        raise RuntimeError('KROWN HEAD changed')
    if git_head(BENCHMARKS) != EXPECTED_BENCHMARKS_HEAD:
        raise RuntimeError('benchmarks HEAD changed')
    metadata = json.loads((SCENARIO / 'metadata.json').read_text(encoding='utf-8'))
    source = Path(metadata['source']['path'])
    if source.stat().st_size != EXPECTED_DATASET_SIZE:
        raise RuntimeError('WatDiv 10M source size changed')
    if metadata['source']['sha256'] != EXPECTED_DATASET_SHA256:
        raise RuntimeError('WatDiv 10M metadata SHA-256 changed')
    FULL_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    temporary = FULL_MANIFEST.with_name(f'.{FULL_MANIFEST.name}.prepare.tmp')
    temporary.unlink(missing_ok=True)
    environment = dict(os.environ)
    environment['PYTHONPATH'] = str(BENCHMARKS) + (
        os.pathsep + environment['PYTHONPATH'] if environment.get('PYTHONPATH') else ''
    )
    command = [
        str(PYTHON), '-m', 'benchmark_core.cli', 'watdiv', 'prepare',
        '--dataset', 'watdiv-10m', '--output', str(temporary),
    ]
    completed = subprocess.run(
        command, cwd=BENCHMARKS, env=environment,
        text=True, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    value = validate_full_manifest(temporary)
    os.replace(temporary, FULL_MANIFEST)
    return value


def _gate_query(source: dict, stream_position: int) -> dict:
    """Project one benchmark occurrence into the KROWN query contract."""
    phase = source['phase']
    projected = {
        key: value for key, value in source.items()
        if key not in {'benchmark', 'dataset', 'workload', 'phase', 'position'}
    }
    projected['stream_phase'] = phase
    projected['stream_position'] = stream_position
    return projected


def build_gate_manifest(full: dict) -> dict:
    queries = full['queries']
    selected = [
        _gate_query(queries[index * 12400], index)
        for index in range(len(STREAMS))
    ]
    gate = {
        key: value for key, value in full.items()
        if key not in {'queries', 'query_count', 'catalog'}
    }
    gate.update({
        'workload': 'watdiv-stress-100-rdflib-gate',
        'query_count': len(selected),
        'gate_selection': {
            'schema': 'watdiv-krown-smoke-gate-v1',
            'rule': 'first physical occurrence from each frozen stream',
            'source_manifest_sha256': sha256(FULL_MANIFEST),
            'source_query_count': 74400,
        },
        'queries': selected,
    })
    atomic_json(GATE_MANIFEST, gate)
    return gate


def execute_gate() -> int:
    results = 'raw/watdiv-10m-rdflib-gate-summary.json'
    output = 'raw/watdiv-10m-rdflib-gate-results.tar.gz'
    failed_results = 'raw/watdiv-10m-rdflib-gate-failed-summary.json'
    failed_output = 'raw/watdiv-10m-rdflib-gate-failed-results.tar.gz'
    command = [
        str(PYTHON), str(MATRIX), '--scenario', str(SCENARIO),
        '--declaration', str(DECLARATION), '--benchmark-root', str(BENCHMARKS / 'WatDiv'),
        '--manifest', 'manifests/watdiv-10m-rdflib-gate.json',
        '--system', 'rdflib/default', '--results', results, '--output', output,
        '--failure-results', failed_results, '--failure-output', failed_output,
    ]
    environment = dict(os.environ)
    environment.setdefault('RUST_LOG', 'vortex_rdf_cli=debug,vortex_rdf_core=debug')
    environment.setdefault('KROWN_RDFLIB_STARTUP_TIMEOUT_S', STARTUP_TIMEOUT_S)
    print(
        f'RDFLib startup timeout: {environment["KROWN_RDFLIB_STARTUP_TIMEOUT_S"]}s',
        flush=True,
    )
    print(' '.join(command), flush=True)
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--execute-gate', action='store_true')
    arguments = parser.parse_args(argv)
    if arguments.prepare_only and arguments.execute_gate:
        parser.error('--prepare-only and --execute-gate are mutually exclusive')
    return arguments


def main() -> int:
    args = parse_args()
    full = prepare_full_manifest()
    gate = build_gate_manifest(full)
    print(f'WATDIV 10M MANIFEST READY queries={len(full["queries"])} path={FULL_MANIFEST}')
    print(f'WATDIV RDFLIB GATE READY queries={len(gate["queries"])} path={GATE_MANIFEST}')
    if args.prepare_only or not args.execute_gate:
        return 0
    return execute_gate()


if __name__ == '__main__':
    raise SystemExit(main())
