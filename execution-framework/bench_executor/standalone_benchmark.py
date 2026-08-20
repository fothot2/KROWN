"""Shared adapter utilities for standalone benchmark CLI resources."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def resolve_shared_path(shared: str, declared: str, kind: str) -> Path:
    """Resolve one relative path and keep it inside data/shared."""
    if not isinstance(declared, str) or not declared:
        raise ValueError(f'{kind} path must be a non-empty string')
    if os.path.isabs(declared):
        raise ValueError(f'{kind} path must be relative')
    shared_path = Path(shared).resolve()
    path = (shared_path / declared).resolve()
    if os.path.commonpath((str(shared_path), str(path))) != str(shared_path):
        raise ValueError(
            f'{kind} path leaves the shared directory: {declared}'
        )
    return path


def input_file(shared: str, declared: str) -> Path:
    """Resolve one existing input file inside data/shared."""
    path = resolve_shared_path(shared, declared, 'Input')
    if not path.is_file():
        raise FileNotFoundError(
            f'Input is not an existing file: {declared}'
        )
    return path


def input_directory(shared: str, declared: str) -> Path:
    """Resolve one existing input directory inside data/shared."""
    path = resolve_shared_path(shared, declared, 'Input')
    if not path.is_dir():
        raise FileNotFoundError(
            f'Input is not an existing directory: {declared}'
        )
    return path


def standalone_command(
        benchmark_command: str,
        benchmark_root: str | None) -> tuple[list[str], dict[str, str]]:
    """Resolve an installed CLI or one development checkout."""
    environment = os.environ.copy()
    if benchmark_root is not None:
        root = Path(benchmark_root).resolve()
        if not (root / 'benchmark_core/cli.py').is_file():
            raise FileNotFoundError(
                f'benchmark_root does not contain benchmark_core: {root}'
            )
        current = environment.get('PYTHONPATH')
        environment['PYTHONPATH'] = (
            str(root) if not current
            else str(root) + os.pathsep + current
        )
        return [sys.executable, '-m', 'benchmark_core.cli'], environment
    executable = shutil.which(benchmark_command)
    if executable is None:
        raise FileNotFoundError(
            f'Benchmark command not found: {benchmark_command}; '
            'install the benchmarks package or provide benchmark_root'
        )
    return [executable], environment



def temporary_output(final: Path, seed: bool = False) -> Path:
    """Create one private sibling path for validated output."""
    import tempfile
    final.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f'.{final.name}.', suffix='.tmp', dir=final.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    if seed and final.is_file():
        shutil.copyfile(final, temporary)
    else:
        temporary.unlink()
    return temporary


def commit_output(temporary: Path, final: Path) -> None:
    """Replace the declared artifact with a validated sibling."""
    if not temporary.is_file():
        raise FileNotFoundError(
            f'Validated temporary output does not exist: {temporary}'
        )
    os.replace(temporary, final)


def discard_output(temporary: Path | None) -> None:
    """Remove an incomplete temporary artifact if it exists."""
    if temporary is not None:
        temporary.unlink(missing_ok=True)
