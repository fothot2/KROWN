#!/usr/bin/env python3
"""Normalize materialized RDFLib query results for correctness checks."""

import hashlib
import json
import re
from typing import Any

from rdflib import BNode, Literal, URIRef

from bench_executor.query_features import classify_query, \
        comparison_metadata

CORRECTNESS_MODES = frozenset({'none', 'fingerprint', 'full'})
_XSD = 'http://www.w3.org/2001/XMLSchema#'
_CANONICAL_DATATYPES = {
    _XSD + 'int': _XSD + 'integer',
    _XSD + 'string': None,
}


def _canonical_datatype(datatype: str | None, language: str | None) -> str | None:
    """Map equivalent RDF literal datatypes to one benchmark form."""
    if language is not None:
        return None
    return _CANONICAL_DATATYPES.get(datatype, datatype)


def _normalize_term(term) -> dict[str, Any] | None:
    """Convert one RDFLib term to stable JSON data."""
    if term is None:
        return None
    if isinstance(term, URIRef):
        return {'type': 'uri', 'value': str(term)}
    if isinstance(term, BNode):
        return {'type': 'bnode', 'value': str(term)}
    if isinstance(term, Literal):
        language = term.language
        datatype = str(term.datatype) if term.datatype else None
        return {
            'type': 'literal',
            'value': str(term),
            'language': language,
            'datatype': _canonical_datatype(datatype, language),
        }
    raise TypeError(f'Unsupported RDF term type: {type(term).__name__}')


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False,
        separators=(',', ':'), sort_keys=True,
    )


def _query_has_order_by(query: str) -> bool:
    """Detect an ORDER BY clause after removing SPARQL comments."""
    without_comments = re.sub(r'#[^\r\n]*', ' ', query)
    return re.search(r'\bORDER\s+BY\b', without_comments, re.I) is not None


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()


def normalize_materialized_result(result, rows: list,
                                  query: str) -> dict[str, Any]:
    """Normalize one already materialized RDFLib result."""
    result_type = str(getattr(result, 'type', '')).upper()
    features = classify_query(query)
    contains_blank_nodes = False

    if result_type == 'SELECT':
        variables = [str(variable) for variable in (result.vars or [])]
        normalized_rows = []
        for row in rows:
            normalized = [_normalize_term(term) for term in row]
            contains_blank_nodes |= any(
                term is not None and term.get('type') == 'bnode'
                for term in normalized
            )
            normalized_rows.append(normalized)
        ordered = features.has_order_by
        fingerprint_rows = normalized_rows if ordered else sorted(
            normalized_rows, key=_canonical_json
        )
        payload = {
            'result_kind': 'select',
            'variables': variables,
            'ordered': ordered,
            'rows': fingerprint_rows,
        }
        retained = {
            'result_kind': 'select',
            'variables': variables,
            'ordered': ordered,
            'rows': normalized_rows,
        }
    elif result_type == 'ASK':
        value = bool(getattr(result, 'askAnswer', rows[0] if rows else False))
        payload = {'result_kind': 'ask', 'boolean': value}
        retained = dict(payload)
    elif result_type in {'CONSTRUCT', 'DESCRIBE'}:
        normalized_rows = []
        for subject, predicate, object_ in rows:
            normalized = [
                _normalize_term(subject),
                _normalize_term(predicate),
                _normalize_term(object_),
            ]
            contains_blank_nodes |= any(
                term.get('type') == 'bnode' for term in normalized
            )
            normalized_rows.append(normalized)
        normalized_rows.sort(key=_canonical_json)
        payload = {
            'result_kind': 'graph',
            'triples': normalized_rows,
        }
        retained = dict(payload)
    else:
        raise ValueError(f'Unsupported RDFLib result type: {result_type}')

    output = {
        'result_kind': payload['result_kind'],
        'result_variables': payload.get('variables', []),
        'result_ordered': payload.get('ordered', False),
        'result_fingerprint': _fingerprint(payload),
        'contains_blank_nodes': contains_blank_nodes,
        'normalized_result': retained,
    }
    output.update(comparison_metadata(features, contains_blank_nodes))
    return output

def _normalize_sparql_json_binding(binding: dict) -> dict:
    """Convert one SPARQL Results JSON binding to canonical term JSON."""
    binding_type = binding.get('type')
    value = binding.get('value')
    if binding_type == 'uri':
        return {'type': 'uri', 'value': value}
    if binding_type == 'bnode':
        return {'type': 'bnode', 'value': value}
    if binding_type in {'literal', 'typed-literal'}:
        language = binding.get('xml:lang') or binding.get('lang')
        return {
            'type': 'literal',
            'value': value,
            'language': language,
            'datatype': _canonical_datatype(binding.get('datatype'), language),
        }
    raise ValueError(f'Unsupported SPARQL JSON binding type: {binding_type}')



def normalize_graph_terms(rows: list, query: str) -> dict[str, Any]:
    """Normalize materialized graph triples through canonical RDF terms."""
    normalized_rows = []
    contains_blank_nodes = False
    for subject, predicate, object_ in rows:
        normalized = [
            _normalize_term(subject),
            _normalize_term(predicate),
            _normalize_term(object_),
        ]
        contains_blank_nodes |= any(
            term is not None and term.get('type') == 'bnode'
            for term in normalized
        )
        normalized_rows.append(normalized)
    normalized_rows.sort(key=_canonical_json)
    payload = {'result_kind': 'graph', 'triples': normalized_rows}
    output = {
        'result_count': len(normalized_rows),
        'result_kind': 'graph',
        'result_variables': [],
        'result_ordered': False,
        'result_fingerprint': _fingerprint(payload),
        'contains_blank_nodes': contains_blank_nodes,
        'normalized_result': payload,
    }
    output.update(comparison_metadata(classify_query(query), contains_blank_nodes))
    return output

def normalize_sparql_json_result(document: dict,
                                 query: str) -> dict[str, Any]:
    """Normalize one complete SPARQL Results JSON document."""
    if not isinstance(document, dict):
        raise ValueError('SPARQL JSON result must be an object')
    worker_kind = document.get('kind')
    if worker_kind == 'select':
        variables = document.get('variables')
        rows = document.get('rows')
        if not isinstance(variables, list) or not isinstance(rows, list):
            raise ValueError('worker SELECT result is invalid')
        document = {'head': {'vars': variables}, 'results': {'bindings': rows}}
    elif worker_kind == 'ask':
        document = {'boolean': document.get('boolean')}
    elif worker_kind == 'graph':
        triples = document.get('triples')
        if not isinstance(triples, list):
            raise ValueError('worker graph result is invalid')
        normalized_rows = sorted(triples, key=_canonical_json)
        payload = {'result_kind': 'graph', 'triples': normalized_rows}
        features = classify_query(query)
        output = {
            'result_count': len(normalized_rows),
            'result_kind': 'graph', 'result_variables': [],
            'result_ordered': False, 'result_fingerprint': _fingerprint(payload),
            'contains_blank_nodes': any(term.get('type') == 'bnode' for row in normalized_rows for term in row),
            'normalized_result': payload,
        }
        output.update(comparison_metadata(features, output['contains_blank_nodes']))
        return output
    features = classify_query(query)
    if 'boolean' in document:
        value = document['boolean']
        if not isinstance(value, bool):
            raise ValueError('SPARQL ASK boolean must be true or false')
        payload = {'result_kind': 'ask', 'boolean': value}
        output = {
            'result_count': 1 if value else 0,
            'result_kind': 'ask',
            'result_variables': [],
            'result_ordered': False,
            'result_fingerprint': _fingerprint(payload),
            'contains_blank_nodes': False,
            'normalized_result': payload,
        }
        output.update(comparison_metadata(features, False))
        return output

    head = document.get('head')
    results = document.get('results')
    if not isinstance(head, dict) or not isinstance(results, dict):
        raise ValueError('SPARQL SELECT JSON requires head and results')
    variables = head.get('vars')
    bindings = results.get('bindings')
    if not isinstance(variables, list) or not all(
            isinstance(variable, str) for variable in variables):
        raise ValueError('SPARQL SELECT variables must be strings')
    if not isinstance(bindings, list):
        raise ValueError('SPARQL SELECT bindings must be an array')

    rows = []
    contains_blank_nodes = False
    for binding_row in bindings:
        if not isinstance(binding_row, dict):
            raise ValueError('SPARQL SELECT binding row must be an object')
        row = []
        for variable in variables:
            raw_term = binding_row.get(variable)
            term = (
                None if raw_term is None
                else _normalize_sparql_json_binding(raw_term)
            )
            contains_blank_nodes |= (
                term is not None and term.get('type') == 'bnode'
            )
            row.append(term)
        rows.append(row)

    ordered = features.has_order_by
    fingerprint_rows = rows if ordered else sorted(rows, key=_canonical_json)
    payload = {
        'result_kind': 'select',
        'variables': variables,
        'ordered': ordered,
        'rows': fingerprint_rows,
    }
    retained = {
        'result_kind': 'select',
        'variables': variables,
        'ordered': ordered,
        'rows': rows,
    }
    output = {
        'result_count': len(rows),
        'result_kind': 'select',
        'result_variables': variables,
        'result_ordered': ordered,
        'result_fingerprint': _fingerprint(payload),
        'contains_blank_nodes': contains_blank_nodes,
        'normalized_result': retained,
    }
    output.update(comparison_metadata(features, contains_blank_nodes))
    return output
