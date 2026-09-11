#!/usr/bin/env python3
"""Canonical outcome contract for RDF benchmark attempts and matrices."""
from __future__ import annotations
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

SCHEMA = 'rdf-attempt-outcome-v1'
CATEGORIES = frozenset({'completed','timeout','skipped','engine-error','semantic-mismatch','confirmed-oom'})
_ERROR_STATUSES = frozenset({'engine_error','connection_error','parse_error','result_error'})

def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ''

def classify_query_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one record without inferring OOM from RSS, size, signal, or exit code."""
    status = record.get('status')
    evidence = record.get('oom_evidence')
    confirmed = isinstance(evidence, Mapping) and evidence.get('confirmed') is True
    if confirmed:
        if evidence.get('rule') != 'confirmed-process-memory-exhaustion-only':
            raise ValueError('confirmed OOM requires the strict OOM rule')
        if not _text(evidence.get('source')) or not _text(evidence.get('detail')):
            raise ValueError('confirmed OOM requires source and detail evidence')
        category = 'confirmed-oom'
    elif status == 'timeout': category = 'timeout'
    elif status in {'skipped','unsupported'}: category = 'skipped'
    elif status == 'validation_mismatch': category = 'semantic-mismatch'
    elif status in _ERROR_STATUSES: category = 'engine-error'
    elif status == 'ok': category = 'completed'
    else: raise ValueError(f'cannot classify query status: {status!r}')
    if category == 'skipped':
        reason = record.get('skip_reason') or record.get('reason')
        if not _text(reason): raise ValueError('skipped outcome requires a reason')
        kind = record.get('skip_kind')
        if kind in {'manual-query-flavour-policy','automatic-query-flavour-quarantine'}:
            policy = record.get('skip_policy_id') or record.get('policy_id')
            digest = record.get('skip_policy_sha256') or record.get('policy_sha256')
            if not _text(policy) or not _text(digest):
                raise ValueError('policy-driven skip requires policy identity and SHA-256 provenance')
    return {'schema':SCHEMA,'category':category,'detail_status':status,'confirmed_oom':category=='confirmed-oom'}

def normalize_query_record(record: Mapping[str, Any]) -> dict[str, Any]:
    value=dict(record); expected=classify_query_record(value)
    supplied=value.get('outcome')
    if supplied is not None and supplied != expected:
        raise ValueError('query outcome does not match canonical classification')
    value['outcome']=expected
    return value

def outcome_counts(records: Iterable[Mapping[str, Any]]) -> dict[str,int]:
    counts=Counter(classify_query_record(r)['category'] for r in records)
    return {name:counts.get(name,0) for name in sorted(CATEGORIES)}

def matrix_status(counts: Mapping[str,int]) -> str:
    total=sum(counts.get(name,0) for name in CATEGORIES)
    if total == 0: return 'failed'
    limitations=sum(counts.get(name,0) for name in CATEGORIES-{'completed'})
    return 'ok' if limitations == 0 else 'completed_with_failures'

def validate_summary_counts(records: Iterable[Mapping[str,Any]], summary: Mapping[str,Any]) -> None:
    rows=list(records); counts=outcome_counts(rows)
    if summary.get('outcome_counts') != counts: raise ValueError('outcome counts do not match records')
    if summary.get('record_count') != len(rows): raise ValueError('record count does not match records')
    if summary.get('success_count') != counts['completed']: raise ValueError('success count does not match outcomes')
    failures=counts['timeout']+counts['engine-error']+counts['semantic-mismatch']+counts['confirmed-oom']
    if summary.get('failure_count') != failures: raise ValueError('failure count does not match outcomes')
    if summary.get('skipped_count') != counts['skipped']: raise ValueError('skipped count does not match outcomes')
