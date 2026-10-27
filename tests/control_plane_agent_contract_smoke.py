#!/usr/bin/env python3
"""Offline control-plane contract boundaries; all inputs are synthetic."""
from __future__ import annotations
import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
MANAGED_INITIAL_POLICY_SHA = '1ac3387de165a091bc99d20e218f7f3140f5f26d21ca6c0b0ea7dba73d66c420'
sys.path.insert(0, str(ROOT))
from tools import run_agent_board as board


def managed_initial_policy_file():
    """Keep original revision-one oracles pinned across operational revisions."""
    return ROOT / 'data_static/a1_ohlcv_managed_history' / (MANAGED_INITIAL_POLICY_SHA + '.json')


class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)
        self.contract = board.contracts()
        self.sha, self.config = board.source_identity()
        self.state = dict(schema_version='system-state-v2', as_of=self.at(-5), expires_at=self.at(60),
            repository='wscha231/r1000-quant-engine', review_pr_number=551,
            master_sha=self.sha, code_sha=self.sha,
            context=dict(current_status_as_of=self.at(-10), current_status_freshness='VERIFIED',
                data_as_of=self.at(-10), actual_book='UNKNOWN', approved_target='UNKNOWN',
                thesis='UNKNOWN', market_regime='UNKNOWN', open_refs=[], handoff_ref='SYNTHETIC', blockers=[]),
            g0=dict(status='PASS', reasons=[]), requests=[], completed_tasks=[], authority=board.AUTHORITY.copy())
        self.add_request('A1')

    def at(self, minutes):
        return (self.now + timedelta(minutes=minutes)).isoformat()

    def artifact(self, name):
        path = self.root / (name + '.json')
        path.write_text(json.dumps({'synthetic': name}))
        return dict(path=path.name, sha256=board.file_hash(path), observed_at=self.at(-30),
                    available_at=self.at(-20), collected_at=self.at(-10), expires_at=self.at(50), status='VERIFIED')

    def add_request(self, agent):
        request = dict(agent=agent, inputs={role: self.artifact(agent + '_' + role)
            for role in self.contract['agents'][agent]['inputs']},
            model=dict(name='synthetic-operator', version='v1'), parameters={'fixture': True})
        if agent == 'A6':
            self.set_payload(request['inputs']['review_bundle'], {'schema_version':'qa-review-bundle-v2','artifacts':{}})
        self.state['requests'].append(request)
        return request

    def set_payload(self, artifact, payload):
        path=self.root/artifact['path']; path.write_text(json.dumps(payload))
        artifact['sha256']=board.file_hash(path)

    def bind_qa_scope(self):
        qa=next(r for r in self.state['requests'] if r['agent']=='A6')
        covered={}
        for request in self.state['requests']:
            if 'A6' in self.contract['agents'][request['agent']]['dependencies']:
                covered.update({k:copy.deepcopy(v) for k,v in request['inputs'].items() if k!='qa_report'})
        self.set_payload(qa['inputs']['review_bundle'], {'schema_version':'qa-review-bundle-v2','artifacts':covered})
        if covered:
            collected=(max(board.timestamp(a['collected_at']) for a in covered.values())+
                       timedelta(seconds=1)).isoformat()
            qa['inputs']['review_bundle']['available_at']=collected
            qa['inputs']['review_bundle']['collected_at']=collected

    def tasks(self):
        return board._plan_tasks(self.state, self.root, self.contract, self.now, self.sha, self.config)

    def complete(self, agent='A1'):
        packet = next(t for t in self.tasks() if t['agent'] == agent)
        identity=packet['identity']
        hashes={role:item['sha256'] for role,item in packet['inputs'].items()}
        def evidence(kind, reference):
            return dict(identity=board.evidence_identity(kind, reference, packet['task_key'],
                         identity, identity['code_sha'], receipt['outputs'], evidence_ready),
                        reference=reference, status='PASS', head_sha=identity['code_sha'],
                        available_at=evidence_ready)
        receipt = dict(schema_version='verification-receipt-v2', agent=agent,
            task_key=packet['task_key'], status='SUCCEEDED', identity=copy.deepcopy(identity),
            source_hashes=copy.deepcopy(hashes), input_hashes=copy.deepcopy(hashes),
            dependency_identities=board.receipt_dependencies(packet['dependency_outputs']),
            code_sha=identity['code_sha'], config_hash=identity['config_hash'],
            model=copy.deepcopy(identity['model']), parameter_hash=board.digest(identity['parameters']),
            outputs={role:self.artifact(agent+'_result_'+role) for role in packet['outputs']},
            runtime_verification={}, focused_tests={}, ci={},
            side_effects=[], reviewed_head=None, created_at=self.at(-9), available_at=self.at(-8),
            verification_status='VERIFIED', execution_mode='DETERMINISTIC_CODE',
            ai_invoked=False, ai_invocation_reason=None)
        request=next(r for r in self.state['requests'] if r['agent']==agent)
        causal=list(request['inputs'].values())
        if agent=='A6':
            bundle=board.read_json(self.root/request['inputs']['review_bundle']['path'])
            causal+=list(bundle['artifacts'].values())
            self.set_payload(receipt['outputs']['qa_report'], {'schema_version':'qa-report-v2',
                'review_bundle_sha256':request['inputs']['review_bundle']['sha256'],
                'reviewed_artifacts':bundle['artifacts'],'verdict':'PASS'})
        causal_ready=max(board.timestamp(a['collected_at']) for a in causal)
        output_ready=(causal_ready+timedelta(seconds=1)).isoformat()
        evidence_ready=(causal_ready+timedelta(milliseconds=1500)).isoformat()
        receipt['created_at']=(causal_ready+timedelta(seconds=2)).isoformat()
        ready=(causal_ready+timedelta(seconds=3)).isoformat()
        receipt['available_at']=ready
        for output in receipt['outputs'].values():
            output['available_at']=output_ready
            output['collected_at']=output_ready
        for kind, reference in (('runtime_verification','synthetic-runtime'),
                                ('focused_tests','synthetic-focused-test'), ('ci','synthetic-ci')):
            receipt[kind]=evidence(kind, reference)
        self.state['completed_tasks'].append(receipt)
        for request in self.state['requests']:
            if agent in self.contract['agents'][request['agent']]['dependencies']:
                request['inputs'].update(copy.deepcopy(receipt['outputs']))
        return receipt

    def args(self):
        path = self.root / 'control_plane/system_state.json'
        board.write_json(path,self.state)
        return argparse.Namespace(latest_run=str(self.root), output_dir=str(self.root/'board'),
                                  run_url='', max_tasks=0)

    def test_nine_roles_and_current_mission_separate_from_operating_gate(self):
        self.assertEqual(set(self.contract['agents']), {f'A{i}' for i in range(9)})
        self.assertEqual(self.contract['mission']['main'], {'net_cagr_min':.35,'mdd_loss_max':.25})
        self.assertEqual(self.contract['mission']['concentrated'], {'net_cagr_min':.50,'mdd_loss_max':.25})
        self.assertEqual(self.contract['mission_source'], 'r1000_config.py:PORTFOLIO_MISSION_TARGETS')
        self.assertEqual(board.mission_targets()['values']['main'], {'cagr':.35,'max_dd':-.25})
        self.assertEqual(board.operating_gates()['values']['main']['cagr'], .30)
        self.assertEqual(board.operating_gates()['values']['concentrated']['max_dd'], -.28)
        for agent in self.contract['agents'].values():
            for path in agent['reuse_candidates']:
                self.assertTrue((ROOT/path).is_file(), path)

    def test_a0_only_and_qa_read_only(self):
        self.add_request('A6')
        for packet in self.tasks():
            self.assertEqual(packet['assigned_by'],'A0')
            self.assertEqual(packet['return_to'],'A0')
            self.assertFalse(packet['authority']['execute'])
            self.assertFalse(packet['authority']['peer_dispatch'])
        self.assertEqual(self.tasks()[1]['mode'],'READ_ONLY')

    def test_only_requested_specialists(self):
        self.assertEqual([t['agent'] for t in self.tasks()],['A1'])
        self.assertEqual(self.tasks()[0]['status'],'READY')

    def test_unexecuted_plan_never_counts_as_completion(self):
        self.assertEqual(self.tasks(),self.tasks())
        self.assertEqual(self.tasks()[0]['status'],'READY')

    def test_same_five_identity_fields_skip_with_verified_output(self):
        self.complete()
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')
        self.assertFalse(board.lifecycle_state(self.tasks()[0])['ai_invocation_required'])

    def test_mission_semantic_change_invalidates_task_key_and_skip(self):
        self.complete()
        prior = self.tasks()[0]
        self.assertEqual(prior['status'], 'SKIP_UNCHANGED')
        original = board.mission_targets
        def changed():
            row = original()
            return {**row, 'mission_contract_sha256': 'f' * 64}
        with patch.object(board, 'mission_targets', changed):
            current = self.tasks()[0]
        self.assertNotEqual(current['identity']['input_hash'], prior['identity']['input_hash'])
        self.assertNotEqual(current['task_key'], prior['task_key'])
        self.assertNotEqual(current['status'], 'SKIP_UNCHANGED')

    def test_receipt_ai_invocation_provenance(self):
        receipt=self.complete()
        receipt['ai_invoked']=True
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')
        receipt['execution_mode']='WORK'; receipt['ai_invocation_reason']='multi-file implementation'
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')  # provider is required for AI
        receipt['model']['provider']='test-provider'
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')  # identity still differs
        self.state['completed_tasks'].clear()
        self.state['requests'][0]['model']['provider']='test-provider'
        receipt=self.complete()
        receipt.update(execution_mode='WORK',ai_invoked=True,
                       ai_invocation_reason='multi-file implementation',
                       confidence='HIGH',next_action='request A0 verification')
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')
        self.assertFalse(board.lifecycle_state(self.tasks()[0])['ai_invocation_required'])

    def test_receipt_v2_missing_stale_conflicting_and_self_report_fail_closed(self):
        self.assertEqual(self.tasks()[0]['status'],'READY')
        receipt=self.complete()
        original=copy.deepcopy(receipt)
        for field,value in [('verification_status','SELF_REPORTED'),('created_at',self.at(-40)),
                            ('available_at',self.at(1)),('source_hashes',{}),('input_hashes',{}),
                            ('dependency_identities',{'A2':{}}),('config_hash','b'*64),
                            ('parameter_hash','b'*64),('side_effects',['target_book']),
                            ('reviewed_head','a'*40)]:
            with self.subTest(field=field):
                receipt.clear(); receipt.update(copy.deepcopy(original)); receipt[field]=value
                try:
                    status=self.tasks()[0]['status']
                except board.ContractError:
                    status='BLOCKED'
                self.assertEqual(status,'BLOCKED')
        for field in ('runtime_verification','focused_tests','ci'):
            receipt.clear(); receipt.update(copy.deepcopy(original))
            receipt[field]['status']='FAIL'
            try:
                status=self.tasks()[0]['status']
            except board.ContractError:
                status='BLOCKED'
            self.assertEqual(status,'BLOCKED')
        receipt.clear(); receipt.update(copy.deepcopy(original)); receipt['ci']['head_sha']='a'*40
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')

    def test_event_gate_requires_current_head_ci_review_and_receipt(self):
        packet=self.tasks()[0]
        head=packet['identity']['code_sha']
        policy=dict(source='GITHUB_RULESET',scope=packet['review_scope'],pr_head_sha=head,
                    base_sha='b'*40,strict=True,ruleset_id=23762701,
                    ruleset_updated_at=self.at(-10),observed_at=self.at(-1),
                    identity='github-ruleset-observation-1',
                    checks=[dict(context=name,integration_id=15368)
                            for name in ('validate','portfolio_guard','review_complete')])
        event=dict(ci='PASS',ci_head=head,ci_checks={'validate@15368':'PASS','portfolio_guard@15368':'PASS'},
                   required_checks_policy=policy,current_base_sha='b'*40,
                   base_ancestor_verified=True,
                   review='CLEAN',review_head=head,unresolved_findings=0,
                   review_scope=packet['review_scope'])
        self.assertNotEqual(board.lifecycle_state(packet,event)['state'],'READY_FOR_ATTESTATION')
        self.assertNotEqual(board.lifecycle_state(packet,{**event,'worker_report':'SUCCEEDED',
            'confidence':'HIGH','next_action':'MERGE',
            'merged':True,'post_merge_verified':True})['state'],'DONE')
        self.complete(); packet=self.tasks()[0]
        self.assertEqual(board.lifecycle_state(packet,event)['state'],'READY_FOR_ATTESTATION')
        for changes in ({'ci':'FAIL'},{'ci_head':'a'*40},{'ci_checks':{'validate':'PASS'}},
                        {'review':'OPEN'},{'review_head':'a'*40},{'unresolved_findings':1},
                        {'unresolved_findings':False},{'unresolved_findings':True},
                        {'review_scope':{'repository':packet['review_scope']['repository'],
                                         'pr_number':552}},
                        {'required_checks_policy':{**policy,'scope':{
                            'repository':packet['review_scope']['repository'],'pr_number':552}}},
                        {'required_checks_policy':{**policy,'base_sha':'c'*40}},
                        {'base_ancestor_verified':False},
                        {'required_checks_policy':{**policy,'observed_at':self.at(-20)}},
                        {'required_checks_policy':{**policy,'checks':[
                            {'context':'validate','integration_id':15368},
                            {'context':'portfolio_guard','integration_id':42}]}}):
            with self.subTest(changes=changes):
                self.assertNotIn(board.lifecycle_state(packet,{**event,**changes})['state'],
                                 ('READY_FOR_ATTESTATION','READY_TO_MERGE'))
        attested={**event,'review_complete':'PASS','review_complete_head':head,
                  'review_complete_scope':packet['review_scope'],
                  'ci_checks':{**event['ci_checks'],'review_complete@15368':'PASS'},
                  'review_complete_evidence':dict(context='review_complete',integration_id=15368,
                      status='PASS',head_sha=head,scope=packet['review_scope'],identity='check-run-1')}
        self.assertEqual(board.lifecycle_state(packet,attested)['state'],'READY_TO_MERGE')
        self.assertEqual(board.lifecycle_state(packet,{**attested,
            'ci_checks':{**attested['ci_checks'],'review_complete@15368':'FAIL'}})['state'],
            'READY_FOR_ATTESTATION')
        ruleset_only={**policy,'checks':policy['checks'][:2]}
        self.assertEqual(board.lifecycle_state(packet,{**attested,
            'required_checks_policy':ruleset_only})['state'],'READY_TO_MERGE')
        self.assertEqual(board.lifecycle_state(packet,{**attested,
            'review_complete_evidence':{**attested['review_complete_evidence'],
                                        'integration_id':42}})['state'],'READY_FOR_ATTESTATION')
        self.assertEqual(board.lifecycle_state(packet,{**attested,
            'review_complete_evidence':{**attested['review_complete_evidence'],
                                        'head_sha':'c'*40}})['state'],'READY_FOR_ATTESTATION')
        self.assertEqual(board.lifecycle_state(packet,{**attested,
            'review_complete_scope':{'repository':packet['review_scope']['repository'],
                                     'pr_number':552}})['state'],'BLOCKED')
        extra={**event,'required_checks_policy':{**policy,'checks':policy['checks']+[
                   {'context':'new_required','integration_id':15368}]},
               'ci_checks':{**event['ci_checks'],'new_required@15368':'FAIL'}}
        self.assertEqual(board.lifecycle_state(packet,extra)['state'],'WAITING_CI')
        self.assertEqual(board.lifecycle_state(packet,{**extra,'ci_checks':{
            **extra['ci_checks'],'new_required@15368':'PASS'}})['state'],'READY_FOR_ATTESTATION')
        self.assertEqual(board.lifecycle_state(packet,{**attested,'review_complete_head':'a'*40})['state'],
                         'READY_FOR_ATTESTATION')
        self.assertEqual(board.lifecycle_state(packet,{**attested,'merged':True})['state'],'POST_MERGE_VERIFY')
        self.assertEqual(board.lifecycle_state(packet,{**attested,'merged':True,'post_merge_verified':True})['state'],
                         'POST_MERGE_VERIFY')

    def test_post_merge_requires_current_merge_and_default_head_binding(self):
        self.complete(); packet=self.tasks()[0]
        head=packet['identity']['code_sha']; merge='b'*40; previous='c'*40
        policy=dict(source='GITHUB_RULESET',scope=packet['review_scope'],pr_head_sha=head,
                    base_sha='b'*40,strict=True,ruleset_id=23762701,
                    ruleset_updated_at=self.at(-10),observed_at=self.at(-1),
                    identity='github-ruleset-observation-1',
                    checks=[dict(context=name,integration_id=15368)
                            for name in ('validate','portfolio_guard','review_complete')])
        event=dict(ci='PASS',ci_head=head,ci_checks={'validate@15368':'PASS',
                   'portfolio_guard@15368':'PASS','review_complete@15368':'PASS'},
                   required_checks_policy=policy,current_base_sha='b'*40,
                   base_ancestor_verified=True,
                   review='CLEAN',review_head=head,unresolved_findings=0,
                   review_scope=packet['review_scope'],review_complete_scope=packet['review_scope'],
                   review_complete='PASS',review_complete_head=head,
                   review_complete_evidence=dict(context='review_complete',integration_id=15368,
                       status='PASS',head_sha=head,scope=packet['review_scope'],identity='check-run-1'),
                   merged=True,
                   merged_pr_head=head,merge_sha=merge,default_branch_head=merge,
                   merge_scope=packet['review_scope'])
        pass_evidence=dict(status='PASS',identity='post-merge-check-run-1',
                           pr_head_sha=head,merge_sha=merge,default_branch_head=merge,
                           review_scope=packet['review_scope'])
        for evidence in ('FAIL',True,{**pass_evidence,'merge_sha':previous},
                         {**pass_evidence,'merge_sha':previous,'default_branch_head':previous}):
            with self.subTest(evidence=evidence):
                self.assertNotEqual(board.lifecycle_state(packet,{**event,
                    'post_merge_verified':evidence})['state'],'DONE')
        self.assertNotEqual(board.lifecycle_state(packet,{**event,'default_branch_head':previous,
            'post_merge_verified':pass_evidence})['state'],'DONE')
        self.assertNotEqual(board.lifecycle_state(packet,{**event,'merged_pr_head':previous,
            'post_merge_verified':pass_evidence})['state'],'DONE')
        self.assertNotEqual(board.lifecycle_state(packet,{**event,
            'post_merge_verified':{**pass_evidence,'pr_head_sha':previous}})['state'],'DONE')
        other_scope={'repository':packet['review_scope']['repository'],'pr_number':552}
        self.assertNotEqual(board.lifecycle_state(packet,{**event,'merge_scope':other_scope,
            'post_merge_verified':pass_evidence})['state'],'DONE')
        self.assertNotEqual(board.lifecycle_state(packet,{**event,
            'post_merge_verified':{**pass_evidence,'review_scope':other_scope}})['state'],'DONE')
        self.assertEqual(board.lifecycle_state(packet,{**event,
            'post_merge_verified':pass_evidence})['state'],'DONE')

    def test_unknown_action_cannot_use_ordinary_gate(self):
        packet=self.tasks()[0]
        for action in ('broker_order','portfolio_weight_change','target_write','novel_operation'):
            with self.subTest(action=action):
                self.assertEqual(board.lifecycle_state(packet,{'action':action})['state'],
                                 'HUMAN_APPROVAL_REQUIRED')
                self.assertEqual(board.lifecycle_state(packet,{'action':action,
                    'risk_tier':'T0_READ'})['state'],'HUMAN_APPROVAL_REQUIRED')
        for action,tier in (('read','T0_READ'),('compute','T1_COMPUTE')):
            self.assertEqual(board.lifecycle_state(packet,{'action':action,'risk_tier':tier})['state'],
                             'WAITING_CI')
        self.assertEqual(board.lifecycle_state(packet,{'action':'read',
            'risk_tier':'T4_ECONOMIC_MUTATION'})['state'],'HUMAN_APPROVAL_REQUIRED')
        self.assertEqual(board.lifecycle_state(packet,{'action':'reversible_repo_write'})['state'],
                         'BLOCKED')

    def test_receipt_evidence_identity_cannot_be_borrowed_from_another_task(self):
        receipt=self.complete(); self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')
        original=copy.deepcopy(receipt)
        for kind in ('runtime_verification','focused_tests','ci'):
            with self.subTest(kind=kind):
                receipt.clear(); receipt.update(copy.deepcopy(original))
                record=receipt[kind]
                record['identity']=board.evidence_identity(kind,record['reference'],
                    'f'*64,receipt['identity'],record['head_sha'],
                    receipt['outputs'],record['available_at'])
                self.assertEqual(self.tasks()[0]['status'],'BLOCKED')
        receipt.clear(); receipt.update(copy.deepcopy(original))
        receipt['ci']['head_sha']='a'*40
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')
        receipt.clear(); receipt.update(copy.deepcopy(original))
        receipt['reviewed_head']=receipt['code_sha']
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')

    def test_receipt_evidence_is_bound_to_output_bytes(self):
        receipt=self.complete()
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')
        output=receipt['outputs']['data_pit']
        self.set_payload(output, {'synthetic':'changed-result'})
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')

    def test_receipt_evidence_is_bound_to_output_metadata(self):
        receipt=self.complete()
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')
        receipt['outputs']['data_pit']['expires_at']=self.at(55)
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')

    def test_evidence_must_postdate_outputs_and_predate_receipt(self):
        receipt=self.complete()
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')
        original=copy.deepcopy(receipt['ci'])
        for value in (receipt['outputs']['data_pit']['collected_at'],
                      receipt['created_at'], receipt['available_at']):
            with self.subTest(available_at=value):
                receipt['ci']=copy.deepcopy(original)
                receipt['ci']['available_at']=value
                receipt['ci']['identity']=board.evidence_identity('ci',
                    receipt['ci']['reference'],receipt['task_key'],receipt['identity'],
                    receipt['ci']['head_sha'],receipt['outputs'],value)
                self.assertEqual(self.tasks()[0]['status'],'BLOCKED')
        receipt['ci']=original
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')

    def test_receipt_must_postdate_output_collection(self):
        receipt=self.complete()
        output=receipt['outputs']['data_pit']
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')
        original_collected=output['collected_at']
        output['collected_at']=receipt['available_at']
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')
        output['collected_at']=receipt['created_at']
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')
        output['collected_at']=original_collected
        self.assertEqual(self.tasks()[0]['status'],'SKIP_UNCHANGED')

    def test_approval_and_notification_boundaries_no_polling(self):
        packet=self.tasks()[0]
        for action in board.APPROVAL_ACTIONS:
            self.assertEqual(board.lifecycle_state(packet,{'action':action})['state'],'HUMAN_APPROVAL_REQUIRED')
        for tier in ('T4_ECONOMIC_MUTATION','T5_IRREVERSIBLE_OR_PROTECTED'):
            self.assertEqual(board.lifecycle_state(packet,{'risk_tier':tier})['state'],
                             'HUMAN_APPROVAL_REQUIRED')
        self.assertEqual(board.lifecycle_state(packet,{'risk_tier':'T3_REVERSIBLE_WRITE',
            'side_effects':['reversible_repo_write']})['state'],'WAITING_CI')
        self.assertEqual(board.lifecycle_state(packet,{'risk_tier':'T3_REVERSIBLE_WRITE',
            'side_effects':['target_book']})['state'],'HUMAN_APPROVAL_REQUIRED')
        self.assertEqual(board.lifecycle_state(packet,{'side_effects':['target_book']})['state'],
                         'HUMAN_APPROVAL_REQUIRED')
        for state in ('WAITING_CI','WAITING_REVIEW','SKIP_UNCHANGED'):
            self.assertNotIn(state,board.NOTIFY_STATES)
        self.assertEqual(board.lifecycle_state(packet,{'ci':'PENDING'})['state'],'WAITING_CI')
        self.assertFalse(board.lifecycle_state(packet,{'ci':'PENDING'})['notification_worthy'])
        self.assertFalse(board.lifecycle_state(packet,{'ci':'PENDING'})['polling_required'])
        self.assertFalse(board.lifecycle_state(packet,{'ci':'PENDING'})['ai_invocation_required'])
        self.assertTrue(board.lifecycle_state(packet,{'integrity_failure':True})['notification_worthy'])
        self.assertTrue(board.lifecycle_state(packet,{'unexpected_regression':True})['notification_worthy'])
        self.assertTrue(packet['dispatch_eligible'])
        self.add_request('A3')
        self.assertFalse(next(t for t in self.tasks() if t['agent']=='A3')['dispatch_eligible'])
        self.assertFalse(self.contract['specialist_dispatch_enabled'])

    def test_each_identity_component_invalidates_cache(self):
        self.complete()
        original=copy.deepcopy(self.state)
        for mutation in ('bytes','code','config','model','version','parameters','context'):
            with self.subTest(mutation=mutation):
                self.state=copy.deepcopy(original)
                sha, config=self.sha,self.config
                req=self.state['requests'][0]
                if mutation=='bytes':
                    item=req['inputs']['source_inventory']; (self.root/item['path']).write_text('new')
                    item['sha256']=board.file_hash(self.root/item['path'])
                elif mutation=='code':
                    self.sha='a'*40; self.state['code_sha']=self.sha
                elif mutation=='config': self.config='b'*64
                elif mutation=='model': req['model']['name']='other'
                elif mutation=='version': req['model']['version']='v2'
                elif mutation=='parameters': req['parameters']['fixture']=False
                else: self.state['context']['market_regime']='CAUTION'
                # Restore original fixture bytes for other identity cases.
                if mutation!='bytes': self.artifact('A1_source_inventory')
                self.assertEqual(self.tasks()[0]['status'],'READY')
                self.sha,self.config=sha,config

    def test_missing_or_tampered_completion_blocks(self):
        r=self.complete(); p=self.root/r['outputs']['data_pit']['path']
        p.write_text('tamper')
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')
        p.unlink()
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')

    def test_completion_cannot_predate_any_causal_input(self):
        self.add_request('A2'); self.complete(); receipt=self.complete('A2')
        receipt['outputs']['leadership_events']['available_at']=self.at(-11)
        self.assertEqual(self.tasks()[1]['status'],'BLOCKED')
        receipt['outputs']['leadership_events']['collected_at']=self.at(-11)
        self.assertEqual(self.tasks()[1]['status'],'BLOCKED')

    def test_output_must_strictly_follow_final_input(self):
        receipt=self.complete()
        final_input=max(board.timestamp(item['collected_at']) for item in
                        self.state['requests'][0]['inputs'].values()).isoformat()
        receipt['outputs']['data_pit']['available_at']=final_input
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')

    def test_wrong_receipt_identity_does_not_skip(self):
        r=self.complete(); r['task_key']='a'*64
        self.assertEqual(self.tasks()[0]['status'],'READY')

    def test_failed_receipt_cannot_be_success(self):
        self.complete()['status']='FAILED'
        with self.assertRaises(board.ContractError): self.tasks()

    def test_dependency_must_complete_not_merely_be_queued(self):
        self.add_request('A2')
        self.assertEqual(self.tasks()[1]['status'],'BLOCKED')
        self.complete()
        self.assertEqual(self.tasks()[1]['status'],'READY')

    def test_changed_dependency_output_invalidates_downstream(self):
        self.add_request('A2'); r=self.complete(); self.complete('A2')
        self.assertEqual(self.tasks()[1]['status'],'SKIP_UNCHANGED')
        output=r['outputs']['data_pit']; path=self.root/output['path']; path.write_text('recomputed')
        output['sha256']=board.file_hash(path)
        self.assertEqual(self.tasks()[1]['status'],'BLOCKED')
        self.state['requests'][1]['inputs']['data_pit']=copy.deepcopy(output)
        self.assertEqual(self.tasks()[0]['status'],'BLOCKED')
        self.assertIn('dependency_incomplete:A1',self.tasks()[1]['reasons'])

    def test_dependency_receipt_metadata_does_not_change_content_identity(self):
        self.add_request('A2'); upstream=self.complete(); self.complete('A2')
        before=self.tasks()[1]['task_key']
        upstream['ci']['reference']='same-head-independent-ci-run'
        upstream['ci']['identity']=board.evidence_identity('ci',upstream['ci']['reference'],
            upstream['task_key'],upstream['identity'],upstream['ci']['head_sha'],
            upstream['outputs'],upstream['ci']['available_at'])
        self.assertEqual(self.tasks()[1]['task_key'],before)
        self.assertEqual(self.tasks()[1]['status'],'SKIP_UNCHANGED')

    def test_completed_dependency_cannot_authorize_unrelated_input(self):
        req=self.add_request('A2'); self.complete()
        req['inputs']['data_pit']=self.artifact('unrelated_data_pit')
        self.assertIn('dependency_input_mismatch:A1:data_pit',self.tasks()[1]['reasons'])

    def test_all_specialists_follow_exact_dependency_contract(self):
        for n in range(2,9): self.add_request('A'+str(n))
        blocked={t['agent']:t for t in self.tasks()}
        self.assertIn('PORTFOLIO_CONTEXT_NOT_VERIFIED',blocked['A5']['reasons'])
        for key in ('actual_book','approved_target','thesis'): self.state['context'][key]='VERIFIED'
        for agent in ('A1','A2','A3','A4','A6','A5','A7','A8'):
            if agent=='A6': self.bind_qa_scope()
            pending={t['agent']:t for t in self.tasks()}
            self.assertEqual(pending[agent]['status'],'READY',agent)
            self.complete(agent)
        self.assertTrue(all(t['status']=='SKIP_UNCHANGED' for t in self.tasks()))

    def test_missing_data_snapshot_blocks_only_non_diagnostic_agents(self):
        self.add_request('A2'); self.add_request('A6'); self.state['context']['data_as_of']=None
        result={t['agent']:t for t in self.tasks()}
        self.assertEqual(result['A1']['status'],'READY')
        self.assertEqual(result['A6']['status'],'READY')
        self.assertIn('DATA_AS_OF_MISSING',result['A2']['reasons'])

    def test_qa_cannot_authorize_unreviewed_downstream_inputs(self):
        for n in range(2,9): self.add_request('A'+str(n))
        for key in ('actual_book','approved_target','thesis'): self.state['context'][key]='VERIFIED'
        for agent in ('A1','A2','A3','A4','A6'): self.complete(agent)
        result={t['agent']:t for t in self.tasks()}
        for agent in ('A5','A7','A8'):
            self.assertEqual(result[agent]['status'],'BLOCKED')
            self.assertTrue(any(r.startswith('QA_INPUT_NOT_REVIEWED:') for r in result[agent]['reasons']))

    def test_failed_qa_report_blocks_consumers(self):
        self.add_request('A6'); self.add_request('A7'); self.bind_qa_scope()
        receipt=self.complete('A6'); artifact=receipt['outputs']['qa_report']
        report=board.read_json(self.root/artifact['path']); report['verdict']='FAIL'
        self.set_payload(artifact,report)
        for req in self.state['requests']:
            if req['agent']=='A7':req['inputs']['qa_report']=copy.deepcopy(artifact)
        result={t['agent']:t for t in self.tasks()}
        self.assertEqual(result['A6']['status'],'BLOCKED')
        self.assertIn('dependency_incomplete:A6',result['A7']['reasons'])

    def test_dirty_specialist_or_untracked_source_changes_identity(self):
        root=self.root/'git-fixture'; root.mkdir()
        paths=['tools/run_agent_board.py','r1000_config.py','requirements_github.txt']
        paths+=['research/control_plane/'+n for n in ('agent_contracts_v2.yaml','task_packet_schema.json','system_state_schema.json')]
        for name in paths:
            dest=root/name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT/name,dest)
        specialist='tools/run_multi_asset_leadership.py'; (root/specialist).write_text('version = 1\n'); paths.append(specialist)
        def git(*args):
            subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
        git('init'); git('add','--',*paths)
        git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','synthetic fixture')
        with patch.object(board,'REPO_ROOT',root):
            original=board.source_identity()
            (root/specialist).write_text('version = 2\n')
            dirty=board.source_identity()
            self.assertEqual(original[0],dirty[0]); self.assertNotEqual(original[1],dirty[1])
            (root/specialist).write_text('version = 1\n')
            (root/'tools/new_helper.py').write_text('version = 1\n')
            self.assertNotEqual(original[1],board.source_identity()[1])

    def test_g0_blocks_non_diagnostic_agents(self):
        self.add_request('A2'); self.add_request('A6'); self.state['g0']['status']='BLOCKED'
        tasks={t['agent']:t for t in self.tasks()}
        self.assertEqual(tasks['A1']['status'],'READY')
        self.assertEqual(tasks['A6']['status'],'READY')
        self.assertIn('G0_NOT_PASS',tasks['A2']['reasons'])

    def test_stale_current_status_is_not_current_authority(self):
        self.add_request('A2'); self.complete(); self.state['context']['current_status_freshness']='STALE'
        self.assertIn('CURRENT_STATUS_NOT_VERIFIED',self.tasks()[1]['reasons'])

    def test_state_time_sha_and_unknown_fields_fail_closed(self):
        original=copy.deepcopy(self.state)
        for key,value in [('expires_at',self.at(-6)),('as_of',self.at(1)),('as_of','2026-09-20T00:00:00'),
                          ('code_sha','a'*40),('extra',True)]:
            with self.subTest(key=key,value=value):
                self.state=copy.deepcopy(original); self.state[key]=value
                with self.assertRaises(board.ContractError): self.tasks()

    def test_context_cannot_claim_verified_without_time_or_from_future(self):
        self.state['context']['current_status_as_of']=None
        with self.assertRaises(board.ContractError): self.tasks()
        self.state['context']['current_status_as_of']=self.at(1)
        with self.assertRaises(board.ContractError): self.tasks()

    def test_input_missing_tampered_stale_future_or_unavailable(self):
        original=copy.deepcopy(self.state)
        for key,value in [('sha256','a'*64),('path','missing.json'),('expires_at',self.at(-1)),
                          ('available_at',self.at(1)),('collected_at',self.at(1))]:
            with self.subTest(key=key):
                self.state=copy.deepcopy(original); self.state['requests'][0]['inputs']['source_inventory'][key]=value
                self.assertEqual(self.tasks()[0]['status'],'BLOCKED')

    def test_no_path_escape_or_symlink(self):
        for path in ('../outside','/etc/passwd'):
            with self.assertRaises(board.ContractError): board.artifact_path(self.root,path)
        (self.root/'link').symlink_to(self.root/'A1_source_inventory.json')
        with self.assertRaises(board.ContractError): board.artifact_path(self.root,'link')

    def test_duplicate_agent_and_receipt_rejected(self):
        self.state['requests'].append(copy.deepcopy(self.state['requests'][0]))
        with self.assertRaises(board.ContractError): self.tasks()
        self.state['requests'].pop(); self.complete()
        self.state['completed_tasks']*=2
        with self.assertRaises(board.ContractError): self.tasks()

    def test_schema_forbids_execution_peer_dispatch_and_a10(self):
        packet=self.tasks()[0]
        for mutate in ('agent','assigned_by','execute','peer_dispatch'):
            x=copy.deepcopy(packet)
            if mutate=='agent': x['agent']='A10'
            elif mutate=='assigned_by': x['assigned_by']='A2'
            else: x['authority'][mutate]=True
            with self.assertRaises(board.ContractError): board.schema_validate(x,'task_packet_schema.json')

    def test_wrong_input_roles_and_false_verified_state(self):
        req=self.state['requests'][0]; req['inputs']['wrong']=req['inputs'].pop('source_inventory')
        with self.assertRaises(board.ContractError): self.tasks()
        req['inputs']['source_inventory']=req['inputs'].pop('wrong')
        req['inputs']['source_inventory']['status']='PARTIAL'
        with self.assertRaises(board.ContractError): self.tasks()

    def test_duplicate_json_nonfinite_and_oversize_rejected(self):
        p=self.root/'bad.json'
        for content in ('{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}',' '* (4*1024*1024+1)):
            p.write_text(content)
            with self.assertRaises(board.ContractError): board.read_json(p)

    def test_board_manifest_binds_actual_outputs_and_ignores_old_metrics(self):
        args=self.args(); (self.root/'backtest_metrics.json').write_text('{"cagr":9.0}')
        result=board.run(args)
        self.assertEqual(result['status'],'BLOCKED')
        out=Path(args.output_dir)
        for name,sha in result['members'].items(): self.assertEqual(board.file_hash(out/name),sha)
        summary=board.read_json(out/'board_summary.json')
        self.assertNotIn('portfolios',summary)
        self.assertFalse(summary['promotion_gate']['human_promotion_review_candidate'])

    def test_missing_state_revokes_previous_success(self):
        args=self.args(); board.run(args)
        (self.root/'control_plane/system_state.json').unlink()
        result=board.run(args)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(board.read_json(Path(args.output_dir)/'agent_task_queue.json'),[])

    def test_interruption_leaves_blocked_receipt(self):
        args=self.args(); board.run(args)
        with patch.object(board,'contracts',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError): board.run(args)
        self.assertEqual(board.read_json(Path(args.output_dir)/'manifest.json')['status'],'BLOCKED')

    def test_task_cap_does_not_silently_drop_dependencies(self):
        self.add_request('A2'); args=self.args(); args.max_tasks=1
        self.assertEqual(board.run(args)['status'],'BLOCKED')

    def test_cli_no_state_returns_nonzero_and_report(self):
        result=subprocess.run([sys.executable,str(ROOT/'tools/run_agent_board.py'),
            '--latest-run',str(self.root),'--output-dir',str(self.root/'cli')],capture_output=True,text=True)
        self.assertEqual(result.returncode,2,result.stderr)
        self.assertTrue((self.root/'cli/report.md').is_file())


class ManagedOHLCVTests(unittest.TestCase):
    """The existing registered A0 contract suite exercises the no-I/O roster adapter."""

    def setUp(self):
        import copy
        from tools import prepare_a1_managed_ohlcv as managed
        self.m = managed
        self.copy = copy.deepcopy
        root = Path(__file__).resolve().parents[1]
        self.inventory, self.sha = managed.load(root / 'data_static/a1_ohlcv_inventory_v1.json')
        self.policy, self.policy_sha = managed.load(managed_initial_policy_file())
        self.assertEqual(self.policy_sha, MANAGED_INITIAL_POLICY_SHA)

    def gate(self, now='2026-10-23T23:30:00Z', force=False):
        return self.m.evaluate_market_session(now_utc=now, force=force)

    def plan(self, now='2026-10-23T23:30:00Z', **kw):
        return self.m.prepare(self.inventory, self.policy, self.sha, self.gate(now), now_utc=now, **kw)

    def changed(self, add=(), remove=()):
        previous = self.copy(self.policy)
        previous_sha = self.m.digest(self.m.encode(previous))
        self.policy.update(revision=2, previous_policy_sha256=previous_sha,
                           active_tickers=sorted((set(previous['active_tickers']) | set(add)) - set(remove)),
                           watch_tickers=sorted((set(previous['watch_tickers']) | set(remove)) - set(add)),
                           changes=[dict(ticker=t, action=action, event_id='change-20261024-' + t,
                                         a0_reference=self.m.A0 + '#issuecomment-12345678')
                                    for action, rows in [('START_UPDATE', add), ('MOVE_TO_WATCH', remove)]
                                    for t in rows])
        return previous, previous_sha

    def test_actual_820_is_deduplicated_and_not_admitted(self):
        report = self.plan()
        self.assertEqual(report['active_count'], 820)
        self.assertEqual(self.inventory['counts'], dict(unique_tickers=820, alpaca_sip=776,
                                                       twelve_data=312, overlap=268))
        self.assertTrue(all(r['next_action'] == 'VERIFY_EXISTING_COVERAGE' and
                            r['missing_interval'] is None and not r['source_admission']
                            for r in report['requests']))
        self.assertIn('BRK.B', self.policy['active_tickers'])

    def test_regular_close_plus_two_hours_and_no_provider_calls(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('provider')) as get:
            report = self.plan()
        get.assert_not_called()
        self.assertEqual(report['status'], 'PREPARED_NO_CAPTURE')
        self.assertEqual(report['earliest_refresh_utc'], '2026-10-23T22:00:00+00:00')
        self.assertEqual((report['provider_requests'], report['dispatches']), (0, 0))
        self.assertFalse(report['collection_enabled'])

    def test_versioned_activation_preserves_roster_and_preparation_boundary(self):
        policy, _ = self.m.load(ROOT / 'data_static/a1_ohlcv_managed_v1.json')
        self.assertEqual(policy['revision'], 2)
        self.assertEqual(policy['previous_policy_sha256'], self.policy_sha)
        self.assertTrue(policy['automatic_capture_enabled'])
        self.assertIsNone(policy['execution_authorization'])
        self.assertEqual(policy['active_tickers'], self.policy['active_tickers'])
        self.assertEqual((policy['watch_tickers'], policy['changes']), ([], []))
        with patch('urllib.request.urlopen', side_effect=AssertionError('provider')) as get:
            report = self.m.prepare(self.inventory, policy, self.sha, self.gate(),
                                    previous=self.policy, previous_sha=self.policy_sha,
                                    now_utc='2026-10-23T23:30:00Z')
        get.assert_not_called()
        self.assertEqual(report['status'], 'PREPARED_NO_CAPTURE')
        self.assertEqual((report['provider_requests'], report['dispatches']), (0, 0))
        self.assertFalse(report['collection_enabled'])

    def test_close_buffer_cannot_be_forced(self):
        now = '2026-10-23T21:00:00Z'
        report = self.m.prepare(self.inventory, self.policy, self.sha, self.gate(now, True), now_utc=now)
        self.assertEqual(report['status'], 'SKIP_MARKET_WINDOW')

    def test_holiday_is_not_a_completed_refresh(self):
        self.assertEqual(self.plan('2026-07-03T23:30:00Z')['status'], 'SKIP_MARKET_WINDOW')

    def test_weekend_is_not_a_completed_refresh(self):
        self.assertEqual(self.plan('2026-10-25T23:30:00Z')['status'], 'SKIP_MARKET_WINDOW')

    def test_early_close_is_calendar_based(self):
        report = self.plan('2026-11-27T21:00:00Z')
        self.assertEqual(report['market_close_utc'], '2026-11-27T18:00:00+00:00')
        self.assertEqual(report['earliest_refresh_utc'], '2026-11-27T20:00:00+00:00')

    def test_winter_close_uses_actual_exchange_time(self):
        report = self.plan('2026-11-23T23:30:00Z')
        self.assertEqual(report['earliest_refresh_utc'], '2026-11-23T23:00:00+00:00')

    def test_stale_and_future_receipts_refuse(self):
        gate = self.gate()
        for now in ['2026-10-24T00:00:00Z', '2026-10-23T23:29:59Z']:
            with self.assertRaisesRegex(ValueError, 'MARKET_RECEIPT'):
                self.m.prepare(self.inventory, self.policy, self.sha, gate, now_utc=now)

    def test_forged_close_or_naive_clock_refuses(self):
        gate = self.gate()
        gate['market_close_utc'] = '2026-10-23T19:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'MARKET_SESSION_CONFLICT'):
            self.m.prepare(self.inventory, self.policy, self.sha, gate, now_utc='2026-10-23T23:30:00Z')
        gate = self.gate()
        gate['checked_at_utc'] = '2026-10-23T23:30:00'
        with self.assertRaisesRegex(ValueError, 'MARKET_CLOCK'):
            self.m.prepare(self.inventory, self.policy, self.sha, gate, now_utc='2026-10-23T23:30:00Z')

    def test_addition_is_review_only_and_removal_preserves_inventory(self):
        before = self.m.encode(self.inventory)
        previous, sha = self.changed(add=['TEST'], remove=['AAPL'])
        report = self.plan(previous=previous, previous_sha=sha)
        self.assertEqual(report['added'], ['TEST'])
        self.assertEqual(report['moved_to_watch'], [dict(ticker='AAPL', action='CONTINUE_TRACKING_RETAIN_HISTORY')])
        self.assertEqual(report['watch_count'], 1)
        self.assertEqual(report['tracked_count'], 821)
        self.assertEqual(next(r for r in report['requests'] if r['ticker'] == 'AAPL')['management_state'], 'WATCH')
        self.assertEqual(report['updates_stopped'], [])
        self.assertEqual(next(r for r in report['requests'] if r['ticker'] == 'TEST')['next_action'],
                         'BACKFILL_REVIEW_REQUIRED')
        self.assertEqual(self.m.encode(self.inventory), before)

    def test_missing_previous_or_wrong_hash_refuses(self):
        previous, sha = self.changed(remove=['AAPL'])
        for p, s in [(None, None), (previous, '0' * 64)]:
            with self.assertRaisesRegex(ValueError, 'PREVIOUS_POLICY'):
                self.plan(previous=p, previous_sha=s)

    def test_unrecorded_or_duplicate_change_refuses(self):
        previous, sha = self.changed(remove=['AAPL'])
        record = self.copy(self.policy['changes'][0])
        for changes in [[], [record, record]]:
            self.policy['changes'] = changes
            with self.assertRaisesRegex(ValueError, 'ROSTER_CHANGE_MISMATCH|DUPLICATE_CHANGE'):
                self.plan(previous=previous, previous_sha=sha)

    def test_wrong_a0_reference_refuses(self):
        previous, sha = self.changed(remove=['AAPL'])
        self.policy['changes'][0]['a0_reference'] = 'https://example.com/approval'
        with self.assertRaisesRegex(ValueError, 'A0_CHANGE_REFERENCE'):
            self.plan(previous=previous, previous_sha=sha)

    def test_config_boolean_cannot_enable_capture(self):
        self.policy['automatic_capture_enabled'] = True
        self.assertFalse(self.plan()['collection_enabled'])

    def test_watch_cannot_silently_drop_price_tracking(self):
        previous, sha = self.changed(remove=['AAPL'])
        self.policy['watch_tickers'] = []
        with self.assertRaisesRegex(ValueError, 'WATCH_HISTORY_MUST_BE_RETAINED'):
            self.plan(previous=previous, previous_sha=sha)

    def test_reentry_reuses_watch_without_duplicate_tracking(self):
        previous, sha = self.changed(remove=['AAPL'])
        self.plan(previous=previous, previous_sha=sha)
        previous = self.copy(self.policy)
        sha = self.m.digest(self.m.encode(previous))
        self.policy.update(revision=3, previous_policy_sha256=sha, watch_tickers=[],
                           active_tickers=sorted(set(previous['active_tickers']) | {'AAPL'}),
                           changes=[dict(ticker='AAPL', action='START_UPDATE', event_id='reentry-20261027-AAPL',
                                         a0_reference=self.m.A0 + '#issuecomment-12345679')])
        report = self.plan(previous=previous, previous_sha=sha)
        self.assertEqual((report['active_count'], report['watch_count'], report['tracked_count']), (820, 0, 820))
        self.assertEqual(report['added'], ['AAPL'])
        self.assertEqual(next(r for r in report['requests'] if r['ticker'] == 'AAPL')['next_action'],
                         'VERIFY_EXISTING_COVERAGE')

    def test_wrong_inventory_hash_or_count_refuses(self):
        self.policy['inventory_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'POLICY_BINDING'):
            self.plan()
        self.policy['inventory_sha256'] = self.sha
        self.inventory['counts']['unique_tickers'] = 821
        with self.assertRaisesRegex(ValueError, 'INVENTORY_COUNTS'):
            self.plan()

    def test_repeated_preparation_has_same_identity(self):
        self.assertEqual(self.plan()['plan_id'], self.plan()['plan_id'])

    def test_git_checkout_preserves_policy_bound_bytes(self):
        result = subprocess.check_output(['git', '-c', 'safe.directory=' + ROOT.as_posix(),
            'check-attr', 'eol', 'text', '--', 'data_static/a1_ohlcv_inventory_v1.json',
            'data_static/a1_ohlcv_managed_v1.json', 'data_static/a1_ohlcv_managed_history/example.json'],
            cwd=ROOT, text=True)
        for name in ['a1_ohlcv_inventory_v1.json', 'a1_ohlcv_managed_v1.json']:
            self.assertIn('data_static/' + name + ': eol: lf', result)
        self.assertIn('data_static/a1_ohlcv_managed_history/example.json: text: unset', result)

    def test_json_duplicate_and_oversize_refuse(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'input.json'
            p.write_bytes(b'{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError, 'DUPLICATE_JSON_KEY'):
                self.m.load(p)
            p.write_bytes(b' ' * (self.m.MAX_BYTES + 1))
            with self.assertRaisesRegex(ValueError, 'INPUT_SIZE'):
                self.m.load(p)

    def test_failed_input_revokes_prior_report_and_alias_is_preserved(self):
        import tempfile
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            (p / 'bad.json').write_text('{')
            output = p / 'report.json'
            output.write_text('{"status":"PREPARED_NO_CAPTURE"}')
            args = SimpleNamespace(inventory=p / 'bad.json', policy=p / 'bad.json',
                                   market_gate=p / 'bad.json', output=output, now_utc=None)
            code, report = self.m.run(args)
            self.assertEqual((code, report['status']), (2, 'BLOCKED_INPUT'))
            self.assertEqual(json.loads(output.read_text())['status'], 'BLOCKED_INPUT')
            before = (p / 'bad.json').read_bytes()
            args.output = p / 'bad.json'
            with self.assertRaisesRegex(ValueError, 'OUTPUT_ALIAS'):
                self.m.run(args)
            self.assertEqual((p / 'bad.json').read_bytes(), before)

    def test_malformed_inventory_cannot_destroy_archived_policy(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            history = p / 'a1_ohlcv_managed_history'
            history.mkdir()
            archive = history / ('a' * 64 + '.json')
            archive.write_bytes(b'EXACT_PRIVATE_PARENT_BYTES')
            args = SimpleNamespace(inventory=p / 'missing', policy=p / 'bad', market_gate=p / 'bad',
                                   output=archive, now_utc=None)
            with self.assertRaisesRegex(ValueError, 'OUTPUT_ALIAS'):
                self.m.run(args)
            self.assertEqual(archive.read_bytes(), b'EXACT_PRIVATE_PARENT_BYTES')


class ManagedExecutionTests(unittest.TestCase):
    """Synthetic standing controls and injected transport; never actual rights proof."""

    def setUp(self):
        from tools import alpaca_sip_managed_refresh as runtime
        from types import SimpleNamespace
        self.r, self.ns = runtime, SimpleNamespace
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = runtime.campaign.utc('2026-10-23T23:30:00Z')
        env = patch.dict('os.environ', {'GITHUB_SHA':'2'*40})
        env.start()
        self.addCleanup(env.stop)
        self.control = dict(schema=runtime.SCHEMA, repository=runtime.REPO,
            task_key='R1000-SYNTHETIC-MANAGED-OFFLINE-ONLY',
            inventory_sha256='a'*64, policy_sha256='b'*64,
            not_before='2026-10-23T00:00:00Z', expires_at='2026-10-24T00:00:00Z',
            max_runs=2, max_symbols_per_run=4, max_active_seconds_per_run=300,
            private_noncommercial=True, supplier_rights_verified=True, source_admission=False,
            rights_ref=dict(file_id='fixture-rights-123', sha256='c'*64, bytes=1),
            bootstrap_ref=dict(file_id='fixture-bootstrap-123', sha256='d'*64, bytes=1),
            opening_evidence_ref=dict(file_id='fixture-opening-123',sha256='1'*64,bytes=1),
            owner_sha256='e'*64, credential_binding='f'*64, opening_evidence_sha256='1'*64,
            source_history_sha256=runtime.sha([]),
            private_root_folder_id='fixture-root-123', private_data_folder_id='fixture-data-123',
            journal_folder_id='fixture-journal-123', evidence_folder_id='fixture-evidence-123',
            opening_usage={k: 1 for k in runtime.TOTAL_KEYS},
            per_run_allowance=dict(provider_gets=50, drive_requests=200, drive_bytes=500_000_000, storage_bytes=500_000),
            cumulative_ceiling=dict(provider_gets=101, drive_requests=401, drive_bytes=1_000_000_001,
                                    storage_bytes=1_000_001, active_seconds=10801, dispatches=3),
            authorized_tickers=['AAPL', 'MSFT'], backfill_tickers=[],
            deployment=dict(pull_request=671, reviewed_head='2'*40, merge_sha='3'*40),
            code_pins={p: '4'*64 for p in runtime.PIN_PATHS},
            approval_reference=runtime.managed.A0+'#issuecomment-12345678')

    def validate(self):
        return self.r.validate_control(self.control, 'a'*64, 'b'*64, self.now)

    def test_absent_rights_stops_before_credentials_github_or_drive(self):
        args = self.ns(policy=managed_initial_policy_file(),
                       inventory=ROOT/'data_static/a1_ohlcv_inventory_v1.json',
                       meter=self.root/'meter.json', output=self.root/'result.json')
        with patch.dict('os.environ', {}, clear=True):
            result = self.r.run(args, gh=lambda _: self.fail('remote metadata'),
                                drive_factory=lambda *a, **k: self.fail('Drive'))
        self.assertEqual((result['status'], result['provider_requests']), ('WAIT_OWNER_EVIDENCE', 0))
        self.assertFalse(args.meter.exists())

    def test_enabled_boolean_still_requires_private_execution_contract(self):
        args = self.ns(policy=self.root/'policy.json', inventory=ROOT/'data_static/a1_ohlcv_inventory_v1.json',
                       meter=self.root/'meter.json', output=self.root/'result.json')
        policy, _ = self.r.managed.load(managed_initial_policy_file())
        policy['automatic_capture_enabled'] = True
        args.policy.write_bytes(self.r.encoded(policy))
        with patch.dict('os.environ', {}, clear=True), self.assertRaisesRegex(self.r.Refused, 'MANAGED_CONTROL_REQUIRED'):
            self.r.run(args, gh=lambda _: self.fail('remote metadata'))

    def test_deployed_activation_still_refuses_missing_contract_before_remote_io(self):
        args = self.ns(policy=ROOT/'data_static/a1_ohlcv_managed_v1.json',
                       inventory=ROOT/'data_static/a1_ohlcv_inventory_v1.json',
                       meter=self.root/'meter.json', output=self.root/'result.json')
        with patch.dict('os.environ', {}, clear=True), self.assertRaisesRegex(self.r.Refused, 'MANAGED_CONTROL_REQUIRED'):
            self.r.run(args, gh=lambda _: self.fail('remote metadata'),
                       drive_factory=lambda *a, **k: self.fail('Drive'))
        self.assertFalse(args.meter.exists())

    def test_output_or_meter_alias_refuses_before_mutation(self):
        args = self.ns(policy=ROOT/'data_static/a1_ohlcv_managed_v1.json',
                       inventory=ROOT/'data_static/a1_ohlcv_inventory_v1.json',
                       meter=ROOT/'data_static/a1_ohlcv_managed_v1.json', output=self.root/'result')
        before = args.policy.read_bytes()
        with self.assertRaisesRegex(ValueError, 'OUTPUT_ALIAS'):
            self.r.run(args)
        self.assertEqual(before, args.policy.read_bytes())

    def test_opening_costs_and_full_reservation_not_reset(self):
        self.validate()
        for key in self.r.TOTAL_KEYS:
            with self.subTest(key=key):
                old = self.control['cumulative_ceiling'][key]
                self.control['cumulative_ceiling'][key] = old-1
                with self.assertRaisesRegex(self.r.Refused, 'MANAGED_CUMULATIVE_RESERVATION'):
                    self.validate()
                self.control['cumulative_ceiling'][key] = old

    def test_expired_or_unreviewed_control_refuses(self):
        self.control['supplier_rights_verified'] = False
        with self.assertRaisesRegex(self.r.Refused, 'WAIT_OWNER_EVIDENCE'):
            self.validate()
        self.control['supplier_rights_verified'] = True
        self.control['expires_at'] = '2026-10-23T23:30:00Z'
        with self.assertRaisesRegex(self.r.Refused, 'MANAGED_WINDOW'):
            self.validate()

    def test_actual_comment_locator_does_not_require_predicted_id(self):
        h = self.validate()
        self.control['approval_reference'] = self.r.managed.A0+'#issuecomment-99999999'
        self.assertEqual(h, self.validate())
        self.control['max_symbols_per_run'] = 3
        self.assertNotEqual(h, self.validate())

    def grant(self):
        return dict(id=12345678, author_association='OWNER', user=dict(type='User'),
            issue_url=f'https://api.github.com/repos/{self.r.REPO}/issues/448',
            created_at='2026-10-23T01:00:00Z', updated_at='2026-10-23T01:00:00Z',
            body=self.r.TAG+json.dumps(dict(control_sha256=self.validate(),
                rights_sha256='c'*64, opening_evidence_sha256='1'*64,
                expires_at=self.control['expires_at'], private_retention_reviewed=True,
                historical_sip_reviewed=True, standing_budget_approved=True)))

    def test_owner_proof_is_exact_immutable_and_no_waiver(self):
        grant = self.grant()
        self.r.owner_grant(self.control, self.validate(), lambda _: grant, self.now)
        for field, value in [('author_association', 'MEMBER'), ('updated_at', '2026-10-23T02:00:00Z'),
                             ('body', 'generic free plan or API success')]:
            bad = dict(grant, **{field: value})
            with self.assertRaises(self.r.Refused):
                self.r.owner_grant(self.control, self.validate(), lambda _: bad, self.now)

    def test_missing_window_incremental_reuse_and_twelve_hold(self):
        windows, reused, held = self.r.missing_windows(['AAPL','MSFT','T'],
            dict(AAPL='2026-10-22', MSFT='2026-10-23'), '2026-10-23', set())
        self.assertEqual(windows, {('2026-10-23','2026-10-24'): ['AAPL']})
        self.assertEqual(reused, ['MSFT'])
        self.assertEqual(held, {'T': 'MISSING_VERIFIED_ALPACA_COVERAGE'})

    def test_unknown_journal_or_failed_run_never_replayed(self):
        history = [dict(id=1,head_sha='2'*40), dict(id=2,head_sha='2'*40)]
        with self.assertRaisesRegex(self.r.Refused, 'UNCONFIRMED_PRIOR_RUN'):
            self.r.restore_journal([], history, 'a'*64)
        base = dict(slot=1,run_id=1,source_sha='2'*40,control_sha256='a'*64)
        rows = [('b'*64, dict(base,state='RESERVED',parent_sha256=None)),
                ('c'*64, dict(base,state='BLOCKED',parent_sha256='b'*64))]
        with self.assertRaisesRegex(self.r.Refused, 'PRIOR_FAILURE_REQUIRES_RECONCILIATION'):
            self.r.restore_journal(rows, history, 'a'*64)

    def test_opt_in_anchor_is_one_verified_previous_close_without_new_backfill(self):
        windows, reused, held = self.r.missing_windows(['AAPL', 'MSFT', 'T'],
            dict(AAPL='2026-10-22', MSFT='2026-10-23'), '2026-10-23', set(),
            include_previous_close=True)
        self.assertEqual(windows, {('2026-10-22', '2026-10-24'): ['AAPL']})
        self.assertEqual(reused, ['MSFT'])
        self.assertEqual(held, {'T': 'MISSING_VERIFIED_ALPACA_COVERAGE'})

    def test_anchor_flag_changes_the_control_hash_and_is_exact_bool(self):
        before = self.validate()
        self.control['include_previous_close'] = True
        self.assertNotEqual(before, self.validate())
        for bad in [None, 1, 0, 'true', []]:
            with self.subTest(value=bad):
                self.control['include_previous_close'] = bad
                with self.assertRaisesRegex(self.r.Refused, 'MANAGED_ANCHOR_SCOPE'):
                    self.validate()

    def test_anchor_flag_false_preserves_original_incremental_window(self):
        args = ({'AAPL'}, {'AAPL':'2026-10-22'}, '2026-10-23', set())
        self.assertEqual(self.r.missing_windows(*args),
                         self.r.missing_windows(*args, include_previous_close=False))

    def test_prior_complete_needs_final_meter_and_exact_chain(self):
        history = [dict(id=1,head_sha='2'*40), dict(id=2,head_sha='2'*40)]
        base = dict(slot=1,run_id=1,source_sha='2'*40,control_sha256='a'*64)
        rows = [('b'*64, dict(base,state='RESERVED',parent_sha256=None)),
                ('c'*64, dict(base,state='COMPLETE',parent_sha256='b'*64,
                              coverage_updates={'AAPL':'2026-10-22'},held={}))]
        with self.assertRaisesRegex(self.r.Refused, 'MANAGED_FINAL_METER_REQUIRED'):
            self.r.restore_journal(rows, history, 'a'*64)
        observed = []
        result = self.r.restore_journal(rows, history, 'a'*64, lambda run,h: observed.append(h))
        self.assertEqual(result, ('c'*64, {'AAPL':'2026-10-22'}, {}))
        self.assertEqual(observed, ['c'*64])

    def test_positive_skipped_job_requires_no_checkpoint(self):
        history = [dict(id=1,managed_skipped=True), dict(id=2)]
        self.assertEqual(self.r.restore_journal([],history,'a'*64), (None,{},{}))
        with self.assertRaisesRegex(self.r.Refused, 'SKIPPED_STATE_CONFLICT'):
            self.r.restore_journal([('b'*64,dict(slot=1))],history,'a'*64)

    def test_final_meter_covers_checkpoint_publication(self):
        meter = dict(schema='a1-sip-campaign-meter-v1',run_id=1,run_attempt=1,source_sha='2'*40,
            managed_control_sha256='a'*64,managed_checkpoint_sha256='b'*64,finalized=True,status='COMPLETE',
            allowance=self.control['per_run_allowance'],transfer_definition=self.r.campaign.METRIC,
            source_admission=False,pit_verified=False,economic_authority=False,
            usage={k:1 for k in self.r.KEYS})
        run = dict(id=1,head_sha='2'*40)
        self.r.verify_final_meter(meter,run,'b'*64,'a'*64,self.control['per_run_allowance'])
        meter['finalized'] = False
        with self.assertRaisesRegex(self.r.Refused,'MANAGED_FINAL_METER'):
            self.r.verify_final_meter(meter,run,'b'*64,'a'*64,self.control['per_run_allowance'])

    def test_full_session_grid_does_not_accept_last_day_only(self):
        import gzip
        rows = [dict(ticker='AAPL',adjustment=a,date=d) for a in ['raw','split']
                for d in ['2026-10-22','2026-10-23']]
        pack = lambda v: gzip.compress(b''.join(self.r.encoded(r) for r in v))
        self.assertEqual(self.r.complete_grid(pack(rows),['AAPL'],'2026-10-22','2026-10-24'), {'AAPL'})
        self.assertEqual(self.r.complete_grid(pack(rows[1:]),['AAPL'],'2026-10-22','2026-10-24'), set())

    def test_metadata_reads_keep_original_deadline_and_bound_calls(self):
        reader = self.r.MetadataReader(lambda _: {}, self.now+timedelta(seconds=46), lambda:self.now)
        self.assertEqual(reader('fixture'), {})
        reader.calls = 170
        with self.assertRaisesRegex(self.r.Refused,'MANAGED_METADATA_BUDGET'):
            reader('fixture')
        reader.calls = 0
        reader.deadline = self.now+timedelta(seconds=44)
        with self.assertRaisesRegex(self.r.Refused,'MANAGED_METADATA_BUDGET'):
            reader('fixture')

    def test_full_source_prefix_fences_new_runs_and_older_rerun_attempts(self):
        rows = [dict(id=i,run_attempt=1,head_sha='2'*40,status='completed',conclusion='success',
                     created_at=f'2026-10-2{i}T00:00:00Z',updated_at=f'2026-10-2{i}T01:00:00Z')
                for i in [1,2]]
        self.control['source_history_sha256'] = self.r.sha(rows)
        fetch = lambda _: dict(total_count=len(rows),workflow_runs=list(reversed(rows)))
        self.assertEqual(self.r.source_history_fence(self.control,fetch),rows)
        rows[0]['run_attempt'] = 2  # latest created ID remains2
        with self.assertRaisesRegex(self.r.Refused,'INTERVENING_SOURCE_ACTIVITY'):
            self.r.source_history_fence(self.control,fetch)
        rows[0]['run_attempt'] = 1
        rows.append(dict(rows[1],id=3))
        with self.assertRaisesRegex(self.r.Refused,'INTERVENING_SOURCE_ACTIVITY'):
            self.r.source_history_fence(self.control,fetch)

    def test_partial_source_history_is_not_a_safe_zero_cost_prefix(self):
        with self.assertRaisesRegex(self.r.Refused,'SOURCE_HISTORY_INCOMPLETE'):
            self.r.source_history_fence(self.control,lambda _:dict(total_count=2,workflow_runs=[]))

    def no_capture(self):
        now = self.r.campaign.utc('2026-07-03T23:30:00Z')
        value = dict(schema='a1-managed-no-capture-v1',status='SKIP_MARKET_WINDOW',
            managed_control_sha256='a'*64,run_id=1,run_attempt=1,source_sha='2'*40,
            observed_at_utc=now.isoformat(),phase='BEFORE_CREDENTIALS',provider_requests=0,
            drive_requests=0,collection_enabled=False,
            market_gate=self.r.managed.evaluate_market_session(now_utc=now,min_close_age_minutes=120))
        run = dict(id=1,head_sha='2'*40,created_at='2026-07-03T23:29:00Z',updated_at='2026-07-03T23:31:00Z')
        return value,run

    def test_holiday_outcome_can_continue_only_with_positive_no_capture_artifact(self):
        value,run = self.no_capture()
        verifier = lambda r,h:self.r.verify_final_meter(value,r,h,'a'*64,self.control['per_run_allowance'])
        self.assertEqual(self.r.restore_journal([], [run,dict(id=2)],'a'*64,verifier), (None,{},{}))
        value['provider_requests'] = 1
        with self.assertRaisesRegex(self.r.Refused,'NO_CAPTURE_PROOF'):
            self.r.restore_journal([], [run,dict(id=2)],'a'*64,verifier)

    def test_no_capture_clock_or_false_holiday_never_passes(self):
        value,run = self.no_capture()
        value['observed_at_utc'] = '2026-10-23T23:30:00Z'
        run.update(created_at='2026-10-23T23:29:00Z',updated_at='2026-10-23T23:31:00Z')
        with self.assertRaisesRegex(self.r.Refused,'NO_CAPTURE_CALENDAR'):
            self.r.verify_final_meter(value,run,None,'a'*64,self.control['per_run_allowance'])
        value,run = self.no_capture()
        run['updated_at'] = '2026-07-03T23:29:59Z'
        with self.assertRaisesRegex(self.r.Refused,'NO_CAPTURE_CLOCK'):
            self.r.verify_final_meter(value,run,None,'a'*64,self.control['per_run_allowance'])
    def test_existing_workflow_reuses_source_lock_and_defaults_disabled(self):
        import yaml
        value = yaml.safe_load((ROOT/'.github/workflows/free_data_daily_update.yml').read_text(encoding='utf-8'))
        job = value['jobs']['managed_a1_refresh']
        self.assertEqual(job['concurrency']['group'], 'a1-private-research-single-writer')
        self.assertFalse(job['concurrency']['cancel-in-progress'])
        self.assertIn("A1_MANAGED_OHLCV_ENABLED == 'true'",job['if'])
        self.assertIn('inputs.managed_refresh',job['if'])
        self.assertNotIn('run_free_data_engine_validation',str(job))

    def memory_capture(self, fail=False):
        """Existing capture/readback code with real RuntimeMeter, entirely in RAM."""
        from urllib.parse import parse_qs, urlsplit
        import re
        r, ns, control = self.r, self.ns, self.control
        class Reply:
            status = 200
            def __init__(self, body):
                self.body = body
                self.fp = ns(raw=ns(_sock=ns(settimeout=lambda _:None)))
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read1(self, n):
                result, self.body = self.body[:n], self.body[n:]
                return result
        class Opener:
            calls = 0
            def open(self, request, **kw):
                self.calls += 1
                if fail: raise OSError('FIXTURE_PRIVATE_TRANSPORT_CANARY')
                u = urlsplit(request.full_url)
                if '/assets/' in u.path:
                    value = dict(symbol=u.path.rsplit('/',1)[1],id='00000000-0000-0000-0000-000000000001',
                                 exchange='NASDAQ',status='active',**{'class':'us_equity'})
                else:
                    names = parse_qs(u.query)['symbols'][0].split(',')
                    value = dict(bars={t:[dict(t='2026-10-23T04:00:00Z',o=10,h=11,l=9,c=10.5,v=100)]
                                       for t in names},next_page_token=None)
                return Reply(r.encoded(value))
        opener = Opener()
        identity = dict(run_id=1,run_attempt=1,source_sha='2'*40,managed_control_sha256='a'*64,
                        parent_checkpoint_sha256=None,examined_before=0)
        meter = r.campaign.RuntimeMeter(control['per_run_allowance'],self.root/'fixture-meter.json',
                                       (self.now+timedelta(seconds=300)).isoformat(),identity,
                                       clock=lambda:self.now,opener=opener)
        class Drive:
            root_id, token = control['private_root_folder_id'], 'fixture-token'
            objects, parents, names = {}, {}, {}
            def cost(self): meter.debit(dict(drive_requests=1,drive_bytes=100))
            def check(self, fid, parent=None, folder=False):
                self.cost()
                r.require(fid in self.objects and self.parents[fid] == parent,'FIXTURE_OWNER')
            def read(self, fid, limit=16_000_000):
                self.cost()
                value = self.objects[fid]
                r.require(len(value)<=limit,'FIXTURE_LIMIT')
                return value
            def request(self, url, **kw):
                self.cost()
                q = parse_qs(urlsplit(url).query)['q'][0]
                parent = re.search(r"'([^']+)' in parents",q).group(1)
                name = re.search(r"name = '([^']+)'",q)
                return r.encoded(dict(files=[dict(id=f,name=self.names[f],size=str(len(b)))
                    for f,b in self.objects.items() if self.parents[f]==parent
                    and (name is None or self.names[f]==name.group(1))]))
            def write(self, folder, body, ext):
                self.cost()
                meter.reserve_storage(len(body))
                fid = 'fixture-object-'+str(len(self.objects)+1).zfill(6)
                self.objects[fid],self.parents[fid],self.names[fid]=body,folder,r.digest(body)+ext
                return dict(file_id=fid,sha256=r.digest(body),bytes=len(body))
        drive = Drive()
        bindings = {}
        for t in ['AAPL','MSFT']:
            raw = r.encoded(dict(symbol=t,id='00000000-0000-0000-0000-000000000001',
                exchange='NASDAQ',status='active',**{'class':'us_equity'}))
            bindings[t] = drive.write(control['evidence_folder_id'],raw,'.json')
        self.fixture_bindings = bindings
        return drive, meter, opener

    def retained_bootstrap(self, dates, start='2026-10-21', end='2026-10-24'):
        """Build original response/normalized/receipt bytes with the real capture."""
        drive, meter, opener = self.memory_capture()
        original_open = opener.open
        def response(request, **kw):
            reply = original_open(request, **kw)
            value = self.r.decode(reply.body)
            for ticker, bars in value.get('bars', {}).items():
                value['bars'][ticker] = [dict(bars[0], t=day+'T04:00:00Z') for day in dates[ticker]]
            reply.body = self.r.encoded(value)
            return reply
        opener.open = response
        names = sorted(dates)
        meter.asset_symbols = tuple(names)
        with patch.object(self.r.capture.time, 'sleep', return_value=None):
            objects, _, _, _ = self.r.capture.capture_one_group(
                drive, self.control['private_data_folder_id'], names, start, end,
                'fixture-api-key', 'fixture-api-secret', 'a'*64, '2'*40, get=meter.perform)
        receipt = self.r.decode(drive.read(objects[-1]['file_id']))
        self.r.capture.verify_archived_group(drive.read(objects[0]['file_id']),
            drive.read(objects[1]['file_id']), receipt)
        bootstrap = dict(groups=[dict(provider='alpaca_sip', symbols=names, receipt=objects[-1])])
        return drive, bootstrap, opener

    def test_retained_bootstrap_refuses_leading_and_interior_session_gaps(self):
        for days in (['2026-10-23'], ['2026-10-21', '2026-10-23']):
            with self.subTest(days=days):
                drive, bootstrap, opener = self.retained_bootstrap({'AAPL':days})
                calls = opener.calls
                with self.assertRaisesRegex(self.r.Refused, '^MANAGED_BOOTSTRAP_INCOMPLETE_GRID$'):
                    self.r.bootstrap_coverage(drive, self.control, bootstrap, {'AAPL'})
                self.assertEqual(opener.calls, calls)

    def test_retained_bootstrap_complete_grid_reuses_without_provider(self):
        days = ['2026-10-21', '2026-10-22', '2026-10-23']
        # End-exclusive Monday includes a normal weekend, which needs no bars.
        drive, bootstrap, opener = self.retained_bootstrap({'AAPL':days}, end='2026-10-26')
        calls = opener.calls
        coverage = self.r.bootstrap_coverage(drive, self.control, bootstrap, {'AAPL'})
        self.assertEqual(coverage, {'AAPL':'2026-10-23'})
        self.assertEqual(self.r.missing_windows({'AAPL'}, coverage, '2026-10-23', set()),
                         ({}, ['AAPL'], {}))
        self.assertEqual(opener.calls, calls)

    def test_retained_unrequested_sibling_gap_does_not_certify_or_block_target(self):
        days = ['2026-10-21', '2026-10-22', '2026-10-23']
        drive, bootstrap, opener = self.retained_bootstrap({'AAPL':days, 'MSFT':[days[-1]]})
        calls = opener.calls
        self.assertEqual(self.r.bootstrap_coverage(drive, self.control, bootstrap, {'AAPL'}),
                         {'AAPL':'2026-10-23'})
        with self.assertRaisesRegex(self.r.Refused, '^MANAGED_BOOTSTRAP_INCOMPLETE_GRID$'):
            self.r.bootstrap_coverage(drive, self.control, bootstrap, {'MSFT'})
        self.assertEqual(opener.calls, calls)

    def test_synthetic_watch_increment_and_durable_resume_reuses_without_provider(self):
        drive,meter,opener = self.memory_capture()
        policy = dict(active_tickers=['AAPL'],watch_tickers=['MSFT'])
        history = [dict(id=1,head_sha='2'*40)]
        ctx = dict(run_id=1,head='2'*40)
        bootstrap = dict(groups=[],asset_identity_refs=self.fixture_bindings)
        # Inject only already-verified prior cutoffs; the original capture,
        # raw/split verifier, metered provider and journal paths are real code.
        with patch.object(self.r,'bootstrap_coverage',return_value={'AAPL':'2026-10-22','MSFT':'2026-10-22'}), \
             patch.object(self.r.capture.time,'sleep',return_value=None):
            result = self.r.execute(self.control,'a'*64,policy,bootstrap,history,drive,meter,ctx,
                                   'fixture-api-key','fixture-api-secret',lambda:self.now)
        self.assertEqual((result['valid_updated'],result['held'],result['rows']), (2,0,4))
        self.assertEqual(meter.used['provider_gets'],4)  # 2 asset + raw/split group
        self.assertEqual(opener.calls,4)
        meter.finish('COMPLETE')
        value = json.loads(meter.journal.read_text(encoding='utf-8'))
        self.r.verify_final_meter(value,history[0],result['checkpoint_sha256'],'a'*64,self.control['per_run_allowance'])
        calls = opener.calls
        history.append(dict(id=2,head_sha='2'*40))
        ctx['run_id'] = 2
        with patch.object(self.r,'bootstrap_coverage',return_value={}):
            second = self.r.execute(self.control,'a'*64,policy,bootstrap,history,drive,meter,ctx,
                'fixture-api-key','fixture-api-secret',lambda:self.now,lambda run,h:None)
        self.assertEqual((second['valid_updated'],second['reused']), (0,2))
        self.assertEqual(opener.calls,calls)
        self.assertEqual(len(self.r.journal_rows(drive,self.control)),4)

    def test_failed_provider_preserves_reservation_and_blocks_next_run(self):
        drive,meter,_ = self.memory_capture(fail=True)
        history = [dict(id=1,head_sha='2'*40)]
        with patch.object(self.r,'bootstrap_coverage',return_value={'AAPL':'2026-10-22'}):
            with self.assertRaisesRegex(self.r.Refused,'NETWORK'):
                self.r.execute(self.control,'a'*64,dict(active_tickers=['AAPL'],watch_tickers=[]),
                    dict(groups=[],asset_identity_refs=self.fixture_bindings),history,drive,meter,dict(run_id=1,head='2'*40),
                    'fixture-api-key','fixture-api-secret',lambda:self.now)
        self.assertEqual(meter.used['provider_gets'],1)
        rows = self.r.journal_rows(drive,self.control)
        with self.assertRaisesRegex(self.r.Refused,'PRIOR_FAILURE_REQUIRES_RECONCILIATION'):
            self.r.restore_journal(rows,history+[dict(id=2)],'a'*64,lambda *a:None)

    def test_unconfirmed_reservation_prevents_even_first_provider_call(self):
        drive,meter,opener = self.memory_capture()
        with patch.object(self.r.capture,'persist_object',side_effect=self.r.Refused('FIXTURE_SAVE_FAILED')):
            with self.assertRaisesRegex(self.r.Refused,'FIXTURE_SAVE_FAILED'):
                self.r.execute(self.control,'a'*64,dict(active_tickers=['AAPL'],watch_tickers=[]),
                    dict(groups=[]),[dict(id=1,head_sha='2'*40)],drive,meter,
                    dict(run_id=1,head='2'*40),'fixture-api-key','fixture-api-secret',lambda:self.now)
        self.assertEqual((opener.calls,meter.used['provider_gets']), (0,0))

    def test_missing_stable_asset_proof_never_issues_provider_request(self):
        drive,meter,opener = self.memory_capture()
        with patch.object(self.r,'bootstrap_coverage',return_value={'AAPL':'2026-10-22'}):
            values = self.r.collect_groups(drive,meter,self.control,dict(groups=[]),{'AAPL'},
                {},{},'2026-10-23','fixture-api-key','fixture-api-secret',lambda:self.now)
        self.assertEqual(values[1],{'AAPL':'MISSING_STABLE_PROVIDER_IDENTITY_PROOF'})
        self.assertEqual(opener.calls,0)

    def test_changed_asset_id_is_held_without_bar_download(self):
        drive,meter,opener = self.memory_capture()
        raw = self.r.encoded(dict(symbol='AAPL',id='00000000-0000-0000-0000-000000000099',
                exchange='NASDAQ',status='active',**{'class':'us_equity'}))
        ref = drive.write(self.control['evidence_folder_id'],raw,'.json')
        with patch.object(self.r,'bootstrap_coverage',return_value={'AAPL':'2026-10-22'}):
            values = self.r.collect_groups(drive,meter,self.control,dict(groups=[],asset_identity_refs={'AAPL':ref}),
                {'AAPL'},{},{},'2026-10-23','fixture-api-key','fixture-api-secret',lambda:self.now)
        self.assertEqual(values[1],{'AAPL':'PROVIDER_SECURITY_ID_CHANGED'})
        self.assertEqual(opener.calls,1)  # asset reference only, no bars

    def test_current_bootstrap_cutoff_is_persisted_and_unvisited_tail_advances(self):
        drive,meter,opener = self.memory_capture()
        self.control['max_symbols_per_run'] = 1
        bootstrap = dict(groups=[],asset_identity_refs=self.fixture_bindings)
        known = dict(AAPL='2026-10-23',MSFT='2026-10-22')
        with patch.object(self.r,'bootstrap_coverage',side_effect=lambda d,c,b,n:{t:known[t] for t in n}), \
             patch.object(self.r.capture.time,'sleep',return_value=None):
            first = self.r.collect_groups(drive,meter,self.control,bootstrap,{'AAPL','MSFT'},
                {},{},'2026-10-23','fixture-api-key','fixture-api-secret',lambda:self.now)
            self.assertEqual(first[0],{'AAPL':'2026-10-23'})
            self.assertEqual(first[2],['AAPL'])
            self.assertEqual(opener.calls,0)
            second = self.r.collect_groups(drive,meter,self.control,bootstrap,{'AAPL','MSFT'},
                first[0],{},'2026-10-23','fixture-api-key','fixture-api-secret',lambda:self.now)
        self.assertEqual(second[0],{'MSFT':'2026-10-23'})
        self.assertEqual(opener.calls,3)


    def test_managed_only_dispatch_isolates_legacy_validation_and_keeps_schedule(self):
        import yaml
        value = yaml.safe_load((ROOT/'.github/workflows/free_data_daily_update.yml').read_text(encoding='utf-8'))
        self.assertEqual(value['jobs']['daily_update']['if'],
            "${{ github.event_name != 'workflow_dispatch' || !inputs.managed_refresh }}")
        trigger = value.get('on',value.get(True))
        self.assertEqual(trigger['schedule'],[dict(cron='30 23 * * 1-5')])
        self.assertFalse(trigger['workflow_dispatch']['inputs']['managed_refresh']['default'])
        self.assertIn('inputs.managed_refresh',value['jobs']['managed_a1_refresh']['if'])
        self.assertEqual(value['jobs']['managed_a1_refresh']['concurrency'],
                         dict(group='a1-private-research-single-writer',**{'cancel-in-progress':False}))

    def test_execution_subset_is_canonical_bounded_and_owner_hash_bound(self):
        original = copy.deepcopy(self.control)
        whole_hash = self.validate()
        self.control.update(max_symbols_per_run=1, execution_tickers=['MSFT'])
        narrow_hash = self.validate()
        self.assertNotEqual(narrow_hash, whole_hash)
        self.assertEqual(self.r.execution_scope(self.control), {'MSFT'})
        grant = self.grant()
        self.control['execution_tickers'] = ['AAPL']
        with self.assertRaisesRegex(self.r.Refused, 'MANAGED_OWNER_SCOPE'):
            self.r.owner_grant(self.control, self.validate(), lambda _:grant, self.now)
        for value,limit in ((None,1), ([],1), ('MSFT',1), (['MSFT','MSFT'],2),
                            (['MSFT','AAPL'],2), (['AAPL','MSFT'],1), (['UNKNOWN'],1), ([False],1)):
            with self.subTest(value=value):
                self.control = copy.deepcopy(original)
                self.control.update(max_symbols_per_run=limit, execution_tickers=value)
                with self.assertRaises((self.r.Refused, ValueError)):
                    self.validate()
        self.control = original
        self.assertIsNone(self.r.execution_scope(self.control))
        self.assertEqual(self.validate(), whole_hash)

    def test_execution_subset_refuses_untracked_or_broadened_policy_before_io(self):
        drive,meter,opener = self.memory_capture()
        self.control.update(max_symbols_per_run=1, execution_tickers=['MSFT'])
        history,ctx = [dict(id=1,head_sha='2'*40)],dict(run_id=1,head='2'*40)
        with patch.object(self.r,'journal_rows',side_effect=AssertionError('journal read')):
            with self.assertRaisesRegex(self.r.Refused,'^MANAGED_EXECUTION_SCOPE$'):
                self.r.execute(self.control,'a'*64,dict(active_tickers=['AAPL'],watch_tickers=[]),
                    dict(groups=[]),history,drive,meter,ctx,'fixture-key','fixture-secret',lambda:self.now)
            self.control['authorized_tickers'] = ['MSFT']
            with self.assertRaisesRegex(self.r.Refused,'^MANAGED_POLICY_SCOPE_CHANGED$'):
                self.r.execute(self.control,'a'*64,dict(active_tickers=['AAPL'],watch_tickers=['MSFT']),
                    dict(groups=[]),history,drive,meter,ctx,'fixture-key','fixture-secret',lambda:self.now)
        self.assertEqual(opener.calls,0)

    def test_execution_subset_real_capture_skips_alphabetical_sibling_and_resumes(self):
        from urllib.parse import parse_qs, urlsplit
        drive,meter,opener = self.memory_capture()
        original_open = opener.open
        def old_response(request, **kw):
            reply = original_open(request, **kw)
            value = self.r.decode(reply.body)
            for bars in value.get('bars',{}).values():
                bars[0]['t'] = '2026-10-22T04:00:00Z'
            reply.body = self.r.encoded(value)
            return reply
        opener.open = old_response
        meter.asset_symbols = ('AAPL','MSFT')
        with patch.object(self.r.capture.time,'sleep',return_value=None):
            originals,_,_,_ = self.r.capture.capture_one_group(drive,
                self.control['private_data_folder_id'],['AAPL','MSFT'],'2026-10-22','2026-10-23',
                'fixture-api-key','fixture-api-secret','a'*64,'2'*40,get=meter.perform)
        old_bytes = {r['file_id']:drive.objects[r['file_id']] for r in originals}
        requested = []
        def next_response(request, **kw):
            requested.append(request.full_url)
            return original_open(request, **kw)
        opener.open = next_response
        self.control.update(max_symbols_per_run=1,execution_tickers=['MSFT'])
        control_sha = self.validate()
        meter.identity['managed_control_sha256'] = control_sha
        bootstrap = dict(groups=[dict(provider='alpaca_sip',symbols=['AAPL','MSFT'],
            receipt=originals[-1])],asset_identity_refs=self.fixture_bindings)
        policy = dict(active_tickers=['AAPL'],watch_tickers=['MSFT'])
        before_policy = copy.deepcopy(policy)
        history,ctx = [dict(id=1,head_sha='2'*40)],dict(run_id=1,head='2'*40)
        calls = opener.calls
        with patch.object(self.r.capture.time,'sleep',return_value=None):
            result = self.r.execute(self.control,control_sha,policy,bootstrap,history,
                drive,meter,ctx,'fixture-api-key','fixture-api-secret',lambda:self.now)
        self.assertEqual((result['valid_updated'],result['held'],result['rows']), (1,0,2))
        self.assertEqual(opener.calls-calls,3)  # selected asset + raw/split; no AAPL I/O
        self.assertEqual(len(requested),3)
        for url in requested:
            parsed = urlsplit(url)
            if '/assets/' in parsed.path:
                self.assertTrue(parsed.path.endswith('/MSFT'))
            else:
                self.assertEqual(parse_qs(parsed.query)['symbols'],['MSFT'])
                self.assertEqual(parse_qs(parsed.query)['start'],['2026-10-23T00:00:00Z'])
                self.assertEqual(parse_qs(parsed.query)['end'],['2026-10-23T23:59:59Z'])
        self.assertEqual(policy,before_policy)
        self.assertEqual({fid:drive.objects[fid] for fid in old_bytes},old_bytes)
        terminal = next(r for _,r in self.r.journal_rows(drive,self.control) if r['state']=='COMPLETE')
        self.assertEqual(terminal['coverage_updates'],{'MSFT':'2026-10-23'})
        meter.finish('COMPLETE')
        value = json.loads(meter.journal.read_text(encoding='utf-8'))
        self.r.verify_final_meter(value,history[0],result['checkpoint_sha256'],control_sha,
                                  self.control['per_run_allowance'])
        calls = opener.calls
        history.append(dict(id=2,head_sha='2'*40)); ctx['run_id'] = 2
        second = self.r.execute(self.control,control_sha,policy,bootstrap,history,drive,meter,ctx,
            'fixture-api-key','fixture-api-secret',lambda:self.now,lambda *a:None)
        self.assertEqual((second['valid_updated'],second['reused']), (0,1))
        self.assertEqual(opener.calls,calls)
        self.control['execution_tickers'] = ['AAPL']
        with self.assertRaisesRegex(self.r.Refused,'MANAGED_STATE_CHAIN'):
            self.r.execute(self.control,self.validate(),policy,bootstrap,history,drive,meter,ctx,
                'fixture-api-key','fixture-api-secret',lambda:self.now,lambda *a:None)
        self.assertEqual(opener.calls,calls)
        self.assertEqual(len(self.r.journal_rows(drive,self.control)),4)

    def test_execution_subset_refuses_foreign_restored_cutoffs_or_holds_before_reserve(self):
        drive,meter,opener = self.memory_capture()
        self.control.update(max_symbols_per_run=1, execution_tickers=['MSFT'])
        history = [dict(id=1,head_sha='2'*40),dict(id=2,head_sha='2'*40)]
        base = dict(slot=1,run_id=1,source_sha='2'*40,control_sha256='a'*64)
        for field in ('coverage_updates','held'):
            with self.subTest(field=field):
                done = dict(base,state='COMPLETE',parent_sha256='b'*64,coverage_updates={},held={})
                done[field] = {'AAPL':'2026-10-22' if field=='coverage_updates' else 'OLD_HOLD'}
                rows = [('b'*64,dict(base,state='RESERVED',parent_sha256=None)),('c'*64,done)]
                with patch.object(self.r,'journal_rows',return_value=rows), \
                     patch.object(self.r.capture,'persist_object',side_effect=AssertionError('reservation')):
                    with self.assertRaisesRegex(self.r.Refused,'^MANAGED_EXECUTION_STATE_SCOPE$'):
                        self.r.execute(self.control,'a'*64,dict(active_tickers=['AAPL'],watch_tickers=['MSFT']),
                            dict(groups=[]),history,drive,meter,dict(run_id=2,head='2'*40),
                            'fixture-key','fixture-secret',lambda:self.now,lambda *a:None)
        self.assertEqual(opener.calls,0)


def main():
    # Keep the existing registered caller and all original contract cases.
    # Stage2 remains supplied-byte proposal validation, never A0 dispatch.
    from a2_a1_discovery_gate_v1_smoke import DiscoveryGateTests
    from a2_a1_ohlcv_handoff_v1_smoke import OHLCVHandoffTests, BoardOHLCVTests
    from a2_a1_readiness_smoke import ReadinessTests, Post669CompatibilityTests
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ControlPlaneTests)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ManagedOHLCVTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ManagedExecutionTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(DiscoveryGateTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(OHLCVHandoffTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(BoardOHLCVTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ReadinessTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(Post669CompatibilityTests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__': raise SystemExit(main())
