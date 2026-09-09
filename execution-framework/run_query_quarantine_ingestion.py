#!/usr/bin/env python3
"""Convert one completed matrix bundle into one evidence document."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_executor.query_quarantine_ingestion_output import (
    build_ingestion_document_from_paths,
)


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(
        description="Create one historical evidence document from one matrix run."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--adapter-identity", required=True)
    parser.add_argument("--artifact-identity", required=True)
    parser.add_argument("--created-at-utc", required=True)
    parser.add_argument("--selector-kind", default="bsbm_template_id")
    parser.add_argument("--summary-sha256")
    parser.add_argument("--archive-sha256")
    parser.add_argument("--exclusion-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv=None):
    arguments = parse_arguments(argv)
    try:
        document = build_ingestion_document_from_paths(
            summary_path=arguments.summary,
            archive_path=arguments.archive,
            manifest_path=arguments.manifest,
            declaration_path=arguments.declaration,
            run_id=arguments.run_id,
            system=arguments.system,
            adapter_identity=arguments.adapter_identity,
            artifact_identity=arguments.artifact_identity,
            created_at_utc=arguments.created_at_utc,
            selector_kind=arguments.selector_kind,
            expected_summary_sha256=arguments.summary_sha256,
            expected_archive_sha256=arguments.archive_sha256,
            exclusion_report_path=arguments.exclusion_report,
            output_path=arguments.output,
        )
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("QUERY QUARANTINE EVIDENCE DOCUMENT BUILD: OK")
    print(f"Output: {arguments.output}")
    print(f"Observations: {len(document['observations'])}")
    print(f"Document SHA-256: {document['document_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
