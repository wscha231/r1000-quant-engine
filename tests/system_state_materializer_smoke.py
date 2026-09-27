#!/usr/bin/env python3
"""Synthetic offline invariants for the canonical system-state intake boundary."""
import argparse
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import materialize_system_state as m
from tools import run_agent_board as b


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)
        self.sha, self.config = b.source_identity()
        self.manifest = dict(observed_at=self.at(-1), expires_at=self.at(30), sources={})
        mission = b.mission_targets()
        self.put('mission', {k: mission[k] for k in ('mission_contract_id', 'mission_contract_sha256',
            'official_metric_mode', 'mission_contract_values')})
        self.put('code', dict(repository=m.REPOSITORY, default_branch='master', master_sha=self.sha,
            observed_at=self.at(-1), g0_run=dict(run_id='history-fixture-1',head_sha=self.sha,conclusion='failure')))
        self.put('control', dict(observed_at=self.at(-1), handoff_ref='SYNTHETIC', issues=[
            dict(number=531,state='open',url='https://github.com/'+m.REPOSITORY+'/issues/531')]))
        self.put('current_status', 'Status snapshot: `2026-01-01 10:05 KST` (`2026-01-01 01:05 UTC`)')
        self.put('quality', dict(schema='long-history-quality-v1',status='PARTIAL_COVERAGE',
            eligible_for_selector=False,as_of=self.at(-30), provider_failures={},
            provider_coverage_gaps={'sec/fixture':'OFFICIAL_COVERAGE_GAP'}))
        self.put('catalog', dict(schema='long-history-catalog-v1',run_id='history-fixture-1',
            created_at=self.at(-25),code_sha=self.sha,eligible_for_selector=False,
            datasets={'current/fixture':dict(latest='2026-08-01',status='COLLECTED',evidence='current_only',normalized='a'*64)}))
        self.put('commit', dict(schema='long-history-commit-v1',run_id='history-fixture-1',
            created_at=self.at(-20),catalog=self.hash('catalog')))
        self.put('execution', dict(schema='long-history-execution-v1',run_id='history-fixture-1',
            created_at=self.at(-15),catalog_sha256=self.hash('catalog'),commit_sha256=self.hash('commit'),
            eligible_for_selector=False,quality_status='PARTIAL_COVERAGE',consumer_rows=2,
            study_recomputed_from_drive=True,reports={'quality.json':self.hash('quality')}))
        self.put('drive_readback', dict(catalog_sha256=self.hash('catalog'),commit_sha256=self.hash('commit'),
            execution_receipt_sha256=self.hash('execution'),quality_status='PARTIAL_COVERAGE',
            remote_verified=True,study_recomputed_from_drive=True,eligible_for_selector=False,consumer_rows=2))

    def at(self, minutes):
        return (self.now+timedelta(minutes=minutes)).isoformat()

    def put(self, role, value):
        p=self.root/(role+'.json')
        p.write_text(value if isinstance(value,str) else json.dumps(value),encoding='utf-8')
        self.manifest['sources'][role]=[dict(path=p.name,identity='fixture:'+role,sha256=b.file_hash(p),
            observed_at=self.at(-40),available_at=self.at(-10),collected_at=self.at(-5),
            expires_at=self.at(30),status='VERIFIED')]

    def hash(self,role):
        return self.manifest['sources'][role][0]['sha256']

    def payload(self,role):
        return json.loads((self.root/(role+'.json')).read_text())

    def state(self):
        return m.materialize(self.manifest,self.root,self.now,self.sha)

    def test_current_identity_and_semantic_determinism(self):
        first=self.state()
        second=m.materialize(copy.deepcopy(self.manifest),self.root,self.now+timedelta(seconds=1),self.sha)
        self.assertEqual(first['state_sha256'],second['state_sha256'])
        self.assertNotEqual(first['generated_at'],second['generated_at'])
        self.assertEqual(first['master_sha'],self.sha)
        self.assertEqual(first['mission']['mission_contract_sha256'],b.mission_targets()['mission_contract_sha256'])
        self.assertEqual(m.verify_state(first,self.manifest,self.root,self.now,self.sha)['state_sha256'],first['state_sha256'])

    def test_newer_master_invalidates_saved_state(self):
        old=self.state(); code=self.payload('code');code['master_sha']='a'*40;self.put('code',code)
        with self.assertRaisesRegex(b.ContractError,'state_sources_changed'):
            m.verify_state(old,self.manifest,self.root,self.now,self.sha)

    def test_newer_execution_invalidates_saved_state(self):
        old=self.state();ex=self.payload('execution');ex['run_id']='history-newer-1';self.put('execution',ex)
        with self.assertRaisesRegex(b.ContractError,'state_sources_changed'):
            m.verify_state(old,self.manifest,self.root,self.now,self.sha)
        self.assertEqual(self.state()['data']['g0_status'],'BLOCKED')

    def test_mission_change_blocks_reuse(self):
        old=self.state();mission=self.payload('mission');mission['mission_contract_sha256']='f'*64;self.put('mission',mission)
        with self.assertRaises(b.ContractError):m.verify_state(old,self.manifest,self.root,self.now,self.sha)
        state=self.state();self.assertEqual(state['mission']['status'],'BLOCKED');self.assertFalse(state['authority']['research_allowed'])

    def test_missing_actual_does_not_block_model_research(self):
        state=self.state()
        self.assertEqual(state['books']['actual_broker']['status'],'UNKNOWN')
        self.assertFalse(state['authority']['account_rebalance_allowed'])
        self.assertTrue(state['authority']['research_allowed'])
        self.assertTrue(state['authority']['model_portfolio_allowed'])
        self.assertEqual(state['books']['model_portfolio']['claim_boundary'],'NOT_ACTUAL_HOLDINGS')

    def test_first_model_proposal_is_not_approved_target(self):
        state=self.state();self.assertEqual(state['books']['approved_target']['status'],'UNKNOWN')
        self.assertTrue(state['authority']['model_portfolio_allowed'])
        self.assertFalse(state['authority']['target_mutation_allowed'])
        self.assertEqual(state['books']['verified_paper']['status'],'UNKNOWN')
        self.assertEqual(state['regime']['status'],'UNKNOWN')

    def test_partial_readback_and_failure_are_independent(self):
        data=self.state()['data']
        self.assertEqual(data['g0_status'],'PARTIAL_COVERAGE')
        self.assertEqual(data['drive_readback_status'],'VERIFIED')
        self.assertEqual(data['workflow_conclusion'],'failure')
        self.assertFalse(data['eligible_for_selector'])
        self.assertFalse(self.state()['authority']['selector_allowed'])

    def test_missing_or_closed_issue_is_not_membership_certification(self):
        for issues in ([],[dict(number=531,state='closed',url='https://github.com/'+m.REPOSITORY+'/issues/531')]):
            control=self.payload('control');control['issues']=issues;self.put('control',control)
            data=self.state()['data']
            for key in ('official_r1000_membership_proven','historical_universe_pit_clean','final_8y_certification_allowed'):
                self.assertFalse(data[key])
            self.assertEqual(data['universe_evidence_class'],'PROXY_CURRENT_SNAPSHOT_HISTORY')

    def test_current_status_never_retimestamped_by_master(self):
        state=self.state();self.assertEqual(state['context']['current_status_freshness'],'STALE')
        self.assertEqual(state['context']['current_status_as_of'],'2026-01-01T01:05:00+00:00')
        self.assertIsNone(state['data']['data_as_of'])
        self.assertEqual(state['data']['dataset_as_of']['current/fixture']['latest'],'2026-08-01')

    def test_malformed_and_conflicting_books_block(self):
        self.put('actual_broker','{"x":1,"x":2}')
        self.assertEqual(self.state()['books']['actual_broker']['status'],'BLOCKED')
        self.put('actual_broker',dict(status='VERIFIED'))
        self.manifest['sources']['actual_broker']*=2
        self.assertEqual(self.state()['books']['actual_broker']['reason'],'conflicting_sources')

    def test_simulation_or_self_report_never_promotes_book(self):
        for role in m.BOOKS+('regime',):
            self.put(role,dict(status='VERIFIED',as_of=self.at(-2),book_kind='SIMULATION'))
        state=self.state()
        for role in m.BOOKS:self.assertEqual(state['books'][role]['status'],'BLOCKED')
        self.assertEqual(state['regime']['status'],'BLOCKED')

    def test_hash_mismatch_revokes_readback_and_research(self):
        (self.root/'catalog.json').write_text('{}')
        state=self.state();self.assertEqual(state['data']['g0_status'],'BLOCKED')
        self.assertNotEqual(state['data']['drive_readback_status'],'VERIFIED')
        self.assertFalse(state['authority']['research_allowed'])

    def test_source_expiry_invalidates_prior_state(self):
        old=self.state();self.manifest['sources']['quality'][0]['expires_at']=self.at(-2)
        self.assertEqual(self.state()['data']['g0_status'],'STALE')
        with self.assertRaises(b.ContractError):m.verify_state(old,self.manifest,self.root,self.now,self.sha)

    def test_stale_book_cannot_remain_verified(self):
        self.put('actual_broker',dict(status='VERIFIED'))
        self.manifest['sources']['actual_broker'][0]['expires_at']=self.at(-2)
        self.assertEqual(self.state()['books']['actual_broker']['status'],'STALE')

    def test_missing_source_does_not_fallback_to_old_success(self):
        self.manifest['sources'].pop('execution')
        state=self.state();self.assertEqual(state['data']['g0_status'],'UNKNOWN')
        self.assertFalse(state['authority']['research_allowed'])

    def test_intake_must_be_fresh_and_cannot_be_self_supplied_state(self):
        self.manifest['expires_at']=self.at(-2)
        with self.assertRaises(b.ContractError):self.state()
        with self.assertRaisesRegex(b.ContractError,'current_canonical_inputs_required'):
            b.build_tasks({},self.root,b.contracts(),self.now,self.sha,self.config)

    def test_public_board_requires_materialized_state(self):
        state=self.state()
        tasks=b.build_tasks(state,self.root,b.contracts(),self.now,self.sha,self.config,
            canonical_inputs=self.manifest,evidence_root=self.root)
        self.assertEqual(tasks,[])
        state.pop('materialization')
        with self.assertRaisesRegex(b.ContractError,'state_not_materialized'):
            b.build_tasks(state,self.root,b.contracts(),self.now,self.sha,self.config,
                canonical_inputs=self.manifest,evidence_root=self.root)

    def test_tampering_and_old_code_fail_closed(self):
        state=self.state();state['authority']['selector_allowed']=True
        with self.assertRaises(b.ContractError):m.verify_state(state,self.manifest,self.root,self.now,self.sha)
        with self.assertRaises(b.ContractError):m.verify_state(self.state(),self.manifest,self.root,self.now,'b'*40)

    def test_inputs_unchanged_and_all_economic_authority_false(self):
        before={p.name:b.file_hash(p) for p in self.root.iterdir()}
        state=self.state()
        self.assertEqual(before,{p.name:b.file_hash(p) for p in self.root.iterdir()})
        for key in ('account_rebalance_allowed','target_mutation_allowed','paper_mutation_allowed',
                    'broker_mutation_allowed','fullrun_allowed','production_activation_allowed'):
            self.assertFalse(state['authority'][key])

    def test_traversal_and_future_metadata_block(self):
        self.manifest['sources']['quality'][0]['path']='../quality.json'
        self.assertEqual(self.state()['data']['g0_status'],'BLOCKED')
        self.manifest['sources']['code'][0]['collected_at']=self.at(5)
        self.assertFalse(self.state()['authority']['research_allowed'])

    def test_public_a0_skip_reuse_is_invalidated_by_data_identity(self):
        from control_plane_agent_contract_smoke import ControlPlaneTests
        fixture=ControlPlaneTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.root=self.root;fixture.now=self.now;fixture.sha=self.sha;fixture.config=self.config
        fixture.state=self.state()
        fixture.add_request('A1')
        self.manifest['requests']=fixture.state['requests']
        fixture.state=self.state()
        fixture.complete()
        self.manifest['completed_tasks']=fixture.state['completed_tasks']
        ready=self.state()
        tasks=b.build_tasks(ready,self.root,b.contracts(),self.now,self.sha,self.config,
            canonical_inputs=self.manifest,evidence_root=self.root)
        self.assertEqual(tasks[0]['status'],'SKIP_UNCHANGED')
        old_key=tasks[0]['task_key']
        # Different hash-bound execution identity, same otherwise valid raw data.
        self.manifest['sources']['execution'][0]['identity']='fixture:new-durable-execution-observation'
        changed=self.state()
        tasks=b.build_tasks(changed,self.root,b.contracts(),self.now,self.sha,self.config,
            canonical_inputs=self.manifest,evidence_root=self.root)
        self.assertNotEqual(tasks[0]['task_key'],old_key)
        self.assertNotEqual(tasks[0]['status'],'SKIP_UNCHANGED')

    def test_malformed_nested_github_run_is_explicitly_blocked(self):
        for value in (None, [], 'failure'):
            with self.subTest(value=value):
                code=self.payload('code');code['g0_run']=value;self.put('code',code)
                state=self.state()
                self.assertEqual(state['data']['g0_status'],'BLOCKED')
                self.assertEqual(state['source_status']['code']['status'],'BLOCKED')
                self.assertFalse(state['authority']['research_allowed'])

    def test_readback_must_match_execution(self):
        readback=self.payload('drive_readback');readback['execution_receipt_sha256']='f'*64
        self.put('drive_readback',readback)
        self.assertEqual(self.state()['data']['drive_readback_status'],'BLOCKED')


def main():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StateTests))
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
