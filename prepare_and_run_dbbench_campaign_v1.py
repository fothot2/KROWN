#!/usr/bin/env python3
"""Prepare and launch the supported DBBench DBpedia campaign."""
from __future__ import annotations

import argparse
import json
import os
import hashlib
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
PRESERVED_TDB2_POINTER = SCENARIO / "preserved-fuseki-tdb2-path.txt"
TDB2_RECEIPT = BENCH_DATA / "fuseki-tdb2-store-receipt.json"
VIRTUOSO_POINTER = SCENARIO / "preserved-virtuoso-path.txt"
VIRTUOSO_RECEIPT = BENCH_DATA / "virtuoso-store-receipt.json"
QLEVER_POINTER = SCENARIO / "preserved-qlever-index-path.txt"
QLEVER_RECEIPT = BENCH_DATA / "qlever-index-receipt.json"
OXIGRAPH_POINTER = SCENARIO / "preserved-oxigraph-rocksdb-path.txt"
OXIGRAPH_RECEIPT = BENCH_DATA / "oxigraph-rocksdb-store-receipt.json"

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




def prepare_fuseki_tdb2_receipt() -> tuple[Path, Path]:
    if not PRESERVED_TDB2_POINTER.is_file():
        raise FileNotFoundError(PRESERVED_TDB2_POINTER)
    store = Path(PRESERVED_TDB2_POINTER.read_text().strip()).resolve()
    if not store.is_dir():
        raise FileNotFoundError(store)
    excluded = {'tdb.lock', 'journal.jrnl'}
    files = [
        {'path': item.relative_to(store).as_posix(), 'size_bytes': item.stat().st_size}
        for item in sorted(store.rglob('*'))
        if item.is_file() and item.name not in excluded
    ]
    if not files:
        raise RuntimeError('preserved Fuseki TDB2 store is empty')
    source = read_json(BENCH_DATA / 'rdf-source-receipt.json')
    atomic_json(TDB2_RECEIPT, {
        'schema': 'fuseki-tdb2-store-receipt-v1',
        'representation': 'fuseki/tdb2-store',
        'source_sha256': source['source']['sha256'],
        'source_size_bytes': source['source']['size_bytes'],
        'store_path': str(store),
        'files': files,
        'logical_bytes': sum(item['size_bytes'] for item in files),
        'allocated_bytes': sum(
            item.stat().st_blocks * 512 for item in store.rglob('*') if item.is_file()
        ),
    })
    return store, TDB2_RECEIPT



def prepare_virtuoso_receipt() -> tuple[Path, Path]:
    if not VIRTUOSO_POINTER.is_file():
        raise FileNotFoundError(
            'Virtuoso reuse requires ' + str(VIRTUOSO_POINTER)
        )
    store = Path(VIRTUOSO_POINTER.read_text().strip()).resolve()
    if not store.is_dir():
        raise FileNotFoundError(store)
    excluded = {
        'virtuoso-temp.db', 'virtuoso.ini', 'virtuoso.lck',
        'virtuoso.log', 'virtuoso.pxa', 'virtuoso.trx',
    }
    files = [
        {
            'path': item.relative_to(store).as_posix(),
            'size_bytes': item.stat().st_size,
        }
        for item in sorted(store.rglob('*'))
        if item.is_file() and item.name not in excluded
    ]
    if not files:
        raise RuntimeError('preserved Virtuoso store is empty')
    source = read_json(BENCH_DATA / 'rdf-source-receipt.json')
    atomic_json(VIRTUOSO_RECEIPT, {
        'schema': 'virtuoso-store-receipt-v1',
        'representation': 'virtuoso/store',
        'source_sha256': source['source']['sha256'],
        'source_size_bytes': source['source']['size_bytes'],
        'store_path': str(store),
        'files': files,
        'logical_bytes': sum(item['size_bytes'] for item in files),
        'allocated_bytes': sum(
            item.stat().st_blocks * 512
            for item in store.rglob('*')
            if item.is_file() and item.name not in excluded
        ),
    })
    return store, VIRTUOSO_RECEIPT



def prepare_qlever_receipt() -> tuple[Path, Path]:
    if not QLEVER_POINTER.is_file():
        raise FileNotFoundError(
            'QLever reuse requires ' + str(QLEVER_POINTER)
        )
    index = Path(QLEVER_POINTER.read_text().strip()).resolve()
    if not index.is_dir():
        raise FileNotFoundError(index)
    suffixes = ('.metrics-log.jsonl', '.resource-usage-log.tsv')
    files = [
        {
            'path': item.relative_to(index).as_posix(),
            'size_bytes': item.stat().st_size,
        }
        for item in sorted(index.rglob('*'))
        if item.is_file() and not item.name.endswith(suffixes)
    ]
    if not files:
        raise RuntimeError('preserved QLever index is empty')
    source = read_json(BENCH_DATA / 'rdf-source-receipt.json')
    atomic_json(QLEVER_RECEIPT, {
        'schema': 'qlever-index-receipt-v1',
        'representation': 'qlever/index',
        'source_sha256': source['source']['sha256'],
        'source_size_bytes': source['source']['size_bytes'],
        'index_path': str(index),
        'files': files,
        'logical_bytes': sum(item['size_bytes'] for item in files),
        'allocated_bytes': sum(
            item.stat().st_blocks * 512
            for item in index.rglob('*')
            if item.is_file() and not item.name.endswith(suffixes)
        ),
    })
    return index, QLEVER_RECEIPT


def prepare_oxigraph_receipt() -> tuple[Path, Path]:
    if not OXIGRAPH_POINTER.is_file():
        raise FileNotFoundError(
            "Oxigraph RocksDB reuse requires " + str(OXIGRAPH_POINTER)
        )
    store = Path(OXIGRAPH_POINTER.read_text().strip()).resolve()
    if not store.is_dir():
        raise FileNotFoundError(store)
    metadata_path = store / ".krown-oxigraph-store.json"
    metadata = read_json(metadata_path)
    if metadata.get("schema") != "oxigraph-rocksdb-build-metadata-v1":
        raise ValueError("invalid Oxigraph RocksDB build metadata")
    current = store / "CURRENT"
    if not current.is_file() or current.stat().st_size <= 0:
        raise RuntimeError("Oxigraph RocksDB CURRENT marker is missing")
    if not any(path.is_file() and path.stat().st_size > 0 for path in store.rglob("*.sst")):
        raise RuntimeError("Oxigraph RocksDB store has no SST files")
    source = read_json(BENCH_DATA / "rdf-source-receipt.json")
    if metadata.get("source_sha256") != source["source"]["sha256"]:
        raise ValueError("Oxigraph RocksDB source identity differs")
    atomic_json(OXIGRAPH_RECEIPT, {
        "schema": "oxigraph-rocksdb-store-receipt-v1",
        "representation": "oxigraph/rocksdb-store",
        "source_sha256": source["source"]["sha256"],
        "source_size_bytes": source["source"]["size_bytes"],
        "graph_triple_count": metadata["graph_triple_count"],
        "store_path": str(store),
    })
    return store, OXIGRAPH_RECEIPT

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
    # Warm only with deterministic selective triple-pattern queries.
    # Per-family first queries can include explosive many-to-many joins.
    warmup = [
        query for query in measured
        if query.get('source_top_group') == 'TP'
    ][:10]
    if len(warmup) != 10:
        raise RuntimeError(f'expected 10 deterministic TP warmups, found {len(warmup)}')

    records = []
    position = 0
    for ordinal, source in enumerate(warmup):
        item = dict(source)
        item["query_id"] = f"warmup/{ordinal:04d}/{source['query_id']}"
        item["source_query_id"] = source["query_id"]
        item["stream_phase"] = "warmup"
        item["stream_position"] = position
        item["reporting_family"] = reporting_family(source)
        item["comparison_mode"] = "count-only"
        item["comparison_warning"] = None
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
        item["comparison_mode"] = "count-only"
        item["comparison_warning"] = None
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
    parser.add_argument(
        "--virtuoso-mode", choices=("build", "reuse"), default="reuse"
    )
    parser.add_argument(
        "--qlever-mode", choices=("build", "reuse"), default="reuse"
    )
    parser.add_argument(
        "--oxigraph-rocksdb-mode",
        choices=("build", "reuse"),
        default="reuse",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.repetitions < 1:
        raise ValueError("--repetitions must be at least 1")
    unknown = sorted(set(args.system).difference(SUPPORTED_SYSTEMS))
    if unknown:
        raise ValueError("Unsupported systems: " + ", ".join(unknown))

    declaration_path, _ = prepare_files()
    reuse_store, reuse_receipt = prepare_fuseki_tdb2_receipt()
    virtuoso_store = virtuoso_receipt = None
    virtuoso_selected = (
        not args.system
        or 'virtuoso/default' in args.system
    )
    if (
        virtuoso_selected
        and args.virtuoso_mode == 'reuse'
    ):
        virtuoso_store, virtuoso_receipt = prepare_virtuoso_receipt()
    qlever_index = qlever_receipt = None
    qlever_selected = (
        not args.system
        or 'qlever/default' in args.system
    )
    if qlever_selected and args.qlever_mode == 'reuse':
        qlever_index, qlever_receipt = prepare_qlever_receipt()
    oxigraph_store = oxigraph_receipt = None
    oxigraph_selected = (
        not args.system
        or "oxigraph/rocksdb" in args.system
    )
    if oxigraph_selected and args.oxigraph_rocksdb_mode == "reuse":
        oxigraph_store, oxigraph_receipt = prepare_oxigraph_receipt()
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
    environment["KROWN_FUSEKI_TDB2_MODE"] = "reuse"
    environment["KROWN_FUSEKI_TDB2_REUSE_PATH"] = str(reuse_store)
    environment["KROWN_FUSEKI_TDB2_RECEIPT"] = str(reuse_receipt)
    environment["KROWN_VIRTUOSO_MODE"] = args.virtuoso_mode
    if (
        virtuoso_selected
        and args.virtuoso_mode == 'reuse'
    ):
        environment["KROWN_VIRTUOSO_REUSE_PATH"] = str(virtuoso_store)
        environment["KROWN_VIRTUOSO_RECEIPT"] = str(virtuoso_receipt)
    environment["KROWN_QLEVER_MODE"] = args.qlever_mode
    if qlever_selected and args.qlever_mode == 'reuse':
        environment["KROWN_QLEVER_REUSE_PATH"] = str(qlever_index)
        environment["KROWN_QLEVER_RECEIPT"] = str(qlever_receipt)
    environment["KROWN_OXIGRAPH_ROCKSDB_MODE"] = args.oxigraph_rocksdb_mode
    environment.setdefault("KROWN_OXIGRAPH_BUILD_TIMEOUT_S", "10800")
    if oxigraph_selected and args.oxigraph_rocksdb_mode == "reuse":
        environment["KROWN_OXIGRAPH_ROCKSDB_REUSE_PATH"] = str(oxigraph_store)
        environment["KROWN_OXIGRAPH_ROCKSDB_RECEIPT"] = str(oxigraph_receipt)
    environment.setdefault("KROWN_RDFLIB_STARTUP_TIMEOUT_S", "1800")
    completed = subprocess.run(
        command,
        cwd=KROWN,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        return completed.returncode
    final_summary = DATA / "campaigns" / args.campaign_id / "final-summary.json"
    if not final_summary.is_file():
        return 1
    final = read_json(final_summary)
    return 0 if final.get("all_systems_reportable") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
