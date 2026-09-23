#!/usr/bin/env python3

"""
Apache Jena Fuseki is a SPARQL server. It can run as an operating system
service, as a Java web application (WAR file), and as a standalone server.

**Website**: https://jena.apache.org/documentation/fuseki2/
"""

import os
import shutil
import subprocess
from pathlib import Path
from time import monotonic, sleep
from typing import Dict

import requests

from bench_executor.container import Container
from bench_executor.logger import Logger
from bench_executor.resource_profile import FUSEKI_HEAPS

VERSION = '6.2.0'
MEMORY_MODE = 'memory'
TDB2_MODE = 'tdb2'
_MODE_COMMANDS = {
    MEMORY_MODE: '--mem --update /ds',
    TDB2_MODE: '--tdb2 --update --loc /fuseki/databases/DB /ds',
}
DATABASE_CONTAINER_PATH = '/fuseki/databases/DB'
READY_ENDPOINT = 'http://localhost:3030/ds/query'
READY_TIMEOUT_SECONDS = 120
READY_POLL_SECONDS = 1
READY_REQUEST_TIMEOUT_SECONDS = 5
READY_QUERY = 'ASK { }'


class Fuseki(Container):
    """Fuseki container for executing SPARQL queries."""
    def __init__(self, data_path: str, config_path: str, directory: str,
                 verbose: bool, dataset_mode: str = TDB2_MODE,
                 database_path: str | None = None):
        """Creates an instance of the Fuseki class.

        Parameters
        ----------
        data_path : str
            Path to the data directory of the case.
        config_path : str
            Path to the config directory of the case.
        directory : str
            Path to the directory to store logs.
        verbose : bool
            Enable verbose logs.
        """
        self._data_path = os.path.abspath(data_path)
        self._config_path = os.path.abspath(config_path)
        self._logger = Logger(__name__, directory, verbose)
        if dataset_mode not in _MODE_COMMANDS:
            raise ValueError(f'Unsupported Fuseki dataset mode: {dataset_mode}')
        self._dataset_mode = dataset_mode
        self.command_arguments = _MODE_COMMANDS[dataset_mode]

        os.umask(0)
        default_database = Path(self._data_path) / 'fuseki'
        selected_database = default_database if database_path is None else Path(database_path).expanduser()
        if not selected_database.is_absolute():
            raise ValueError('database_path must be absolute')
        self._database_path = selected_database.resolve()
        self._database_path.mkdir(parents=True, exist_ok=True)

        initial_heap, max_heap = FUSEKI_HEAPS[dataset_mode]

        volumes = [f'{self._data_path}/shared:/data']
        if dataset_mode == TDB2_MODE:
            volumes.append(
                f'{self._database_path}:/fuseki/databases/DB'
            )
        self._volumes = tuple(volumes)
        super().__init__(f'kgconstruct/fuseki:v{VERSION}',
                         f'Fuseki-{dataset_mode}', self._logger,
                         ports={'3030': '3030'},
                         environment={
                             'JAVA_OPTIONS': f'-Xms{initial_heap} -Xmx{max_heap}'
                         }, volumes=volumes)
        self._endpoint = 'http://localhost:3030/ds/sparql'

    @staticmethod
    def cleanup_data(data_path: str) -> bool:
        """Restore host ownership of stale container-created database files."""
        data_root = os.path.realpath(os.path.abspath(data_path))
        database_path = os.path.realpath(os.path.join(data_root, 'fuseki'))
        if os.path.commonpath([data_root, database_path]) != data_root:
            raise ValueError('Fuseki database path leaves the data directory')
        if not os.path.exists(database_path):
            return True

        command = [
            'docker', 'run', '--rm', '--user', '0:0',
            '--volume', f'{database_path}:/cleanup',
            '--entrypoint', 'sh', f'kgconstruct/fuseki:v{VERSION}',
            '-c', 'chmod -R a+rwX /cleanup',
        ]
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return True
        except (OSError, subprocess.CalledProcessError):
            return False

    def reset_store(self) -> bool:
        """Create an empty TDB2 directory before one measured load."""
        data_root = Path(self._data_path).resolve()
        store = getattr(
            self, '_database_path', data_root / 'fuseki'
        )
        if store.is_symlink():
            self._logger.error('Fuseki database path is a symbolic link')
            return False
        resolved_store = store.resolve()
        if resolved_store != (data_root / 'fuseki').resolve():
            self._logger.error('Refusing to reset a non-default Fuseki database path')
            return False
        if resolved_store.exists() and not resolved_store.is_dir():
            self._logger.error('Fuseki database path is not a directory')
            return False
        if resolved_store.is_dir():
            for path in resolved_store.rglob('*'):
                if path.is_symlink():
                    self._logger.error(
                        f'Fuseki database contains a symbolic link: {path}'
                    )
                    return False
            if not self.cleanup_data(self._data_path):
                self._logger.error('Cannot make the Fuseki database writable')
                return False
            try:
                shutil.rmtree(resolved_store)
            except OSError as error:
                self._logger.error(f'Cannot reset the Fuseki database: {error}')
                return False
        try:
            resolved_store.mkdir(parents=True, exist_ok=False)
            resolved_store.chmod(0o777)
        except OSError as error:
            self._logger.error(f'Cannot create the Fuseki database: {error}')
            return False
        return True

    def initialization(self) -> bool:
        """Initialize Fuseki's database.

        Returns
        -------
        success : bool
            Whether the initialization was successfull or not.
        """
        # Fuseki should start with a initialized database, start Fuseki
        # if not initialized to avoid the pre-run start during benchmark
        # execution
        success = self.wait_until_ready()
        if not success:
            return False
        success = self.stop()

        return success

    @property
    def root_mount_directory(self) -> str:
        """Subdirectory in the root directory of the case for Fuseki.

        Returns
        -------
        subdirectory : str
            Subdirectory of the root directory for Fuseki.
        """
        return __name__.lower()

    @property
    def headers(self) -> Dict[str, Dict[str, str]]:
        """HTTP headers of SPARQL queries for serialization formats.

        Only supported serialization formats are included in the dictionary.
        Currently, the following formats are supported:
        - N-Triples
        - Turtle
        - CSV
        - RDF/JSON
        - RDF/XML
        - JSON-LD

        Returns
        -------
        headers : dict
            Dictionary of headers to use for each serialization format.
        """
        headers = {}
        headers['ntriples'] = {'Accept': 'text/plain'}
        headers['turtle'] = {'Accept': 'text/turtle'}
        headers['csv'] = {'Accept': 'text/csv'}
        headers['rdfjson'] = {'Accept': 'application/rdf+json'}
        headers['rdfxml'] = {'Accept': 'application/rdf+xml'}
        headers['jsonld'] = {'Accept': 'application/ld+json'}
        return headers

    def wait_until_ready(self, command: str = '') -> bool:
        """Start Fuseki and wait for a successful bounded HTTP probe."""
        command = f'{command} {self.command_arguments}'
        if not self.run(command):
            self._logger.error(f'Command "{command}" failed')
            return False

        deadline = monotonic() + READY_TIMEOUT_SECONDS
        while monotonic() < deadline:
            try:
                response = requests.post(
                    READY_ENDPOINT,
                    data={'query': READY_QUERY},
                    timeout=READY_REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get('boolean') is True:
                    return True
            except (requests.RequestException, ValueError):
                pass
            sleep(READY_POLL_SECONDS)

        self._logger.error(
            f'Waiting for Fuseki HTTP readiness timed out after '
            f'{READY_TIMEOUT_SECONDS} seconds'
        )
        return False

    def load(self, rdf_file: str) -> bool:
        """Load an RDF file into Fuseki.

        Currently, only N-Triples files are supported.

        Parameters
        ----------
        rdf_file : str
            Name of the RDF file to load.

        Returns
        -------
        success : bool
            Whether the loading was successfull or not.
        """
        path = os.path.join(self._data_path, 'shared', rdf_file)

        if not os.path.exists(path):
            self._logger.error(f'RDF file "{rdf_file}" does not exist')
            return False

        # Load directory with data with HTTP post
        try:
            h = {'Content-Type': 'application/n-triples'}
            r = requests.post('http://localhost:3030/ds',
                              data=open(path, 'rb'),
                              headers=h)
            self._logger.debug(f'Loaded triples: {r.text}')
            r.raise_for_status()
        except Exception as e:
            self._logger.error(f'Failed to load RDF: "{e}" into Fuseki')
            return False

        return True

    def stop(self) -> bool:
        """Stop Fuseki and preserve the measured TDB2 representation."""
        if not super().stop():
            return False
        if getattr(self, '_dataset_mode', TDB2_MODE) == TDB2_MODE:
            if not self.cleanup_data(self._data_path):
                self._logger.error(
                    'Failed to restore host ownership of the Fuseki database'
                )
                return False
        return True

    @property
    def endpoint(self):
        """SPARQL endpoint URL"""
        return self._endpoint


if __name__ == '__main__':
    print(f'ℹ️  Starting up Fuseki v{VERSION}...')
    f = Fuseki('data', 'config', 'log', True)
    f.wait_until_ready()
    input('ℹ️  Press any key to stop')
    f.stop()
    print('ℹ️  Stopped')
