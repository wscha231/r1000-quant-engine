#!/usr/bin/env python3
"""Deterministic H1 admission regressions; no vendor/network/economic runs."""
from __future__ import annotations
import copy
import base64
import contextlib
import io
import json
import sys
import tempfile
import itertools
import os
import signal
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import earnings_consensus_h1 as h1
from tools import collect_earnings_estimates_finnhub as c
from tools import build_earnings_estimate_archive_manifest as manifest
from tools.run_free_data_selection_overlay import build_overlay

HARD_EXIT_CODE = 87 if os.name == "nt" else -signal.SIGKILL


def terminate_without_cleanup() -> None:
    if os.name == "nt":
        os._exit(HARD_EXIT_CODE)
    os.kill(os.getpid(), signal.SIGKILL)


def estimate(value=1.0, period="2026-12-31", **overrides):
    return dict(period=period, avg=value, high=1.4, low=0.8, numberAnalysts=5,
                issuer_id="CIK:1", security_id="FIGI:AAA", period_type="ANNUAL",
                accounting_basis="GAAP", currency="USD", share_or_ADR_unit="DILUTED_COMMON_SHARE", **overrides)


def snapshot(time="2026-04-01T18:00:00Z", value=1.0, period="2026-12-31", ticker="AAA", **kwargs):
    args = dict(fetch_date=pd.Timestamp(time[:10]), eps_payload={"data": [estimate(value, period)]},
                revenue_payload={"data": [estimate(100.0, period)]}, earnings_payload=[],
                recommendation_payload=[dict(strongBuy=4,buy=3,sell=1,strongSell=0)],
                observed_at=time, collected_at=time)
    args.update(kwargs)
    return c.parse_snapshot_row(ticker, **args)


def features(rows):
    return c.compute_estimate_revision_features(pd.DataFrame(rows))[0]


def legacy_snapshot():
    # Complete pre-V2 parse_snapshot_row() output on master e97a8509, including
    # its original zero-filled economics and empty optional date strings.
    return dict(ticker='LEG', as_of_date='2026-04-01', available_from='2026-04-01',
                fetch_source='finnhub', eps_estimate_access=True,
                revenue_estimate_access=True, vendor_estimate_access=True,
                has_forward_estimate=0, est_eps_fy1=0.0, est_eps_fy2=0.0,
                est_rev_fy1=0.0, n_analysts=0, est_dispersion=0.0,
                actual_eps_last=0.0, actual_report_date='', earnings_surprise_last=0.0,
                surprise_streak=0, recommendation_period='', recommendation_bull_count=0,
                recommendation_bear_count=0, est_eps_revision_breadth=0.0)


def crash_fixture(root: Path, boundary: str = "") -> int:
    """Run in a fresh interpreter; SIGKILL cannot execute Python rollback/finally."""
    history = root / "history"
    checkpoint, queue = root / "checkpoint.json", root / "queue.csv"
    argv = ["collector", "--tickers", "AAA", "--api-key", "fixture",
            "--fetch-date", "2026-07-01", "--snapshot-dir", str(history),
            "--signals-output", str(root / "signals.parquet"), "--summary", str(root / "summary.json"),
            "--collection-checkpoint", str(checkpoint), "--collection-queue", str(queue),
            "--collection-attempt-id", "crash-run"]
    replace = os.replace

    def kill_at_replace(source, target):
        target = Path(target)
        label = target.name
        if label == c.TRANSACTION_MARKER_NAME:
            label = json.loads(Path(source).read_text())["status"]
        if boundary == "before_pending" and label == "pending":
            terminate_without_cleanup()
        replace(source, target)
        if boundary == label:
            terminate_without_cleanup()

    fresh = snapshot("2026-07-01T18:00:00Z", 2)
    # Native Windows probes test abrupt process death and state admission;
    # POSIX directory durability itself is exercised by the Linux CI run.
    directory_sync = (patch.object(c, "_fsync_directory")
                      if os.name == "nt" else contextlib.nullcontext())
    with directory_sync, patch.object(c, "utc_now", return_value="2026-07-01T18:00:00Z"), \
         patch.object(c, "collect_live_snapshot", return_value=(pd.DataFrame([fresh]), [], ["AAA"], {})), \
         patch.object(c.os, "replace", side_effect=kill_at_replace), \
         patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
        return c.main()


def crash_manifest(root: Path) -> dict:
    from tools.build_earnings_estimate_archive_manifest import build_manifest
    return build_manifest(
        snapshot_dir=str(root / "history"), signals=str(root / "signals.parquet"),
        summary=str(root / "summary.json"), collector_log=str(root / "collector.log"),
        manifest=str(root / "manifest.json"), index=str(root / "index.jsonl"),
        run_id="crash-run", run_attempt="1", head_sha="fixture-head", ref="fixture",
        workflow="fixture", artifact_name="fixture", queue_checkpoint=str(root / "checkpoint.json"),
        queue_csv=str(root / "queue.csv"), queue_summary=str(root / "queue-summary.json"),
        queue_report=str(root / "queue.md"))


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(c, 'utc_now', return_value='2026-07-01T18:00:00Z')
        clock.start()
        self.addCleanup(clock.stop)
        if os.name == "nt":
            directory_sync = patch.object(c, "_fsync_directory")
            directory_sync.start()
            self.addCleanup(directory_sync.stop)

    def test_damaged_middle_vintage_blocks_archive_without_fallback(self):
        april = snapshot('2026-04-01T18:00:00Z', 1)
        may = snapshot('2026-05-01T18:00:00Z', None)
        june = snapshot('2026-06-01T18:00:00Z', 2)
        for damage in ('snapshot_version_id', 'source_payload_sha256', 'source_contract', 'observed_at', 'ticker'):
            bad = {**may, damage: 'corrupt'}
            for rows in itertools.permutations([april, bad, june]):
                result, summary = c.compute_estimate_revision_features(pd.DataFrame(rows))
                self.assertTrue(result.empty, damage)
                self.assertEqual(summary['reason'], 'archive_integrity_failure')
                self.assertEqual(summary['invalid_rows'], 1)
            self.assertTrue(c.latest_signal_by_ticker(pd.DataFrame([april, bad, june]),
                            decision_date='2026-07-01').empty)
        control = features([april, may, june])
        self.assertTrue(pd.isna(control.iloc[-1].est_eps_revision_30d))
        self.assertEqual(features([april, snapshot('2026-05-01T18:00:00Z', 1.5), june]).iloc[-1].est_eps_revision_30d, 1/3)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'estimates_20260501.parquet'
            pd.DataFrame([{**may, 'snapshot_version_id': 'bad'}]).to_parquet(path)
            stored = path.read_bytes()
            result, summary = c.compute_estimate_revision_features(c.load_snapshot_history(Path(temp)))
            self.assertTrue(result.empty)
            self.assertEqual(summary['reason'], 'archive_integrity_failure')
            self.assertEqual(path.read_bytes(), stored)

    def test_h2_positive_legacy_contract_blocks_unknown_and_stripped_v2(self):
        from r1000_config import PHASE18_ESTIMATE_REVISION_COLUMNS
        legacy = {**dict.fromkeys(PHASE18_ESTIMATE_REVISION_COLUMNS, 0.0), **legacy_snapshot(),
                  'ticker': 'AAA', 'has_forward_estimate': 1, 'estimate_revision_confirmed': 1,
                  'estimate_revision_replacement_gate_pass': 1, 'est_eps_revision_breadth': 1.0}
        self.assertTrue(c.verified_legacy_signal(legacy))
        scored = pd.DataFrame([{'ticker': 'AAA', 'score': 1.0}, {'ticker': 'BBB', 'score': 1.1}])
        args = dict(decision_date=pd.Timestamp('2026-07-01'), listing=pd.DataFrame(),
                    earnings_calendar=pd.DataFrame(), top_n=2)
        baseline, _ = build_overlay(scored, signals=pd.DataFrame(), **args)
        valid, _ = build_overlay(scored, signals=pd.DataFrame([legacy]), **args)
        self.assertGreater(valid.set_index('ticker').loc['AAA', 'free_data_forward_estimate_score'], 0)
        v2 = features([snapshot()]).to_dict('records')[0]
        bad_rows = [{**legacy, 'source_contract': 'unknown-source-v99'},
                    {k:v for k,v in legacy.items() if k != 'as_of_date'},
                    {**legacy, 'est_eps_revision_30d': float('inf')}]
        for contract in ('earnings-consensus-source-v2', 'unknown-source-v99', None, ''):
            bad_rows.append({**v2, 'source_contract': contract, 'estimate_revision_confirmed': 1,
                             'estimate_revision_replacement_gate_pass': 1})
        bad_rows.append({k:v for k,v in v2.items() if k != 'source_contract'})
        for bad in bad_rows:
            self.assertFalse(c.verified_legacy_signal(bad))
            for rows in ([bad], [legacy, bad], [bad, legacy]):
                out, _ = build_overlay(scored, signals=pd.DataFrame(rows), **args)
                for col in ('free_data_forward_estimate_score', 'free_data_selection_score', 'free_data_selection_rank'):
                    pd.testing.assert_series_equal(out.set_index('ticker')[col].sort_index(),
                                                   baseline.set_index('ticker')[col].sort_index())
        union = {**legacy, **{k:None for k in v2 if k not in legacy}}
        self.assertTrue(c.verified_legacy_signal(union))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'legacy.parquet'
            legacy['as_of_date'] = legacy['available_from'] = pd.Timestamp('2026-04-01')
            pd.DataFrame([legacy]).to_parquet(path)
            self.assertTrue(c.verified_legacy_signal(pd.read_parquet(path).to_dict('records')[0]))

    def test_collector_reports_integrity_failure_and_clears_stale_signals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history = root / 'history'; history.mkdir()
            old = history / 'estimates_20260401.parquet'
            pd.DataFrame([{**snapshot(), 'snapshot_version_id': 'damaged'}]).to_parquet(old)
            old_bytes = old.read_bytes()
            signal_path = root / 'signals.parquet'
            features([snapshot()]).to_parquet(signal_path)
            fresh = snapshot('2026-07-01T18:00:00Z', 2)
            with patch.object(c, 'collect_live_snapshot', return_value=(pd.DataFrame([fresh]), [])), \
                 patch.object(sys, 'argv', ['collector', '--tickers', 'AAA', '--api-key', 'fixture',
                     '--fetch-date', '2026-07-01', '--snapshot-dir', str(history),
                     '--signals-output', str(signal_path), '--summary', str(root / 'summary.json')]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(c.main(), 2)
            summary = json.loads((root / 'summary.json').read_text())
            self.assertEqual(summary['status'], 'blocked_data_integrity')
            self.assertEqual(summary['reason'], 'archive_integrity_failure')
            self.assertTrue(pd.read_parquet(signal_path).empty)
            self.assertEqual(old.read_bytes(), old_bytes)

    def test_archive_commit_waits_for_full_history_integrity(self):
        for corrupted in (True, False):
            with self.subTest(corrupted=corrupted), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                history = root / 'history'; history.mkdir()
                may = history / 'estimates_20260501.parquet'
                july = history / 'estimates_20260701.parquet'
                older = snapshot('2026-05-01T18:00:00Z', 1)
                if corrupted:
                    older['snapshot_version_id'] = 'damaged'
                row_a = snapshot('2026-07-01T17:00:00Z', 2)
                row_b = snapshot('2026-07-01T18:00:00Z', 3)
                pd.DataFrame([older]).to_parquet(may, index=False)
                pd.DataFrame([row_a]).to_parquet(july, index=False)
                may_bytes, july_bytes = may.read_bytes(), july.read_bytes()
                signal_path = root / 'signals.parquet'
                features([row_a]).to_parquet(signal_path)
                original_compute = c.compute_estimate_revision_features
                original_write = pd.DataFrame.to_parquet
                events = []

                def compute(frame, **kwargs):
                    self.assertEqual(may.read_bytes(), may_bytes)
                    self.assertEqual(july.read_bytes(), july_bytes)
                    self.assertEqual(len(frame), 3)
                    result = original_compute(frame, **kwargs)
                    events.append('blocked' if corrupted else 'validated')
                    return result

                def write(frame, path, *args, **kwargs):
                    if Path(path).parent == history:
                        self.assertIn('validated', events)
                        self.assertNotEqual(Path(path), july)
                        events.append('archive_staged')
                    return original_write(frame, path, *args, **kwargs)

                argv = ['collector', '--tickers', 'AAA', '--api-key', 'fixture',
                        '--fetch-date', '2026-07-01', '--snapshot-dir', str(history),
                        '--signals-output', str(signal_path), '--summary', str(root / 'summary.json')]
                with patch.object(c, 'collect_live_snapshot', return_value=(pd.DataFrame([row_b]), [])), \
                     patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                    with patch.object(c, 'compute_estimate_revision_features', side_effect=compute), \
                         patch.object(pd.DataFrame, 'to_parquet', new=write):
                        self.assertEqual(c.main(), 2 if corrupted else 0)
                    summary = json.loads((root / 'summary.json').read_text())
                    self.assertEqual(may.read_bytes(), may_bytes)
                    if corrupted:
                        self.assertEqual(summary['status'], 'blocked_data_integrity')
                        self.assertEqual(summary['reason'], 'archive_integrity_failure')
                        self.assertEqual(july.read_bytes(), july_bytes)
                        self.assertTrue(pd.read_parquet(signal_path).empty)
                        self.assertEqual(events, ['blocked'])
                        self.assertNotIn(row_b['snapshot_version_id'], pd.read_parquet(july).snapshot_version_id.tolist())
                    else:
                        self.assertEqual(summary['status'], 'completed')
                        self.assertEqual(events, ['validated', 'archive_staged'])
                        self.assertEqual(set(pd.read_parquet(july).snapshot_version_id),
                                         {row_a['snapshot_version_id'], row_b['snapshot_version_id']})
                        committed = july.read_bytes()
                        signal_bytes = signal_path.read_bytes()
                        self.assertEqual(c.main(), 0)
                        self.assertEqual(july.read_bytes(), committed)
                        self.assertEqual(signal_path.read_bytes(), signal_bytes)
                    expected_files = [may.name, july.name]
                    if not corrupted:
                        expected_files.append(c.TRANSACTION_MARKER_NAME)
                    self.assertEqual(sorted(p.name for p in history.iterdir()), sorted(expected_files))

    def test_version_integrity_precedes_every_consumer_clock(self):
        before = snapshot('2026-04-01T18:00:00Z', 1)
        after = snapshot('2026-05-02T18:00:00Z', 2)
        args = dict(event_available_at='2026-07-01T20:00:00Z',
                    identity=json.loads(before['eps_fy1_identity']), fetch_source='finnhub')
        for field in ('observed_at', 'collected_at', 'first_seen_at',
                      'strategy_available_at', 'provider_published_at'):
            # Only the chosen clock puts this otherwise pre-event row after
            # the event. Tampering it must not turn it into frozen evidence.
            late = {**before, field: '2026-07-01T21:00:00Z'}
            late['snapshot_version_id'] = h1.snapshot_digest(late)
            bad = {**late, field: '2026-07-01T19:00:00Z'}
            self.assertFalse(h1.persisted_v2_snapshot_is_valid(bad), field)
            with patch.object(h1, 'availability', side_effect=AssertionError('clock read before version')):
                self.assertIsNone(h1.frozen_pre_event_consensus([bad], **args), field)
                self.assertIsNone(h1.same_period_revision(after, bad), field)
                self.assertIsNone(h1.same_period_revision(bad, before), field)
            for rows in ([before, bad], [bad, before]):
                self.assertIsNone(h1.frozen_pre_event_consensus(rows, **args), field)
            with patch.object(c, 'availability', side_effect=AssertionError('clock read before version')):
                self.assertTrue(features([bad]).empty, field)
                self.assertTrue(c.latest_signal_by_ticker(pd.DataFrame([bad]),
                                decision_date=args['event_available_at']).empty, field)
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'estimates_20260401.parquet'
                pd.DataFrame([bad]).to_parquet(path)
                historical = c.load_snapshot_history(Path(temp))
                self.assertTrue(c.compute_estimate_revision_features(historical)[0].empty, field)
            signals = features([before])
            signals.loc[0, field] = '2026-07-01T19:00:00Z'
            self.assertTrue(c.latest_signal_by_ticker(signals,
                            decision_date=args['event_available_at']).empty, field)
        self.assertEqual(h1.frozen_pre_event_consensus([before], **args)['value'], 1)
        self.assertEqual(h1.same_period_revision(after, before), 1)
        self.assertEqual(features([before, after]).iloc[-1].est_eps_revision_30d, 1)
        self.assertFalse(c.latest_signal_by_ticker(features([before, after]),
                         decision_date=args['event_available_at']).empty)

    def test_malformed_persisted_inputs_fail_without_consumer_exceptions(self):
        valid = snapshot()
        args = dict(event_available_at='2026-07-01T20:00:00Z',
                    identity=json.loads(valid['eps_fy1_identity']), fetch_source='finnhub')
        for bad in (True, [], 'row', 123, None, {},
                    {**valid, 'consensus_observations_json': '['},
                    {**valid, 'snapshot_version_id': '0' * 64}):
            self.assertFalse(h1.persisted_v2_snapshot_is_valid(bad))
            self.assertIsNone(h1.frozen_pre_event_consensus([bad], **args))
            self.assertIsNone(h1.same_period_revision(valid, bad))
            self.assertIsNone(h1.same_period_revision(bad, valid))

    def test_nonfinite_identity_scalars_never_become_economic_identity(self):
        fields = ('currency', 'security_id', 'issuer_id', 'accounting_basis',
                  'period_type', 'share_or_ADR_unit')
        for field in fields:
            for value in (float('inf'), float('-inf'), float('nan')):
                item = estimate(); item[field] = value
                old = snapshot(eps_payload={'data': [item]}, revenue_payload={})
                item = {**item, 'avg': 2}
                new = snapshot('2026-05-02T18:00:00Z', eps_payload={'data': [item]}, revenue_payload={})
                self.assertIsNone(h1.text_value(value))
                self.assertNotEqual(old['identity_status'], 'VERIFIED', field)
                self.assertNotEqual(new['identity_status'], 'VERIFIED', field)
                self.assertIsNone(h1.same_period_revision(new, old), field)
                identity = json.loads(old['consensus_observations_json'])[0]['identity']
                self.assertFalse(h1.identity_complete(identity), field)
                self.assertIsNone(h1.frozen_pre_event_consensus([old, new],
                    event_available_at='2026-07-01T20:00:00Z', identity=identity,
                    fetch_source='finnhub'), field)
        for value, expected in ((1, '1'), (1.5, '1.5'), (' USD ', 'USD')):
            self.assertEqual(h1.text_value(value), expected)
        self.assertEqual(snapshot()['identity_status'], 'VERIFIED')

    def test_legacy_requires_complete_producer_columns_and_types(self):
        legacy = legacy_snapshot()
        self.assertEqual(set(legacy), c.LEGACY_REQUIRED_COLUMNS)
        self.assertEqual(set(c.LEGACY_FIELD_TYPE_CONTRACT), set(legacy))
        self.assertEqual(c.classify_persisted_archive_row(legacy), 'VERIFIED_LEGACY')
        sparse = {k: legacy[k] for k in ('ticker', 'as_of_date', 'available_from')}
        invalid_rows = [sparse]
        invalid_rows.extend({k: v for k, v in legacy.items() if k != missing} for missing in legacy)
        for field in legacy:
            invalid_rows.extend({**legacy, field: value} for value in ([], {'bad': 'shape'}, None))
        invalid_rows.extend({**legacy, field: value} for field, value in (
            ('eps_estimate_access', 1), ('has_forward_estimate', True),
            ('has_forward_estimate', 2), ('n_analysts', 1.5),
            ('est_eps_fy1', '1.2'), ('est_eps_fy1', float('inf')),
            ('est_eps_fy1', True), ('as_of_date', '2026-02-30'),
            ('actual_report_date', 'yesterday'), ('recommendation_period', '2026-07'),
            ('fetch_source', ''), ('ticker', '')))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'day.parquet'
            current = pd.DataFrame([snapshot()])
            for bad in invalid_rows:
                self.assertEqual(c.classify_persisted_archive_row(bad), 'INVALID_OR_UNKNOWN_SCHEMA', bad)
                # Real malformed storage is rejected before any archive write.
                pd.DataFrame([bad]).to_parquet(path)
                stored = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'invalid_or_unknown_existing'):
                    c.merge_same_day_snapshot(path, current)
                self.assertEqual(path.read_bytes(), stored)
            # Integral floats are the same legacy integers after Parquet union.
            legacy['n_analysts'] = 0.0
            union = {**legacy, **{k: None for k in snapshot() if k not in legacy}}
            self.assertEqual(c.classify_persisted_archive_row(union), 'VERIFIED_LEGACY')
            pd.DataFrame([union]).to_parquet(path)
            mixed, _ = c.merge_same_day_snapshot(path, current)
            mixed.to_parquet(path)
            repeated, _ = c.merge_same_day_snapshot(path, current)
            pd.testing.assert_frame_equal(mixed.reset_index(drop=True), repeated.reset_index(drop=True),
                                          check_dtype=False)

    def test_causal_event_equivalent_formats_dedupe(self):
        keys = [h1.causal_event_id(issuer, period, timestamp)
                for issuer, period, timestamp in [
                    ('CIK:1', '2026-06-30', '2026-07-01T20:00:00Z'),
                    (' CIK:1 ', '20260630', '2026-07-01T16:00:00-04:00'),
                    ('CIK:1', '2026-W27-2', '2026-07-01T20:00:00+00:00')]]
        self.assertEqual(len(set(keys)), 1)
        self.assertEqual(len(h1.dedupe_causal_events([
            dict(causal_event_id=k, causal_link_verified=True, kind=str(i))
            for i, k in enumerate(keys)])), 1)

    def test_consensus_hash_mismatch_blocks_both_consumers(self):
        before = snapshot(); after = snapshot('2026-05-02T18:00:00Z', 2)
        identity = json.loads(before['eps_fy1_identity'])
        bad = copy.deepcopy(before)
        records = json.loads(bad['consensus_observations_json'])
        records[0]['value'] = 999
        bad['consensus_observations_json'] = json.dumps(records)
        self.assertEqual(h1.consensus_records(bad), [])
        self.assertIsNone(h1.same_period_revision(after, bad))
        bad_current = copy.deepcopy(after)
        bad_current['consensus_observations_json'] = bad['consensus_observations_json']
        self.assertIsNone(h1.same_period_revision(bad_current, before))
        self.assertIsNone(h1.frozen_pre_event_consensus([bad], event_available_at='2026-05-03T20:00:00Z', identity=identity, fetch_source='finnhub'))
        self.assertIsNone(h1.frozen_pre_event_consensus([before, bad_current], event_available_at='2026-05-03T20:00:00Z', identity=identity, fetch_source='finnhub'))
        tampered_view = copy.deepcopy(after); tampered_view['est_eps_fy1'] = 999
        self.assertIsNone(h1.same_period_revision(tampered_view, before))

    def test_unknown_publication_post_event_collection_cannot_invalidate(self):
        before = snapshot('2026-07-01T18:00:00Z', 1)
        identity = json.loads(before['eps_fy1_identity'])
        unknown = snapshot('2026-07-01T19:59:00Z', None,
                           collected_at='2026-07-01T20:01:00Z', provider_published_at='2026-07-01')
        args = dict(event_available_at='2026-07-01T20:00:00Z', identity=identity, fetch_source='finnhub')
        self.assertEqual(h1.frozen_pre_event_consensus([before, unknown], **args)['value'], 1)
        unknown['collected_at'] = '2026-07-01T19:59:59Z'
        unknown['snapshot_version_id'] = h1.snapshot_digest(unknown)
        self.assertIsNone(h1.frozen_pre_event_consensus([before, unknown], **args))
        for key in ('first_seen_at', 'strategy_available_at', 'provider_published_at'):
            delayed = {**unknown, key: '2026-07-01T20:01:00Z'}
            delayed['snapshot_version_id'] = h1.snapshot_digest(delayed)
            self.assertEqual(h1.frozen_pre_event_consensus([before, delayed], **args)['value'], 1)

    def test_unknown_publication_only_blocks_current_or_newer_vintage(self):
        old_unknown = snapshot('2026-07-01T18:00:00Z', None, provider_published_at='2026-07-01')
        verified = snapshot('2026-07-01T19:00:00Z', 2)
        new_unknown = snapshot('2026-07-01T19:30:00Z', None, provider_published_at='2026-07-01')
        equal_unknown = snapshot('2026-07-01T19:00:00Z', None, provider_published_at='2026-07-01')
        post_event = snapshot('2026-07-01T19:30:00Z', None,
                              collected_at='2026-07-01T20:01:00Z', provider_published_at='2026-07-01')
        args = dict(event_available_at='2026-07-01T20:00:00Z',
                    identity=json.loads(verified['eps_fy1_identity']), fetch_source='finnhub')
        for rows in ([old_unknown, verified], [verified, old_unknown],
                     [old_unknown, verified, post_event]):
            self.assertEqual(h1.frozen_pre_event_consensus(rows, **args)['value'], 2)
        for unknown in (new_unknown, equal_unknown):
            for rows in ([verified, unknown], [unknown, verified]):
                self.assertIsNone(h1.frozen_pre_event_consensus(rows, **args))

    def test_malformed_identity_types_fail_closed(self):
        before = snapshot()
        for field, invalid in [('currency', True), ('security_id', ['ABC']),
                               ('issuer_id', {}), ('share_or_ADR_unit', ['ADR'])]:
            item = estimate(1.2)
            item[field] = invalid
            row = snapshot('2026-05-02T18:00:00Z', eps_payload={'data': [item]}, revenue_payload={})
            self.assertNotEqual(row['identity_status'], 'VERIFIED', field)
            self.assertIsNone(h1.same_period_revision(row, before), field)
            self.assertIsNone(h1.frozen_pre_event_consensus(
                [row], event_available_at='2026-05-03T20:00:00Z',
                identity=json.loads(before['eps_fy1_identity']), fetch_source='finnhub'), field)
            self.assertFalse(h1.identity_complete({**json.loads(before['eps_fy1_identity']), field: invalid}))
        self.assertEqual(snapshot()['identity_status'], 'VERIFIED')

    def test_malformed_top_level_identity_never_raises_or_admits(self):
        before = snapshot()
        canonical = json.loads(before['eps_fy1_identity'])
        after = snapshot('2026-05-02T18:00:00Z', 2)
        for invalid in (True, False, [], ['ABC'], 'ABC', 123, {}):
            self.assertFalse(h1.identity_complete(invalid))
            self.assertIsNone(h1.frozen_pre_event_consensus(
                [before], event_available_at='2026-05-03T20:00:00Z',
                identity=invalid, fetch_source='finnhub'))
            self.assertIsNone(h1.earnings_surprise(
                2, {'identity': invalid}, identity=invalid,
                announcement_at='2026-05-03T20:00:00Z'))
            malformed = {**after, 'eps_fy1_identity': invalid}
            self.assertIsNone(h1.same_period_revision(malformed, before))
        self.assertIsNone(h1.same_period_revision({**after, 'eps_fy1_identity': '[invalid'}, before))
        self.assertTrue(h1.identity_complete(canonical))
        self.assertEqual(h1.frozen_pre_event_consensus(
            [before], event_available_at='2026-05-03T20:00:00Z',
            identity=canonical, fetch_source='finnhub')['value'], 1)
        self.assertAlmostEqual(h1.same_period_revision(after, before), 1)

    def test_stripped_v2_markers_cannot_downgrade_to_legacy(self):
        original = snapshot()
        current = pd.DataFrame([snapshot('2026-04-01T19:00:00Z', 2)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'day.parquet'
            for stripped in (('source_contract',), ('snapshot_version_id',),
                             ('source_contract', 'snapshot_version_id')):
                corrupt = copy.deepcopy(original)
                for key in stripped:
                    corrupt.pop(key)
                self.assertEqual(c.classify_persisted_archive_row(corrupt), 'V2_REQUIRES_VALIDATION')
                pd.DataFrame([corrupt]).to_parquet(path)
                stored = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                    c.merge_same_day_snapshot(path, current)
                self.assertEqual(path.read_bytes(), stored)
            corrupt = copy.deepcopy(original)
            corrupt['source_contract'] = None
            corrupt['snapshot_version_id'] = None
            records = json.loads(corrupt['consensus_observations_json'])
            records[0]['value'] = 999
            corrupt['consensus_observations_json'] = json.dumps(records)
            pd.DataFrame([corrupt]).to_parquet(path)
            with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                c.merge_same_day_snapshot(path, current)
            legacy = legacy_snapshot()
            self.assertEqual(c.classify_persisted_archive_row(legacy), 'VERIFIED_LEGACY')
            pd.DataFrame([legacy]).to_parquet(path)
            mixed, _ = c.merge_same_day_snapshot(path, pd.DataFrame([original]))
            self.assertEqual(set(mixed['ticker']), {'LEG', 'AAA'})
            mixed.to_parquet(path)
            repeated, _ = c.merge_same_day_snapshot(path, pd.DataFrame([original]))
            self.assertEqual(len(repeated), 2)
            self.assertEqual(mixed['snapshot_version_id'].fillna('').tolist(),
                             repeated['snapshot_version_id'].fillna('').tolist())

    def test_positive_legacy_classification_rejects_remaining_v2_or_unknown_fields(self):
        v2 = snapshot()
        legacy = legacy_snapshot()
        self.assertEqual(c.classify_persisted_archive_row(legacy), 'VERIFIED_LEGACY')
        base, parsed, live = h1.snapshot_field_profiles()
        v2_distinct = (base | parsed | live) - c.LEGACY_ARCHIVE_FIELDS
        self.assertTrue({'observed_at', 'collected_at', 'first_seen_at',
                         'strategy_available_at', 'eps_fy1_status'} <= v2_distinct)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'day.parquet'
            for marker in ('observed_at', 'collected_at', 'first_seen_at',
                           'strategy_available_at', 'eps_fy1_status'):
                thin = {k: None for k in v2}
                thin.update({k: v2[k] for k in ('ticker', 'as_of_date', 'available_from', marker)})
                self.assertEqual(c.classify_persisted_archive_row(thin), 'V2_REQUIRES_VALIDATION')
                pd.DataFrame([thin]).to_parquet(path)
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                    c.merge_same_day_snapshot(path, pd.DataFrame([v2]))
                self.assertEqual(path.read_bytes(), before, marker)
            unknown = {**legacy, 'future_v3_provenance': 'unverified'}
            self.assertEqual(c.classify_persisted_archive_row(unknown), 'INVALID_OR_UNKNOWN_SCHEMA')
            pd.DataFrame([unknown]).to_parquet(path)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'invalid_or_unknown_existing_estimate_archive_schema'):
                c.merge_same_day_snapshot(path, pd.DataFrame([v2]))
            self.assertEqual(path.read_bytes(), before)
            legacy_union = {**legacy, **{key: None for key in v2_distinct}}
            self.assertEqual(c.classify_persisted_archive_row(legacy_union), 'VERIFIED_LEGACY')
            pd.DataFrame([legacy_union]).to_parquet(path)
            mixed, _ = c.merge_same_day_snapshot(path, pd.DataFrame([v2]))
            self.assertEqual(set(mixed['ticker']), {'LEG', 'AAA'})
            mixed.to_parquet(path)
            again, _ = c.merge_same_day_snapshot(path, pd.DataFrame([v2]))
            self.assertEqual(len(again), 2)
            self.assertEqual(mixed['snapshot_version_id'].fillna('').tolist(),
                             again['snapshot_version_id'].fillna('').tolist())

    def test_persisted_v2_row_integrity_before_same_day_merge(self):
        original = snapshot(value=None)
        correction = snapshot('2026-04-01T19:00:00Z', 2)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'day.parquet'
            pd.DataFrame([original]).to_parquet(path)
            h1.validate_persisted_snapshot(pd.read_parquet(path).to_dict('records')[0])
            for mutation in ('records', 'source_hash', 'version', 'contract'):
                corrupt = copy.deepcopy(original)
                if mutation == 'records':
                    records = json.loads(corrupt['consensus_observations_json'])
                    records[0]['value'] = 900
                    corrupt['consensus_observations_json'] = json.dumps(records)
                elif mutation == 'source_hash':
                    corrupt['source_payload_sha256'] = '0' * 64
                elif mutation == 'version':
                    corrupt['est_eps_fy1'] = 900
                else:
                    corrupt['source_contract'] = 'unsupported-contract'
                pd.DataFrame([corrupt]).to_parquet(path)
                with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                    c.merge_same_day_snapshot(path, pd.DataFrame([correction]))
            pd.DataFrame([original]).to_parquet(path)
            merged, _ = c.merge_same_day_snapshot(path, pd.DataFrame([correction]))
            self.assertEqual(len(merged), 2)
            merged.to_parquet(path)
            repeat, _ = c.merge_same_day_snapshot(path, pd.DataFrame([correction]))
            self.assertEqual(len(repeat), 2)
            self.assertEqual(merged['snapshot_version_id'].tolist(), repeat['snapshot_version_id'].tolist())
            # A legacy row can widen the Parquet schema; its null columns on
            # V2 rows must not become part of the original version payload.
            legacy = legacy_snapshot()
            pd.DataFrame([legacy]).to_parquet(path)
            mixed, _ = c.merge_same_day_snapshot(path, pd.DataFrame([original]))
            mixed.to_parquet(path)
            repeated, _ = c.merge_same_day_snapshot(path, pd.DataFrame([original]))
            self.assertEqual(len(repeated), 2)
            tampered = repeated.copy()
            tampered.loc[tampered['ticker'] == 'AAA', 'legacy_only'] = 'injected'
            tampered.to_parquet(path)
            with self.assertRaisesRegex(ValueError, 'invalid_existing_v2'):
                c.merge_same_day_snapshot(path, pd.DataFrame([correction]))

    def test_vendor_access_is_independent_of_estimate_value(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for eps_access, revenue_access, errors in (
                (True, True, []), (True, False, [{'ticker': 'AAA', 'vendor': 'finnhub',
                    'endpoint': '/stock/revenue-estimate', 'vendor_entitlement_blocked': True,
                    'status_code': 403}]), (False, False, [{'ticker': 'AAA', 'vendor': 'finnhub',
                    'endpoint': '/stock/eps-estimate', 'vendor_entitlement_blocked': True,
                    'status_code': 403}])):
                row = snapshot('2026-07-01T18:00:00Z', None, eps_payload={'data': [estimate(None)]},
                               revenue_payload={'data': [estimate(None)]},
                               eps_estimate_access=eps_access, revenue_estimate_access=revenue_access)
                with patch.object(c, 'collect_live_snapshot', return_value=(pd.DataFrame([row]), errors)), \
                     patch.object(sys, 'argv', ['collector', '--tickers', 'AAA', '--api-key', 'fixture',
                         '--fetch-date', '2026-07-01', '--snapshot-dir', str(root / 'snapshots'),
                         '--signals-output', str(root / 'signals.parquet'), '--summary', str(root / 'summary.json')]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(c.main(), 0)
                payload = json.loads((root / 'summary.json').read_text())
                self.assertEqual(payload['vendor_estimate_access'], eps_access and revenue_access)
                self.assertEqual(payload['eps_estimate_access_rows'], int(eps_access))
                self.assertEqual(payload['revenue_estimate_access_rows'], int(revenue_access))
                self.assertEqual(payload['estimate_value_rows'], 0)
                self.assertEqual(payload['status'], 'blocked_partial_coverage' if eps_access else 'blocked_vendor_entitlement')
                self.assertEqual(payload['vendor_access_rows'], int(eps_access and revenue_access))

    def test_live_collection_stops_at_utc_rollover(self):
        clocks = ['2026-07-01T23:59:59Z'] * 2 + ['2026-07-02T00:00:00Z'] * 2
        with patch.object(c, 'utc_now', side_effect=clocks), patch.object(
                c, 'fetch_estimate_payloads_by_order', return_value=({}, {}, 'fmp', True, True, True)) as fetch:
            with self.assertRaisesRegex(ValueError, 'collection_utc_day_rollover'):
                c.collect_live_snapshot(['AAA', 'BBB'], finnhub_api_key='', alphavantage_api_key='',
                    fmp_api_key='fixture', vendor_order=['fmp'], fetch_date=pd.Timestamp('2026-07-01'),
                    sleep_seconds=0, max_errors=10)
            self.assertEqual(fetch.call_count, 1)

    def test_recommendation_is_not_breadth(self):
        row = snapshot()
        self.assertEqual(row['analyst_recommendation_balance'], .75)
        self.assertIsNone(row['est_eps_revision_breadth'])
        self.assertIsNone(features([row]).iloc[0]['est_eps_revision_breadth'])

    def test_missing_not_zero(self):
        row = snapshot(eps_payload={"data": [estimate(None)]}, revenue_payload={})
        self.assertIsNone(row['est_eps_fy1'])
        self.assertEqual(row['eps_fy1_status'], 'MISSING')
        self.assertEqual(row['rev_fy1_status'], 'NO_COVERAGE')
        self.assertIsNone(snapshot(recommendation_payload=[])['analyst_recommendation_balance'])

    def test_same_period_revision_eps_and_revenue(self):
        rows = [snapshot(), snapshot('2026-05-02T18:00:00Z', 1.2,
                                    revenue_payload={"data": [estimate(110)]})]
        last = features(rows).iloc[-1]
        self.assertAlmostEqual(last.est_eps_revision_30d, .2)
        self.assertAlmostEqual(last.est_rev_revision_30d, .1)

    def test_fy_roll_is_not_revision(self):
        last = features([snapshot(),snapshot('2026-05-02T18:00:00Z',2,'2027-12-31')]).iloc[-1]
        self.assertTrue(pd.isna(last.est_eps_revision_30d))

    def test_fy_view_can_match_prior_fy2_only_same_identity(self):
        before = snapshot(eps_payload={"data":[estimate(1),estimate(2,'2027-12-31')]})
        after = snapshot('2026-05-02T18:00:00Z',2.2,'2027-12-31')
        self.assertAlmostEqual(h1.same_period_revision(after,before),.1)
        self.assertEqual(json.loads(after['eps_fy1_identity'])['fiscal_period_end'],'2027-12-31')

    def test_currency_unit_security_and_basis_block(self):
        before=snapshot()
        for key,value in [('currency','EUR'),('share_or_ADR_unit','ADR_2_COMMON'),('security_id','FIGI:OTHER'),('issuer_id','CIK:2'),('accounting_basis','NON_GAAP'),('period_type','QUARTERLY')]:
            item=estimate(1.2); item[key]=value
            after=snapshot('2026-05-02T18:00:00Z',eps_payload={'data':[item]})
            self.assertIsNone(h1.same_period_revision(after,before),key)

    def test_after_close_and_utc_offsets(self):
        row=snapshot('2026-07-01T16:01:00-04:00')
        self.assertTrue(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-01T20:00:00Z').empty)
        self.assertFalse(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-02T20:00:00Z').empty)
        self.assertTrue(c.latest_signal_by_ticker(features([row]),decision_date='2026-07-01').empty)

    def test_no_snapshot_historical_backfill(self):
        row=snapshot('2026-07-02T21:00:00Z',fetch_date=pd.Timestamp('2000-01-01'))
        self.assertEqual(row['as_of_date'],'2026-07-02')
        self.assertTrue(c.compute_estimate_revision_features(pd.DataFrame([row]),as_of_date='2000-01-01')[0].empty)
        with patch.object(sys,'argv',['collector','--fetch-date','2000-01-01']):
            with self.assertRaisesRegex(ValueError,'backfill'): c.main()

    def test_frozen_pre_announcement(self):
        before=snapshot('2026-07-01T19:59:00Z',1)
        simultaneous=snapshot('2026-07-01T20:00:00Z',3)
        after=snapshot('2026-07-01T20:01:00Z',9)
        identity=json.loads(before['eps_fy1_identity'])
        frozen=h1.frozen_pre_event_consensus([before,simultaneous,after],event_available_at='2026-07-01T20:00:00Z',identity=identity,fetch_source='finnhub')
        self.assertEqual(frozen['value'],1)
        self.assertAlmostEqual(h1.earnings_surprise(1.5,frozen,identity=identity,announcement_at='2026-07-01T20:00:00Z'),.5)
        self.assertIsNone(h1.earnings_surprise(1.5,frozen,identity={**identity,'currency':'EUR'},announcement_at='2026-07-01T20:00:00Z'))
        self.assertIsNone(snapshot(earnings_payload=[{'period':'2026-06-30','surprisePercent':99}])['earnings_surprise_last'])

    def test_provider_corrections_preserve_versions(self):
        before=snapshot('2026-07-01T19:00:00Z',1)
        correction=snapshot('2026-07-01T21:00:00Z',2,provider_published_at='2026-06-01T00:00:00Z')
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'estimates.parquet'; pd.DataFrame([before]).to_parquet(p)
            merged,_=c.merge_same_day_snapshot(p,pd.DataFrame([correction]))
            self.assertEqual(len(merged),2)
            self.assertEqual(c.latest_signal_by_ticker(merged,decision_date='2026-07-01T20:00:00Z').iloc[0].est_eps_fy1,1)
            self.assertNotEqual(before['snapshot_version_id'],correction['snapshot_version_id'])

    def test_causal_event_dedupe(self):
        key=h1.causal_event_id('CIK:1','2026-06-30','2026-07-01T20:00:00Z')
        rows=[dict(causal_event_id=key,causal_link_verified=True,kind=k) for k in ['surprise','revision','rating','target_price','news']]
        self.assertEqual(len(h1.dedupe_causal_events(rows+rows)),1)
        self.assertEqual(len(h1.dedupe_causal_events(rows)[0]['reactions']),5)
        self.assertEqual(h1.dedupe_causal_events([dict(causal_event_id=key)]),[])

    def test_provider_missing_preserves_attempted_candidate(self):
        with patch.object(c,'fetch_estimate_payloads_by_order',return_value=({}, {}, 'fmp', True, True, True)):
            rows,_,attempted,_=c.collect_live_snapshot(['AAA','BBB'],finnhub_api_key='',alphavantage_api_key='',fmp_api_key='fixture',vendor_order=['fmp'],fetch_date=pd.Timestamp('2026-07-01'),sleep_seconds=0,max_errors=10)
        self.assertEqual(rows.ticker.tolist(),['AAA','BBB'])
        self.assertEqual(attempted,['AAA','BBB'])
        self.assertEqual(rows.provider_coverage_status.tolist(),['NO_COVERAGE','NO_COVERAGE'])

    def test_partial_update_equals_full_recompute(self):
        rows=[snapshot(ticker='AAA'),snapshot(ticker='BBB'),snapshot('2026-05-02T18:00:00Z',1.2),snapshot('2026-05-02T18:00:00Z',1.3,ticker='BBB')]
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'day.parquet'; pd.DataFrame(rows[:3]).to_parquet(p)
            merged,_=c.merge_same_day_snapshot(p,pd.DataFrame(rows[3:]))
            expected=features(rows).sort_values(['ticker','available_from']).reset_index(drop=True)
            actual=features(merged.to_dict('records')).sort_values(['ticker','available_from']).reset_index(drop=True)
            pd.testing.assert_frame_equal(actual,expected,check_like=True)

    def test_explicit_zero_remains_zero(self):
        row=snapshot(value=0)
        self.assertEqual(row['est_eps_fy1'],0)
        self.assertEqual(row['eps_fy1_status'],'EXPLICIT_ZERO')
        self.assertEqual(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',0),snapshot()),-1)
        self.assertIsNone(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',1),row))

    def test_null_survives_storage_and_compute(self):
        row=snapshot(value=None)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'test.parquet'; pd.DataFrame([row]).to_parquet(p)
            out=features(pd.read_parquet(p).to_dict('records'))
            self.assertTrue(pd.isna(out.iloc[0].est_eps_fy1))
            self.assertTrue(pd.isna(out.iloc[0].est_eps_revision_30d))
        for value in [None,'',float('nan'),float('inf'),True]: self.assertIsNone(h1.optional_float(value))

    def test_incomplete_identity_and_date_only_are_not_admitted(self):
        after=snapshot('2026-05-02T18:00:00Z',eps_payload={'data':[{'period':'2026','avg':2}]})
        self.assertIsNone(h1.same_period_revision(after,snapshot()))
        self.assertIsNone(h1.iso_utc('2026-07-01'))
        self.assertIsNone(h1.iso_utc('2026-07-01T20:00:00'))
        self.assertTrue(features([{'ticker':'AAA','available_from':'2026-07-01','est_eps_fy1':1}]).empty)

    def test_vendor_switch_not_revision(self):
        self.assertIsNone(h1.same_period_revision(snapshot('2026-05-02T18:00:00Z',2,fetch_source='fmp'),snapshot()))

    def test_revenue_fy1_is_first_not_last(self):
        row=snapshot(revenue_payload={'data':[estimate(100),estimate(200,'2027-12-31')]})
        self.assertEqual(row['est_rev_fy1'],100)
        self.assertEqual(row['rev_fy1_period_end'],'2026-12-31')

    def test_h2_consumers_stay_inactive(self):
        signals=features([snapshot(),snapshot('2026-05-02T18:00:00Z',2)])
        scored=pd.DataFrame([{'ticker':'AAA','score':.7,'portfolio_future_winner_engine_score':1},{'ticker':'BBB','score':.8,'portfolio_future_winner_engine_score':2}])
        out,summary=c.apply_estimate_revision_confirmation(scored,signals,decision_date='2026-05-03',enabled=True)
        self.assertEqual(out.portfolio_future_winner_engine_score.tolist(),[1,2])
        args=dict(decision_date=pd.Timestamp('2026-05-03'),listing=pd.DataFrame(),earnings_calendar=pd.DataFrame(),top_n=2)
        baseline,_=build_overlay(scored,signals=pd.DataFrame(),**args)
        result,_=build_overlay(scored,signals=signals,**args)
        pd.testing.assert_frame_equal(baseline,result)

    def test_availability_uses_latest_required_timestamp(self):
        row=snapshot('2026-07-01T18:00:00Z',collected_at='2026-07-02T18:00:00Z',first_seen_at='2026-06-01T18:00:00Z')
        self.assertEqual(row['strategy_available_at'],'2026-07-02T18:00:00Z')

    def test_missing_latest_does_not_fall_back_to_old_known(self):
        rows=[snapshot(),snapshot('2026-04-02T18:00:00Z',None),snapshot('2026-05-03T18:00:00Z',2)]
        self.assertTrue(pd.isna(features(rows).iloc[-1].est_eps_revision_30d))

    def test_conflicting_same_time_is_unknown(self):
        before=snapshot(); conflict=snapshot(value=3); after=snapshot('2026-05-02T18:00:00Z',2)
        self.assertTrue(pd.isna(features([before,conflict,after]).iloc[-1].est_eps_revision_30d))

    def test_frozen_latest_missing_or_absent_is_not_backfilled(self):
        before=snapshot('2026-07-01T18:00:00Z',1)
        identity=json.loads(before['eps_fy1_identity'])
        for latest in [snapshot('2026-07-01T19:00:00Z',None), snapshot('2026-07-01T19:00:00Z',eps_payload={},revenue_payload={})]:
            self.assertIsNone(h1.frozen_pre_event_consensus([before,latest],event_available_at='2026-07-01T20:00:00Z',identity=identity,fetch_source='finnhub'))

    def test_current_conflict_rejects_both_orders(self):
        before=snapshot(); a=snapshot('2026-05-02T18:00:00Z',2); b=snapshot('2026-05-02T18:00:00Z',3)
        for rows in ([before,a,b],[before,b,a]):
            result=features(rows)
            self.assertTrue(result.iloc[-2:].est_eps_revision_30d.isna().all())
            self.assertTrue(c.latest_signal_by_ticker(result,decision_date='2026-05-03').empty)

    def test_forward_view_preserves_history_and_sorts_canonical_period(self):
        items=[]
        for year in [2027,2020,2026,2021]:
            item=estimate(year, f'{year}-12-31'); item['fiscal_period_end']=item.pop('period'); items.append(item)
        row=snapshot('2026-07-01T18:00:00Z',eps_payload={'data':items})
        self.assertEqual(row['est_eps_fy1'],2026)
        self.assertEqual(row['est_eps_fy2'],2027)
        self.assertEqual(len(h1.consensus_records(row)),5)
        self.assertEqual(snapshot('2026-07-01T18:00:00Z',eps_payload={'data':[estimate(1,'2020-12-31')]},revenue_payload={})['has_forward_estimate'],0)

    def test_missing_publication_precision_preserved_and_blocked(self):
        row=snapshot(provider_published_at='2027-01-01')
        self.assertEqual(row['publication_status'],'UNKNOWN_PUBLICATION_PRECISION')
        self.assertIn('2027-01-01',row['provider_published_at_raw'])
        self.assertIsNone(row['strategy_available_at'])
        self.assertTrue(features([row]).empty)

    def test_live_endpoint_status_separates_failures(self):
        def fetch(_session,endpoint,ticker,_key,*,errors,**_):
            if endpoint=='/stock/eps-estimate':
                errors.append(dict(ticker=ticker,vendor='finnhub',endpoint=endpoint,status_code=500,vendor_entitlement_blocked=False))
                return None
            if endpoint=='/stock/revenue-estimate': return {'data':[estimate(100)]}
            return []
        args=dict(finnhub_api_key='fixture',alphavantage_api_key='',fmp_api_key='',vendor_order=['finnhub'],fetch_date=pd.Timestamp('2026-07-01'),sleep_seconds=0,max_errors=10)
        with patch.object(c,'fetch_json_optional',side_effect=fetch), patch.object(c,'utc_now',return_value='2026-07-01T18:00:00Z'):
            rows,_,_,_=c.collect_live_snapshot(['AAA'],**args)
        row=rows.iloc[0]
        self.assertEqual(row.eps_fy1_status,'FETCH_FAILED')
        self.assertEqual(row.rev_fy1_status,'OBSERVED')
        self.assertEqual(row.provider_coverage_status,'PARTIAL')
        def rec_failed(_session,endpoint,ticker,_key,*,errors,**_):
            if endpoint=='/stock/recommendation':
                errors.append(dict(ticker=ticker,vendor='finnhub',endpoint=endpoint,status_code=500,vendor_entitlement_blocked=False))
                return None
            return {'data':[]} if endpoint in c.ESTIMATE_ENDPOINTS else []
        with patch.object(c,'fetch_json_optional',side_effect=rec_failed):
            rows,_,_,_=c.collect_live_snapshot(['AAA'],**args)
        self.assertEqual(rows.iloc[0].provider_coverage_status,'NO_COVERAGE')
        self.assertEqual(rows.iloc[0].recommendation_fetch_status,'FETCH_FAILED')

    def test_vendor_normalization_retains_missing_and_zero(self):
        eps,_=c.fmp_to_payloads([dict(date='2026-12-31',epsAvg=None),dict(date='2027-12-31',epsAvg=0)])
        self.assertEqual(len(eps['data']),2)
        self.assertIsNone(eps['data'][0]['avg'])
        self.assertEqual(eps['data'][1]['avg'],0)
        self.assertEqual(eps['data'][1]['period_type'],'ANNUAL')

    def test_failed_live_refresh_invalidates_frozen_provider(self):
        before=snapshot('2026-07-01T18:00:00Z',1)
        def failed(_session,endpoint,ticker,_key,*,errors,**_):
            errors.append(dict(ticker=ticker,vendor='finnhub',endpoint=endpoint,status_code=500,vendor_entitlement_blocked=False))
            return None
        with patch.object(c,'fetch_json_optional',side_effect=failed),patch.object(c,'utc_now',return_value='2026-07-01T19:00:00Z'):
            rows,_,_,_=c.collect_live_snapshot(['AAA'],finnhub_api_key='fixture',alphavantage_api_key='',fmp_api_key='',vendor_order=['finnhub'],fetch_date=pd.Timestamp('2026-07-01'),sleep_seconds=0,max_errors=10)
        failed_row=rows.iloc[0].to_dict()
        self.assertEqual(failed_row['fetch_source'],'')
        self.assertEqual(failed_row['attempted_estimate_providers_json'],'["finnhub"]')
        self.assertIsNone(h1.frozen_pre_event_consensus([before,failed_row],event_available_at='2026-07-01T20:00:00Z',identity=json.loads(before['eps_fy1_identity']),fetch_source='finnhub'))

    def test_provider_attempt_ledger_keeps_accessible_empty_and_av_200_errors_fail_access(self):
        def finnhub(_session, endpoint, _ticker, _key, *, errors, **_):
            if endpoint in c.ESTIMATE_ENDPOINTS:
                metric_value = 1.0 if endpoint == '/stock/eps-estimate' else 100.0
                return {'data': [estimate(metric_value)]}
            return []
        with patch.object(c, 'fetch_fmp_payloads', return_value=({}, {})), \
             patch.object(c, 'fetch_json_optional', side_effect=finnhub):
            rows, _, _, _ = c.collect_live_snapshot(
                ['AAA'], finnhub_api_key='fh', alphavantage_api_key='', fmp_api_key='fmp',
                vendor_order=['fmp', 'finnhub'], fetch_date=pd.Timestamp('2026-07-01'),
                sleep_seconds=0, max_errors=10)
        row = rows.iloc[0].to_dict()
        self.assertEqual(json.loads(row['attempted_estimate_providers_json']), ['finnhub', 'fmp'])
        older = snapshot('2026-06-01T18:00:00Z', 0.5, fetch_source='fmp')
        identity = json.loads(older['eps_fy1_identity'])
        self.assertIsNone(h1.frozen_pre_event_consensus(
            [older, row], event_available_at='2026-07-01T20:00:00Z',
            identity=identity, fetch_source='fmp'))

        for key in ('Information', 'Note', 'Error Message'):
            av_errors = []
            attempts = []
            with patch.object(c, 'fetch_url_json', return_value={key: 'vendor error'}):
                result = c.fetch_estimate_payloads_by_order(
                    object(), 'AAA', finnhub_api_key='', alphavantage_api_key='av',
                    fmp_api_key='', vendor_order=['alphavantage'], sleep_seconds=0,
                    errors=av_errors, attempted_providers=attempts)
            self.assertEqual(attempts, ['alphavantage'])
            self.assertTrue(result[-1])
            self.assertFalse(result[3], key)
            self.assertFalse(result[4], key)
            self.assertTrue(av_errors, key)
            self.assertEqual(av_errors[-1]['status_code'], 200)

        av_errors = []
        attempts = []
        with patch.object(c, 'fetch_url_json', return_value={}):
            empty = c.fetch_estimate_payloads_by_order(
                object(), 'AAA', finnhub_api_key='', alphavantage_api_key='av',
                fmp_api_key='', vendor_order=['alphavantage'], sleep_seconds=0,
                errors=av_errors, attempted_providers=attempts)
        self.assertEqual(attempts, ['alphavantage'])
        self.assertTrue(empty[3])
        self.assertTrue(empty[4])
        self.assertFalse(av_errors)

    def test_archive_read_failure_blocks_and_leaves_queue_unacknowledged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history = root / 'history'; history.mkdir()
            current_path = history / 'estimates_20260701.parquet'
            current_path.write_bytes(b'not-a-parquet-file')
            current_bytes = current_path.read_bytes()
            signal_path = root / 'signals.parquet'
            features([snapshot('2026-06-01T18:00:00Z', 1)]).to_parquet(signal_path)
            checkpoint = root / 'checkpoint.json'
            queue = root / 'queue.csv'
            checkpoint.write_text(json.dumps({'ticker_states': [
                {'ticker': 'AAA', 'last_selected_at_utc': '', 'selection_count': 0}
            ]}), encoding='utf-8')
            queue.write_text(
                'ticker,selected,last_selected_at_utc,selection_count\\nAAA,true,,0\\n',
                encoding='utf-8')
            checkpoint_bytes, queue_bytes = checkpoint.read_bytes(), queue.read_bytes()
            fresh = snapshot('2026-07-01T18:00:00Z', 2)
            argv = ['collector', '--tickers', 'AAA', '--api-key', 'fixture',
                    '--fetch-date', '2026-07-01', '--snapshot-dir', str(history),
                    '--signals-output', str(signal_path), '--summary', str(root / 'summary.json'),
                    '--collection-checkpoint', str(checkpoint), '--collection-queue', str(queue)]
            with patch.object(c, 'collect_live_snapshot',
                              return_value=(pd.DataFrame([fresh]), [], ['AAA'], {})), \
                 patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(c.main(), 2)
            summary = json.loads((root / 'summary.json').read_text())
            self.assertEqual(summary['status'], 'blocked_data_integrity')
            self.assertEqual(summary['reason'], 'archive_integrity_failure')
            self.assertEqual(summary['collection_attempt_ack']['status'], 'deferred_until_durable_commit')
            self.assertTrue(pd.read_parquet(signal_path).empty)
            self.assertEqual(current_path.read_bytes(), current_bytes)
            self.assertEqual(checkpoint.read_bytes(), checkpoint_bytes)
            self.assertEqual(queue.read_bytes(), queue_bytes)

    def test_acknowledgement_is_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint = root / 'checkpoint.json'
            queue = root / 'queue.csv'
            checkpoint.write_text(json.dumps({'ticker_states': [
                {'ticker': 'AAA', 'last_selected_at_utc': '', 'selection_count': 0}
            ]}), encoding='utf-8')
            queue.write_text(
                'ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n',
                encoding='utf-8')
            attempt_id = 'attempt-1'
            first = c.acknowledge_collection_attempts(
                checkpoint, queue, ['AAA'], attempted_at_utc='2026-07-01T18:00:00Z',
                attempt_id=attempt_id)
            self.assertEqual(first['status'], 'acknowledged')
            checkpoint_once, queue_once = checkpoint.read_bytes(), queue.read_bytes()
            second = c.acknowledge_collection_attempts(
                checkpoint, queue, ['AAA'], attempted_at_utc='2026-07-01T19:00:00Z',
                attempt_id=attempt_id)
            self.assertEqual(second['status'], 'acknowledged')
            self.assertTrue(second['idempotent_replay'])
            self.assertEqual(checkpoint.read_bytes(), checkpoint_once)
            self.assertEqual(queue.read_bytes(), queue_once)
            payload = json.loads(checkpoint.read_text())
            self.assertEqual(payload['ticker_states'][0]['selection_count'], 1)

            checkpoint.write_bytes(checkpoint_once)
            queue.write_bytes(queue_once)
            before_checkpoint, before_queue = checkpoint.read_bytes(), queue.read_bytes()
            real_replace = c.os.replace
            failed = {'done': False}
            def fail_queue_once(src, dst):
                if Path(dst) == queue and not failed['done']:
                    failed['done'] = True
                    raise OSError('queue replace injected failure')
                return real_replace(src, dst)
            with patch.object(c.os, 'replace', side_effect=fail_queue_once):
                with self.assertRaisesRegex(OSError, 'queue replace injected failure'):
                    c.acknowledge_collection_attempts(
                        checkpoint, queue, ['AAA'], attempted_at_utc='2026-07-02T18:00:00Z',
                        attempt_id='attempt-2')
            self.assertEqual(checkpoint.read_bytes(), before_checkpoint)
            self.assertEqual(queue.read_bytes(), before_queue)

    def test_main_rolls_back_archive_on_signal_or_summary_commit_failure(self):
        for fail_target in ('signal', 'summary'):
            with self.subTest(fail_target=fail_target), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                history = root / 'history'; history.mkdir()
                snapshot_path = history / 'estimates_20260701.parquet'
                row_a = snapshot('2026-07-01T17:00:00Z', 1)
                row_b = snapshot('2026-07-01T18:00:00Z', 2)
                pd.DataFrame([row_a]).to_parquet(snapshot_path, index=False)
                archive_before = snapshot_path.read_bytes()
                signal_path = root / 'signals.parquet'
                features([row_a]).to_parquet(signal_path)
                summary_path = root / 'summary.json'
                checkpoint = root / 'checkpoint.json'
                queue = root / 'queue.csv'
                checkpoint.write_text(json.dumps({'ticker_states': [
                    {'ticker': 'AAA', 'last_selected_at_utc': '', 'selection_count': 0}
                ]}), encoding='utf-8')
                queue.write_text(
                    'ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n',
                    encoding='utf-8')
                checkpoint_before, queue_before = checkpoint.read_bytes(), queue.read_bytes()
                argv = ['collector', '--tickers', 'AAA', '--api-key', 'fixture',
                        '--fetch-date', '2026-07-01', '--snapshot-dir', str(history),
                        '--signals-output', str(signal_path), '--summary', str(summary_path),
                        '--collection-checkpoint', str(checkpoint), '--collection-queue', str(queue)]
                real_replace = c.os.replace
                failed = {'done': False}
                def fail_once(src, dst):
                    target = signal_path if fail_target == 'signal' else summary_path
                    if Path(dst) == target and not failed['done']:
                        failed['done'] = True
                        raise OSError(f'{fail_target} replace injected failure')
                    return real_replace(src, dst)
                with patch.object(c, 'collect_live_snapshot',
                                  return_value=(pd.DataFrame([row_b]), [], ['AAA'], {})), \
                     patch.object(c.os, 'replace', side_effect=fail_once), \
                     patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(c.main(), 2)
                self.assertEqual(snapshot_path.read_bytes(), archive_before)
                self.assertTrue(pd.read_parquet(signal_path).empty)
                blocked = json.loads(summary_path.read_text())
                self.assertEqual(blocked['status'], 'blocked_data_integrity')
                self.assertEqual(blocked['reason'], 'collector_transaction_commit_failure')
                self.assertEqual(blocked['collection_attempt_ack']['status'],
                                 'deferred_until_durable_commit')
                self.assertEqual(checkpoint.read_bytes(), checkpoint_before)
                self.assertEqual(queue.read_bytes(), queue_before)

                marker_path = history / c.TRANSACTION_MARKER_NAME
                self.assertEqual(json.loads(marker_path.read_text())["status"], "rolled_back")
                coverage = root / "coverage.csv"
                coverage.write_text("ticker\nAAA\n__CASH__\n")
                from tools.build_forward_estimate_incremental_universe import build_incremental_universe
                planner_args = dict(snapshot_dir=str(history), shard_dir=str(root / "shards"),
                    output=str(root / "collector-input.csv"), summary=str(root / "queue-summary.json"),
                    coverage_file=str(coverage), latest_run="", canonical_universe=str(root / "universe.csv"),
                    checkpoint=str(checkpoint), queue_output=str(queue), collector_summary=str(summary_path),
                    signals=str(signal_path), report=str(root / "queue.md"),
                    expected_universe_count=2, as_of_date="2026-07-01")
                before_restart = {path.relative_to(root): path.read_bytes()
                                  for path in root.rglob("*") if path.is_file()}
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, "collector_transaction_rolled_back_requires_verified_repair"):
                        build_incremental_universe(**planner_args)
                    for retry_argv in (argv, argv[:-4]):
                        with patch.object(c, "collect_live_snapshot") as collect, \
                             patch.object(sys, "argv", retry_argv), \
                             self.assertRaisesRegex(ValueError, "collector_transaction_rolled_back_requires_verified_repair"):
                            c.main()
                        collect.assert_not_called()
                    self.assertEqual({path.relative_to(root): path.read_bytes()
                                      for path in root.rglob("*") if path.is_file()}, before_restart)
                result = crash_manifest(root)
                self.assertFalse(result["publishable"])
                self.assertIn("collector_transaction_rolled_back_requires_verified_repair",
                              result["publication_failures"])

    def test_rollback_requires_complete_accepted_state_restoration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint, queue = root / "checkpoint.json", root / "queue.csv"
            checkpoint.write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
            queue.write_text("ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            self.assertEqual(crash_fixture(root), 0)
            history = root / "history"
            marker_path = history / c.TRANSACTION_MARKER_NAME
            accepted = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            marker = json.loads(marker_path.read_text())

            def verify():
                return manifest.require_verified_collector_state(history,
                    summary_path=root / "summary.json", checkpoint_path=checkpoint,
                    queue_path=queue, signals_path=root / "signals.parquet")

            # Even an otherwise hash-matching accepted generation cannot waive rollback.
            marker_path.write_text(json.dumps({**marker, "status": "rolled_back"}))
            local_checkpoint, local_queue = history / "checkpoint.json", history / "queue.csv"
            local_checkpoint.write_bytes(accepted[checkpoint])
            local_queue.write_bytes(accepted[queue])
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "collector_transaction_rolled_back_requires_verified_repair"):
                    verify()
                with self.assertRaisesRegex(ValueError, "collector_transaction_rolled_back_requires_verified_repair"):
                    c.acknowledge_collection_attempts(local_checkpoint, local_queue, ["AAA"],
                        attempted_at_utc="2026-07-01T19:00:00Z", attempt_id="unverified-retry")
                self.assertEqual(local_checkpoint.read_bytes(), accepted[checkpoint])
                self.assertEqual(local_queue.read_bytes(), accepted[queue])
            # Relabeling the marker alone is not a verified repair of corrupted payloads.
            (root / "signals.parquet").write_bytes(b"damaged rollback payload")
            marker_path.write_bytes(accepted[marker_path])
            with self.assertRaisesRegex(ValueError, "collector_signals_hash_mismatch"):
                verify()
            for path, payload in accepted.items():
                path.write_bytes(payload)
            self.assertEqual(verify()["state"], "accepted")
            self.assertEqual(json.loads(checkpoint.read_text())["ticker_states"][0]["selection_count"], 1)

    def test_sigkill_publication_boundaries_and_restart(self):
        boundaries = ("before_pending", "pending", "estimates_20260701.parquet",
                      "signals.parquet", "checkpoint.json", "queue.csv", "summary.json", "committed")
        for boundary in boundaries:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "history").mkdir()
                checkpoint, queue = root / "checkpoint.json", root / "queue.csv"
                checkpoint.write_text(json.dumps({"ticker_states": [
                    {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
                queue.write_text("ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
                child = subprocess.run([sys.executable, "-c",
                    "import sys; from pathlib import Path; sys.path.insert(0, 'tests'); "
                    "from earnings_consensus_h1_smoke import crash_fixture; "
                    "raise SystemExit(crash_fixture(Path(sys.argv[1]), sys.argv[2]))",
                    str(root), boundary], cwd=ROOT, capture_output=True, text=True, timeout=30)
                self.assertEqual(child.returncode, HARD_EXIT_CODE, child.stderr)
                manifest = crash_manifest(root)
                interrupted = boundary not in {"before_pending", "committed"}
                if interrupted:
                    expected_verdict = ("blocked_transaction_mismatch" if boundary == "summary.json"
                                        else "blocked_missing_or_invalid_summary")
                    self.assertEqual(manifest["verdict"], expected_verdict)
                    self.assertFalse(manifest["publishable"])
                    self.assertFalse(manifest["transaction_integrity"]["verified"])
                    # Repeated retries preserve the incomplete evidence byte-for-byte.
                    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
                    for _ in range(2):
                        with self.assertRaisesRegex(ValueError, "incomplete_collector_transaction"):
                            crash_fixture(root)
                    self.assertEqual(before, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()})
                    # The planner runs BEFORE the collector in the real workflow.
                    from tools.build_forward_estimate_incremental_universe import build_incremental_universe
                    with self.assertRaisesRegex(ValueError, "incomplete_collector_transaction"):
                        build_incremental_universe(snapshot_dir=str(root / "history"),
                            shard_dir=str(root / "shards"), output=str(root / "universe.csv"),
                            summary=str(root / "queue-summary.json"),
                            checkpoint=str(checkpoint), queue_output=str(queue))
                    self.assertEqual(before, {p: p.read_bytes() for p in root.rglob("*") if p.is_file()})
                    if boundary == "summary.json":
                        # Summary is last: the old summary-before-checkpoint window
                        # is impossible, but finalization still must be checked.
                        self.assertEqual(json.loads(checkpoint.read_text())["ticker_states"][0]["selection_count"], 1)
                        self.assertIn(",1", queue.read_text())
                else:
                    for _ in range(2):
                        self.assertEqual(crash_fixture(root), 0)
                        accepted = crash_manifest(root)
                        self.assertTrue(accepted["transaction_integrity"]["verified"], accepted)
                    self.assertEqual(json.loads(checkpoint.read_text())["ticker_states"][0]["selection_count"], 1)
                    self.assertIn(",1", queue.read_text())
                    self.assertEqual(len(pd.read_parquet(root / "history" / "estimates_20260701.parquet")), 1)

    def test_restart_binding_rejects_mixed_generation_and_accepts_bound_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "history").mkdir()
            checkpoint, queue = root / "checkpoint.json", root / "queue.csv"
            checkpoint.write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
            queue.write_text("ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            self.assertEqual(crash_fixture(root), 0)

            accepted_checkpoint = checkpoint.read_bytes()
            accepted_queue = queue.read_bytes()
            state = manifest.require_verified_collector_state(
                root / "history",
                summary_path=root / "summary.json",
                checkpoint_path=checkpoint,
                queue_path=queue,
                signals_path=root / "signals.parquet",
            )
            self.assertEqual(state["state"], "accepted")

            queue.unlink()
            state = manifest.require_verified_collector_state(
                root / "history",
                summary_path=root / "summary.json",
                checkpoint_path=checkpoint,
                queue_path=queue,
                signals_path=root / "signals.parquet",
                allow_missing_queue=True,
            )
            self.assertEqual(state["state"], "accepted")

            damaged = json.loads(accepted_checkpoint)
            damaged["ticker_states"][0]["selection_count"] = 99
            checkpoint.write_text(json.dumps(damaged))
            with self.assertRaisesRegex(ValueError, "collector_transaction_state_mismatch"):
                manifest.require_verified_collector_state(
                    root / "history",
                    summary_path=root / "summary.json",
                    checkpoint_path=checkpoint,
                    queue_path=queue,
                    signals_path=root / "signals.parquet",
                    allow_missing_queue=True,
                )

            checkpoint.write_bytes(accepted_checkpoint)
            queue.write_bytes(accepted_queue + b"\n")
            marker = json.loads(
                (root / "history" / c.TRANSACTION_MARKER_NAME).read_text()
            )
            summary = json.loads((root / "summary.json").read_text())
            tx = summary["transaction_commit"]
            planned = json.loads(accepted_checkpoint)
            planned["planning_parent_transaction"] = {
                "commit_id": marker["commit_id"],
                "summary_sha256": marker["summary_sha256"],
                "attempt_id": tx["attempt_id"],
                "checkpoint_sha256": tx["checkpoint_sha256"],
                "checkpoint_bytes_base64": base64.b64encode(accepted_checkpoint).decode("ascii"),
            }
            planned["planned_queue_sha256"] = manifest.sha256_file(queue)
            checkpoint.write_text(json.dumps(planned))
            state = manifest.require_verified_collector_state(
                root / "history",
                summary_path=root / "summary.json",
                checkpoint_path=checkpoint,
                queue_path=queue,
                signals_path=root / "signals.parquet",
            )
            self.assertEqual(state["state"], "planned")

            planned["planning_parent_transaction"]["commit_id"] = "wrong"
            checkpoint.write_text(json.dumps(planned))
            with self.assertRaisesRegex(ValueError, "collector_transaction_state_mismatch"):
                manifest.require_verified_collector_state(
                    root / "history",
                    summary_path=root / "summary.json",
                    checkpoint_path=checkpoint,
                    queue_path=queue,
                    signals_path=root / "signals.parquet",
                )

    def test_manifest_missing_invalid_or_pending_state_is_non_publishable(self):
        def manifest_cli(root: Path) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "build_earnings_estimate_archive_manifest.py"),
                    "--snapshot-dir", str(root / "history"),
                    "--signals", str(root / "signals.parquet"),
                    "--summary", str(root / "summary.json"),
                    "--collector-log", str(root / "collector.log"),
                    "--manifest", str(root / "manifest-cli.json"),
                    "--index", str(root / "index-cli.jsonl"),
                    "--run-id", "crash-run",
                    "--run-attempt", "1",
                    "--head-sha", "fixture-head",
                    "--ref", "fixture",
                    "--workflow", "fixture",
                    "--artifact-name", "fixture",
                    "--queue-checkpoint", str(root / "checkpoint.json"),
                    "--queue-csv", str(root / "queue.csv"),
                    "--queue-summary", str(root / "queue-summary.json"),
                    "--queue-report", str(root / "queue.md"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "history").mkdir()
            (root / "checkpoint.json").write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
            (root / "queue.csv").write_text(
                "ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            self.assertEqual(crash_fixture(root), 0)
            self.assertTrue(crash_manifest(root)["publishable"])
            self.assertEqual(manifest_cli(root).returncode, 0)

            good_summary = (root / "summary.json").read_bytes()
            good_marker = (root / "history" / c.TRANSACTION_MARKER_NAME).read_bytes()

            (root / "summary.json").unlink()
            missing = crash_manifest(root)
            self.assertFalse(missing["publishable"])
            self.assertEqual(missing["verdict"], "blocked_missing_or_invalid_summary")
            self.assertNotEqual(manifest_cli(root).returncode, 0)

            (root / "summary.json").write_text("{")
            invalid = crash_manifest(root)
            self.assertFalse(invalid["publishable"])
            self.assertEqual(invalid["verdict"], "blocked_missing_or_invalid_summary")
            self.assertNotEqual(manifest_cli(root).returncode, 0)

            (root / "summary.json").write_bytes(good_summary)
            marker = json.loads(good_marker)
            marker["status"] = "pending"
            (root / "history" / c.TRANSACTION_MARKER_NAME).write_text(json.dumps(marker))
            pending = crash_manifest(root)
            self.assertFalse(pending["publishable"])
            self.assertEqual(pending["verdict"], "blocked_transaction_mismatch")
            self.assertNotEqual(manifest_cli(root).returncode, 0)

    def test_planning_cannot_advance_or_reset_accepted_collection_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint, queue = root / "checkpoint.json", root / "queue.csv"
            checkpoint.write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
            queue.write_text("ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            self.assertEqual(crash_fixture(root), 0)
            accepted_bytes = checkpoint.read_bytes()
            accepted = json.loads(accepted_bytes)
            marker = json.loads((root / "history" / c.TRANSACTION_MARKER_NAME).read_text())
            tx = json.loads((root / "summary.json").read_text())["transaction_commit"]
            parent = {"commit_id": marker["commit_id"], "summary_sha256": marker["summary_sha256"],
                      "attempt_id": tx["attempt_id"], "checkpoint_sha256": tx["checkpoint_sha256"],
                      "checkpoint_bytes_base64": base64.b64encode(accepted_bytes).decode("ascii")}

            def admit():
                return manifest.require_verified_collector_state(root / "history",
                    summary_path=root / "summary.json", checkpoint_path=checkpoint,
                    queue_path=queue, signals_path=root / "signals.parquet")

            cases = ("advanced", "reset", "clock", "bool_count", "duplicate",
                     "new_advanced", "ack", "missing_bytes", "tampered_bytes", "wrong_attempt")
            for damage in cases:
                with self.subTest(damage=damage):
                    planned = copy.deepcopy(accepted)
                    planned["planning_parent_transaction"] = copy.deepcopy(parent)
                    planned["planned_queue_sha256"] = manifest.sha256_file(queue)
                    row = planned["ticker_states"][0]
                    if damage == "advanced": row["selection_count"] = 99
                    elif damage == "reset": row["selection_count"] = 0
                    elif damage == "clock": row["last_selected_at_utc"] = "different"
                    elif damage == "bool_count": row["selection_count"] = True
                    elif damage == "duplicate": planned["ticker_states"].append(copy.deepcopy(row))
                    elif damage == "new_advanced": planned["ticker_states"].append(
                        {"ticker": "NEW", "selection_count": 1, "last_selected_at_utc": ""})
                    elif damage == "ack": planned["last_collection_attempt_ack"]["acknowledged_ticker_count"] = 99
                    elif damage == "missing_bytes": planned["planning_parent_transaction"].pop("checkpoint_bytes_base64")
                    elif damage == "tampered_bytes": planned["planning_parent_transaction"]["checkpoint_bytes_base64"] = base64.b64encode(b"{}").decode("ascii")
                    elif damage == "wrong_attempt": planned["planning_parent_transaction"]["attempt_id"] = "other"
                    checkpoint.write_text(json.dumps(planned))
                    before = checkpoint.read_bytes(), queue.read_bytes()
                    with self.assertRaisesRegex(ValueError, "collector_(planning_parent_state|transaction_state)_mismatch"):
                        admit()
                    self.assertEqual(before, (checkpoint.read_bytes(), queue.read_bytes()))

            planned = copy.deepcopy(accepted)
            planned["planning_parent_transaction"] = parent
            planned["planned_queue_sha256"] = manifest.sha256_file(queue)
            planned["ticker_states"].append({"ticker": "NEW", "selection_count": 0, "last_selected_at_utc": ""})
            checkpoint.write_text(json.dumps(planned))
            state = admit()
            self.assertEqual(state["state"], "planned")
            self.assertEqual(state["checkpoint_bytes_base64"], parent["checkpoint_bytes_base64"])

    def test_new_acknowledgement_drops_embedded_planning_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint, queue = root / "checkpoint.json", root / "queue.csv"
            checkpoint.write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}],
                "planning_parent_transaction": {"checkpoint_bytes_base64": "old-generation"},
                "planned_queue_sha256": "old-plan"}))
            queue.write_text("ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            ack, checkpoint_bytes, _ = c.prepare_collection_attempt_acknowledgement(
                checkpoint, queue, ["AAA"], attempted_at_utc="2026-07-01T18:00:00Z", attempt_id="new-run")
            self.assertEqual(ack["status"], "acknowledged")
            committed = json.loads(checkpoint_bytes)
            self.assertNotIn("planning_parent_transaction", committed)
            self.assertNotIn("planned_queue_sha256", committed)

    def test_actual_planner_retains_one_verified_checkpoint_generation(self):
        from tools.build_forward_estimate_incremental_universe import build_incremental_universe
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            coverage = root / "coverage.csv"
            coverage.write_text("ticker\nAAA\n__CASH__\n")
            args = dict(snapshot_dir=str(root / "history"), shard_dir=str(root / "shards"),
                output=str(root / "collector-input.csv"), summary=str(root / "queue-summary.json"),
                coverage_file=str(coverage), latest_run="", canonical_universe=str(root / "universe.csv"),
                checkpoint=str(root / "checkpoint.json"), queue_output=str(root / "queue.csv"),
                collector_summary=str(root / "summary.json"), signals=str(root / "signals.parquet"),
                report=str(root / "queue.md"), expected_universe_count=2, as_of_date="2026-07-01")
            build_incremental_universe(**args)
            self.assertEqual(crash_fixture(root), 0)
            accepted_bytes = (root / "checkpoint.json").read_bytes()
            for _ in range(2):
                build_incremental_universe(**args)
                planned = json.loads((root / "checkpoint.json").read_text())
                encoded = planned["planning_parent_transaction"]["checkpoint_bytes_base64"]
                self.assertEqual(base64.b64decode(encoded), accepted_bytes)
                self.assertEqual(planned["ticker_states"][0]["selection_count"], 1)
                state = manifest.require_verified_collector_state(root / "history",
                    summary_path=root / "summary.json", checkpoint_path=root / "checkpoint.json",
                    queue_path=root / "queue.csv", signals_path=root / "signals.parquet")
                self.assertEqual(state["state"], "planned")

    def test_workflow_restores_binding_evidence_and_gates_accepted_persistence(self):
        text = (ROOT / ".github" / "workflows" / "earnings_estimates_daily.yml").read_text()
        self.assertIn("outputs/earnings_estimates_daily/summary.json", text)
        self.assertIn("outputs/earnings_estimates_daily/collection_queue.csv", text)
        cache_start = text.index("- name: Save earnings estimate archive cache")
        upload_start = text.index("- name: Upload earnings estimate artifact")
        cache_block = text[cache_start:upload_start]
        self.assertIn("if: ${{ steps.build_manifest.outcome == 'success' }}", cache_block)
        self.assertNotIn("if: always()", cache_block)

    def test_pending_and_missing_marker_cannot_accept_a_previous_good_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checkpoint.json").write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
            (root / "queue.csv").write_text(
                "ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            self.assertEqual(crash_fixture(root), 0)
            self.assertTrue(crash_manifest(root)["transaction_integrity"]["verified"])
            marker = root / "history" / c.TRANSACTION_MARKER_NAME
            good_marker = marker.read_bytes()
            for state in ("missing", "wrong_commit_id", "wrong_summary_hash"):
                marker.write_bytes(good_marker)
                if state == "missing":
                    marker.unlink()
                else:
                    payload = json.loads(good_marker)
                    payload["commit_id" if state == "wrong_commit_id" else "summary_sha256"] = "wrong"
                    marker.write_text(json.dumps(payload))
                self.assertFalse(crash_manifest(root)["transaction_integrity"]["verified"], state)
            marker.write_bytes(good_marker)
            summary_before = (root / "summary.json").read_bytes()
            child = subprocess.run([sys.executable, "-c",
                "import sys; from pathlib import Path; sys.path.insert(0, 'tests'); "
                "from earnings_consensus_h1_smoke import crash_fixture; "
                "raise SystemExit(crash_fixture(Path(sys.argv[1]), 'pending'))",
                str(root)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(child.returncode, HARD_EXIT_CODE, child.stderr)
            self.assertEqual(summary_before, (root / "summary.json").read_bytes())
            self.assertFalse(crash_manifest(root)["transaction_integrity"]["verified"])
            with self.assertRaisesRegex(ValueError, "incomplete_collector_transaction"):
                crash_fixture(root)

    def test_publication_cannot_downgrade_transaction_schema_or_omit_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checkpoint.json").write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
            (root / "queue.csv").write_text(
                "ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            self.assertEqual(crash_fixture(root), 0)
            self.assertTrue(crash_manifest(root)["publishable"])
            summary_path = root / "summary.json"
            marker_path = root / "history" / c.TRANSACTION_MARKER_NAME
            good_summary = json.loads(summary_path.read_text())
            good_marker = json.loads(marker_path.read_text())
            for schema, retain_marker in itertools.product(
                ("earnings-estimate-collector-transaction-v1", "unknown", None,
                 "earnings-estimate-collector-transaction-v2"), (False, True)
            ):
                if schema == "earnings-estimate-collector-transaction-v2" and retain_marker:
                    continue
                with self.subTest(schema=schema, retain_marker=retain_marker):
                    changed = copy.deepcopy(good_summary)
                    if schema is None:
                        changed["transaction_commit"].pop("schema_version")
                    else:
                        changed["transaction_commit"]["schema_version"] = schema
                    summary_path.write_text(json.dumps(changed))
                    if retain_marker:
                        marker_path.write_text(json.dumps({**good_marker,
                            "summary_sha256": manifest.sha256_file(summary_path)}))
                    else:
                        marker_path.unlink(missing_ok=True)
                    result = crash_manifest(root)
                    self.assertFalse(result["publishable"])
                    self.assertFalse(result["transaction_integrity"]["verified"])
                    expected = ("collector_transaction_schema_mismatch" if schema !=
                        "earnings-estimate-collector-transaction-v2" else "collector_final_marker_mismatch")
                    self.assertIn(expected, result["publication_failures"])

    def test_missing_binding_hashes_cannot_disable_component_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "checkpoint.json").write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
            (root / "queue.csv").write_text(
                "ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            self.assertEqual(crash_fixture(root), 0)
            summary_path = root / "summary.json"
            marker_path = root / "history" / c.TRANSACTION_MARKER_NAME
            good_summary = json.loads(summary_path.read_text())
            good_marker = json.loads(marker_path.read_text())
            fields = ("snapshot_sha256", "signals_sha256", "checkpoint_sha256", "queue_sha256")
            for field, damage in itertools.product(fields, ("missing", "empty", "malformed", "boolean")):
                with self.subTest(field=field, damage=damage):
                    changed = copy.deepcopy(good_summary)
                    if damage == "missing":
                        changed["transaction_commit"].pop(field)
                    else:
                        changed["transaction_commit"][field] = {
                            "empty": "", "malformed": "wrong", "boolean": True}[damage]
                    summary_path.write_text(json.dumps(changed))
                    marker_path.write_text(json.dumps({**good_marker,
                        "summary_sha256": manifest.sha256_file(summary_path)}))
                    result = crash_manifest(root)
                    self.assertFalse(result["publishable"])
                    self.assertFalse(result["transaction_integrity"]["verified"])
                    self.assertIn(f"{field}_missing_or_invalid", result["publication_failures"])
                    with self.assertRaisesRegex(ValueError, "collector_transaction_binding_hash_missing_or_invalid"):
                        manifest.require_verified_collector_state(root / "history",
                            summary_path=summary_path, checkpoint_path=root / "checkpoint.json",
                            queue_path=root / "queue.csv", signals_path=root / "signals.parquet")
            for damage in ("checkpoint_queue_hashes", "transaction_and_marker"):
                with self.subTest(summary_ack="disabled", damage=damage):
                    changed = copy.deepcopy(good_summary)
                    changed["collection_attempt_ack"]["status"] = "disabled"
                    if damage == "checkpoint_queue_hashes":
                        changed["transaction_commit"].pop("checkpoint_sha256")
                        changed["transaction_commit"].pop("queue_sha256")
                    else:
                        changed.pop("transaction_commit")
                    summary_path.write_text(json.dumps(changed))
                    if damage == "checkpoint_queue_hashes":
                        marker_path.write_text(json.dumps({**good_marker,
                            "summary_sha256": manifest.sha256_file(summary_path)}))
                    else:
                        marker_path.unlink()
                    result = crash_manifest(root)
                    self.assertTrue(result["transaction_integrity"]["required"])
                    self.assertFalse(result["publishable"])
                    self.assertIn("collection_acknowledgement_status_mismatch", result["publication_failures"])
            changed = copy.deepcopy(good_summary)
            for field in fields:
                changed["transaction_commit"].pop(field)
            summary_path.write_text(json.dumps(changed))
            marker_path.write_text(json.dumps({**good_marker,
                "summary_sha256": manifest.sha256_file(summary_path)}))
            (root / "signals.parquet").write_bytes(b"corrupted component")
            self.assertFalse(crash_manifest(root)["publishable"])

    def test_actual_cache_paths_restore_a_complete_committed_planning_parent(self):
        from tools.build_forward_estimate_incremental_universe import build_incremental_universe
        text = (ROOT / ".github" / "workflows" / "earnings_estimates_daily.yml").read_text()

        def cache_paths(step_name):
            step = text.split(f"      - name: {step_name}", 1)[1].split("      - name:", 1)[0]
            return re.search(r"          path: \|\n(.*?)          key:", step, re.S).group(1).split()

        def copy_paths(source, destination, paths):
            for relative in paths:
                origin, target = source / relative, destination / relative
                if not origin.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if origin.is_dir():
                    shutil.copytree(origin, target)
                else:
                    shutil.copy2(origin, target)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture"; fixture.mkdir()
            (fixture / "checkpoint.json").write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "", "selection_count": 0}]}))
            (fixture / "queue.csv").write_text(
                "ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            self.assertEqual(crash_fixture(fixture), 0)
            produced, cache, restored = root / "produced", root / "cache", root / "restored"
            archive = "data_pit/events/earnings_estimates"
            signals = "data_pit/events/earnings_revision_signals.parquet"
            summary = "outputs/earnings_estimates_daily/summary.json"
            queue = "outputs/earnings_estimates_daily/collection_queue.csv"
            (produced / archive).parent.mkdir(parents=True)
            shutil.copytree(fixture / "history", produced / archive)
            shutil.copy2(fixture / "checkpoint.json", produced / archive / "collection_checkpoint.json")
            for origin, relative in ((fixture / "signals.parquet", signals),
                                     (fixture / "summary.json", summary), (fixture / "queue.csv", queue)):
                (produced / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, produced / relative)
            copy_paths(produced, cache, cache_paths("Save earnings estimate archive cache"))
            copy_paths(cache, restored, cache_paths("Restore earnings estimate archive cache"))
            state = manifest.require_verified_collector_state(restored / archive,
                summary_path=restored / summary, checkpoint_path=restored / archive / "collection_checkpoint.json",
                queue_path=restored / queue, signals_path=restored / signals)
            self.assertEqual(state["state"], "accepted")
            coverage = root / "coverage.csv"; coverage.write_text("ticker\nAAA\n__CASH__\n")
            build_incremental_universe(snapshot_dir=str(restored / archive), shard_dir=str(root / "shards"),
                output=str(root / "collector-input.csv"), summary=str(root / "queue-summary.json"),
                coverage_file=str(coverage), latest_run="", canonical_universe=str(restored / archive / "collection_universe.csv"),
                checkpoint=str(restored / archive / "collection_checkpoint.json"), queue_output=str(restored / queue),
                collector_summary=str(restored / summary), signals=str(restored / signals),
                report=str(root / "queue.md"), expected_universe_count=2, as_of_date="2026-07-01")
            planned = json.loads((restored / archive / "collection_checkpoint.json").read_text())
            self.assertEqual(base64.b64decode(planned["planning_parent_transaction"]["checkpoint_bytes_base64"]),
                             (fixture / "checkpoint.json").read_bytes())

    def test_old_incomplete_and_malformed_markers_remain_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.mkdir(exist_ok=True)
            path = root / c.TRANSACTION_MARKER_NAME
            for contents in ("{", "[]", json.dumps({
                "schema_version": c.TRANSACTION_MARKER_SCHEMA,
                "status": "pending", "commit_id": "old-run-before-restart"})):
                path.write_text(contents)
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, "incomplete_collector_transaction"):
                        c.require_complete_collector_transaction(root)
                    self.assertEqual(path.read_text(), contents)

    def test_pre_marker_checkpoint_queue_split_cannot_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checkpoint, queue = root / "checkpoint.json", root / "queue.csv"
            checkpoint.write_text(json.dumps({"ticker_states": [
                {"ticker": "AAA", "last_selected_at_utc": "then", "selection_count": 1}],
                "last_collection_attempt_ack": {"status": "acknowledged", "attempt_id": "old"}}))
            queue.write_text("ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n")
            before = checkpoint.read_bytes(), queue.read_bytes()
            for attempt in ("old", "new"):
                with self.assertRaisesRegex(ValueError, "incomplete_legacy_collector_transaction"):
                    c.prepare_collection_attempt_acknowledgement(checkpoint, queue, ["AAA"],
                        attempted_at_utc="now", attempt_id=attempt)
            from tools.build_forward_estimate_incremental_universe import build_incremental_universe
            with self.assertRaisesRegex(ValueError, "missing_collector_transaction_marker"):
                build_incremental_universe(snapshot_dir=str(root / "history"),
                    checkpoint=str(checkpoint), queue_output=str(queue), shard_dir=str(root / "shards"),
                    output=str(root / "universe.csv"), summary=str(root / "queue-summary.json"))
            self.assertEqual(before, (checkpoint.read_bytes(), queue.read_bytes()))

    def test_success_transaction_publishes_acknowledged_summary_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history = root / 'history'; history.mkdir()
            signal_path = root / 'signals.parquet'
            summary_path = root / 'summary.json'
            checkpoint = root / 'checkpoint.json'
            queue = root / 'queue.csv'
            checkpoint.write_text(json.dumps({'ticker_states': [
                {'ticker': 'AAA', 'last_selected_at_utc': '', 'selection_count': 0}
            ]}), encoding='utf-8')
            queue.write_text(
                'ticker,selected,last_selected_at_utc,selection_count\nAAA,true,,0\n',
                encoding='utf-8')
            fresh = snapshot('2026-07-01T18:00:00Z', 2)
            argv = ['collector', '--tickers', 'AAA', '--api-key', 'fixture',
                    '--fetch-date', '2026-07-01', '--snapshot-dir', str(history),
                    '--signals-output', str(signal_path), '--summary', str(summary_path),
                    '--collection-checkpoint', str(checkpoint), '--collection-queue', str(queue)]
            with patch.object(c, 'collect_live_snapshot',
                              return_value=(pd.DataFrame([fresh]), [], ['AAA'], {})), \
                 patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(c.main(), 0)
            payload = json.loads(summary_path.read_text())
            self.assertEqual(payload['collection_attempt_ack']['status'], 'acknowledged')
            attempt_id = payload['collection_attempt_id']
            self.assertEqual(payload['collection_attempt_ack']['attempt_id'], attempt_id)
            self.assertEqual(json.loads(checkpoint.read_text())
                             ['last_collection_attempt_ack']['attempt_id'], attempt_id)
            self.assertEqual(json.loads(checkpoint.read_text())
                             ['ticker_states'][0]['selection_count'], 1)
            archive_bytes = (history / 'estimates_20260701.parquet').read_bytes()
            signal_bytes = signal_path.read_bytes()
            checkpoint_bytes = checkpoint.read_bytes()
            queue_bytes = queue.read_bytes()
            with patch.object(c, 'collect_live_snapshot',
                              return_value=(pd.DataFrame([fresh]), [], ['AAA'], {})), \
                 patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(c.main(), 0)
            payload2 = json.loads(summary_path.read_text())
            self.assertTrue(payload2['collection_attempt_ack']['idempotent_replay'])
            self.assertEqual((history / 'estimates_20260701.parquet').read_bytes(), archive_bytes)
            self.assertEqual(signal_path.read_bytes(), signal_bytes)
            self.assertEqual(checkpoint.read_bytes(), checkpoint_bytes)
            self.assertEqual(queue.read_bytes(), queue_bytes)


if __name__=='__main__': unittest.main()
