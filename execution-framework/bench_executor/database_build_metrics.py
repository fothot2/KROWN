#!/usr/bin/env python3
"""Build metrics and stable size measurement for persistent RDF databases."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any


def build_metrics_from_phase(
    elapsed_ns: int,
    memory_metrics: dict[str, Any],
    phase: str,
    *,
    status: str = 'ok',
    returncode: int | None = 0,
) -> dict[str, Any]:
    """Create one build record from one isolated container-memory phase."""
    if not isinstance(elapsed_ns, int) or isinstance(elapsed_ns, bool) or elapsed_ns < 0:
        raise ValueError('elapsed_ns must be a non-negative integer')
    if status not in {'ok', 'failed'}:
        raise ValueError("status must be 'ok' or 'failed'")
    if not isinstance(memory_metrics, dict):
        raise TypeError('memory_metrics must be a dictionary')
    phases = memory_metrics.get('phases')
    if not isinstance(phases, dict) or phase not in phases:
        raise ValueError(f'memory phase is missing: {phase}')
    phase_metrics = phases[phase]
    memory = {
        'scope': memory_metrics.get('scope'),
        'unit': memory_metrics.get('unit'),
        'sampling_interval_ms': memory_metrics.get('sampling_interval_ms'),
        'sample_errors': memory_metrics.get('sample_errors'),
        'sample_count': phase_metrics.get('sample_count'),
        'peak_rss_bytes': phase_metrics.get('peak_rss_bytes'),
    }
    return {
        'schema': 'rdf-representation-build-metrics-v1',
        'status': status,
        'clock': 'perf_counter_ns',
        'elapsed_ns': elapsed_ns,
        'returncode': returncode,
        'memory': memory,
    }


def measure_persistent_paths(
    paths: Iterable[Path],
    *,
    excluded_names: Iterable[str] = (),
    excluded_prefixes: Iterable[str] = (),
    excluded_suffixes: Iterable[str] = (),
) -> dict[str, Any]:
    """Measure declared persistent paths without following symbolic links."""
    roots = tuple(Path(path).resolve() for path in paths)
    if not roots:
        raise ValueError('paths must not be empty')
    names = tuple(excluded_names)
    prefixes = tuple(excluded_prefixes)
    suffixes = tuple(excluded_suffixes)
    logical = allocated = files = directories = excluded_files = 0
    for root in roots:
        if not root.exists():
            raise FileNotFoundError(root)
        candidates = [root] if root.is_file() else [root, *sorted(root.rglob('*'))]
        for path in candidates:
            if path.is_symlink():
                raise ValueError(f'persistent path contains a symbolic link: {path}')
            info = path.stat(follow_symlinks=False)
            if path.is_file():
                if (
                    path.name in names
                    or (prefixes and path.name.startswith(prefixes))
                    or (suffixes and path.name.endswith(suffixes))
                ):
                    excluded_files += 1
                    continue
                files += 1
                logical += info.st_size
                allocated += info.st_blocks * 512
            elif path.is_dir():
                directories += 1
            else:
                raise ValueError(f'unsupported persistent path entry: {path}')
    return {
        'schema': 'rdf-representation-size-v1',
        'boundary': 'adapter-declared-paths',
        'paths': [str(path) for path in roots],
        'exclusion_policy': {
            'kind': 'filename-rules',
            'names': list(names),
            'prefixes': list(prefixes),
            'suffixes': list(suffixes),
            'excluded_file_count': excluded_files,
        },
        'logical_bytes': logical,
        'allocated_bytes': allocated,
        'file_count': files,
        'directory_count': directories,
    }
