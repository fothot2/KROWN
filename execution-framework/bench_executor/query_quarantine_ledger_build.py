"""Build immutable v2 query-quarantine evidence ledgers."""
from __future__ import annotations

import errno
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from bench_executor.query_quarantine_contract import EvidenceObservation, content_sha256
from bench_executor.query_quarantine_evidence import deduplicate_independent_observations

INGESTION_SCHEMA = "rdf-query-quarantine-ingestion-output-v1"
INGESTION_CLASSIFICATION = "historical-evidence-candidate"
LEDGER_V2_SCHEMA = "rdf-query-quarantine-evidence-ledger-v2"
_DOCUMENT_FIELDS = {"schema", "created_at_utc", "classification", "source_bundle", "observations", "document_sha256"}
_SOURCE_FIELDS = {"summary_sha256", "archive_sha256", "manifest_sha256", "declaration_sha256", "run_id"}
_LEDGER_FIELDS = {"schema", "created_at_utc", "source_ingestion_document_sha256s", "entries", "ledger_sha256"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty text without surrounding whitespace")
    return value


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 value")
    return value


def _document_body(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in sorted(_DOCUMENT_FIELDS - {"document_sha256"})}


def validate_ingestion_document(value: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[EvidenceObservation, ...]]:
    if not isinstance(value, Mapping):
        raise TypeError("ingestion document must be an object")
    if set(value) != _DOCUMENT_FIELDS or value.get("schema") != INGESTION_SCHEMA:
        raise ValueError("invalid ingestion document fields or schema")
    _text(value["created_at_utc"], "created_at_utc")
    if value.get("classification") != INGESTION_CLASSIFICATION:
        raise ValueError("ingestion classification must be historical-evidence-candidate")
    source = value.get("source_bundle")
    if not isinstance(source, Mapping) or set(source) != _SOURCE_FIELDS:
        raise ValueError("invalid source_bundle fields")
    for field in _SOURCE_FIELDS - {"run_id"}:
        _sha(source[field], f"source_bundle.{field}")
    run_id = _text(source["run_id"], "source_bundle.run_id")
    supplied_document_sha256 = _sha(value["document_sha256"], "document_sha256")
    if supplied_document_sha256 != content_sha256(_document_body(value)):
        raise ValueError("document_sha256 mismatch")
    raw_observations = value.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        raise ValueError("observations must be a non-empty array")
    observations = []
    evidence_ids = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping):
            raise TypeError("serialized observation must be an object")
        supplied = dict(raw)
        evidence_id = supplied.pop("evidence_id", None)
        compatibility_sha256 = supplied.pop("compatibility_sha256", None)
        observation = EvidenceObservation(**supplied)
        if evidence_id != observation.evidence_id:
            raise ValueError("evidence_id mismatch")
        if compatibility_sha256 != observation.compatibility_sha256:
            raise ValueError("compatibility_sha256 mismatch")
        if observation.run_id != run_id:
            raise ValueError("ingestion document contains mixed run IDs")
        if observation.source_summary_sha256 != source["summary_sha256"]:
            raise ValueError("source summary provenance mismatch")
        if observation.source_archive_sha256 != source["archive_sha256"]:
            raise ValueError("source archive provenance mismatch")
        if observation.evidence_id in evidence_ids:
            raise ValueError("duplicate observation inside ingestion document")
        evidence_ids.add(observation.evidence_id)
        observations.append(observation)
    normalized = {**_document_body(value), "document_sha256": supplied_document_sha256}
    return normalized, tuple(observations)


def load_ingestion_document(path: Path) -> tuple[str, tuple[EvidenceObservation, ...]]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"ingestion input is not an existing file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    normalized, observations = validate_ingestion_document(value)
    return normalized["document_sha256"], observations


def build_ledger_v2(documents: Iterable[tuple[str, tuple[EvidenceObservation, ...]]], created_at_utc: str) -> dict[str, Any]:
    created = _text(created_at_utc, "created_at_utc")
    document_hashes = set()
    observations = []
    for document_sha256, values in documents:
        document_hashes.add(_sha(document_sha256, "source ingestion document SHA-256"))
        observations.extend(values)
    if not document_hashes:
        raise ValueError("at least one ingestion document is required")
    entries = [item.to_dict() for item in deduplicate_independent_observations(observations)]
    body = {
        "schema": LEDGER_V2_SCHEMA,
        "created_at_utc": created,
        "source_ingestion_document_sha256s": sorted(document_hashes),
        "entries": entries,
    }
    return {**body, "ledger_sha256": content_sha256(body)}


def validate_ledger_v2(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _LEDGER_FIELDS:
        raise ValueError("invalid v2 ledger fields")
    if value.get("schema") != LEDGER_V2_SCHEMA:
        raise ValueError("unsupported v2 ledger schema")
    _text(value["created_at_utc"], "created_at_utc")
    hashes = value.get("source_ingestion_document_sha256s")
    if not isinstance(hashes, list) or not hashes or hashes != sorted(set(hashes)):
        raise ValueError("source ingestion document hashes must be a non-empty sorted unique array")
    for item in hashes:
        _sha(item, "source ingestion document SHA-256")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise TypeError("ledger entries must be an array")
    observations = []
    for raw in entries:
        supplied = dict(raw)
        evidence_id = supplied.pop("evidence_id", None)
        compatibility_sha256 = supplied.pop("compatibility_sha256", None)
        observation = EvidenceObservation(**supplied)
        if evidence_id != observation.evidence_id:
            raise ValueError("evidence_id mismatch")
        if compatibility_sha256 != observation.compatibility_sha256:
            raise ValueError("compatibility_sha256 mismatch")
        observations.append(observation)
    normalized_entries = [item.to_dict() for item in deduplicate_independent_observations(observations)]
    if entries != normalized_entries:
        raise ValueError("ledger entries are not canonical")
    body = {key: value[key] for key in ("schema", "created_at_utc", "source_ingestion_document_sha256s", "entries")}
    if value.get("ledger_sha256") != content_sha256(body):
        raise ValueError("ledger_sha256 mismatch")
    return {**body, "ledger_sha256": value["ledger_sha256"]}


def publish_ledger_no_overwrite(path: Path, ledger: Mapping[str, Any]) -> None:
    target = Path(path)
    validate_ledger_v2(ledger)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"ledger output already exists: {target}")
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(ledger, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            raise FileExistsError(f"ledger output already exists: {target}")
        except OSError as error:
            if error.errno not in {errno.EPERM, errno.EOPNOTSUPP}:
                raise
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(ledger, stream, indent=2, sort_keys=True, allow_nan=False)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        validate_ledger_v2(json.loads(target.read_text(encoding="utf-8")))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_ledger_from_paths(input_paths: Iterable[Path], output_path: Path, created_at_utc: str) -> dict[str, Any]:
    paths = [Path(path).resolve() for path in input_paths]
    if not paths:
        raise ValueError("at least one --input is required")
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate ingestion input path")
    documents = [load_ingestion_document(path) for path in paths]
    ledger = build_ledger_v2(documents, created_at_utc)
    publish_ledger_no_overwrite(output_path, ledger)
    return ledger
