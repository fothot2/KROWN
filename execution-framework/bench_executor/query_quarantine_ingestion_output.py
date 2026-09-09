"""Write one historical evidence document from one explicit matrix bundle."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bench_executor.query_quarantine_contract import content_sha256
from bench_executor.query_quarantine_ingestion import ingest_matrix_bundle
from bench_executor.query_quarantine_ledger_build import (
    INGESTION_CLASSIFICATION,
    INGESTION_SCHEMA,
    validate_ingestion_document,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_ingestion_document(
    *,
    summary_path: Path,
    archive_path: Path,
    manifest_path: Path,
    declaration_path: Path,
    run_id: str,
    system: str,
    adapter_identity: str,
    artifact_identity: str,
    created_at_utc: str,
    selector_kind: str = "bsbm_template_id",
    expected_summary_sha256: str | None = None,
    expected_archive_sha256: str | None = None,
    exclusion_report_path: Path | None = None,
) -> dict[str, Any]:
    """Ingest explicit source files and build one validated evidence document."""
    manifest_path = Path(manifest_path)
    declaration_path = Path(declaration_path)
    for path, label in (
        (manifest_path, "manifest"),
        (declaration_path, "declaration"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is not an existing file: {path}")
    if not isinstance(created_at_utc, str) or not created_at_utc.strip():
        raise ValueError("created_at_utc must be non-empty")
    observations = ingest_matrix_bundle(
        summary_path=Path(summary_path),
        archive_path=Path(archive_path),
        manifest_path=manifest_path,
        declaration_path=declaration_path,
        run_id=run_id,
        system=system,
        adapter_identity=adapter_identity,
        artifact_identity=artifact_identity,
        selector_kind=selector_kind,
        expected_summary_sha256=expected_summary_sha256,
        expected_archive_sha256=expected_archive_sha256,
        exclusion_report_path=exclusion_report_path,
    )
    body = {
        "schema": INGESTION_SCHEMA,
        "created_at_utc": created_at_utc,
        "classification": INGESTION_CLASSIFICATION,
        "source_bundle": {
            "summary_sha256": observations[0].source_summary_sha256,
            "archive_sha256": observations[0].source_archive_sha256,
            "manifest_sha256": _sha256_file(manifest_path),
            "declaration_sha256": _sha256_file(declaration_path),
            "run_id": run_id,
        },
        "observations": [item.to_dict() for item in observations],
    }
    document = {**body, "document_sha256": content_sha256(body)}
    validate_ingestion_document(document)
    return document


def publish_ingestion_document_no_overwrite(
    path: Path, document: Mapping[str, Any]
) -> None:
    """Publish one validated evidence document without overwrite."""
    target = Path(path)
    validate_ingestion_document(document)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"evidence document output already exists: {target}")
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            raise FileExistsError(
                f"evidence document output already exists: {target}"
            )
        except OSError as error:
            if error.errno not in {errno.EPERM, errno.EOPNOTSUPP}:
                raise
            descriptor = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(
                        document, stream, indent=2, sort_keys=True,
                        allow_nan=False,
                    )
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        validate_ingestion_document(
            json.loads(target.read_text(encoding="utf-8"))
        )
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_ingestion_document_from_paths(
    *, output_path: Path, **arguments: Any
) -> dict[str, Any]:
    """Build and publish one evidence document."""
    document = build_ingestion_document(**arguments)
    publish_ingestion_document_no_overwrite(output_path, document)
    return document
