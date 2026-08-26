#!/usr/bin/env python3
"""Execute one external RDF experiment declaration across registered systems."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Mapping

from bench_executor.benchmark_result import write_query_records_atomic
from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
from bench_executor.logger import Logger
from bench_executor.rdf_experiment_manifest import (
    load_rdf_experiment_declaration,
    system_adapter_specifications,
)
from bench_executor.rdf_query_benchmark import (
    _load_query_manifest,
    _QueryOutcome,
    _QueryTimeoutError,
    _RdfQueryAdapter,
    _RdfQueryBenchmark,
)
from bench_executor.rdflib_query_benchmark import RdfLibQueryBenchmark
from bench_executor.sparql_http_benchmark import SparqlHttpBenchmark
from bench_executor.sparql_result import normalize_sparql_json_result
from bench_executor.standalone_benchmark import (
    commit_output,
    discard_output,
    input_file,
    resolve_shared_path,
    temporary_output,
)

SUMMARY_SCHEMA = "rdf-experiment-matrix-summary-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = temporary_output(path)
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        commit_output(temporary, path)
        temporary = None
    finally:
        discard_output(temporary)


def _stage_artifacts(
        declaration_path: Path,
        artifacts: Mapping[str, DatasetArtifact],
        shared: Path) -> dict[str, DatasetArtifact]:
    """Verify and hard-link or copy declared files into data/shared."""
    declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
    benchmark_root = declaration_path.parents[1]
    staged: dict[str, DatasetArtifact] = {}
    stage_root = shared / "rdf-matrix-artifacts"
    stage_root.mkdir(parents=True, exist_ok=True)
    for representation, artifact in artifacts.items():
        receipt = (benchmark_root / declaration["representations"][representation]).resolve()
        receipt_value = json.loads(receipt.read_text(encoding="utf-8"))
        if len(receipt_value["files"]) != len(artifact.files):
            raise ValueError(f"receipt file count changed for {representation}")
        files = []
        for index, (record, declared) in enumerate(zip(receipt_value["files"], artifact.files)):
            source = (receipt.parent / record["path"]).resolve()
            try:
                source.relative_to(receipt.parent.resolve())
            except ValueError as error:
                raise ValueError("representation file escapes its receipt directory") from error
            if (not source.is_file() or source.stat().st_size != declared.size_bytes
                    or _sha256(source) != declared.sha256):
                raise ValueError(f"representation file differs from receipt: {source}")
            suffix = source.suffix
            relative = Path("rdf-matrix-artifacts") / (
                representation.replace("/", "--") + f"--{index}{suffix}"
            )
            target = (shared / relative).resolve()
            try:
                target.relative_to(shared.resolve())
            except ValueError as error:
                raise ValueError("staged artifact escapes data/shared") from error
            target.unlink(missing_ok=True)
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
            files.append(ArtifactFile(relative.as_posix(), target.stat().st_size, _sha256(target)))
        staged[representation] = DatasetArtifact(
            benchmark=artifact.benchmark,
            dataset=artifact.dataset,
            source_format=artifact.source_format,
            source_size_bytes=artifact.source_size_bytes,
            source_sha256=artifact.source_sha256,
            representation=artifact.representation,
            files=tuple(files),
            producer=dict(artifact.producer),
        )
    return staged


def _constructor_arguments(
        adapter_class: type,
        artifact: DatasetArtifact,
        data_path: str,
        config_path: str,
        directory: str,
        verbose: bool,
        configuration,
        supplied: Mapping[str, Any]) -> dict[str, Any]:
    """Bind standard KROWN context and explicit adapter options by name."""
    available: dict[str, Any] = {
        "artifact": artifact,
        "data_path": data_path,
        "config_path": config_path,
        "directory": directory,
        "verbose": verbose,
        **dict(configuration.parameters),
        **dict(supplied),
    }
    if configuration.system == "oxigraph":
        available.setdefault("backend", configuration.configuration)
    signature = inspect.signature(adapter_class)
    arguments = {}
    missing = []
    for name, parameter in signature.parameters.items():
        if name in available:
            arguments[name] = available[name]
        elif parameter.default is inspect.Parameter.empty:
            missing.append(name)
    if missing:
        raise ValueError(
            f"Missing explicit adapter options for {configuration.system_id}: "
            + ", ".join(missing)
        )
    return arguments



def _environment_adapter_options(
        declarations: Mapping[str, Mapping[str, str]] | None,
        environment: Mapping[str, str] | None = None) -> dict[str, dict[str, str]]:
    """Resolve explicit adapter options from named environment variables."""
    if declarations is None:
        return {}
    if not isinstance(declarations, Mapping):
        raise TypeError("adapter_option_env must be an object")
    source = os.environ if environment is None else environment
    resolved: dict[str, dict[str, str]] = {}
    for system_id, options in declarations.items():
        if not isinstance(system_id, str) or not system_id:
            raise ValueError("adapter_option_env system ID must be non-empty")
        if not isinstance(options, Mapping) or not options:
            raise ValueError(f"adapter_option_env for {system_id} must be a non-empty object")
        values = {}
        for option, variable in options.items():
            if not isinstance(option, str) or not option:
                raise ValueError("adapter option name must be non-empty")
            if not isinstance(variable, str) or not variable:
                raise ValueError("adapter environment variable name must be non-empty")
            value = source.get(variable)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Environment variable is not set: {variable}")
            values[option] = value
        resolved[system_id] = values
    return resolved

class _ComunicaQueryAdapter(_RdfQueryAdapter):
    """Execute complete SPARQL queries through one file-backed command adapter."""
    def __init__(self, adapter, artifact: Path, timeout_s: float):
        self._adapter = adapter
        self._artifact = artifact
        self._timeout_s = timeout_s

    def execute(self, query: str) -> _QueryOutcome:
        command = self._adapter.docker_command(
            host_artifact=self._artifact, query=query
        )
        try:
            result = subprocess.run(
                command, text=True, capture_output=True,
                timeout=self._timeout_s, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise _QueryTimeoutError(
                f"file-backed query exceeded {self._timeout_s}s"
            ) from error
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("file-backed adapter returned invalid SPARQL JSON") from error
        normalized = normalize_sparql_json_result(document, query)
        return _QueryOutcome(
            result_count=normalized["result_count"],
            result_fingerprint=normalized["result_fingerprint"],
            metadata={
                "measurement_boundary": "file-backed-complete-response",
                **{key: value for key, value in normalized.items()
                   if key not in {"result_count", "result_fingerprint", "normalized_result"}},
            },
        )


def _run_file_backed(
        adapter, artifact_path: Path, manifest_path: Path,
        output_path: Path, experiment, system_id: str) -> bool:
    manifest = _load_query_manifest(str(manifest_path))
    policy = experiment.execution_policy
    benchmark = _RdfQueryBenchmark(
        adapter_factory=lambda: _ComunicaQueryAdapter(
            adapter, artifact_path, float(policy["timeout_s"])
        ),
        experiment_id=experiment.experiment_id,
        system=system_id,
        manifest=manifest,
        warmup_runs=int(policy["warmup_runs"]),
        measured_runs=int(policy["measured_runs"]),
    )
    benchmark.run(str(output_path))
    return True


def _result_summary(path: Path, experiment, representation: str) -> dict[str, Any]:
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid JSONL line {line_number}") from error
    if not records:
        raise ValueError(f"empty result artifact: {path}")
    failures = sum(row.get("status") not in {"ok", "skipped", "unsupported"}
                   for row in records)
    return {
        "experiment_id": experiment.experiment_id,
        "system": experiment.system_configuration,
        "representation": representation,
        "record_count": len(records),
        "failure_count": failures,
        "result_file": path.name,
        "sha256": _sha256(path),
    }


class RdfExperimentMatrixResource:
    """Run a benchmark-neutral external RDF experiment declaration."""
    def __init__(self, data_path: str, config_path: str, directory: str,
                 verbose: bool):
        self._data_path = Path(data_path).resolve()
        self._shared = self._data_path / "shared"
        self._config_path = Path(config_path).resolve()
        self._directory = Path(directory).resolve()
        self._verbose = verbose
        self._logger = Logger(__name__, str(self._directory), verbose)
        self._shared.mkdir(parents=True, exist_ok=True)

    @property
    def name(self):
        return __name__

    @property
    def root_mount_directory(self) -> str:
        return __name__.lower()

    def execute(
            self,
            declaration_file: str,
            manifest_file: str,
            results_file: str,
            output_file: str,
            adapter_options: Mapping[str, Mapping[str, Any]] | None = None,
            adapter_option_env: Mapping[str, Mapping[str, str]] | None = None) -> bool:
        """Execute all declaration bindings and publish summary plus archive."""
        summary_temporary = archive_temporary = None
        run_directory = None
        try:
            declaration_path = Path(declaration_file).expanduser().resolve()
            if not declaration_path.is_file():
                raise FileNotFoundError(f"experiment declaration is missing: {declaration_path}")
            manifest_path = input_file(str(self._shared), manifest_file)
            experiments, original_artifacts = load_rdf_experiment_declaration(declaration_path)
            artifacts = _stage_artifacts(declaration_path, original_artifacts, self._shared)
            specifications = {
                item.system_id: item for item in system_adapter_specifications()
            }
            options = {} if adapter_options is None else dict(adapter_options)
            environment_options = _environment_adapter_options(adapter_option_env)
            for system_id, values in environment_options.items():
                merged = dict(options.get(system_id, {}))
                merged.update(values)
                options[system_id] = merged
            unknown = sorted(set(options).difference(specifications))
            if unknown:
                raise ValueError("adapter_options contains unknown systems: " + ", ".join(unknown))
            run_directory = Path(tempfile.mkdtemp(prefix="rdf-matrix-", dir=self._shared))
            summaries = []
            for experiment in experiments:
                system_id = experiment.system_configuration
                specification = specifications[system_id]
                representation = specification.configuration.representation
                artifact = artifacts[representation]
                output_path = run_directory / (system_id.replace("/", "--") + ".jsonl")
                module_name, separator, class_name = specification.adapter.partition(":")
                if not separator:
                    raise ValueError(f"invalid adapter path: {specification.adapter}")
                module = __import__(module_name, fromlist=[class_name])
                adapter_class = getattr(module, class_name)
                adapter = None
                if specification.configuration.kind == "server":
                    arguments = _constructor_arguments(
                        adapter_class, artifact, str(self._data_path),
                        str(self._config_path), str(self._directory), self._verbose,
                        specification.configuration, options.get(system_id, {}),
                    )
                    adapter = adapter_class(**arguments)
                    benchmark = SparqlHttpBenchmark(
                        str(self._data_path), str(self._config_path),
                        str(self._directory), self._verbose,
                    )
                    relative_output = output_path.relative_to(self._shared).as_posix()
                    policy = experiment.execution_policy
                    lifecycle = adapter.run(lambda endpoint: benchmark.execute(
                        endpoint=endpoint,
                        manifest_file=manifest_file,
                        results_file=relative_output,
                        experiment_id=experiment.experiment_id,
                        system=system_id,
                        timeout_s=float(policy["timeout_s"]),
                        warmup_runs=int(policy["warmup_runs"]),
                        measured_runs=int(policy["measured_runs"]),
                        correctness_mode="fingerprint",
                    ))
                    if not lifecycle.success:
                        raise RuntimeError(
                            f"system lifecycle failed for {system_id}: {lifecycle.error}"
                        )
                elif specification.parameters.get("engine") in {"default", "vortex", "cottas"}:
                    query = RdfLibQueryBenchmark(
                        str(self._data_path), str(self._config_path),
                        str(self._directory), self._verbose,
                    )
                    policy = experiment.execution_policy
                    query_parameters = {
                        "engine": specification.parameters["engine"],
                        "artifact_file": artifact.files[0].path,
                        "manifest_file": manifest_file,
                        "results_file": output_path.relative_to(self._shared).as_posix(),
                        "experiment_id": experiment.experiment_id,
                        "system": system_id,
                        "warmup_runs": int(policy["warmup_runs"]),
                        "measured_runs": int(policy["measured_runs"]),
                        "timeout_s": float(policy["timeout_s"]),
                        "timeout_mode": "worker",
                        "correctness_mode": "fingerprint",
                    }
                    if "vortex_layout" in specification.parameters:
                        query_parameters["vortex_layout"] = specification.parameters["vortex_layout"]
                    if not query.execute(**query_parameters):
                        raise RuntimeError(f"RDFLib-backed execution failed for {system_id}")
                elif specification.configuration.kind == "file-backed":
                    adapter = adapter_class(**dict(options.get(system_id, {})))
                    _run_file_backed(
                        adapter, self._shared / artifact.files[0].path,
                        manifest_path, output_path, experiment, system_id,
                    )
                else:
                    raise ValueError(f"no generic execution strategy for {system_id}")
                summaries.append(_result_summary(output_path, experiment, representation))

            summary_path = resolve_shared_path(str(self._shared), results_file, "Output")
            archive_path = resolve_shared_path(str(self._shared), output_file, "Output")
            summary_temporary = temporary_output(summary_path)
            _atomic_json(summary_temporary, {
                "schema": SUMMARY_SCHEMA,
                "declaration_sha256": _sha256(declaration_path),
                "manifest_sha256": _sha256(manifest_path),
                "experiments": summaries,
            })
            archive_temporary = temporary_output(archive_path)
            with tarfile.open(archive_temporary, "w:gz") as archive:
                for path in sorted(run_directory.glob("*.jsonl")):
                    archive.add(path, arcname=path.name, recursive=False)
            commit_output(summary_temporary, summary_path)
            summary_temporary = None
            commit_output(archive_temporary, archive_path)
            archive_temporary = None
            self._logger.info(f"Completed {len(summaries)} RDF experiment bindings")
            return True
        except Exception as error:
            self._logger.error(
                f"RDF experiment matrix failed: {type(error).__name__}: {error}"
            )
            return False
        finally:
            discard_output(summary_temporary)
            discard_output(archive_temporary)
            if run_directory is not None:
                shutil.rmtree(run_directory, ignore_errors=True)
