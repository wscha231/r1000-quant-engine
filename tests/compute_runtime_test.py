from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research_only.mission_v3 import compute_runtime as c
from research_only.mission_v3 import compute_m0 as m
from research_only.mission_v3 import mission_metrics as old


def echo(inputs, params):
    if params.get('fail'):
        raise ValueError('private payload must not leak')
    return c.canonical({'hashes': {k: c.sha(v) for k,v in sorted(inputs.items())}, 'params':params})


def wrong_output(inputs, params):
    return 'not bytes'


def context():
    return {'decision_cutoff':'2026-09-16T20:00:00Z', 'universe_sha256':c.sha(b'cohort')}


def tasks():
    return [c.Task('a','echo',{'x':b'alpha'}, {}, {}, context()),
            c.Task('b','echo',{'x':b'beta'}, {}, {}, context()),
            c.Task('report','echo',{}, {'title':'report'}, {'a':'a','b':'b'}, context())]


def m0_fixture(count=4):
    plan={'schema_version':m.PLAN_SCHEMA, 'universe_ids':['SYNTH:ABC', 'SYNTH:XYZ'],
          'decision_cutoff':'2026-09-16T20:00:00Z', 'report_title':'synthetic', 'entries':[]}
    blobs={}
    for i in range(count):
        b={'contract':dict(old.REFERENCE), 'sessions':[old.REFERENCE['start'],old.REFERENCE['end']], 'portfolios':{}}
        for sleeve in ('main','concentrated'):
            meta={'sleeve':sleeve,'run_id':'synthetic', 'source_commit':'a'*40,
                  'currency':'USD','sampling':'DAILY_EOD_LEDGER','nav_basis':'NET_WITHOUT_EXTERNAL_FLOWS'}
            for key in old.META_KEYS:
                if key.endswith('sha256'): meta[key]='b'*64
            b['portfolios'][sleeve]={'metadata':meta,'nav_rows':[
                {'date':old.REFERENCE['start'],'nav':'100000','external_flow':0},
                {'date':old.REFERENCE['end'],'nav':str(100000+i*1000),'external_flow':0}]}
        identity=f'case{i}'; blobs[identity]=c.canonical(b)
        plan['entries'].append({'id':identity,'path':f'input/case{i}.json','sha256':c.sha(blobs[identity])})
    return plan,blobs


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.registry={'echo':c.Operator('echo',echo)}

    def execute(self, ts=None, name='cache', **kw):
        return c.run(ts if ts is not None else tasks(), self.registry,self.root/name,**kw)

    def test_single_ready_task_stays_serial_without_process_startup(self):
        ts=[tasks()[0]]
        with patch.object(c, 'ProcessPoolExecutor', side_effect=AssertionError('must not start')):
            result=self.execute(ts,workers=4)
        self.assertEqual(result['task_receipts']['a']['worker_pid'],os.getpid())

    def test_optimizer_mode_is_in_environment_identity(self):
        self.assertEqual(c.runtime_identity()['optimize'],str(sys.flags.optimize))

    def test_input_dependency_alias_collision_rejected(self):
        ts=tasks(); ts[-1].inputs['a']=b'collision'
        with self.assertRaises(c.ComputeError): self.execute(ts)

    def test_equivalent_utc_cutoff_reuses_cache(self):
        self.execute(); ts=tasks()
        for t in ts: t.context['decision_cutoff']='2026-09-17T05:00:00+09:00'
        self.assertEqual(self.execute(ts)['stats']['computed'],0)

    def test_cached_spec_tampering_rejected(self):
        self.execute()
        con=sqlite3.connect(self.root/'cache/compute.sqlite3')
        with con: con.execute('UPDATE results SET spec=?',(b'bad',))
        con.close()
        with self.assertRaises(c.ComputeError): self.execute()

    def test_cold_then_warm_exact_cache(self):
        first=self.execute(); second=self.execute()
        self.assertEqual(first['stats']['computed'],3)
        self.assertEqual(second['stats']['computed'],0)
        self.assertEqual(second['stats']['cache_hits'],3)
        self.assertEqual(first['semantic_output_hash'],second['semantic_output_hash'])

    def test_serial_parallel_2_4_exact_equality(self):
        a=self.execute(name='s',workers=1)
        for n in (2,4):
            b=self.execute(name=f'p{n}',workers=n)
            self.assertEqual(a['outputs'],b['outputs'])
            pids={b['task_receipts'][i].get('worker_pid') for i in ('a','b')}
            self.assertTrue(pids); self.assertNotIn(os.getpid(),pids)

    def test_incremental_one_input_recomputes_only_descendants(self):
        self.execute(); ts=tasks()
        ts[0].inputs['x']=b'changed'
        result=self.execute(ts)
        self.assertEqual(result['stats']['computed'],2)
        self.assertEqual(result['task_receipts']['b']['status'],'CACHE_HIT')

    def test_report_only_change_reuses_upstream(self):
        self.execute(); ts=tasks(); ts[-1].parameters['title']='new'
        result=self.execute(ts)
        self.assertEqual(result['stats']['computed'],1)
        self.assertEqual(result['stats']['cache_hits'],2)

    def test_context_change_invalidates_all(self):
        self.execute(); ts=tasks()
        for t in ts: t.context['decision_cutoff']='2026-09-17T20:00:00Z'
        self.assertEqual(self.execute(ts)['stats']['computed'],3)

    def test_universe_change_invalidates_all(self):
        self.execute(); ts=tasks()
        for t in ts: t.context['universe_sha256']=c.sha(b'new universe')
        self.assertEqual(self.execute(ts)['stats']['computed'],3)

    def test_explicit_code_dependency_changes_cache_key(self):
        f=self.root/'dependency.txt'; f.write_text('v1')
        self.registry['echo']=c.Operator('echo',echo,(('fixture',str(f)),))
        self.execute(); f.write_text('v2')
        self.assertEqual(self.execute()['stats']['computed'],3)

    def test_unrelated_file_does_not_invalidate_cache(self):
        self.execute(); (self.root/'README.md').write_text('irrelevant text')
        self.assertEqual(self.execute()['stats']['computed'],0)

    def test_failed_task_not_cached_or_replaced_by_old_success(self):
        self.execute(); ts=tasks(); ts[0].parameters['fail']=True
        result=self.execute(ts)
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertIsNone(result['semantic_output_hash'])
        self.assertEqual(result['task_receipts']['a']['status'],'FAILED')
        self.assertEqual(result['task_receipts']['report']['status'],'BLOCKED_DEPENDENCY')
        self.assertNotIn('private payload',json.dumps(result['task_receipts']))
        again=self.execute(ts)
        self.assertEqual(again['task_receipts']['a']['status'],'FAILED')
        self.assertEqual(again['stats']['computed'],1)

    def test_resume_matches_uninterrupted(self):
        stopped=self.execute(stop_after_tasks=1)
        self.assertEqual(stopped['status'],'INCOMPLETE')
        resumed=self.execute(workers=2)
        fresh=self.execute(name='fresh',workers=1)
        self.assertEqual(resumed['outputs'],fresh['outputs'])
        self.assertEqual(resumed['stats']['computed'],2)
        self.assertEqual(resumed['stats']['cache_hits'],1)

    def test_rollback_uncommitted_sqlite_entry_not_a_success(self):
        with c.ExactCache(self.root/'cache') as db:
            spec=b'abc'; value=b'good'
            db.db.execute('BEGIN')
            db.db.execute('INSERT INTO results VALUES(?,?,?,?)',(c.sha(spec),spec,value,c.sha(value)))
        with c.ExactCache(self.root/'cache') as db:
            self.assertIsNone(db.get(spec))

    def test_corrupt_cached_output_rejected(self):
        self.execute()
        con=sqlite3.connect(self.root/'cache/compute.sqlite3')
        with con: con.execute("UPDATE results SET output=?",(b'corrupt',))
        con.close()
        with self.assertRaises(c.ComputeError): self.execute()

    def test_cache_conflict_never_overwrites(self):
        with c.ExactCache(self.root/'cache') as db:
            db.put(b'spec',b'old')
            with self.assertRaises(c.ComputeError): db.put(b'spec',b'new')
            self.assertEqual(db.get(b'spec'),b'old')

    def test_same_pure_task_aliases_share_computation(self):
        ts=tasks(); ts[1].inputs['x']=b'alpha'
        r=self.execute(ts,workers=2)
        self.assertEqual(r['stats']['computed'],2)
        self.assertEqual(r['stats']['deduplicated'],1)
        self.assertEqual(r['outputs']['a'],r['outputs']['b'])

    def test_duplicate_ids_missing_dependencies_cycles_rejected_before_cache(self):
        for ts in ([tasks()[0],tasks()[0]], [c.Task('a','echo',{}, {}, {'x':'missing'},context())],
                   [c.Task('a','echo',{}, {}, {'x':'b'},context()),c.Task('b','echo',{}, {}, {'x':'a'},context())]):
            with self.subTest(ts=ts), self.assertRaises(c.ComputeError): self.execute(ts)
        self.assertFalse((self.root/'cache').exists())

    def test_unknown_operation_and_nonpure_closure_not_allowed(self):
        ts=tasks(); ts[0]=c.Task('a','shell',{}, {}, {},context())
        with self.assertRaises(c.ComputeError): self.execute(ts)
        with self.assertRaises(c.ComputeError): c.Operator('bad',lambda x,p:b'').identity()

    def test_warm_cache_obeys_same_cumulative_output_budget(self):
        leaves = tasks()[:2]
        full = self.execute(leaves)
        sizes = [len(value) for value in full['outputs'].values()]
        limit = max(sizes) + 1
        self.assertLess(limit, sum(sizes))
        with patch.object(c, 'MAX_PLAN_BYTES', limit):
            with self.assertRaisesRegex(c.ComputeError, 'PLAN_OUTPUT_SIZE'):
                self.execute(leaves)
            with self.assertRaisesRegex(c.ComputeError, 'PLAN_OUTPUT_SIZE'):
                self.execute(leaves, name='fresh-limited')

    def test_worker_and_input_resource_limits(self):
        for n in (0,5,True):
            with self.subTest(n=n), self.assertRaises(c.ComputeError): self.execute(workers=n)
        with patch.object(c,'MAX_PLAN_BYTES',1), self.assertRaises(c.ComputeError): self.execute()

    def test_invalid_params_or_cutoff_or_context(self):
        for field,value in [('decision_cutoff','2026-09-16'),('universe_sha256','fake')]:
            ts=tasks(); ts[0].context[field]=value
            with self.subTest(field=field), self.assertRaises(c.ComputeError): self.execute(ts)
        ts=tasks(); ts[0].parameters['nan']=float('nan')
        with self.assertRaises(c.ComputeError): self.execute(ts)

    def test_source_dependency_aliases_must_be_unique(self):
        with self.assertRaises(c.ComputeError):
            c.Operator('echo',echo,(('operator',str(Path(__file__))),)).identity()

    def test_bad_worker_return_fails_closed(self):
        self.registry['echo']=c.Operator('echo',wrong_output)
        r=self.execute()
        self.assertEqual(r['status'],'INCOMPLETE')
        self.assertEqual(r['task_receipts']['report']['status'],'BLOCKED_DEPENDENCY')

    def test_inputs_not_mutated(self):
        ts=tasks(); original=copy.deepcopy(ts)
        self.execute(ts)
        self.assertEqual(ts,original)

    def test_task_plan_order_does_not_change_result(self):
        a=self.execute(name='a'); b=self.execute(list(reversed(tasks())),name='b',workers=2)
        self.assertEqual(a['outputs'],b['outputs'])

    def test_sharding_1118_ids_has_no_drop_or_reorder_dependency(self):
        ids=[f'SYNTH:{i:04d}' for i in range(1118)]
        groups=c.shard_ids(ids,8)
        self.assertEqual(c.join_shards(ids,groups),sorted(ids))
        self.assertEqual(groups,c.shard_ids(list(reversed(ids)),8))
        self.assertEqual(sum(map(len,groups)),1118)

    def test_incomplete_duplicate_and_extra_shard_results_rejected(self):
        ids=['a','b','c']; groups=c.shard_ids(ids,2)
        for g in ([['a','b']], [['a','a','b','c']], [['a','b','c','d']]):
            with self.subTest(g=g),self.assertRaises(c.ComputeError): c.join_shards(ids,g)
        with self.assertRaises(c.ComputeError): c.shard_ids(['a','a'],2)

    def test_symlink_cache_and_input_rejected(self):
        target=self.root/'target'; target.mkdir()
        link=self.root/'link'
        try: link.symlink_to(target,target_is_directory=True)
        except OSError: self.skipTest('symlinks not supported on this host')
        with self.assertRaises(c.ComputeError): c.ExactCache(link)
        f=target/'input'; f.write_bytes(b'abc')
        with self.assertRaises(c.ComputeError): c.safe_file(link/'input')


class M0IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.plan,self.blobs=m0_fixture()

    def execute(self,name='cache',workers=1):
        return c.run(m.build_tasks(self.plan,self.blobs),m.operators(),self.root/name,workers=workers)

    def test_actual_m0_results_equal_direct_function(self):
        r=self.execute(workers=2)
        self.assertEqual(r['status'],'COMPLETE')
        for identity,blob in self.blobs.items():
            self.assertEqual(r['outputs']['m0:'+identity],c.canonical(old.assess_pair(old.strict_json(blob.decode()))))
        self.assertEqual(r['mission_status'],'NOT_PROVEN')

    def test_warm_and_one_changed_bundle_calls(self):
        first=self.execute(); warm=self.execute()
        self.assertEqual(warm['stats']['computed'],0)
        b=json.loads(self.blobs['case0']); b['portfolios']['main']['nav_rows'][1]['nav']='99999'
        self.blobs['case0']=c.canonical(b)
        self.plan['entries'][0]['sha256']=c.sha(self.blobs['case0'])
        changed=self.execute()
        self.assertEqual(changed['stats']['computed'],2)
        self.assertEqual(changed['stats']['cache_hits'],3)

    def test_direct_parallel_and_cached_hashes_equal(self):
        a=self.execute(name='a')
        b=self.execute(name='b',workers=4)
        self.assertEqual(a['semantic_output_hash'],b['semantic_output_hash'])
        self.assertEqual(b['semantic_output_hash'],self.execute(name='b',workers=2)['semantic_output_hash'])

    def test_invalid_m0_input_blocks_report_not_other_valid_tasks(self):
        b=json.loads(self.blobs['case0']); b['contract']['main_max_mdd_loss']='0.25'
        self.blobs['case0']=c.canonical(b); self.plan['entries'][0]['sha256']=c.sha(self.blobs['case0'])
        r=self.execute()
        self.assertEqual(r['task_receipts']['report']['status'],'BLOCKED_DEPENDENCY')
        self.assertEqual(r['task_receipts']['m0:case1']['status'],'COMPUTED')

    def test_bundle_hash_and_denominator_enforced(self):
        bad=dict(self.blobs); bad['case0']+=b' '
        with self.assertRaises(c.ComputeError): m.build_tasks(self.plan,bad)
        with self.assertRaises(c.ComputeError): m.build_tasks(self.plan,dict(list(self.blobs.items())[:-1]))

    def test_report_title_only_recomputes_one(self):
        self.execute(); self.plan['report_title']='new'
        r=self.execute()
        self.assertEqual(r['stats']['computed'],1)
        self.assertEqual(r['stats']['cache_hits'],4)

    def test_plan_readback_pin_traversal_and_cli(self):
        for row in self.plan['entries']:
            f=self.root/row['path']; f.parent.mkdir(exist_ok=True); f.write_bytes(self.blobs[row['id']])
        p=self.root/'plan.json'; p.write_bytes(c.canonical(self.plan)); pin=c.sha(p.read_bytes())
        plan,blobs=m.load_plan(p,pin)
        self.assertEqual(plan,self.plan); self.assertEqual(blobs,self.blobs)
        with self.assertRaises(c.ComputeError): m.load_plan(p,'0'*64)
        command=[sys.executable,'-m','research_only.mission_v3.compute_m0',str(p),'--plan-sha256',pin,
                 '--cache-dir',str(self.root/'cache'),'--run-dir',str(self.root/'run'),'--workers','2']
        done=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(done.returncode,0,done.stderr+done.stdout)
        self.assertTrue((self.root/'run/manifest.json').exists())
        repeat=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=30)
        self.assertEqual(repeat.returncode,2)
        self.plan['entries'][0]['path']='../secret.json'; p.write_bytes(c.canonical(self.plan))
        with self.assertRaises(c.ComputeError): m.load_plan(p,c.sha(p.read_bytes()))


if __name__=='__main__': unittest.main()
