#!/usr/bin/env python3
"""Prepare and launch the supported DBBench DBpedia campaign."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

KROWN = Path("/users/u0182905/KROWN")
BENCHMARKS = Path("/users/u0182905/benchmarks")
DBBENCH = BENCHMARKS / "DBBench"
DBPEDIA = Path("/users/u0182905/DBPedia")
CURRENT = DBPEDIA / "data/current-evaluation"
SCENARIO = KROWN / "benchmark-integration/dbbench-dbpedia"
DATA = SCENARIO / "data/shared"
MANIFESTS = DATA / "manifests"
EXPERIMENTS = DBBENCH / "experiments"
BENCH_DATA = DBBENCH / "data/dbpedia-en-all"

VALIDATION_GATE_CAMPAIGN_ID = 'dbbench-dbpedia-vortex-gate-20260921T185447Z'

SUPPORTED_SYSTEMS = (
    "fuseki/memory",
    "fuseki/tdb2",
    "virtuoso/default",
    "qlever/default",
    "oxigraph/memory",
    "oxigraph/rocksdb",
    "pycottas/default",
    "rdflib/default",
    "vortex-rdf/dictionary-secondary-by-reference",
    "vortex-rdf/dictionary-secondary-by-reference-memory",
    "vortex-rdf/dictionary-secondary-by-copy",
    "vortex-rdf/dictionary-secondary-by-copy-memory",
)

RECEIPTS = {
    "rdf/source": "rdf-source-receipt.json",
    "cottas/default": "cottas-default-receipt.json",
    "vortex-rdf/dictionary-secondary-by-reference": "vortex-rdf-dictionary-secondary-by-reference-receipt.json",
    "vortex-rdf/dictionary-secondary-by-copy": "vortex-rdf-dictionary-secondary-by-copy-receipt.json",
}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def link_artifact(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_file() or not source.samefile(target):
            raise RuntimeError(f"Existing artifact is not the expected hard link: {target}")
        return
    try:
        os.link(source, target)
    except OSError as error:
        raise RuntimeError(
            f"Cannot hard-link {source} to {target}; refusing to duplicate a large artifact"
        ) from error


def stage_receipts() -> None:
    BENCH_DATA.mkdir(parents=True, exist_ok=True)
    for representation, receipt_name in RECEIPTS.items():
        source_receipt = CURRENT / receipt_name
        if not source_receipt.is_file():
            raise FileNotFoundError(f"Required receipt is missing: {source_receipt}")
        value = read_json(source_receipt)
        if value.get("representation") != representation:
            raise ValueError(f"Receipt representation differs: {source_receipt}")
        rewritten = dict(value)
        rewritten_files = []
        for item in value["files"]:
            source_file = source_receipt.parent / item["path"]
            target_file = BENCH_DATA / item["path"]
            link_artifact(source_file, target_file)
            rewritten_files.append(dict(item))
        rewritten["files"] = rewritten_files
        atomic_json(BENCH_DATA / receipt_name, rewritten)

    source_receipt = read_json(BENCH_DATA / "rdf-source-receipt.json")
    inventory = {
        "schema": "rdf-dataset-inventory-v1",
        "benchmark": "dbbench",
        "dataset": "dbpedia-en-all",
        "source": source_receipt["source"],
        "representations": [
            {"representation": representation, "receipt": receipt_name}
            for representation, receipt_name in RECEIPTS.items()
        ],
    }
    atomic_json(BENCH_DATA / "dataset-inventory.json", inventory)



def validated_invalid_source_queries() -> tuple[set[str], list[dict[str, Any]]]:
    """Return the deterministic invalid source-query set from the 3-run gate."""
    per_run: list[set[str]] = []
    evidence: dict[str, dict[str, Any]] = {}
    for repetition in range(1, 4):
        system_root = (
            DATA / 'executions'
            / f'{VALIDATION_GATE_CAMPAIGN_ID}-r{repetition:02d}'
            / 'systems/vortex-rdf--dictionary-secondary-by-copy-memory'
        )
        archive_path = None
        for name in ('results.tar.gz', 'failed-results.tar.gz'):
            candidate = system_root / name
            if candidate.is_file():
                archive_path = candidate
                break
        if archive_path is None:
            raise FileNotFoundError(
                f'validation gate result archive is missing: {system_root}'
            )
        invalid: set[str] = set()
        with tarfile.open(archive_path, 'r:gz') as archive:
            members = [
                member for member in archive.getmembers()
                if member.isfile() and member.name.endswith('.jsonl')
            ]
            if not members:
                raise RuntimeError(f'no JSONL result member in {archive_path}')
            for member in members:
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                for raw in stream:
                    if not raw.strip():
                        continue
                    record = json.loads(raw)
                    if record.get('phase') != 'measured':
                        continue
                    if record.get('status') != 'engine_error':
                        continue
                    source_id = record.get('source_query_id')
                    if not isinstance(source_id, str) or not source_id:
                        query_id = record.get('query_id')
                        if not isinstance(query_id, str) or not query_id:
                            raise RuntimeError(
                                'gate engine-error record misses query_id'
                            )
                        parts = query_id.split('/', 2)
                        if (
                            len(parts) != 3
                            or parts[0] not in {'warmup', 'measured'}
                            or not parts[1].isdigit()
                            or not parts[2]
                        ):
                            raise RuntimeError(
                                'cannot recover source query ID from '
                                f'query_id={query_id!r}'
                            )
                        source_id = parts[2]
                    invalid.add(source_id)
                    evidence.setdefault(source_id, {
                        'source_query_id': source_id,
                        'query_sha256': record.get('query_sha256'),
                        'reporting_family': record.get('reporting_family'),
                        'error_type': record.get('error_type'),
                        'error_message': record.get('error_message'),
                    })
        per_run.append(invalid)
    if not per_run or any(values != per_run[0] for values in per_run[1:]):
        raise RuntimeError(
            'validation-gate invalid-query sets differ across repetitions'
        )
    invalid = per_run[0]
    if len(invalid) != 20:
        raise RuntimeError(
            f'expected 20 deterministic invalid queries, found {len(invalid)}'
        )
    return invalid, [evidence[key] for key in sorted(invalid)]

def reporting_family(query: dict[str, Any]) -> str:
    metadata = query
    top = metadata.get("source_top_group")
    file_name = str(metadata.get("source_file_name", "unknown.txt"))
    stem = Path(file_name).stem
    if top == "TP":
        return f"TP/{stem}"
    if top == "JOINS":
        size = metadata.get("source_size_group") or "unknown"
        return f"JOINS/{size}/{stem}"
    return f"UNKNOWN/{stem}"


def prepare_base_manifest(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "DBBench.manifest",
        "--query-root",
        str(DBPEDIA / "queries"),
        "--output",
        str(path),
        "--workload",
        "dbbench-dbpedia-full",
        "--dataset",
        "dbpedia",
        "--groups",
        "TP",
        "JOINS",
        "--join-sizes",
        "small",
        "big",
    ]
    subprocess.run(command, cwd=BENCHMARKS, check=True)
    value = read_json(path)
    if value.get("query_count") != 4828:
        raise RuntimeError(f"Expected 4828 DBBench queries, found {value.get('query_count')}")
    return value


def preexpanded_manifest(
    base: dict[str, Any], invalid_source_ids: set[str]
) -> dict[str, Any]:
    measured = [
        query for query in base["queries"]
        if query["query_id"] not in invalid_source_ids
    ]
    by_family: dict[str, dict[str, Any]] = {}
    for query in measured:
        by_family.setdefault(reporting_family(query), query)
    warmup = [by_family[key] for key in sorted(by_family)]

    records = []
    position = 0
    for ordinal, source in enumerate(warmup):
        item = dict(source)
        item["query_id"] = f"warmup/{ordinal:04d}/{source['query_id']}"
        item["source_query_id"] = source["query_id"]
        item["stream_phase"] = "warmup"
        item["stream_position"] = position
        item["reporting_family"] = reporting_family(source)
        # Compatibility alias for the current generic in-run quarantine selector.
        item["bsbm_template_id"] = item["reporting_family"]
        records.append(item)
        position += 1
    for ordinal, source in enumerate(measured):
        item = dict(source)
        item["query_id"] = f"measured/{ordinal:04d}/{source['query_id']}"
        item["source_query_id"] = source["query_id"]
        item["stream_phase"] = "measured"
        item["stream_position"] = position
        item["reporting_family"] = reporting_family(source)
        item["bsbm_template_id"] = item["reporting_family"]
        records.append(item)
        position += 1

    return {
        "schema_version": 1,
        "workload": "dbbench-dbpedia-full",
        "dataset": "dbpedia-en-all",
        "source_format": "dbbench-preexpanded",
        "query_count": len(records),
        "source_query_count": len(measured),
        "warmup_query_count": len(warmup),
        "measured_query_count": len(measured),
        "duplicate_query_content": base.get("duplicate_query_content", []),
        "queries": records,
        "source": base.get("source"),
    }


def declaration() -> dict[str, Any]:
    bindings = [
        {"system": "fuseki/memory", "representation": "rdf/source"},
        {"system": "fuseki/tdb2", "representation": "rdf/source"},
        {"system": "virtuoso/default", "representation": "rdf/source"},
        {"system": "qlever/default", "representation": "rdf/source"},
        {"system": "oxigraph/memory", "representation": "rdf/source"},
        {"system": "oxigraph/rocksdb", "representation": "rdf/source"},
        {"system": "pycottas/default", "representation": "cottas/default"},
        {"system": "rdflib/default", "representation": "rdf/source"},
        {
            "system": "vortex-rdf/dictionary-secondary-by-reference",
            "representation": "vortex-rdf/dictionary-secondary-by-reference",
        },
        {
            "system": "vortex-rdf/dictionary-secondary-by-reference-memory",
            "representation": "vortex-rdf/dictionary-secondary-by-reference",
        },
        {
            "system": "vortex-rdf/dictionary-secondary-by-copy",
            "representation": "vortex-rdf/dictionary-secondary-by-copy",
        },
        {
            "system": "vortex-rdf/dictionary-secondary-by-copy-memory",
            "representation": "vortex-rdf/dictionary-secondary-by-copy",
        },
    ]
    return {
        "schema": "rdf-experiment-declaration-v1",
        "experiment": "dbbench/dbpedia-en-all/full",
        "benchmark": "dbbench",
        "dataset": "dbpedia-en-all",
        "workload": "dbbench-dbpedia-full",
        "inventory": "data/dbpedia-en-all/dataset-inventory.json",
        "representations": {
            representation: f"data/dbpedia-en-all/{receipt}"
            for representation, receipt in RECEIPTS.items()
        },
        "bindings": bindings,
        "execution_policy": {
            "warmup_runs": 0,
            "measured_runs": 1,
            "timeout_s": 5.0,
        },
    }


def prepare_files() -> tuple[Path, Path]:
    stage_receipts()
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    EXPERIMENTS.mkdir(parents=True, exist_ok=True)

    base_path = DBBENCH / "generated/dbpedia-full-base.json"
    base = prepare_base_manifest(base_path)
    invalid_source_ids, invalid_evidence = validated_invalid_source_queries()
    invalid_path = MANIFESTS / "dbbench-dbpedia-invalid-queries.json"
    atomic_json(invalid_path, {
        "schema": "dbbench-invalid-query-inventory-v1",
        "validation_campaign_id": VALIDATION_GATE_CAMPAIGN_ID,
        "invalid_query_count": len(invalid_evidence),
        "queries": invalid_evidence,
    })
    manifest_path = MANIFESTS / "dbbench-dbpedia-full.json"
    manifest = preexpanded_manifest(base, invalid_source_ids)
    manifest["invalid_query_inventory"] = invalid_path.name
    manifest["invalid_source_query_count"] = len(invalid_source_ids)
    atomic_json(manifest_path, manifest)

    declaration_path = EXPERIMENTS / "dbpedia-en-all-full.json"
    atomic_json(declaration_path, declaration())

    metadata = {
        "schema": "krown-external-benchmark-scenario-v1",
        "benchmark": "dbbench",
        "dataset": "dbpedia-en-all",
        "benchmark_repository": str(BENCHMARKS),
        "declarations": {"full": str(declaration_path)},
        "manifests": {"full": "manifests/dbbench-dbpedia-full.json"},
        "representation_build_ledger": str(CURRENT / "representation-build-ledger.json"),
        "excluded_representations": {
            "hdt/default": "confirmed construction OOM on the 64 GiB evaluation machine"
        },
    }
    atomic_json(SCENARIO / "metadata.json", metadata)
    return declaration_path, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--system", action="append", default=[])
    parser.add_argument("--system-limit-s", type=int, default=36000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.repetitions < 1:
        raise ValueError("--repetitions must be at least 1")
    unknown = sorted(set(args.system).difference(SUPPORTED_SYSTEMS))
    if unknown:
        raise ValueError("Unsupported systems: " + ", ".join(unknown))

    declaration_path, _ = prepare_files()
    if args.prepare_only:
        print("DBBENCH CAMPAIGN PREPARATION OK")
        print(f"declaration={declaration_path}")
        print(f"manifest={MANIFESTS / 'dbbench-dbpedia-full.json'}")
        return 0

    command = [
        sys.executable,
        str(KROWN / "execution-framework/run_rdf_campaign.py"),
        "--scenario",
        str(SCENARIO),
        "--declaration",
        str(declaration_path),
        "--benchmark-root",
        str(DBBENCH),
        "--manifest",
        "manifests/dbbench-dbpedia-full.json",
        "--repetitions",
        str(args.repetitions),
        "--system-limit-s",
        str(args.system_limit_s),
        "--campaign-id",
        args.campaign_id,
    ]
    for system in args.system:
        command.extend(("--system", system))
    if args.resume:
        command.append("--resume")
    if args.retry_failed:
        command.append("--retry-failed")

    print(" ".join(command), flush=True)
    if args.dry_run:
        return 0

    environment = dict(os.environ)
    environment["KROWN_IN_RUN_TIMEOUT_QUARANTINE_THRESHOLD"] = "20"
    environment.setdefault("KROWN_RDFLIB_STARTUP_TIMEOUT_S", "1800")
    return subprocess.run(command, cwd=KROWN, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
