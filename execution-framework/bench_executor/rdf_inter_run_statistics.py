"""Outcome-aware inter-run statistics for RDF query records."""
from __future__ import annotations
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

SCHEMA='rdf-inter-run-statistics-v1'
METHOD='linear-interpolation-r7'
OUTCOMES=('completed','timeout','skipped','engine-error','semantic-mismatch','confirmed-oom')
GROUP_FIELDS=('benchmark','dataset','workload','experiment_id','system','representation','query_id','phase','measurement_boundary','storage','process_temperature','lifecycle')

def _category(record: Mapping[str,Any]) -> str:
    outcome=record.get('outcome')
    category=outcome.get('category') if isinstance(outcome,Mapping) else None
    if category not in OUTCOMES: raise ValueError(f'invalid normalized outcome: {category!r}')
    return category

def _mode(record: Mapping[str,Any], name: str) -> Any:
    mode=record.get('execution_mode')
    return mode.get(name) if isinstance(mode,Mapping) else record.get(name)

def _key(record: Mapping[str,Any]) -> tuple[Any,...]:
    values=[]
    for name in GROUP_FIELDS:
        value=_mode(record,name) if name in {'storage','process_temperature','lifecycle'} else record.get(name)
        if value is None or value=='': raise ValueError(f'missing compatibility field: {name}')
        values.append(value)
    return tuple(values)

def _percentile(values: list[float], probability: float) -> float | None:
    if not values: return None
    ordered=sorted(values)
    if len(ordered)==1: return ordered[0]
    position=(len(ordered)-1)*probability
    lower=math.floor(position); upper=math.ceil(position)
    if lower==upper: return ordered[lower]
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)

def numeric_statistics(values: Iterable[int|float]) -> dict[str,Any]:
    numbers=list(values)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in numbers):
        raise ValueError('statistics values must be finite non-negative numbers')
    if not numbers:
        return {'observation_count':0,'minimum':None,'maximum':None,'mean':None,'median':None,'sample_standard_deviation':None,'p50':None,'p90':None,'p95':None,'p99':None}
    return {
      'observation_count':len(numbers),'minimum':min(numbers),'maximum':max(numbers),
      'mean':statistics.fmean(numbers),'median':statistics.median(numbers),
      'sample_standard_deviation':statistics.stdev(numbers) if len(numbers)>1 else None,
      'p50':_percentile(numbers,.50),'p90':_percentile(numbers,.90),
      'p95':_percentile(numbers,.95),'p99':_percentile(numbers,.99),
    }

def build_inter_run_statistics(records: Iterable[Mapping[str,Any]], sources: Iterable[str]|None=None) -> dict[str,Any]:
    rows=[dict(r) for r in records]
    source_list=list(sources or [])
    groups=defaultdict(list)
    observations=[]
    seen=set()
    for index,row in enumerate(rows):
        key=_key(row); category=_category(row)
        run=row.get('run'); matrix=row.get('matrix_run_id')
        if isinstance(run,bool) or not isinstance(run,int) or run<0: raise ValueError('run must be a non-negative integer')
        if not isinstance(matrix,str) or not matrix: raise ValueError('matrix_run_id must be a non-empty string')
        identity=(matrix,run,*key)
        if identity in seen: raise ValueError('duplicate inter-run observation identity')
        seen.add(identity)
        elapsed=row.get('elapsed_ns')
        numeric=None
        if category=='completed':
            if isinstance(elapsed,bool) or not isinstance(elapsed,int) or elapsed<0: raise ValueError('completed outcome requires non-negative elapsed_ns')
            numeric=elapsed
        groups[key].append((category,numeric,matrix,run,index))
        observations.append({'source':source_list[index] if index<len(source_list) else None,'matrix_run_id':matrix,'run':run,'compatibility_key':dict(zip(GROUP_FIELDS,key)),'outcome':category,'elapsed_ns':numeric})
    result=[]
    for key,items in sorted(groups.items(),key=lambda x:tuple(str(v) for v in x[0])):
        counts=Counter(item[0] for item in items)
        stats=numeric_statistics(item[1] for item in items if item[1] is not None)
        result.append({**dict(zip(GROUP_FIELDS,key)),'percentile_method':METHOD,'record_count':len(items),'outcome_counts':{name:counts.get(name,0) for name in OUTCOMES},'elapsed_ns':stats,'matrix_run_ids':sorted({item[2] for item in items}),'runs':sorted({item[3] for item in items})})
    return {'schema':SCHEMA,'percentile_method':METHOD,'group_count':len(result),'record_count':len(rows),'groups':result,'observations':observations}

def flatten_groups(report: Mapping[str,Any]) -> list[dict[str,Any]]:
    rows=[]
    for group in report.get('groups',[]):
        row={name:group.get(name) for name in GROUP_FIELDS}
        row.update({f'outcome_{name}':group['outcome_counts'][name] for name in OUTCOMES})
        row.update({f'elapsed_ns_{name}':value for name,value in group['elapsed_ns'].items()})
        row['record_count']=group['record_count']; row['percentile_method']=group['percentile_method']
        rows.append(row)
    return rows
