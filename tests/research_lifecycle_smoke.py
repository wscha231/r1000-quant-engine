#!/usr/bin/env python3
"""Causal regressions for durable inputs, two clocks and reevaluation scope."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.research_lifecycle import Store, digest, read_json, reevaluation_plan

NOW = '2026-09-10T08:00:00Z'


def record(value=100, available='2019-06-03T20:00:00Z', effective='2019-06-03T20:00:00Z', **kw):
    return dict(source='test_source', kind='price', entity='US:AAA', field='raw_close',
                effective_at=effective, available_at=available, value=value,
                evidence='retrospective_price', **kw)


def batch(records=None, retrieved=NOW):
    return dict(dataset='fresh_research', data_kind='SYNTHETIC', retrieved_at=retrieved,
                source_uri='https://example.com/archive', raw_sha256='a'*64,
                records=[record()] if records is None else records)


def request(snapshot, **kw):
    result = dict(dataset_snapshot=snapshot, strategy_hash='1'*64, code_sha='2'*40,
        window_start='2018-09-10T00:00:00Z', window_end='2026-09-09T23:59:59Z',
        evidence_mode='ARCHIVED_RECONSTRUCTION', research_history_id='run287_complete_history',
        environment=dict(initial_cash_usd=100000, objective='after_cost_usd_cagr', max_drawdown_abs=.25,
                         costs={'US':25,'KR':25}, universe_policy='historical_exchange_membership_v1',
                         benchmark_policy='declared_total_return_v1', calendar_policy='exchange_sessions_v1'))
    result.update(kw)
    return result


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = NOW
        self.store = Store(self.root, clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def ingest(self, value=None, expected=None):
        return self.store.ingest(batch() if value is None else value, expected_head=expected)

    def test_new_baseline_does_not_require_old_archive_or_reset_objective(self):
        out = self.ingest()
        plan = reevaluation_plan(self.store, request(out['snapshot']))
        self.assertFalse(plan['legacy_artifacts_required'])
        self.assertEqual(plan['initial_cash_usd'],100000)
        self.assertEqual(plan['objective'],'after_cost_usd_cagr')
        self.assertFalse(plan['historical_replay_ready'])
        self.assertFalse(plan['unseen_holdout_claimed'])

    def test_repeat_is_noop_but_keeps_collection_receipt(self):
        first = self.ingest()
        self.now = '2026-09-11T08:00:00Z'
        again = self.ingest(batch(retrieved=self.now), expected=first['snapshot'])
        self.assertEqual(first['snapshot'],again['snapshot'])
        self.assertNotEqual(first['receipt'],again['receipt'])
        self.assertEqual(again['added_records'],0)

    def test_only_changed_month_is_written_and_old_snapshot_remains(self):
        initial = self.ingest(batch([record(), record(101, '2019-07-01T20:00:00Z','2019-07-01T20:00:00Z')]))
        updated = self.ingest(batch([record(102,'2019-07-02T20:00:00Z','2019-07-02T20:00:00Z')]),expected=initial['snapshot'])
        self.assertEqual(updated['changed_partitions'],1)
        self.assertEqual(len(list(self.store.records(initial['snapshot']))),2)
        self.assertEqual(len(list(self.store.records(updated['snapshot']))),3)
        self.assertEqual(Store(self.root).head('fresh_research'),updated['snapshot'])

    def test_stale_writer_cannot_replace_newer_head(self):
        first = self.ingest()
        with self.assertRaisesRegex(ValueError,'stale_dataset_head'):
            self.ingest(batch([record(101,'2019-07-01T20:00:00Z','2019-07-01T20:00:00Z')]))
        self.assertEqual(self.store.head('fresh_research'), first['snapshot'])

    def test_conflict_does_not_partially_publish_valid_rows(self):
        first=self.ingest()
        with self.assertRaisesRegex(ValueError,'ambiguous_same_time_revision'):
            self.ingest(batch([record(110,'2019-07-01T20:00:00Z','2019-07-01T20:00:00Z'),record(999)]),expected=first['snapshot'])
        self.assertEqual(self.store.head('fresh_research'),first['snapshot'])
        self.assertEqual(len(list(self.store.records(first['snapshot']))),1)

    def test_later_revision_cannot_change_earlier_asof(self):
        first=self.ingest()
        second=self.ingest(batch([record(200,'2020-01-01T00:00:00Z')]),expected=first['snapshot'])
        old=self.store.as_of(second['snapshot'],'2019-12-31T23:59:59Z')
        new=self.store.as_of(second['snapshot'],'2020-01-01T00:00:00Z')
        self.assertEqual(old[0]['value'],100)
        self.assertEqual(new[0]['value'],200)

    def test_fractional_second_revisions_use_time_not_string_order(self):
        first=self.ingest(batch([record(100,'2019-06-03T20:00:00Z')]))
        second=self.ingest(batch([record(200,'2019-06-03T20:00:00.100000Z')]),expected=first['snapshot'])
        self.assertEqual(self.store.as_of(second['snapshot'],NOW)[0]['value'],200)

    def test_current_macro_is_never_historical_pit(self):
        row=record(4.1, NOW, '2019-06-03T00:00:00Z')
        row.update(kind='macro', field='rate', evidence='current_only')
        out=self.ingest(batch([row]))
        self.assertEqual(self.store.as_of(out['snapshot'],NOW),[])
        self.assertEqual(len(self.store.as_of(out['snapshot'],NOW,evidence_mode='FORWARD_RECORDED',retrieved_by=NOW)),1)
        row['available_at']='2019-06-03T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'current_snapshot_backdated'):
            self.ingest(batch([row]),expected=out['snapshot'])

    def test_repeated_current_value_preserves_first_seen_but_value_reversal_does_not(self):
        row=record(4.1,NOW,'2019-06-03T00:00:00Z')
        row.update(kind='macro',field='rate',evidence='current_only')
        first=self.ingest(batch([row]))
        self.now='2026-09-11T08:00:00Z'; row['available_at']=self.now
        again=self.ingest(batch([row],retrieved=self.now),expected=first['snapshot'])
        self.assertEqual(first['snapshot'],again['snapshot'])
        row['value']=4.2
        changed=self.ingest(batch([row],retrieved=self.now),expected=again['snapshot'])
        self.now='2026-09-12T08:00:00Z'; row.update(value=4.1,available_at=self.now)
        reverse=self.ingest(batch([row],retrieved=self.now),expected=changed['snapshot'])
        self.assertEqual(len(list(self.store.records(reverse['snapshot']))),3)

    def test_imported_history_is_not_a_past_system_observation(self):
        old_batch=batch(retrieved='2019-06-04T00:00:00Z')
        out=self.ingest(old_batch)
        self.assertEqual(self.store.as_of(out['snapshot'],'2019-06-05T00:00:00Z',
                         evidence_mode='FORWARD_RECORDED',retrieved_by='2019-06-05T00:00:00Z'),[])
        self.assertEqual(len(self.store.as_of(out['snapshot'],'2019-06-05T00:00:00Z')),1)

    def test_bad_batch_or_nonfinite_or_future_retrieval_never_creates_head(self):
        for bad in [batch([]), batch([record(float('nan'))]), batch(retrieved='2099-01-01T00:00:00Z')]:
            with self.assertRaises(ValueError):self.ingest(bad)
        self.assertIsNone(self.store.head('fresh_research'))

    def test_sensitive_source_query_and_mixed_fixture_rejected(self):
        bad=batch();bad['source_uri']='https://example.com/data?token=private'
        with self.assertRaisesRegex(ValueError,'public_source_uri'):self.ingest(bad)
        out=self.ingest();bad=batch();bad['data_kind']='REAL'
        with self.assertRaisesRegex(ValueError,'mixed_real_synthetic'):self.ingest(bad,expected=out['snapshot'])

    def test_corruption_and_path_traversal_rejected(self):
        out=self.ingest()
        path=self.store.objects/(out['snapshot']+'.json')
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'object_corruption'):self.store.snapshot(out['snapshot'])
        with self.assertRaisesRegex(ValueError,'object_id'):self.store.get('../secret')

    def test_duplicate_json_fields_rejected(self):
        p=self.root/'duplicate.json';p.write_text('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError,'duplicate_json_key'):read_json(p)

    def test_planner_detects_historical_revision_and_preserves_portfolio_path(self):
        first=self.ingest()
        second=self.ingest(batch([record(200,'2020-01-01T00:00:00Z')]),expected=first['snapshot'])
        out=reevaluation_plan(self.store,request(second['snapshot']),request(first['snapshot']))
        self.assertEqual(out['affected_from'],'2020-01-01T00:00:00Z')
        self.assertEqual(out['execution'],'FULL_CHRONOLOGICAL_REPLAY')
        self.assertTrue(out['paired_comparison_required'])
        self.assertFalse(out['checkpoint_resume_supported'])

    def test_late_release_does_not_invalidate_prepublication_history(self):
        first=self.ingest()
        second=self.ingest(batch([record(200,'2026-09-10T00:00:00Z')]),expected=first['snapshot'])
        out=reevaluation_plan(self.store,request(second['snapshot']),request(first['snapshot']))
        self.assertEqual(out['status'],'NO_RELEVANT_CHANGE')
        self.assertTrue(out['reuse_requires_verified_result'])

    def test_rule_change_and_window_extension_have_distinct_plans(self):
        first=self.ingest()['snapshot'];old=request(first)
        changed=copy.deepcopy(old);changed['environment']['costs']['US']=5
        out=reevaluation_plan(self.store,changed,old)
        self.assertEqual(out['status'],'FULL_REEVALUATION')
        self.assertEqual(out['affected_from'],old['window_start'])
        self.assertEqual(out['comparison_kind'],'ENVIRONMENT_SENSITIVITY')
        self.assertFalse(out['direct_alpha_comparison_allowed'])
        new=request(first,window_end='2026-09-10T23:59:59Z')
        out=reevaluation_plan(self.store,new,old)
        self.assertEqual(out['reason'],'window_extended')
        self.assertEqual(out['execution'],'FULL_CHRONOLOGICAL_REPLAY')

    def test_trial_history_cannot_be_reset_by_a_new_baseline(self):
        sha=self.ingest()['snapshot'];old=request(sha)
        with self.assertRaisesRegex(ValueError,'research_history_cannot_reset'):
            reevaluation_plan(self.store,request(sha,research_history_id='forget_failures'),old)
        self.store.begin('first',old,now=NOW)
        with self.assertRaisesRegex(ValueError,'research_history_cannot_reset'):
            self.store.begin('fresh_name',request(sha,research_history_id='forget_failures'),now=NOW)

    def test_failed_blocked_and_inflight_attempts_remain_visible(self):
        req=request(self.ingest()['snapshot'])
        self.store.begin('trial1',req,now=NOW)
        self.store.begin('trial2',req,now=NOW)
        self.store.finish('trial1',status='FAILED',result_hash=None,reason='source_gap',now=NOW)
        with self.assertRaisesRegex(ValueError,'already_finished'):
            self.store.finish('trial1',status='COMPLETED',result_hash='a'*64,reason='ok',now=NOW)
        with self.assertRaisesRegex(ValueError,'already_registered'):
            self.store.begin('trial1',req,now=NOW)
        rows=self.store.attempts()
        self.assertEqual(rows[0]['finished']['status'],'FAILED')
        self.assertIsNone(rows[1]['finished'])
        self.assertFalse(rows[0]['finished']['promotion_allowed'])

    def test_backup_reopens_with_identical_head_and_failed_history(self):
        sha=self.ingest()['snapshot']
        self.store.begin('trial1',request(sha),now=NOW)
        self.store.finish('trial1',status='BLOCKED',result_hash=None,reason='source_gap',now=NOW)
        with tempfile.TemporaryDirectory() as parent:
            destination=Path(parent)/'checkpoint'
            out=self.store.backup(destination)
            reopened=Store(destination)
            self.assertEqual(reopened.head('fresh_research'),sha)
            self.assertEqual(list(reopened.records(sha)),list(self.store.records(sha)))
            self.assertEqual(reopened.attempts(),self.store.attempts())
            self.assertFalse(out['remote_persistence_verified'])
            with self.assertRaisesRegex(ValueError,'backup_destination_exists'):
                self.store.backup(destination)

    def test_corrupt_backup_is_not_published(self):
        sha=self.ingest()['snapshot']
        (self.store.objects/(sha+'.json')).write_text('{}')
        with tempfile.TemporaryDirectory() as parent:
            destination=Path(parent)/'checkpoint'
            with self.assertRaisesRegex(ValueError,'object_corruption'):
                self.store.backup(destination)
            self.assertFalse(destination.exists())


if __name__=='__main__':
    unittest.main(verbosity=2)
