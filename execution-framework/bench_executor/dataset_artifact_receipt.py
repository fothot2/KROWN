#!/usr/bin/env python3
"""Verify an external representation receipt and construct a DatasetArtifact."""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from typing import Any
from bench_executor.experiment_matrix_contract import ArtifactFile, DatasetArtifact
_SHA=re.compile(r"^[0-9a-f]{64}$")
def _sha(path: Path)->str:
 d=hashlib.sha256()
 with path.open("rb") as f:
  for block in iter(lambda:f.read(1024*1024),b""): d.update(block)
 return d.hexdigest()
def load_dataset_artifact_receipt(path: str)->DatasetArtifact:
 receipt_path=Path(path).expanduser().resolve(); root=receipt_path.parent
 value=json.loads(receipt_path.read_text(encoding="utf-8"))
 if not isinstance(value,dict) or value.get("schema")!="rdf-representation-receipt-v1": raise ValueError("Unsupported representation receipt")
 required={"schema","benchmark","dataset","created_at_utc","source","representation","files","producer"}
 if set(value)!=required: raise ValueError("Representation receipt has unexpected fields")
 source=value["source"]
 if not isinstance(source,dict) or set(source)!={"format","size_bytes","sha256"} or not _SHA.fullmatch(str(source.get("sha256",""))): raise ValueError("Invalid source identity")
 files=[]
 for item in value["files"]:
  relative=Path(item["path"])
  if relative.is_absolute() or ".." in relative.parts: raise ValueError("Receipt file path must be relative and contained")
  target=(root/relative).resolve()
  try: target.relative_to(root)
  except ValueError as error: raise ValueError("Receipt file path escapes its directory") from error
  if not target.is_file() or target.stat().st_size!=item["size_bytes"] or _sha(target)!=item["sha256"]: raise ValueError(f"Representation file differs from receipt: {relative.as_posix()}")
  files.append(ArtifactFile(relative.as_posix(),item["size_bytes"],item["sha256"]))
 return DatasetArtifact(benchmark=value["benchmark"],dataset=value["dataset"],source_format=source["format"],source_size_bytes=source["size_bytes"],source_sha256=source["sha256"],representation=value["representation"],files=tuple(files),producer=value["producer"])
