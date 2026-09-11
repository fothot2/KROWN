import unittest
from bench_executor.outcome_contract import classify_query_record, matrix_status, normalize_query_record, outcome_counts, validate_summary_counts

class OutcomeContractTest(unittest.TestCase):
    def base(self,status='ok',**extra): return {'status':status,**extra}
    def test_all_categories(self):
        rows=[self.base(),self.base('timeout'),self.base('skipped',skip_reason='warmup timeout'),self.base('engine_error'),self.base('validation_mismatch'),self.base('engine_error',oom_evidence={'confirmed':True,'rule':'confirmed-process-memory-exhaustion-only','source':'worker stderr','detail':'MemoryError: allocation failed'})]
        self.assertEqual([classify_query_record(r)['category'] for r in rows],['completed','timeout','skipped','engine-error','semantic-mismatch','confirmed-oom'])
        self.assertEqual(matrix_status(outcome_counts(rows)),'completed_with_failures')
    def test_large_rss_or_sigkill_is_not_oom(self):
        row=self.base('engine_error',peak_rss_bytes=999999999999,returncode=-9)
        self.assertEqual(classify_query_record(row)['category'],'engine-error')
    def test_policy_skip_requires_provenance(self):
        with self.assertRaisesRegex(ValueError,'policy identity'):
            classify_query_record(self.base('skipped',skip_reason='policy',skip_kind='manual-query-flavour-policy'))
    def test_mismatch_is_not_engine_error(self):
        self.assertEqual(classify_query_record(self.base('validation_mismatch'))['category'],'semantic-mismatch')
    def test_supplied_outcome_must_match(self):
        row=self.base('timeout',outcome={'schema':'rdf-attempt-outcome-v1','category':'completed','detail_status':'timeout','confirmed_oom':False})
        with self.assertRaisesRegex(ValueError,'does not match'): normalize_query_record(row)
    def test_query_record_publication_adds_outcome(self):
        from bench_executor.benchmark_result import validate_query_record
        row={'schema_version':1,'experiment_id':'e','system':'s','dataset':'d','workload':'w','query_id':'q','phase':'measured','run':0,'order':0,'status':'timeout','elapsed_ns':10}
        self.assertEqual(validate_query_record(row)['outcome']['category'],'timeout')
    def test_summary_consistency(self):
        rows=[self.base(),self.base('timeout'),self.base('skipped',skip_reason='unsupported flavour')]
        summary={'record_count':3,'success_count':1,'failure_count':1,'skipped_count':1,'outcome_counts':outcome_counts(rows)}
        validate_summary_counts(rows,summary)

if __name__ == '__main__': unittest.main()
