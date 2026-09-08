#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.docker_cgroup_memory import (
    _container_pid,
    _unified_cgroup_path,
    container_memory_current_bytes,
)


class DockerCgroupMemoryTests(unittest.TestCase):
    def test_container_pid_returns_live_pid(self):
        result = SimpleNamespace(returncode=0, stdout='123\n')
        with patch(
            'bench_executor.docker_cgroup_memory.subprocess.run',
            return_value=result,
        ) as run:
            self.assertEqual(_container_pid('container-name'), 123)
        run.assert_called_once_with(
            [
                'docker', 'container', 'inspect', '--format',
                '{{.State.Pid}}', 'container-name',
            ],
            text=True,
            stdout=-1,
            stderr=-3,
            check=False,
        )

    def test_container_pid_returns_none_when_absent_or_stopped(self):
        with patch(
            'bench_executor.docker_cgroup_memory.subprocess.run',
            return_value=SimpleNamespace(returncode=1, stdout=''),
        ):
            self.assertIsNone(_container_pid('missing'))
        with patch(
            'bench_executor.docker_cgroup_memory.subprocess.run',
            return_value=SimpleNamespace(returncode=0, stdout='0\n'),
        ):
            self.assertIsNone(_container_pid('stopped'))

    def test_reads_memory_current_from_unified_cgroup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / 'proc/42'
            cgroup = root / 'cgroup/system.slice/docker-test.scope'
            proc.mkdir(parents=True)
            cgroup.mkdir(parents=True)
            (proc / 'cgroup').write_text(
                '0::/system.slice/docker-test.scope\n', encoding='utf-8'
            )
            (cgroup / 'memory.current').write_text('123456\n', encoding='ascii')
            with patch(
                'bench_executor.docker_cgroup_memory._container_pid',
                return_value=42,
            ):
                value = container_memory_current_bytes(
                    'test', cgroup_root=root / 'cgroup', proc_root=root / 'proc'
                )
        self.assertEqual(value, 123456)

    def test_rejects_missing_unified_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory) / '7'
            proc.mkdir()
            (proc / 'cgroup').write_text('1:name:/legacy\n', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'cgroup v2'):
                _unified_cgroup_path(7, Path(directory))


if __name__ == '__main__':
    unittest.main()
