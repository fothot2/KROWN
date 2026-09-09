"""Build immutable query-quarantine snapshots from v1 or v2 ledgers."""
from __future__ import annotations

import errno
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from bench_executor.query_quarantine_resolver import (
    resolve_snapshot,
    validate_snapshot,
)


def publish_snapshot_no_overwrite(path: Path, snapshot: Mapping[str, Any]) -> None:
    """Validate and publish one snapshot without replacing an existing file."""
    target = Path(path)
    validate_snapshot(snapshot)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"snapshot output already exists: {target}")
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            raise FileExistsError(f"snapshot output already exists: {target}")
        except OSError as error:
            if error.errno not in {errno.EPERM, errno.EOPNOTSUPP}:
                raise
            descriptor = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(
                        snapshot, stream, indent=2, sort_keys=True,
                        allow_nan=False,
                    )
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        validate_snapshot(json.loads(target.read_text(encoding="utf-8")))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_snapshot_from_paths(
    ledger_path: Path,
    policy_path: Path,
    output_path: Path,
    created_at_utc: str,
) -> dict[str, Any]:
    """Load explicit inputs and publish one new immutable snapshot."""
    ledger_path = Path(ledger_path)
    policy_path = Path(policy_path)
    if not ledger_path.is_file():
        raise FileNotFoundError(f"ledger is not an existing file: {ledger_path}")
    if not policy_path.is_file():
        raise FileNotFoundError(f"policy is not an existing file: {policy_path}")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    snapshot = resolve_snapshot(ledger, policy, created_at_utc)
    publish_snapshot_no_overwrite(output_path, snapshot)
    return snapshot
