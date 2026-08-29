#!/usr/bin/env python3
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rdflib import Literal, URIRef
from bench_executor.sparql_result import _normalize_json_term, normalize_graph_terms, normalize_sparql_json_result
XSD='http://www.w3.org/2001/XMLSchema#'
RDF='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
G='CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }'
S='SELECT ?v WHERE { ?s ?p ?v }'
class Tests(unittest.TestCase):
 def graph(self,obj):
  return normalize_sparql_json_result({'kind':'graph','triples':[[{'type':'uri','value':'http://e/s'},{'type':'uri','value':'http://e/p'},obj]]},G)
 def test_query08_language(self):
  expected={'type':'literal','value':'review','language':'en','datatype':None}
  self.assertEqual(_normalize_json_term({'type':'literal','value':'review','language':'en','datatype':RDF+'langString'}),expected)
  fps=[]
  for field in ('language','xml:lang','lang'):
   term={'type':'literal','value':'review','datatype':RDF+'langString',field:'en'}
   fps.append(normalize_sparql_json_result({'kind':'select','variables':['v'],'rows':[{'v':term}]},S)['result_fingerprint'])
  self.assertEqual(len(set(fps)),1)
 def test_query12_xsd_string_graph(self):
  plain=self.graph({'type':'literal','value':'text'})
  typed=self.graph({'type':'typed-literal','value':'text','datatype':XSD+'string'})
  self.assertEqual(plain['result_fingerprint'],typed['result_fingerprint'])
  rdflib=normalize_graph_terms([(URIRef('http://e/s'),URIRef('http://e/p'),Literal('text'))],G)
  self.assertEqual(typed['result_fingerprint'],rdflib['result_fingerprint'])
 def test_datatypes(self):
  self.assertEqual(_normalize_json_term({'type':'literal','value':'3','datatype':XSD+'int'})['datatype'],XSD+'integer')
  self.assertEqual(_normalize_json_term({'type':'literal','value':'3.0','datatype':XSD+'decimal'})['datatype'],XSD+'decimal')
 def test_malformed(self):
  bad=(None,{'type':'uri','value':None},{'type':'uri','value':'x','datatype':XSD+'string'},{'type':'literal','value':'x','language':'en','lang':'fr'},{'type':'literal','value':'x','datatype':4},{'type':'unknown','value':'x'})
  for term in bad:
   with self.subTest(term=term),self.assertRaises(ValueError): _normalize_json_term(term)
  with self.assertRaisesRegex(ValueError,'three-term arrays'):
   normalize_sparql_json_result({'kind':'graph','triples':[[{'type':'uri','value':'x'}]]},G)
if __name__=='__main__': unittest.main()
