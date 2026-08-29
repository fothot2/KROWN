#!/usr/bin/env python3
"""Publish one generic cross-system RDF comparison report."""
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from bench_executor.logger import Logger
from bench_executor.rdf_cross_system_comparison import compare_archives
from bench_executor.standalone_benchmark import (
    commit_output,
    discard_output,
    input_file,
    resolve_shared_path,
    temporary_output,
)


class RdfCrossSystemComparisonResource:
    """Compare result archives produced by independent RDF matrix runs."""

    def __init__(self, data_path: str, config_path: str, directory: str,
                 verbose: bool):
        self._shared = Path(data_path).resolve() / "shared"
        self._directory = Path(directory).resolve()
        self._logger = Logger(__name__, str(self._directory), verbose)
        self.last_outcome = "success"
        self._shared.mkdir(parents=True, exist_ok=True)

    @property
    def name(self):
        return __name__

    @property
    def root_mount_directory(self) -> str:
        return __name__.lower()

    def execute(self, manifest_file: str, archive_files: Sequence[str],
                output_file: str, policy_file: str | None = None) -> bool:
        """Compare existing shared inputs and atomically publish one report."""
        temporary = None
        self.last_outcome = "success"
        try:
            if (not isinstance(archive_files, Sequence)
                    or isinstance(archive_files, (str, bytes))
                    or not archive_files):
                raise ValueError("archive_files must be a non-empty array")
            if any(not isinstance(item, str) or not item
                   for item in archive_files):
                raise ValueError(
                    "archive_files entries must be non-empty strings"
                )

            manifest_path = input_file(str(self._shared), manifest_file)
            archive_paths = [
                input_file(str(self._shared), item)
                for item in archive_files
            ]
            policy_path = (
                None if policy_file is None
                else input_file(str(self._shared), policy_file)
            )
            output_path = resolve_shared_path(
                str(self._shared), output_file, "Output"
            )
            report = compare_archives(
                manifest_path, archive_paths, policy_path
            )

            temporary = temporary_output(output_path)
            temporary.write_text(
                json.dumps(
                    report, indent=2, sort_keys=True, allow_nan=False
                ) + "\n",
                encoding="utf-8",
            )
            commit_output(temporary, output_path)
            temporary = None
            self._logger.info(
                "Wrote cross-system RDF comparison report to "
                f'"{output_path}"'
            )
            return True
        except Exception as error:
            self.last_outcome = "failure"
            self._logger.error(
                "Cross-system RDF comparison failed: "
                f"{type(error).__name__}: {error}"
            )
            return False
        finally:
            discard_output(temporary)
