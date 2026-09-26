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
sys.path.insert(0, str(ROOT))
from tools import run_agent_board as board


class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime.now(timezone.utc)
        self.contract = board.contracts()
        self.sha, self.config = board.source_identity()
        self.state = dict(schema_version='system-state-v2', as_of=self.at(-5), expires_at=self.at(60),
            repository='wscha231/r1000-quant-engine', master_sha=self.sha, code_sha=self.sha,
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

    def tasks(self):
        return board.build_tasks(self.state, self.root, self.contract, self.now, self.sha, self.config)

    def complete(self, agent='A1'):
        packet = next(t for t in self.tasks() if t['agent'] == agent)
        receipt = dict(agent=agent, task_key=packet['task_key'], status='SUCCEEDED',
                       outputs={role:self.artifact(agent+'_result_'+role) for role in packet['outputs']})
        request=next(r for r in self.state['requests'] if r['agent']==agent)
        causal=list(request['inputs'].values())
        if agent=='A6':
            bundle=board.read_json(self.root/request['inputs']['review_bundle']['path'])
            causal+=list(bundle['artifacts'].values())
            self.set_payload(receipt['outputs']['qa_report'], {'schema_version':'qa-report-v2',
                'review_bundle_sha256':request['inputs']['review_bundle']['sha256'],
                'reviewed_artifacts':bundle['artifacts'],'verdict':'PASS'})
        ready=max(board.timestamp(a['collected_at']) for a in causal).isoformat()
        for output in receipt['outputs'].values():
            output['available_at']=ready
            output['collected_at']=ready
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
        self.assertEqual(self.tasks()[1]['status'],'READY')

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
        self.assertEqual(result['A6']['status'],'SKIP_UNCHANGED')
        self.assertIn('QA_NOT_PASS',result['A7']['reasons'])

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
        self.assertEqual(result['status'],'PROPOSAL_ONLY')
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


def main():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ControlPlaneTests))
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__': raise SystemExit(main())
