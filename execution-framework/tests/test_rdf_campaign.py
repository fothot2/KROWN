#!/usr/bin/env python3
import json,sys,tempfile,unittest
import unittest.mock
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bench_executor.rdf_campaign import CampaignSpecification,RdfCampaign,atomic_json,retain,require_clean_matrix_environment
class CampaignTests(unittest.TestCase):
 def test_specification_rejects_unsafe_manifest_and_duplicate_systems(self):
  with self.assertRaises(ValueError):CampaignSpecification('/tmp/s','/tmp/d','../m',systems=('a/b',))
  with self.assertRaises(ValueError):CampaignSpecification('/tmp/s','/tmp/d','m',systems=('a/b','a/b'))
 def test_atomic_json_and_retention(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'a';target=root/'b';source.write_text('x');retain(source,target);self.assertFalse(source.exists());self.assertEqual(target.read_text(),'x');atomic_json(root/'v.json',{'x':1});self.assertEqual(json.loads((root/'v.json').read_text()),{'x':1})
 def test_matrix_command_passes_explicit_benchmark_root(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);spec=CampaignSpecification(root/'scenario',root/'decl.json','manifest.json',root/'bench',systems=('rdflib/default',));c=RdfCampaign(spec,root/'matrix.py',root/'report.py',root/'inter.py');command=c._matrix_command('run','rdflib/default','raw/x');self.assertEqual(command[command.index('--benchmark-root')+1],str((root/'bench').resolve()))
 def test_outcome_counts_separate_reportable_and_terminal_failures(self):
  rows=[{"state":"completed"},{"state":"completed-with-failures"},{"state":"structural-failure"},{"state":"timed-out"},{"state":"interrupted"}]
  self.assertEqual(RdfCampaign._outcome_counts(rows),{"reportable_count":2,"structural_failure_count":1,"timed_out_count":1,"interrupted_count":1,"infrastructure_blocked_count":0})
 def test_run_continues_after_failure_and_across_repetitions(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);scenario=root/'scenario';shared=scenario/'data/shared';shared.mkdir(parents=True);declaration=root/'declaration.json';declaration.write_text(json.dumps({"bindings":[{"system":"a/one"},{"system":"b/two"}]}));(shared/'manifest.json').write_text('{}')
   runners=[]
   for name in ('matrix.py','report.py','inter.py'):
    path=root/name;path.write_text('# runner');runners.append(path)
   spec=CampaignSpecification(scenario,declaration,'manifest.json',repetitions=2,campaign_id='campaign')
   campaign=RdfCampaign(spec,*runners)
   calls=[]
   def run_system(run_root,run_id,system,environment,retry_failed):
    calls.append((run_id,system,retry_failed));state='structural-failure' if system=='a/one' else 'completed';return {"system":system,"state":state,"exit_code":1 if state!='completed' else 0,"detail":None}
   campaign._run_system=run_system
   campaign._inter_run=lambda *args:{"state":"not-run"}
   result=campaign.run()
   self.assertEqual(calls,[('campaign-r01','a/one',False),('campaign-r01','b/two',False),('campaign-r02','a/one',False),('campaign-r02','b/two',False)])
   self.assertTrue(result['execution_complete']);self.assertTrue(result['complete']);self.assertFalse(result['all_systems_reportable']);self.assertEqual(result['structural_failure_count'],2);self.assertEqual(result['reportable_count'],2)
 def test_run_stops_only_after_interruption(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);scenario=root/'scenario';shared=scenario/'data/shared';shared.mkdir(parents=True);declaration=root/'declaration.json';declaration.write_text(json.dumps({"bindings":[{"system":"a/one"},{"system":"b/two"}]}));(shared/'manifest.json').write_text('{}')
   runners=[]
   for name in ('matrix.py','report.py','inter.py'):
    path=root/name;path.write_text('# runner');runners.append(path)
   campaign=RdfCampaign(CampaignSpecification(scenario,declaration,'manifest.json',repetitions=2,campaign_id='campaign'),*runners)
   calls=[]
   def run_system(run_root,run_id,system,environment,retry_failed):
    calls.append((run_id,system));return {"system":system,"state":"interrupted","exit_code":None,"detail":"interrupt"}
   campaign._run_system=run_system
   result=campaign.run()
   self.assertEqual(calls,[('campaign-r01','a/one')]);self.assertFalse(result['execution_complete']);self.assertEqual(result['interrupted_count'],1)

 def test_campaign_preflight_rejects_existing_matrix_container_before_system_state(self):
  with unittest.mock.patch('bench_executor.rdf_campaign.matrix_owned_containers',return_value=('Fuseki-tdb2',)):
   with self.assertRaisesRegex(RuntimeError,'campaign preflight: Fuseki-tdb2'):
    require_clean_matrix_environment('campaign preflight')
 def test_run_stops_after_infrastructure_blocked_system(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);scenario=root/'scenario';shared=scenario/'data/shared';shared.mkdir(parents=True);declaration=root/'declaration.json';declaration.write_text(json.dumps({'bindings':[{'system':'a/one'},{'system':'b/two'}]}));(shared/'manifest.json').write_text('{}')
   runners=[]
   for name in ('matrix.py','report.py','inter.py'):
    path=root/name;path.write_text('# runner');runners.append(path)
   campaign=RdfCampaign(CampaignSpecification(scenario,declaration,'manifest.json',repetitions=2,campaign_id='campaign'),*runners)
   calls=[]
   def run_system(run_root,run_id,system,environment,retry_failed):
    calls.append((run_id,system));return {'system':system,'state':'infrastructure-blocked','exit_code':1,'detail':'stale container'}
   campaign._run_system=run_system
   with unittest.mock.patch('bench_executor.rdf_campaign.require_clean_matrix_environment'):
    result=campaign.run()
   self.assertEqual(calls,[('campaign-r01','a/one')]);self.assertFalse(result['execution_complete']);self.assertEqual(result['infrastructure_blocked_count'],1)

if __name__=='__main__':unittest.main()
