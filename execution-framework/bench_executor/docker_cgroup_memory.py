#!/usr/bin/env python3
"""Read current Docker container memory from the Linux cgroup v2 hierarchy."""
from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

_CGROUP_ROOT = Path('/sys/fs/cgroup')
_PROC_ROOT = Path('/proc')


def _container_pid(container: str) -> int | None:
    """Return the live host PID for one container name or ID."""
    if not isinstance(container, str) or not container.strip():
        raise ValueError('container must be a non-empty string')
    result = subprocess.run(
        ['docker', 'container', 'inspect', '--format', '{{.State.Pid}}', container],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value.isdigit():
        raise RuntimeError('Docker returned an invalid container PID')
    pid = int(value)
    return pid if pid > 0 else None


def _unified_cgroup_path(pid: int, proc_root: Path = _PROC_ROOT) -> PurePosixPath:
    """Return the unified cgroup v2 path for one live host process."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError('pid must be a positive integer')
    lines = (proc_root / str(pid) / 'cgroup').read_text(encoding='utf-8').splitlines()
    matches = [line.split(':', 2)[2] for line in lines if line.startswith('0::')]
    if len(matches) != 1:
        raise RuntimeError('process has no unique cgroup v2 membership')
    path = PurePosixPath(matches[0])
    if not path.is_absolute() or '..' in path.parts:
        raise RuntimeError('process cgroup path is invalid')
    return path


def container_memory_current_bytes(
    container: str,
    *,
    cgroup_root: Path = _CGROUP_ROOT,
    proc_root: Path = _PROC_ROOT,
) -> int | None:
    """Return current charged cgroup memory for one running container."""
    pid = _container_pid(container)
    if pid is None:
        return None
    relative = _unified_cgroup_path(pid, proc_root).relative_to('/')
    memory_file = cgroup_root / relative / 'memory.current'
    value = memory_file.read_text(encoding='ascii').strip()
    if not value.isdigit():
        raise RuntimeError('memory.current is not a non-negative integer')
    return int(value)
