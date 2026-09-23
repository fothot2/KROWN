#!/usr/bin/env python3

"""
Virtuoso is a secure and high-performance platform for modern data access,
integration, virtualization, and multi-model data management (tables & graphs)
based on innovative support of existing open standards
(e.g., SQL, SPARQL, and GraphQL).

**Website**: https://virtuoso.openlinksw.com/<br>
**Repository**: https://github.com/openlink/virtuoso-opensource
"""

import os
import shutil
from pathlib import Path, PurePosixPath
from threading import Thread
from typing import Dict

import requests

from bench_executor.container import Container
from bench_executor.logger import Logger
from bench_executor.resource_profile import VIRTUOSO_LOADER_CORES, virtuoso_buffers

VERSION = '7.2.17'
MAX_ROWS = '10000000'
QUERY_TIMEOUT = '0'  # no limit
MAX_VECTOR_SIZE = '3000000'  # max value is 'around' 3,500,000 from docs
PASSWORD = 'root'
NUMBER_OF_BUFFERS_PER_GB = 85000
MAX_DIRTY_BUFFERS_PER_GB = 65000
LOAD_GRAPH_IRI = 'http://example.com/graph'
SPARQL_ENDPOINT = 'http://localhost:8890/sparql'


def _ld_dir_command(directory: str, rdf_file: str) -> str:
    """Build one loader registration for the configured RDF graph."""
    return (
        "'isql' -U dba -P root "
        f"exec=\"ld_dir('{directory}','{rdf_file}', "
        f"'{LOAD_GRAPH_IRI}');\""
    )


def _split_loader_path(rdf_file: str, rdf_dir: str = '') -> tuple[str, str]:
    """Return the loader directory and basename for one nested artifact."""
    relative = PurePosixPath(rdf_file)
    prefix = PurePosixPath(rdf_dir) if rdf_dir else PurePosixPath()
    if relative.is_absolute() or prefix.is_absolute():
        raise ValueError('Virtuoso loader paths must be relative')
    if '..' in relative.parts or '..' in prefix.parts:
        raise ValueError('Virtuoso loader path leaves /usr/share/proj')
    directory = PurePosixPath('/usr/share/proj') / prefix / relative.parent
    return str(directory), relative.name


def _count_ntriples(path: str) -> int:
    """Count non-empty, non-comment N-Triples statement lines."""
    count = 0
    with open(path, 'rb') as stream:
        for line in stream:
            stripped = line.lstrip()
            if stripped and not stripped.startswith(b'#'):
                count += 1
    return count


def _spawn_loader(container, outcomes):
    """Thread function to parallel load RDF.

    Parameters
    ----------
    container : Container
        The Virtuoso container on which the RDF loader should run.
    """
    success, logs = container.exec('\'isql\' -U dba -P root '
                                   'exec="rdf_loader_run();"')
    outcomes.append(success)


class Virtuoso(Container):
    """Virtuoso container to execute SPARQL queries"""

    def __init__(self, data_path: str, config_path: str, directory: str,
                 verbose: bool, database_path: str | None = None):
        """Creates an instance of the Virtuoso class.

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

        default_database = Path(self._data_path) / 'virtuoso'
        selected_database = (
            default_database if database_path is None
            else Path(database_path).expanduser()
        )
        if not selected_database.is_absolute():
            raise ValueError('database_path must be absolute')
        self._database_path = selected_database.resolve()
        os.umask(0)
        self._database_path.mkdir(parents=True, exist_ok=True)
        database_dir = str(self._database_path)
        number_of_buffers, max_dirty_buffers = virtuoso_buffers()
        environment = {'DBA_PASSWORD': PASSWORD,
                       'VIRT_SPARQL_ResultSetMaxRows': MAX_ROWS,
                       'VIRT_SPARQL_MaxQueryExecutionTime': QUERY_TIMEOUT,
                       'VIRT_SPARQL_ExecutionTimeout': QUERY_TIMEOUT,
                       'VIRT_SPARQL_MaxQueryCostEstimationTime': QUERY_TIMEOUT,
                       'VIRT_Parameters_MaxVectorSize': MAX_VECTOR_SIZE,
                       'VIRT_Parameters_NumberOfBuffers': number_of_buffers,
                       'VIRT_Parameters_MaxDirtyBuffers': max_dirty_buffers}
        super().__init__(f'kgconstruct/virtuoso:v{VERSION}',
                         'Virtuoso', self._logger,
                         ports={'8890': '8890', '1111': '1111'},
                         environment=environment,
                         volumes=[f'{self._data_path}/shared:/usr/share/proj',
                                  f'{database_dir}:/database'])
        self._endpoint = SPARQL_ENDPOINT

    def reset_store(self) -> bool:
        """Create an empty benchmark-local database before one measured load."""
        data_root = Path(self._data_path).resolve()
        store = getattr(self, '_database_path', data_root / 'virtuoso')
        if store.is_symlink():
            self._logger.error('Virtuoso database path is a symbolic link')
            return False
        resolved_store = store.resolve()
        if resolved_store != (data_root / 'virtuoso').resolve():
            self._logger.error(
                'Refusing to reset a non-default Virtuoso database path'
            )
            return False
        if resolved_store.exists() and not resolved_store.is_dir():
            self._logger.error('Virtuoso database path is not a directory')
            return False
        if resolved_store.is_dir():
            for path in resolved_store.rglob('*'):
                if path.is_symlink():
                    self._logger.error(
                        f'Virtuoso database contains a symbolic link: {path}'
                    )
                    return False
            try:
                shutil.rmtree(resolved_store)
            except OSError as error:
                self._logger.error(f'Cannot reset the Virtuoso database: {error}')
                return False
        try:
            resolved_store.mkdir(parents=True, exist_ok=False)
            resolved_store.chmod(0o777)
        except OSError as error:
            self._logger.error(f'Cannot create the Virtuoso database: {error}')
            return False
        return True

    def initialization(self) -> bool:
        """Initialize Virtuoso's database.

        Returns
        -------
        success : bool
            Whether the initialization was successfull or not.
        """
        # Virtuoso should start with a initialized database, start Virtuoso
        # if not initialized to avoid the pre-run start during benchmark
        # execution
        success = self.wait_until_ready()
        if not success:
            return False
        success = self.stop()

        return success

    @property
    def root_mount_directory(self) -> str:
        """Subdirectory in the root directory of the case for Virtuoso.

        Returns
        -------
        subdirectory : str
            Subdirectory of the root directory for Virtuoso.
        """
        return __name__.lower()

    def wait_until_ready(self, command: str = '') -> bool:
        """Wait until Virtuoso is ready to execute SPARQL queries.

        Parameters
        ----------
        command : str
            Command to execute in the Virtuoso container, optionally, defaults
            to no command.

        Returns
        -------
        success : bool
            Whether the Virtuoso was initialized successfull or not.
        """
        return self.run_and_wait_for_log('Server online at', command=command)

    def load(self, rdf_file: str, rdf_dir: str = '') -> bool:
        """Load an RDF file into Virtuoso.

        Currently, only N-Triples files are supported.

        Parameters
        ----------
        rdf_file : str
            Name of the RDF file to load.
        rdf_dir : str
            Name of the directory where RDF file(s) are stored.
            Default root of the data directory.

        Returns
        -------
        success : bool
            Whether the loading was successfull or not.
        """
        return self.load_parallel(rdf_file, VIRTUOSO_LOADER_CORES, rdf_dir)

    def load_parallel(self, rdf_file: str, cores: int,
                      rdf_dir: str = '') -> bool:
        """Load an RDF file into Virtuoso in parallel.

        Currently, only N-Triples files are supported.

        Parameters
        ----------
        rdf_file : str
            Name of the RDF file to load.
        cores : int
            Number of CPU cores for loading.
        rdf_dir : str
            Name of the directory where RDF file(s) are stored.
            Default root of the data directory.

        Returns
        -------
        success : bool
            Whether the loading was successfull or not.
        """
        success = True

        success, logs = self.exec(f'sh -c "ls /usr/share/proj/{rdf_file}"')
        for line in logs:
            self._logger.debug(line)
        if not success:
            self._logger.error('RDF files do not exist for loading')
            return False

        # Register the basename in its actual mounted directory.
        try:
            directory, loader_file = _split_loader_path(rdf_file, rdf_dir)
        except ValueError as error:
            self._logger.error(str(error))
            return False
        success, logs = self.exec(_ld_dir_command(directory, loader_file))
        for line in logs:
            self._logger.debug(line)
        if not success:
            self._logger.error('ISQL loader query failure')
            return False

        loader_threads = []
        loader_outcomes = []
        self._logger.debug(f'Spawning {cores} loader threads')
        for i in range(cores):
            t = Thread(
                target=_spawn_loader, args=(self, loader_outcomes),
                daemon=True,
            )
            t.start()
            loader_threads.append(t)

        for t in loader_threads:
            t.join()
        if len(loader_outcomes) != cores or not all(loader_outcomes):
            self._logger.error('One or more Virtuoso loader threads failed')
            return False
        self._logger.debug(f'Loading finished with {cores} threads')

        # Re-enable checkpoints and scheduler which are disabled automatically
        # after loading RDF with rdf_loader_run()
        success, logs = self.exec('\'isql\' -U dba -P root exec="checkpoint;"')
        for line in logs:
            self._logger.debug(line)
        if not success:
            self._logger.error('ISQL re-enable checkpoints query failure')
            return False

        success, logs = self.exec('\'isql\' -U dba -P root '
                                  'exec="checkpoint_interval(60);"')
        for line in logs:
            self._logger.debug(line)
        if not success:
            self._logger.error('ISQL checkpoint interval query failure')
            return False

        success, logs = self.exec('\'isql\' -U dba -P root '
                                  'exec="scheduler_interval(10);"')
        for line in logs:
            self._logger.debug(line)
        if not success:
            self._logger.error('ISQL scheduler interval query failure')
            return False

        source_path = os.path.join(
            self._data_path, 'shared', rdf_dir, rdf_file
        )
        try:
            expected = _count_ntriples(source_path)
            response = requests.post(
                SPARQL_ENDPOINT,
                data={
                    'query': (
                        'SELECT (COUNT(*) AS ?count) WHERE { GRAPH <'
                        + LOAD_GRAPH_IRI + '> { ?s ?p ?o } }'
                    ),
                },
                headers={'Accept': 'application/sparql-results+json'},
                timeout=120,
            )
            response.raise_for_status()
            bindings = response.json()['results']['bindings']
            actual = int(bindings[0]['count']['value'])
        except (OSError, KeyError, IndexError, TypeError, ValueError,
                requests.RequestException) as error:
            self._logger.error(
                f'Failed to verify the Virtuoso loader graph: {error}'
            )
            return False
        if actual <= 0:
            self._logger.error(
                'Virtuoso loaded graph is empty'
            )
            return False

        if actual > expected:
            self._logger.error(
                f'Virtuoso graph cardinality {actual} exceeds '
                f'the {expected} physical N-Triples statements'
            )
            return False

        reduction = expected - actual

        self._logger.debug(
            f'Virtuoso loader validation succeeded: '
            f'source_statements={expected}, '
            f'graph_triples={actual}, '
            f'cardinality_reduction={reduction}'
        )

        return True

    def stop(self) -> bool:
        """Stop Virtuoso and preserve the measured database."""
        command = "'isql' -U dba -P root " 'exec="checkpoint;"'
        success, logs = self.exec(command)
        for line in logs:
            self._logger.debug(line)
        if not success:
            self._logger.error('ISQL final checkpoint query failure')
            return False
        return super().stop()

    @property
    def endpoint(self) -> str:
        """SPARQL endpoint URL"""
        return self._endpoint

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
        headers['ntriples'] = {'Accept': 'text/ntriples'}
        headers['turtle'] = {'Accept': 'text/turtle'}
        headers['rdfxml'] = {'Accept': 'application/rdf+xml'}
        headers['rdfjson'] = {'Accept': 'application/rdf+json'}
        headers['csv'] = {'Accept': 'text/csv'}
        headers['jsonld'] = {'Accept': 'application/ld+json'}
        return headers


if __name__ == '__main__':
    print(f'ℹ️  Starting up Virtuoso v{VERSION}...')
    v = Virtuoso('data', 'config', 'log', True)
    v.wait_until_ready()
    input('ℹ️  Press any key to stop')
    v.stop()
    print('ℹ️  Stopped')
