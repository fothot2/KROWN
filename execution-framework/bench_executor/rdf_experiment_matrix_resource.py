#!/usr/bin/env python3
"""Execute one external RDF experiment declaration across registered systems."""
from __future__ import annotations

import hashlib
import inspect
import importlib.util
import json
import os
import shutil
import socket
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

PREFLIGHT_SCHEMA = "rdf-experiment-matrix-preflight-v1"
_PLACEHOLDER_MARKERS = ("<", ">", "todo", "replace-me", "validated ")
_ENGINE_MODULES = {
    "default": "rdflib",
    "cottas": "pycottas.cottas_store",
    "vortex": "vortex_rdflib",
}


def _require_concrete_runtime_value(value: Any, field: str) -> str:
    """Return one explicit value and reject shell-style placeholders."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    lowered = normalized.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        raise ValueError(f"{field} contains a placeholder value")
    return normalized


def _docker_image_available(image: str) -> bool:
    """Check local image metadata without pulling or starting a container."""
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _selected_experiments(experiments, selected_systems):
    """Select systems in declaration order without changing benchmark intent."""
    if selected_systems is None:
        return tuple(experiments)
    if not isinstance(selected_systems, (list, tuple)) or not selected_systems:
        raise ValueError("selected_systems must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip()
           for item in selected_systems):
        raise ValueError("selected_systems entries must be non-empty strings")
    normalized = [item.strip() for item in selected_systems]
    if len(set(normalized)) != len(normalized):
        raise ValueError("selected_systems contains duplicate systems")
    available = {item.system_configuration for item in experiments}
    unknown = sorted(set(normalized).difference(available))
    if unknown:
        raise ValueError("selected_systems contains unknown systems: " + ", ".join(unknown))
    selected = set(normalized)
    return tuple(item for item in experiments
                 if item.system_configuration in selected)


def _environment_system_selection(variable, environment=None):
    """Read one optional comma-separated runtime selection."""
    if variable is None:
        return None
    if not isinstance(variable, str) or not variable.strip():
        raise ValueError("selected_systems_env must be a non-empty string")
    source = os.environ if environment is None else environment
    value = source.get(variable)
    if value is None or not value.strip():
        return None
    return [item.strip() for item in value.split(",")]


def _running_krown_containers() -> list[str]:
    """Return running containers whose stable names belong to matrix systems."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        text=True, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("cannot inspect running Docker containers")
    prefixes = ("Fuseki", "Virtuoso", "QLever", "Oxigraph-")
    return sorted(name for name in result.stdout.splitlines()
                  if name.startswith(prefixes))


def _port_available(port: int) -> bool:
    """Check whether one loopback TCP port can be bound now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _runtime_preflight(
        declaration_path: Path,
        manifest_path: Path,
        adapter_options: Mapping[str, Mapping[str, Any]] | None = None,
        adapter_option_env: Mapping[str, Mapping[str, str]] | None = None,
        environment: Mapping[str, str] | None = None,
        selected_systems: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    """Build and validate a complete plan without starting query systems."""
    if not declaration_path.is_file():
        raise FileNotFoundError(f"experiment declaration is missing: {declaration_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"query manifest is missing: {manifest_path}")
    _load_query_manifest(str(manifest_path))
    experiments, artifacts = load_rdf_experiment_declaration(declaration_path)
    declared_systems = [item.system_configuration for item in experiments]
    experiments = _selected_experiments(experiments, selected_systems)
    specifications = {item.system_id: item for item in system_adapter_specifications()}
    options = {} if adapter_options is None else {
        key: dict(value) for key, value in adapter_options.items()
    }
    environment_options = _environment_adapter_options(
        adapter_option_env, environment
    )
    for system_id, values in environment_options.items():
        merged = dict(options.get(system_id, {}))
        merged.update(values)
        options[system_id] = merged
    unknown = sorted(set(options).difference(specifications))
    if unknown:
        raise ValueError("adapter_options contains unknown systems: " + ", ".join(unknown))

    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker executable is not available")
    daemon = subprocess.run(
        [docker, "info", "--format", "{{json .ServerVersion}}"],
        text=True, capture_output=True, check=False,
    )
    if daemon.returncode != 0:
        raise RuntimeError("Docker daemon is not available")
    stale_containers = _running_krown_containers()
    if stale_containers:
        raise RuntimeError(
            "matrix-owned Docker containers are already running: "
            + ", ".join(stale_containers)
        )

    images: set[str] = set()
    ports: set[int] = set()
    modules: set[str] = set()
    plan = []
    for experiment in experiments:
        system_id = experiment.system_configuration
        specification = specifications[system_id]
        module_name, separator, class_name = specification.adapter.partition(":")
        if not separator:
            raise ValueError(f"invalid adapter path: {specification.adapter}")
        module = __import__(module_name, fromlist=[class_name])
        adapter_class = getattr(module, class_name)
        supplied = dict(options.get(system_id, {}))
        for name, value in list(supplied.items()):
            if isinstance(value, str):
                supplied[name] = _require_concrete_runtime_value(
                    value, f"{system_id}.{name}"
                )
        configuration = specification.configuration
        artifact = artifacts[configuration.representation]
        if configuration.kind == "server":
            _constructor_arguments(
                adapter_class, artifact, "/preflight/data", "/preflight/config",
                "/preflight/log", False, configuration, supplied,
            )
        engine = specification.parameters.get("engine")
        if engine in _ENGINE_MODULES:
            modules.add(_ENGINE_MODULES[engine])
        image = supplied.get("image") or configuration.parameters.get("image")
        if isinstance(image, str):
            images.add(_require_concrete_runtime_value(image, f"{system_id}.image"))
        if system_id == "fuseki/default":
            images.add("kgconstruct/fuseki:v6.2.0"); ports.add(3030)
        elif system_id == "virtuoso/default":
            images.add("kgconstruct/virtuoso:v7.2.17"); ports.update((1111, 8890))
        elif system_id == "qlever/default":
            images.add(str(supplied.get("image", "kgconstruct/qlever:v0.6.0")))
            ports.add(int(supplied.get("port", 7001)))
        elif system_id.startswith("oxigraph/"):
            images.add("dtaikg/oxigraph:0.5.9"); ports.add(int(supplied.get("port", 7878)))
        elif system_id == "comunica/hdt":
            images.add(str(configuration.parameters["image"]))
        plan.append({
            "experiment_id": experiment.experiment_id,
            "system": system_id,
            "kind": configuration.kind,
            "representation": configuration.representation,
            "artifact_files": [item.path for item in artifact.files],
            "adapter": specification.adapter,
        })

    missing_modules = sorted(
        name for name in modules if importlib.util.find_spec(name) is None
    )
    if missing_modules:
        raise RuntimeError("missing Python runtime modules: " + ", ".join(missing_modules))
    missing_images = sorted(image for image in images if not _docker_image_available(image))
    if missing_images:
        raise RuntimeError("missing local Docker images: " + ", ".join(missing_images))
    busy_ports = sorted(port for port in ports if not _port_available(port))
    if busy_ports:
        raise RuntimeError("required TCP ports are busy: " + ", ".join(map(str, busy_ports)))
    return {
        "schema": PREFLIGHT_SCHEMA,
        "declaration_sha256": _sha256(declaration_path),
        "manifest_sha256": _sha256(manifest_path),
        "docker_server_version": json.loads(daemon.stdout),
        "required_images": sorted(images),
        "required_python_modules": sorted(modules),
        "required_ports": sorted(ports),
        "declared_systems": declared_systems,
        "selected_systems": [item["system"] for item in plan],
        "experiments": plan,
    }


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


_COMPACT_RESULT_FIELDS = (
    "query_id", "phase", "run", "status", "elapsed_ns",
    "result_count", "result_fingerprint",
)


def _compact_result_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only fields needed for timing and semantic comparison."""
    missing = [name for name in _COMPACT_RESULT_FIELDS if name not in record]
    if missing:
        raise ValueError("result record misses compact fields: " + ", ".join(missing))
    compact = {name: record[name] for name in _COMPACT_RESULT_FIELDS}
    if record["status"] != "ok":
        for name in ("error_type", "error_message"):
            value = record.get(name)
            if value is not None:
                compact[name] = value
    return compact


def _compact_result_file(path: Path) -> None:
    """Replace one validated matrix JSONL file with its compact form."""
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                records.append(_compact_result_record(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise ValueError(f"cannot compact result line {line_number}: {error}") from error
    if not records:
        raise ValueError(f"empty result artifact: {path}")
    temporary = path.with_name(f".{path.name}.compact.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, separators=(",", ":"), allow_nan=False))
                stream.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_result_bundle(
        run_directory: Path, summary_path: Path, archive_path: Path,
        experiments: list[dict[str, Any]], status: str,
        failed_system: str | None = None, error: str | None = None) -> None:
    """Publish one compact atomic summary and archive."""
    summary = {"status": status, "experiments": experiments}
    if failed_system is not None:
        summary["failed_system"] = failed_system
    if error is not None:
        summary["error"] = error
    summary_temporary = temporary_output(summary_path)
    archive_temporary = temporary_output(archive_path)
    try:
        _atomic_json(summary_temporary, summary)
        with tarfile.open(archive_temporary, "w:gz") as archive:
            for path in sorted(run_directory.glob("*.jsonl")):
                archive.add(path, arcname=path.name, recursive=False)
        commit_output(summary_temporary, summary_path)
        summary_temporary = None
        commit_output(archive_temporary, archive_path)
        archive_temporary = None
    finally:
        discard_output(summary_temporary)
        discard_output(archive_temporary)


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
        "system": experiment.system_configuration,
        "representation": representation,
        "record_count": len(records),
        "failure_count": failures,
        "result_file": path.name,
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

    def preflight(
            self,
            declaration_file: str,
            manifest_file: str,
            output_file: str,
            adapter_options: Mapping[str, Mapping[str, Any]] | None = None,
            adapter_option_env: Mapping[str, Mapping[str, str]] | None = None,
            selected_systems: list[str] | None = None,
            selected_systems_env: str | None = None) -> bool:
        """Publish a dry runtime plan without starting any query system."""
        temporary = None
        try:
            declaration_path = Path(declaration_file).expanduser().resolve()
            manifest_path = input_file(str(self._shared), manifest_file)
            environment_selection = _environment_system_selection(
                selected_systems_env
            )
            if selected_systems is not None and environment_selection is not None:
                raise ValueError(
                    "selected_systems and selected_systems_env are mutually exclusive"
                )
            selection = selected_systems if selected_systems is not None else environment_selection
            report = _runtime_preflight(
                declaration_path, manifest_path, adapter_options,
                adapter_option_env, selected_systems=selection,
            )
            output_path = resolve_shared_path(
                str(self._shared), output_file, "Output"
            )
            temporary = temporary_output(output_path)
            _atomic_json(temporary, report)
            commit_output(temporary, output_path)
            temporary = None
            self._logger.info(
                f"Preflight validated {len(report['experiments'])} RDF bindings"
            )
            return True
        except Exception as error:
            self._logger.error(
                f"RDF experiment preflight failed: {type(error).__name__}: {error}"
            )
            return False
        finally:
            discard_output(temporary)

    def execute(
            self,
            declaration_file: str,
            manifest_file: str,
            results_file: str,
            output_file: str,
            adapter_options: Mapping[str, Mapping[str, Any]] | None = None,
            adapter_option_env: Mapping[str, Mapping[str, str]] | None = None,
            selected_systems: list[str] | None = None,
            selected_systems_env: str | None = None,
            failure_results_file: str | None = None,
            failure_output_file: str | None = None) -> bool:
        """Execute selected declaration bindings and publish summary plus archive."""
        run_directory = None
        summaries: list[dict[str, Any]] = []
        current_system: str | None = None
        try:
            declaration_path = Path(declaration_file).expanduser().resolve()
            if not declaration_path.is_file():
                raise FileNotFoundError(f"experiment declaration is missing: {declaration_path}")
            manifest_path = input_file(str(self._shared), manifest_file)
            environment_selection = _environment_system_selection(
                selected_systems_env
            )
            if selected_systems is not None and environment_selection is not None:
                raise ValueError(
                    "selected_systems and selected_systems_env are mutually exclusive"
                )
            selection = selected_systems if selected_systems is not None else environment_selection
            _runtime_preflight(
                declaration_path, manifest_path, adapter_options,
                adapter_option_env, selected_systems=selection,
            )
            experiments, original_artifacts = load_rdf_experiment_declaration(declaration_path)
            experiments = _selected_experiments(experiments, selection)
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
                current_system = system_id
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
                _compact_result_file(output_path)
                summaries.append(_result_summary(output_path, experiment, representation))

            summary_path = resolve_shared_path(str(self._shared), results_file, "Output")
            archive_path = resolve_shared_path(str(self._shared), output_file, "Output")
            _publish_result_bundle(
                run_directory, summary_path, archive_path, summaries, "ok"
            )
            self._logger.info(f"Completed {len(summaries)} RDF experiment bindings")
            return True
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            self._logger.error(f"RDF experiment matrix failed: {message}")
            if (run_directory is not None and failure_results_file is not None
                    and failure_output_file is not None):
                try:
                    failure_summary = resolve_shared_path(
                        str(self._shared), failure_results_file, "Output"
                    )
                    failure_archive = resolve_shared_path(
                        str(self._shared), failure_output_file, "Output"
                    )
                    _publish_result_bundle(
                        run_directory, failure_summary, failure_archive, summaries,
                        "failed", current_system, message,
                    )
                except Exception as publish_error:
                    self._logger.error(
                        "Failed to publish matrix diagnostics: "
                        f"{type(publish_error).__name__}: {publish_error}"
                    )
            return False
        finally:
            if run_directory is not None:
                shutil.rmtree(run_directory, ignore_errors=True)
