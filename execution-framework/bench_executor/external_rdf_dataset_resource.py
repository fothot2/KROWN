#!/usr/bin/env python3
"""Stage one external RDF dataset without storing it in KROWN."""
from __future__ import annotations
import hashlib, os, shutil
from pathlib import Path
from bench_executor.logger import Logger
from bench_executor.standalone_benchmark import resolve_shared_path

_SUPPORTED = {'.nt', '.ttl', '.nq', '.trig'}

class ExternalRdfDatasetResource:
    """Create an owned link or copy inside data/shared."""
    def __init__(self, data_path: str, config_path: str, directory: str, verbose: bool):
        self._shared = str((Path(data_path).resolve() / 'shared'))
        self._logger = Logger(__name__, directory, verbose)
        self._destination = None
        self._marker = None

    @property
    def name(self): return __name__
    @property
    def root_mount_directory(self) -> str: return __name__.lower()

    def execute(self, source_env: str, destination_file: str,
                mode: str = 'link', expected_sha256: str | None = None) -> bool:
        try:
            if mode not in {'link', 'copy'}:
                raise ValueError(f'Unsupported staging mode: {mode}')
            source_value = os.environ.get(source_env)
            if not source_value:
                raise ValueError(f'Environment variable is not set: {source_env}')
            source = Path(source_value).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(f'External RDF dataset is not a file: {source}')
            if source.suffix.lower() not in _SUPPORTED:
                raise ValueError(f'Unsupported RDF extension: {source.suffix}')
            destination = resolve_shared_path(self._shared, destination_file, 'Dataset')
            marker = destination.with_name('.' + destination.name + '.krown-stage')
            if destination.exists() or destination.is_symlink() or marker.exists():
                raise FileExistsError(f'Staged dataset already exists: {destination}')
            if expected_sha256 is not None:
                digest = hashlib.sha256()
                with source.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                if digest.hexdigest() != expected_sha256.lower():
                    raise ValueError('External RDF dataset SHA-256 mismatch')
            destination.parent.mkdir(parents=True, exist_ok=True)
            if mode == 'link': destination.symlink_to(source)
            else: shutil.copyfile(source, destination)
            marker.write_text(f'{mode}\n{source}\n', encoding='utf-8')
            self._destination, self._marker = destination, marker
            self._logger.info(f'Staged external RDF dataset at "{destination}"')
            return True
        except Exception as error:
            self._logger.error(f'External RDF dataset staging failed: {type(error).__name__}: {error}')
            return False

    def stop(self) -> bool:
        if self._marker is None or self._destination is None: return True
        try:
            if self._marker.is_file():
                self._destination.unlink(missing_ok=True)
                self._marker.unlink(missing_ok=True)
            return True
        except OSError as error:
            self._logger.error(f'External RDF dataset cleanup failed: {error}')
            return False

    @staticmethod
    def cleanup_data(data_path: str) -> bool:
        shared = Path(data_path).resolve() / 'shared'
        try:
            for marker in shared.rglob('.*.krown-stage'):
                name = marker.name[1:-len('.krown-stage')]
                destination = marker.with_name(name)
                destination.unlink(missing_ok=True)
                marker.unlink(missing_ok=True)
            return True
        except OSError:
            return False
