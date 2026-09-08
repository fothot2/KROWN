#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench_executor.docker_cgroup_memory import container_memory_current_bytes


class DockerCgroupTeardownRaceTests(unittest.TestCase):
    def proc_tree(self, directory: str) -> tuple[Path, Path]:
        root = Path(directory)
        proc = root / 'proc'
        cgroup = root / 'cgroup'
        member = proc / '123'
        member.mkdir(parents=True)
        cgroup.mkdir()
        (member / 'cgroup').write_text(
            '0::/system.slice/docker-test.scope\n', encoding='utf-8'
        )
        return proc, cgroup

    def test_missing_cgroup_is_ignored_after_container_disappears(self):
        with tempfile.TemporaryDirectory() as directory:
            proc, cgroup = self.proc_tree(directory)
            with patch(
                'bench_executor.docker_cgroup_memory._container_pid',
                side_effect=[123, None],
            ) as lookup:
                value = container_memory_current_bytes(
                    'Virtuoso', cgroup_root=cgroup, proc_root=proc
                )
        self.assertIsNone(value)
        self.assertEqual(lookup.call_count, 2)

    def test_missing_cgroup_remains_error_for_live_container(self):
        with tempfile.TemporaryDirectory() as directory:
            proc, cgroup = self.proc_tree(directory)
            with patch(
                'bench_executor.docker_cgroup_memory._container_pid',
                side_effect=[123, 123],
            ), self.assertRaises(FileNotFoundError):
                container_memory_current_bytes(
                    'Virtuoso', cgroup_root=cgroup, proc_root=proc
                )

    def test_valid_live_cgroup_value_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            proc, cgroup = self.proc_tree(directory)
            memory = cgroup / 'system.slice/docker-test.scope/memory.current'
            memory.parent.mkdir(parents=True)
            memory.write_text('4096\n', encoding='ascii')
            with patch(
                'bench_executor.docker_cgroup_memory._container_pid',
                return_value=123,
            ) as lookup:
                value = container_memory_current_bytes(
                    'Virtuoso', cgroup_root=cgroup, proc_root=proc
                )
        self.assertEqual(value, 4096)
        lookup.assert_called_once_with('Virtuoso')


if __name__ == '__main__':
    unittest.main()
