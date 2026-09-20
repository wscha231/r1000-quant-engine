"""Offline counterexamples at current-score and after-close consumer boundaries."""
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import sys
import tempfile
import types
import subprocess
import contextlib
import io
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import r1000_legacy_input_guard as guard
import r1000_unified_universe as bridge

NOW = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)


def scores():
    return pd.DataFrame([dict(ticker='AAPL', score=1.0, score_source='model', current_price_live=100.0,
        rebalance_date='2026-09-18', valuation_price_cutoff_date='2026-09-18',
        feature_available_from='2026-09-18T20:00:00Z',
        score_available_from='2026-09-18T20:01:00Z', ranking_eligible=True)])


def write_packet(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame=scores();frame['input_packet_kind']='unified_bridge_v1'
    frame.to_csv(path,index=False)
    receipt={'status':'LEGACY_COMPATIBILITY_ONLY','compatible_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    Path(str(path)+'.coverage.json').write_text(json.dumps(receipt))


class CurrentInputTests(unittest.TestCase):
    def reject(self, frame, pattern=None, **kwargs):
        with self.assertRaisesRegex(guard.InputIntegrityError, pattern or '.'):
            guard.validate_current_frame(frame, now=NOW, **kwargs)

    def test_current_rows_pass_without_approval_fields(self):
        result = guard.validate_current_frame(scores(), now=NOW)
        self.assertEqual(result['score'].tolist(), [1])
        self.assertNotIn('investment_approved', result)

    def test_stale_scores_even_with_current_price(self):
        frame=scores();frame['rebalance_date']='2026-07-13';self.reject(frame, 'date')

    def test_stale_price_even_with_current_score(self):
        frame=scores();frame['valuation_price_cutoff_date']='2026-08-24';self.reject(frame, 'date')

    def test_extra_conflicting_score_date_rejected(self):
        frame=scores();frame['score_date']='2026-07-13';self.reject(frame, 'date')

    def test_future_dates_rejected(self):
        frame=scores();frame['rebalance_date']='2026-09-21';self.reject(frame, 'date')

    def test_missing_dates_not_inferred_from_other_fields(self):
        for field in ['rebalance_date', 'valuation_price_cutoff_date', 'feature_available_from']:
            with self.subTest(field=field): self.reject(scores().drop(columns=field))

    def test_naive_invalid_future_or_old_availability_rejected(self):
        for value in ['2026-09-18T20:00:00', None, 'bad', '2026-09-21T20:00:00Z', '2026-09-17T20:00:00Z']:
            with self.subTest(value=value):
                frame=scores();frame['feature_available_from']=value;self.reject(frame)

    def test_missing_or_invalid_score_availability_rejected(self):
        self.reject(scores().drop(columns='score_available_from'), 'score_available_from_required')
        for value in [None, 'bad', '2026-09-18T20:01:00', '2026-09-21T00:00:00Z', '2026-09-18T19:59:00Z']:
            with self.subTest(value=value):
                frame=scores();frame['score_available_from']=value;self.reject(frame)

    def test_score_cannot_predate_its_features(self):
        frame=scores();frame['feature_available_from']='2026-09-18T20:02:00Z'
        self.reject(frame, 'score_not_available')

    def test_synthetic_source_cannot_be_laundered(self):
        for value in [' Finnhub_SYNTHETIC ', 'UNSCORED_INVENTORY', 'legacy_model_source_unverified', None]:
            with self.subTest(value=value):
                frame=scores();frame['score_source']=value;self.reject(frame)

    def test_false_upstream_flag_blocks(self):
        for value in [False, None, 1, 'false']:
            with self.subTest(value=value):
                frame=scores();frame['ranking_eligible']=value;self.reject(frame)

    def test_unapproved_valuation_or_split_quarantine_blocks(self):
        for field, value in [('valuation_approved',False),('corporate_action_quarantine',True),('corporate_action_quarantine',None)]:
            with self.subTest(field=field,value=value):
                frame=scores();frame[field]=value;self.reject(frame)

    def test_invalid_missing_or_conflicting_prices_block(self):
        self.reject(scores().drop(columns='current_price_live'))
        for value in [0,-1,None,True,float('inf')]:
            with self.subTest(value=value):
                frame=scores();frame['current_price_live']=value;self.reject(frame)
        frame=scores();frame['px']=200;self.reject(frame,'conflicting_current_prices')

    def test_nan_inf_bool_scores_not_numbers(self):
        for value in [None, float('inf'), float('-inf'), True]:
            with self.subTest(value=value):
                frame=scores();frame['score']=value;self.reject(frame)

    def test_duplicate_casefolded_ticker_blocks_packet(self):
        frame=pd.concat([scores(),scores()], ignore_index=True);frame.loc[1,'ticker']=' aapl '
        self.reject(frame, 'duplicate')

    def test_empty_packet_blocks(self): self.reject(scores().iloc[:0])

    def test_zero_real_score_preserved(self):
        frame=scores();frame['score']=0
        self.assertEqual(guard.validate_current_frame(frame, now=NOW)['score'].iloc[0],0)

    def test_weekend_holiday_preclose_and_early_close_calendar(self):
        cases=[('2026-09-20T01:00Z','2026-09-18'), ('2026-09-07T23:00Z','2026-09-04'),
               ('2026-09-18T19:59Z','2026-09-17'), ('2026-11-27T17:59Z','2026-11-25'),
               ('2026-11-27T18:00Z','2026-11-27')]
        for now, expected in cases:
            with self.subTest(now=now): self.assertEqual(guard.latest_completed_close(now)[0],expected)

    def test_target_requires_current_observation_and_valid_weights(self):
        frame=scores();frame['weight']=1
        self.assertEqual(len(guard.validate_current_frame(frame, kind='targets',now=NOW)),1)
        for value in [-0.1, float('nan'), 1.2, 0, True]:
            with self.subTest(value=value):
                frame['weight']=value;self.reject(frame,kind='targets')

    def test_conflicting_weight_fields_block(self):
        frame=scores();frame['weight']=0.2;frame['proposed_weight']=0.8
        self.reject(frame,'conflicting',kind='targets')

    def test_blocked_coverage_vetoes_even_current_retained_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scores.csv';scores().to_csv(path,index=False)
            Path(str(path)+'.coverage.json').write_text(json.dumps({'status':'BLOCKED_MISSING_MODEL_COVERAGE'}))
            with self.assertRaisesRegex(guard.InputIntegrityError,'blocked_coverage'):
                guard.load_current_csv(path,now=NOW)

    def test_coverage_must_bind_exact_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scores.csv';scores().to_csv(path,index=False)
            receipt={'status':'LEGACY_COMPATIBILITY_ONLY','compatible_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            Path(str(path)+'.coverage.json').write_text(json.dumps(receipt))
            self.assertEqual(len(guard.load_current_csv(path,now=NOW)),1)
            path.write_bytes(path.read_bytes()+b'\n')
            with self.assertRaisesRegex(guard.InputIntegrityError,'hash_mismatch'):
                guard.load_current_csv(path,now=NOW)

    def test_missing_receipt_requires_explicit_legacy_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'scores.csv';scores().to_csv(path,index=False)
            with self.assertRaisesRegex(guard.InputIntegrityError,'coverage_receipt_required'):
                guard.load_current_csv(path,now=NOW)
            self.assertEqual(len(guard.load_current_csv(path,now=NOW,receipt_policy='legacy_source')),1)
            frame=scores();frame['rebalance_date']='2026-07-13';frame.to_csv(path,index=False)
            with self.assertRaisesRegex(guard.InputIntegrityError,'date'):
                guard.load_current_csv(path,now=NOW,receipt_policy='legacy_source')

    def test_named_or_renamed_bridge_cannot_use_legacy_exemption(self):
        with tempfile.TemporaryDirectory() as folder:
            for name, marked in [('scored_unified.csv',False),('20260918.csv',True)]:
                with self.subTest(name=name):
                    path=Path(folder)/name;frame=scores()
                    if marked: frame['input_packet_kind']='unified_bridge_v1'
                    frame.to_csv(path,index=False)
                    with self.assertRaisesRegex(guard.InputIntegrityError,'coverage_receipt_required'):
                        guard.load_current_csv(path,now=NOW,receipt_policy='legacy_source')

    def test_workflow_publication_keeps_csv_and_receipt_together(self):
        import yaml
        workflow=yaml.safe_load((ROOT/'.github/workflows/unified_monthly.yml').read_text())
        steps={step.get('name'):step for step in workflow['jobs']['unify']['steps']}
        paths=steps['Upload unified artifact']['with']['path'].split()
        self.assertIn('outputs/scored_unified.csv',paths)
        self.assertIn('outputs/scored_unified.csv.coverage.json',paths)
        self.assertIn("load_current_csv('outputs/scored_unified.csv')",steps['Run validation after unify']['run'])
        commit=steps['Commit unified CSV + snapshot']['run']
        self.assertIn('cp outputs/scored_unified.csv.coverage.json "$SNAPSHOT.coverage.json"',commit)
        self.assertIn('git add -f outputs/scored_unified.csv outputs/scored_unified.csv.coverage.json "$SNAPSHOT" "$SNAPSHOT.coverage.json"',commit)
        self.assertNotIn('git push || true',commit)
        rebuild=(ROOT/'.github/workflows/full_rebuild_manual.yml').read_text()
        self.assertIn('cp outputs/scored_unified.csv.coverage.json "$DEST/"',rebuild)
        self.assertIn('"$DEST/scored_unified.csv"',rebuild)

    def test_copy_bridge_packet_preserves_bytes_and_invalidates_interrupted_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.csv';dest=Path(folder)/'dest.csv';write_packet(source)
            guard.copy_bridge_packet(source,dest)
            self.assertEqual(source.read_bytes(),dest.read_bytes())
            self.assertEqual(len(guard.load_current_csv(dest,now=NOW)),1)
            original=guard._atomic_packet_bytes
            def interrupted(path,raw):
                if Path(path)==dest: raise OSError('simulated interrupted transport')
                return original(path,raw)
            with patch.object(guard,'_atomic_packet_bytes',side_effect=interrupted):
                with self.assertRaises(OSError): guard.copy_bridge_packet(source,dest)
            with self.assertRaisesRegex(guard.InputIntegrityError,'blocked_coverage'):
                guard.load_current_csv(dest,now=NOW)

    def test_local_drive_transport_round_trip(self):
        from tools import sync_cloud_to_drive as sync
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'cloud_results/full_rebuild/latest_r1000/scored_unified.csv'
            write_packet(source);destination=root/'drive'
            with patch.object(sync,'ROOT',root), patch.object(sys,'argv',['sync','--mode','r1000','--drive-base',str(destination)]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(sync.main(),0)
            result=destination/'outputs/scored_unified.csv'
            self.assertEqual(result.read_bytes(),source.read_bytes())
            self.assertEqual(len(guard.load_current_csv(result,now=NOW)),1)

    def test_local_drive_transport_fails_before_unrelated_copies(self):
        from tools import sync_cloud_to_drive as sync
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'cloud_results/full_rebuild/latest_r1000/scored_unified.csv'
            write_packet(source);Path(str(source)+'.coverage.json').unlink()
            (source.parent/'portfolio_latest.csv').write_text('should not copy')
            destination=root/'drive'
            with patch.object(sync,'ROOT',root), patch.object(sys,'argv',['sync','--mode','r1000','--drive-base',str(destination)]), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(guard.InputIntegrityError,'coverage_receipt_required'): sync.main()
            self.assertFalse((destination/'outputs/portfolio_latest.csv').exists())

    def test_manifest_transport_requires_valid_packet_members(self):
        from tools import build_gdrive_sync_manifest as manifest
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'scored_unified.csv';write_packet(source)
            args=types.SimpleNamespace(latest_run=str(root),mode='research',run_id='fixture',safe_branch='fixture')
            entries=manifest.build_entries(args)
            packet=[r for r in entries if r['relative_source'].startswith('scored_unified.csv')]
            self.assertEqual(len(packet),2)
            self.assertTrue(all(r['required'] and r['exists'] and not r['production_valid'] for r in packet))
            source.write_bytes(source.read_bytes()+b'\n')
            with self.assertRaisesRegex(guard.InputIntegrityError,'hash_mismatch'): manifest.build_entries(args)

    def test_disabled_daily_step_is_successful_no_action_diagnostic(self):
        import yaml
        workflow=yaml.safe_load((ROOT/'.github/workflows/after_close_daily.yml').read_text())
        step=next(s for job in workflow['jobs'].values() for s in job['steps'] if s.get('name')=='Layer 4 disabled diagnostic')
        self.assertNotIn('r1000_layer4_swap.py',step['run'])
        with tempfile.TemporaryDirectory() as folder:
            result=subprocess.run(['bash','-e','-o','pipefail','-c',step['run']],cwd=folder,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            packet=json.loads((Path(folder)/'outputs/paper_runs/layer4_disabled.json').read_text())
            self.assertEqual(packet,{'status':'DISABLED','reason':'RS_ONLY_SWAP_DISABLED','swap_suggestions':[]})

    def test_explicit_publication_stages_ignored_packet_pair(self):
        import yaml, os
        workflow=yaml.safe_load((ROOT/'.github/workflows/unified_monthly.yml').read_text())
        commit=next(s['run'] for s in workflow['jobs']['unify']['steps'] if s.get('name')=='Commit unified CSV + snapshot')
        add=next(line for line in commit.splitlines() if line.startswith('git add '))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            subprocess.run(['git','init','-q'],cwd=root,check=True)
            (root/'.gitignore').write_text('outputs/\ncloud_results/\n')
            write_packet(root/'outputs/scored_unified.csv');write_packet(root/'cloud_results/unified/fixture.csv')
            (root/'outputs/unrelated.txt').write_text('do not stage')
            env=dict(os.environ,SNAPSHOT='cloud_results/unified/fixture.csv')
            subprocess.run(['bash','-e','-c',add],cwd=root,env=env,check=True,capture_output=True)
            staged=subprocess.check_output(['git','diff','--cached','--name-only'],cwd=root,text=True).splitlines()
            self.assertEqual(len(staged),4)
            self.assertNotIn('outputs/unrelated.txt',staged)

    def test_historical_membership_union_is_not_current_universe(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'scores.csv';scores().to_csv(source,index=False)
            universe=types.ModuleType('aggressive.universe')
            universe.load_universe=lambda _: (['T'+str(i) for i in range(1200)],{'source_used':'main_engine_cache'})
            features=types.ModuleType('aggressive.finnhub_cache_loader')
            features.load_finnhub_features_dict=lambda: self.fail('archive union must be rejected before features')
            with patch.dict(sys.modules,{'aggressive.universe':universe,'aggressive.finnhub_cache_loader':features}):
                with self.assertRaisesRegex(bridge.IncompleteUniverseError,'universe_coverage'):
                    bridge.build_unified_scored(source,Path(folder)/'out.csv')

    def test_bridge_full_coverage_stale_scores_still_block(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.csv';out=Path(folder)/'out.csv'
            frame=pd.concat([scores()]*1000,ignore_index=True)
            frame['ticker']=['T'+str(i) for i in range(1000)]
            frame['rebalance_date']='2026-07-13';frame.to_csv(source,index=False);out.write_text('preserve')
            universe=types.ModuleType('aggressive.universe')
            universe.load_universe=lambda _: (frame['ticker'].tolist(),{'source_used':'iwb_live'})
            features=types.ModuleType('aggressive.finnhub_cache_loader');features.load_finnhub_features_dict=lambda: {}
            with patch.dict(sys.modules,{'aggressive.universe':universe,'aggressive.finnhub_cache_loader':features}):
                with self.assertRaises(bridge.IncompleteUniverseError): bridge.build_unified_scored(source,out)
            self.assertEqual(out.read_text(),'preserve')
            self.assertEqual(json.loads(Path(str(out)+'.coverage.json').read_text())['status'],'BLOCKED_INPUT_INTEGRITY')

    def test_complete_current_bridge_writes_hash_bound_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.csv';out=Path(folder)/'out.csv'
            frame=pd.concat([scores()]*1000,ignore_index=True);frame['ticker']=['T'+str(i) for i in range(1000)]
            frame.to_csv(source,index=False)
            universe=types.ModuleType('aggressive.universe')
            universe.load_universe=lambda _: (frame['ticker'].tolist(),{'source_used':'iwb_live'})
            features=types.ModuleType('aggressive.finnhub_cache_loader');features.load_finnhub_features_dict=lambda: {}
            with patch.dict(sys.modules,{'aggressive.universe':universe,'aggressive.finnhub_cache_loader':features}), patch.object(
                    bridge,'validate_current_frame',side_effect=lambda f: guard.validate_current_frame(f,now=NOW)):
                bridge.build_unified_scored(source,out,verbose=False)
            self.assertEqual(len(guard.load_current_csv(out,now=NOW)),1000)
            receipt=json.loads(Path(str(out)+'.coverage.json').read_text())
            self.assertFalse(receipt['investment_approved'])

    def test_failed_build_invalidates_old_success_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'out.csv';out.write_text('preserve')
            Path(str(out)+'.coverage.json').write_text('{"status":"LEGACY_COMPATIBILITY_ONLY"}')
            universe=types.ModuleType('aggressive.universe');universe.load_universe=lambda _: self.fail('not reached')
            features=types.ModuleType('aggressive.finnhub_cache_loader');features.load_finnhub_features_dict=lambda: {}
            with patch.dict(sys.modules,{'aggressive.universe':universe,'aggressive.finnhub_cache_loader':features}):
                with self.assertRaises(FileNotFoundError): bridge.build_unified_scored(Path(folder)/'absent.csv',out)
            self.assertEqual(out.read_text(),'preserve')
            self.assertEqual(json.loads(Path(str(out)+'.coverage.json').read_text())['status'],'BLOCKED_BUILD_IN_PROGRESS')

    def test_first_existing_stale_target_not_replaced_by_fallback(self):
        # Broker calls are forbidden in this offline loader integration test.
        broker=types.ModuleType('aggressive.executor')
        for name in ('_existing_positions','_fetch_account_snapshot','_get_trading_client',
                     '_place_limit_buy','_place_market_sell'):
            setattr(broker,name,lambda *a, **kw: self.fail('broker reached'))
        telegram=types.ModuleType('aggressive.telegram_alert')
        telegram.send_alert=lambda *a, **kw: self.fail('message reached')
        with patch.dict(sys.modules, {'aggressive.executor':broker,'aggressive.telegram_alert':telegram}):
            import r1000_paper_executor as executor
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old.csv';frame=scores();frame['weight']=1;frame['rebalance_date']='2026-07-13';frame.to_csv(path,index=False)
            with patch.object(executor,'ADVISOR_PATHS',{'core':[str(path)]}):
                with self.assertRaises(guard.InputIntegrityError): executor.load_advisor_picks('core')

    def test_rs_only_swap_produces_no_action(self):
        import r1000_layer4_swap as swap
        with patch.object(swap,'build_candidate_pool',side_effect=AssertionError('should not rank')):
            result=swap.layer4_swap_suggestions('unused','unused')
        self.assertIn('RS_ONLY_SWAP_DISABLED',result[0]['error'])
        self.assertTrue(all('swap_to' not in row for row in result))

    def test_layer4_cli_reports_blocked_and_nonzero(self):
        import r1000_layer4_swap as swap
        with patch.object(sys,'argv',['layer4','--json']): self.assertEqual(swap.main(),2)

    def test_bridge_bool_score_rejected(self):
        _, summary, valid=bridge.reconcile_inventory(pd.DataFrame({'ticker':['A'],'score':[True]}),['A'])
        self.assertEqual(summary['unscored_securities'],1);self.assertTrue(valid.empty)

    def test_all_legacy_cli_score_loaders_use_shared_guard(self):
        for name in ('r1000_rebalance_advisor.py','r1000_rebalance_advisor_v3.py','r1000_rebalance_advisor_v4.py'):
            source=(ROOT/name).read_text()
            self.assertIn('load_current_csv(args.scored_csv',source)
            self.assertNotIn('pd.read_csv(args.scored_csv)',source)


if __name__ == '__main__': unittest.main()
