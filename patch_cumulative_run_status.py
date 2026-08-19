#!/usr/bin/env python3

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = Path('/users/u0182905/KROWN')
EXECUTOR = REPOSITORY / 'execution-framework/bench_executor/executor.py'
UNIT_TESTS = REPOSITORY / 'execution-framework/tests/unit_tests'
SCHEMA = REPOSITORY / 'execution-framework/bench_executor/data/metadata.schema'

EXPECTED_HASHES = {
    EXECUTOR: 'bd960aef2ef7f04733d960daa79ee9249eb69f41666ebe2a1359c95195697e1e',
    UNIT_TESTS: 'd4c14221399f3764d739bdb4d30a8dbce537047567264f448be5b249d0e9e012',
    SCHEMA: '06c741ffabe12444ffadb0e5505eb0b5dd095c6d99a5873b205c49b3c70e124a',
}

ENV = {
    **os.environ,
    'RUST_LOG': 'vortex_rdf_cli=debug,vortex_rdf_core=debug',
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f'Expected one exact source block for {label}. Found {count}.'
        )
    return text.replace(old, new, 1)


def verify_inputs():
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise RuntimeError(f'Missing required file: {path}')
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(
                f'SHA-256 mismatch for {path}\n'
                f'Expected: {expected}\n'
                f'Actual:   {actual}\n'
                'The script made no changes.'
            )


def patch_executor(text):
    text = replace_once(
        text,
        """        success = True\n        data = case['data']\n""",
        """        run_success = True\n        data = case['data']\n""",
        'run status initialization',
    )

    text = replace_once(
        text,
        """                self._progress_cb('Initializing', step['resource'], success)\n""",
        """                self._progress_cb('Initializing', step['resource'], True)\n""",
        'initialization callback status',
    )

    old_loop = """        for index, step in enumerate(data['steps']):\n            success = True\n            module = self._class_module_mapping[step['resource']]\n            resource = getattr(module, step['resource'])(data_path, CONFIG_DIR,\n                                                         directory,\n                                                         self._verbose)\n            active_resources.append(resource)\n\n            # Containers may need to start up first before executing a command\n            if hasattr(resource, 'wait_until_ready'):\n                if not resource.wait_until_ready():\n                    success = False\n                    self._logger.error('Waiting until resource '\n                                       f'\"{step[\"resource\"]} is ready failed')\n                    self._progress_cb(step['resource'], step['name'], success)\n                    break\n\n                self._logger.debug(f'Resource {step[\"resource\"]} ready')\n\n            # Execute command\n            command = getattr(resource, step['command'])\n            if not command(**step['parameters']):\n                success = False\n                msg = f'Executing command \"{step[\"command\"]}\" ' + \\\n                      f'failed for resource \"{step[\"resource\"]}\"'\n                # Some steps are non-critical like queries, they may fail but\n                # should not cause a complete case failure. Allow these\n                # failures if the may_fail key is present\n                if step.get('may_fail', False):\n                    self._logger.warning(msg)\n                    self._progress_cb(step['resource'], step['name'], success)\n                    continue\n                else:\n                    self._logger.error(msg)\n                    self._progress_cb(step['resource'], step['name'], success)\n                    break\n\n            self._logger.debug(f'Command \"{step[\"command\"]}\" executed on '[/s]"""
    # Build the exact block without the sentinel used above.
    old_loop = old_loop.replace("[/s]", "")

    # Use smaller exact replacements. This reduces risk from the long block.
    text = replace_once(
        text,
        """        for index, step in enumerate(data['steps']):\n            success = True\n""",
        """        for index, step in enumerate(data['steps']):\n            step_success = True\n""",
        'step status initialization',
    )
    text = replace_once(
        text,
        """                    success = False\n                    self._logger.error('Waiting until resource '\n""",
        """                    step_success = False\n                    run_success = False\n                    self._logger.error('Waiting until resource '\n""",
        'readiness failure status',
    )
    text = replace_once(
        text,
        """                    self._progress_cb(step['resource'], step['name'], success)\n                    break\n""",
        """                    self._progress_cb(\n                        step['resource'], step['name'], step_success\n                    )\n                    break\n""",
        'readiness failure callback',
    )
    text = replace_once(
        text,
        """            if not command(**step['parameters']):\n                success = False\n""",
        """            if not command(**step['parameters']):\n                step_success = False\n                run_success = False\n""",
        'command failure status',
    )
    text = text.replace(
        "self._progress_cb(step['resource'], step['name'], success)",
        "self._progress_cb(step['resource'], step['name'], step_success)",
    )
    if text.count("self._progress_cb(step['resource'], step['name'], step_success)") != 3:
        raise RuntimeError('Expected three step callback calls after replacement.')

    text = replace_once(
        text,
        """        if checkpoint and success:\n""",
        """        if checkpoint and run_success:\n""",
        'case checkpoint condition',
    )
    text = replace_once(
        text,
        """        if success:\n            self._logger.debug('Copying generated files for run')\n""",
        """        if run_success:\n            self._logger.debug('Copying generated files for run')\n""",
        'artifact and run checkpoint condition',
    )
    text = replace_once(
        text,
        """        return success\n""",
        """        return run_success\n""",
        'run return status',
    )

    if "            success = True\n" in text:
        raise RuntimeError('The old per-step status reset remains.')
    return text


def patch_tests(text):
    text = replace_once(
        text,
        'import tempfile\n',
        'import tempfile\nfrom types import SimpleNamespace\nfrom unittest.mock import MagicMock, patch\n',
        'test support imports',
    )

    anchor = '    def test_declared_artifact_path_accepts_any_extension(self):\n'
    tests = '''    def test_executor_retains_may_fail_step_failure(self):\n        class FakeResource:\n            def __init__(self, data_path, config_dir, log_dir, verbose):\n                pass\n\n            def execute(self, succeed):\n                return succeed\n\n            def stop(self):\n                pass\n\n        class FakeCollector:\n            def __init__(self, *args, **kwargs):\n                pass\n\n            def next_step(self):\n                pass\n\n            def stop(self):\n                pass\n\n        with tempfile.TemporaryDirectory() as directory:\n            with open(os.path.join(directory, 'log.txt'),\n                      'w', encoding='utf-8'):\n                pass\n\n            executor = Executor.__new__(Executor)\n            executor._class_module_mapping = {\n                'FakeResource': SimpleNamespace(\n                    FakeResource=FakeResource\n                )\n            }\n            executor._verbose = False\n            executor._logger = MagicMock()\n            executor._progress_cb = MagicMock()\n            executor.clean = MagicMock(return_value=True)\n\n            case = {\n                'directory': directory,\n                'data': {\n                    'name': 'cumulative-status',\n                    'steps': [\n                        {\n                            'name': 'expected failure',\n                            'resource': 'FakeResource',\n                            'command': 'execute',\n                            'parameters': {'succeed': False},\n                            'may_fail': True,\n                        },\n                        {\n                            'name': 'later success',\n                            'resource': 'FakeResource',\n                            'command': 'execute',\n                            'parameters': {'succeed': True},\n                        },\n                    ],\n                },\n            }\n\n            with patch('bench_executor.executor.Collector', FakeCollector), \\\n                    patch('bench_executor.executor.sleep'):\n                success = executor.run(\n                    case, interval=0.1, run=2, checkpoint=True\n                )\n\n            self.assertFalse(success)\n            self.assertFalse(os.path.exists(os.path.join(\n                directory, 'results', 'run_2', '.done'\n            )))\n            self.assertFalse(os.path.exists(os.path.join(\n                directory, '.done'\n            )))\n            self.assertEqual(executor._progress_cb.call_count, 4)\n            executor._progress_cb.assert_any_call(\n                'FakeResource', 'expected failure', False\n            )\n            executor._progress_cb.assert_any_call(\n                'FakeResource', 'later success', True\n            )\n\n'''
    return replace_once(
        text,
        anchor,
        tests + anchor,
        'cumulative status unit test',
    )


def run(command, cwd=REPOSITORY):
    print('+', ' '.join(str(item) for item in command), flush=True)
    subprocess.run(command, cwd=cwd, env=ENV, check=True)


def validate():
    tests_directory = REPOSITORY / 'execution-framework/tests'
    run([
        sys.executable, '-m', 'py_compile',
        str(EXECUTOR), str(UNIT_TESTS),
    ])
    run([
        sys.executable, './unit_tests',
        'UnitTests.test_executor_retains_may_fail_step_failure',
        'UnitTests.test_declared_artifact_path_accepts_any_extension',
        'UnitTests.test_move_declared_artifact_keeps_nested_path',
    ], cwd=tests_directory)
    run([sys.executable, '-m', 'json.tool', str(SCHEMA)])
    run([
        'git', 'diff', '--check', '--',
        'execution-framework/bench_executor/executor.py',
        'execution-framework/tests/unit_tests',
    ])


def main():
    verify_inputs()
    backup_directory = Path(tempfile.mkdtemp(
        prefix='krown-cumulative-status-', dir='/tmp'
    ))
    backups = {}
    try:
        for source in (EXECUTOR, UNIT_TESTS):
            backup = backup_directory / source.name
            shutil.copy2(source, backup)
            backups[source] = backup

        EXECUTOR.write_text(
            patch_executor(EXECUTOR.read_text(encoding='utf-8')),
            encoding='utf-8',
        )
        UNIT_TESTS.write_text(
            patch_tests(UNIT_TESTS.read_text(encoding='utf-8')),
            encoding='utf-8',
        )
        validate()
    except Exception as error:
        print(f'Patch failed: {error}', file=sys.stderr)
        print('The script will restore both files.', file=sys.stderr)
        for destination, backup in backups.items():
            if backup.is_file():
                shutil.copy2(backup, destination)
        shutil.rmtree(backup_directory, ignore_errors=True)
        raise

    shutil.rmtree(backup_directory, ignore_errors=True)
    print('Patch and validation succeeded.')
    print(f'executor.py SHA-256: {sha256(EXECUTOR)}')
    print(f'unit_tests SHA-256: {sha256(UNIT_TESTS)}')


if __name__ == '__main__':
    main()
