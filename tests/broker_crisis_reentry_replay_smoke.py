#!/usr/bin/env python3
"""Smoke test broker-ledger conversion of crisis re-entry target books."""
from __future__ import annotations

import argparse
import sys
import io
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import redirect_stdout

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_broker_crisis_reentry_replay import run  # noqa: E402
from tools.run_broker_crisis_reentry_replay import render_report  # noqa: E402
from tools import run_broker_crisis_reentry_replay as crisis_runner  # noqa: E402
from tools.run_broker_ledger_replay import REPLAY_GENERATED_ARTIFACTS  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, prices: list[float]) -> None:
    dates = pd.bdate_range("2026-01-01", periods=len(prices))
    frame = pd.DataFrame({"Close": prices, "Adj Close": prices, "Open": prices}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


class BlockedCrisisReportChecks(unittest.TestCase):
    def test_blocked_unknown_or_redacted_status_never_formats_stale_values(self):
        metrics = {"cagr": .1, "sharpe": 1.2, "max_dd": -.05, "avg_cash_weight": .1, "trade_count": 2}
        cases = [{**metrics, "status": status} for status in ("blocked", None, "unknown")]
        cases += [{**metrics, "status": "completed", "metric_mode": "DO_NOT_USE"},
                  {**metrics, "status": "completed", "performance_fields_redacted": True}]
        for data in cases:
            with self.subTest(data=data):
                report = render_report(data)
                self.assertEqual(report.count("N/A"), 5)
                self.assertNotIn("10.00%", report)
                self.assertNotIn("0.00%", report)

    def test_missing_or_nonfinite_report_values_are_unavailable_and_zero_is_valid(self):
        fields = ("cagr", "sharpe", "max_dd", "avg_cash_weight", "trade_count")
        for field in fields:
            for value in (None, True, float("nan"), float("inf")):
                with self.subTest(field=field, value=value):
                    report = render_report({"status": "completed", **dict.fromkeys(fields, 0.), field: value})
                    self.assertIn("N/A", report)
        report = render_report({"status": "completed", **dict.fromkeys(fields, 0.)})
        self.assertNotIn("N/A", report)
        self.assertIn("0.00%", report)


class CrisisCallerLifecycleChecks(unittest.TestCase):
    target_exports=("target_book.csv","target_book_diagnostics.json")

    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.latest=self.root/'latest';self.cache=self.root/'cache';self.out=self.root/'out'
        self.holdings=self.latest/'crisis_reentry_replay/holdings.csv';self.holdings.parent.mkdir(parents=True)
        self.cache.mkdir();_write_price(self.cache,'AAA',[100.,101.,102.,103.,104.,105.,106.,107.])
        self.rows=pd.DataFrame([{'policy_id':'fast_reentry','rebalance_date':'2026-01-02','ticker':'AAA','weight':.7},
                               {'policy_id':'fast_reentry','rebalance_date':'2026-01-05','ticker':'AAA','weight':.4}])
        self.rows.to_csv(self.holdings,index=False)

    def invoke(self, **changes):
        values=dict(latest_run=self.latest,price_cache=self.cache,output_dir=self.out,policy_id='fast_reentry',
                    starting_capital=10000.,fill_mode='next_close',cost_bps=25.)
        values.update(changes);return run(**values)

    def seed_completed(self):
        self.rows.to_csv(self.holdings,index=False)
        self.assertEqual(self.invoke()['status'],'completed')
        self.assertTrue((self.out/'equity_curve.csv').exists())
        self.assertTrue(all((self.out/name).exists() for name in self.target_exports))
        for name in REPLAY_GENERATED_ARTIFACTS:
            if not (self.out/name).exists():(self.out/name).write_bytes(('old-conditional-'+name).encode())
        caller=self.out/'caller-owned.txt';caller.write_bytes(b'caller-owned')
        archive=self.out/'archive';archive.mkdir(exist_ok=True)
        for name in (*REPLAY_GENERATED_ARTIFACTS,*self.target_exports):
            (archive/name).write_bytes(('nested-owned-'+name).encode())

    def check_blocked(self, payload, *, targets_absent=True):
        self.assertEqual(payload['status'],'blocked')
        for name in REPLAY_GENERATED_ARTIFACTS:
            if name not in ('metrics.json','replay_report.md'):
                self.assertFalse((self.out/name).exists(),name)
        if targets_absent:
            for name in self.target_exports:self.assertFalse((self.out/name).exists(),name)
        self.assertEqual(json.loads((self.out/'metrics.json').read_text())['status'],'blocked')
        self.assertIn('N/A',(self.out/'replay_report.md').read_text())
        self.check_preserved()

    def check_preserved(self):
        self.assertEqual((self.out/'caller-owned.txt').read_bytes(),b'caller-owned')
        for name in (*REPLAY_GENERATED_ARTIFACTS,*self.target_exports):
            self.assertEqual((self.out/'archive'/name).read_bytes(),('nested-owned-'+name).encode())

    def test_all_actual_early_input_failures_clear_native_and_wrapper_exports(self):
        cases=('missing_holdings','missing_policy','empty_holdings','missing_policy_column',
               'missing_rebalance_date','missing_ticker','missing_weight','empty_file','invalid_utf8','malformed_csv')
        for case in cases:
            with self.subTest(case=case):
                self.seed_completed();original_input=self.holdings.read_bytes();values={}
                if case=='missing_holdings':self.holdings.rename(self.root/('retired-'+case))
                elif case=='missing_policy':values['policy_id']='absent_policy'
                elif case=='empty_holdings':self.rows.iloc[:0].to_csv(self.holdings,index=False)
                elif case=='missing_policy_column':self.rows.drop(columns=['policy_id']).to_csv(self.holdings,index=False)
                elif case.startswith('missing_'):self.rows.drop(columns=[case[len('missing_'):]]).to_csv(self.holdings,index=False)
                elif case=='empty_file':self.holdings.write_bytes(b'')
                elif case=='invalid_utf8':self.holdings.write_bytes(b'\xff\xfe\xfd')
                else:self.holdings.write_bytes(b'policy_id,rebalance_date,ticker,weight\n"unterminated')
                current_input=self.holdings.read_bytes() if self.holdings.exists() else None
                with patch.object(crisis_runner,'broker_replay',side_effect=AssertionError('must not replay early failure')):
                    payload=self.invoke(**values)
                self.check_blocked(payload)
                self.assertEqual(self.holdings.read_bytes() if self.holdings.exists() else None,current_input)
                if case=='missing_holdings':self.assertEqual((self.root/('retired-'+case)).read_bytes(),original_input)

    def test_early_failure_cannot_retain_either_wrapper_target_export(self):
        self.seed_completed()
        before={name:(self.out/name).read_bytes() for name in self.target_exports}
        payload=self.invoke(policy_id='absent_policy');self.assertEqual(payload['status'],'blocked')
        for name in self.target_exports:
            with self.subTest(export=name):
                self.assertFalse((self.out/name).exists(),name+' survived with prior bytes='+str(
                    (self.out/name).exists() and (self.out/name).read_bytes()==before[name]))

    def test_partially_written_target_exports_are_invalidated_on_build_failure(self):
        self.seed_completed();before=self.holdings.read_bytes()
        original=crisis_runner.write_json
        def failed_diagnostic(path,payload):
            if path.name=='target_book_diagnostics.json':raise ValueError('synthetic diagnostic write failure')
            return original(path,payload)
        with patch.object(crisis_runner,'write_json',side_effect=failed_diagnostic):payload=self.invoke()
        self.check_blocked(payload);self.assertEqual(self.holdings.read_bytes(),before)
        self.seed_completed()
        def failed_builder(*_args):
            for name in self.target_exports:(self.out/name).write_bytes(b'partially current')
            raise ValueError('synthetic late target preparation failure')
        with patch.object(crisis_runner,'build_target_book',side_effect=failed_builder):payload=self.invoke()
        self.check_blocked(payload)

    def test_completed_retry_refreshes_targets_and_preserves_inputs_archives(self):
        self.seed_completed();before=self.holdings.read_bytes()
        payload=self.invoke()
        self.assertEqual(payload['status'],'completed');self.assertEqual(payload['metric_mode'],'broker_ledger_next_close')
        self.assertEqual(self.holdings.read_bytes(),before)
        self.assertEqual(len(pd.read_csv(self.out/'target_book.csv')),2)
        self.assertEqual(json.loads((self.out/'target_book_diagnostics.json').read_text())['rows'],2)
        self.assertFalse((self.out/'reserve_reason_audit.json').exists())
        self.check_preserved()

    def test_early_blocked_cli_replaces_previous_evidence_and_keeps_failure_exit(self):
        self.seed_completed();self.holdings.unlink()
        command=[sys.executable,*(['-O'] if not __debug__ else []),str(REPO_ROOT/'tools/run_broker_crisis_reentry_replay.py'),
                 '--latest-run',str(self.latest),'--price-cache',str(self.cache),'--output-dir',str(self.out)]
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,1,result.stderr)
        self.check_blocked(json.loads(result.stdout))


class CrisisInputPreservationChecks(unittest.TestCase):
    setUp = CrisisCallerLifecycleChecks.setUp
    invoke = CrisisCallerLifecycleChecks.invoke
    names = (*REPLAY_GENERATED_ARTIFACTS, *CrisisCallerLifecycleChecks.target_exports)

    def test_fixed_holdings_alias_to_all_known_exports_blocks_and_preserves_input(self):
        self.out.mkdir()
        self.holdings.unlink()
        for mode in ("next_close", "next_open", "same_close"):
            for name in self.names:
                with self.subTest(mode=mode, name=name):
                    if self.holdings.is_symlink(): self.holdings.unlink()
                    backing = self.out / name; self.rows.to_csv(backing, index=False); before = backing.read_bytes()
                    self.holdings.symlink_to(backing)
                    for other in self.names:
                        if other != name: (self.out / other).write_bytes(b"old successful export")
                    with patch.object(crisis_runner, "build_target_book", side_effect=AssertionError("must not build")):
                        payload = self.invoke(fill_mode=mode)
                    self.assertEqual(payload["status"], "blocked")
                    self.assertEqual(payload["reason"], "caller_input_collides_with_replay_output")
                    self.assertEqual(backing.read_bytes(), before); self.assertTrue(self.holdings.is_symlink())
                    for other in self.names:
                        if other not in (name, "metrics.json", "replay_report.md"):
                            self.assertFalse((self.out / other).exists(), other)
                    args = argparse.Namespace(latest_run=str(self.latest), price_cache=str(self.cache), output_dir=str(self.out),
                        policy_id="fast_reentry", starting_capital=10000., fill_mode=mode, cost_bps=25.,
                        no_integer_shares=False, max_fill_lag_days=7)
                    with patch.object(crisis_runner, "parse_args", return_value=args), redirect_stdout(io.StringIO()):
                        self.assertNotEqual(crisis_runner.main(), 0)
                    self.assertEqual(backing.read_bytes(), before); self.holdings.unlink()

    def test_disjoint_source_and_nested_archive_remain_completed(self):
        before = self.holdings.read_bytes(); archive = self.out / "archive"; archive.mkdir(parents=True)
        for name in self.names: (archive / name).write_bytes(b"archive")
        self.assertEqual(self.invoke()["status"], "completed")
        self.assertEqual(self.holdings.read_bytes(), before)
        for name in self.names: self.assertEqual((archive / name).read_bytes(), b"archive")


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        crisis = latest / "crisis_reentry_replay"
        crisis.mkdir(parents=True)
        pd.DataFrame(
            [
                {"policy_id": "fast_reentry", "rebalance_date": "2026-01-01", "ticker": "AAA", "weight": 0.70},
                {"policy_id": "fast_reentry", "rebalance_date": "2026-01-01", "ticker": "CASH", "weight": 0.30},
                {"policy_id": "fast_reentry", "rebalance_date": "2026-01-08", "ticker": "AAA", "weight": 0.90},
                {"policy_id": "fast_reentry", "rebalance_date": "2026-01-08", "ticker": "CASH", "weight": 0.10},
                {"policy_id": "other", "rebalance_date": "2026-01-01", "ticker": "BBB", "weight": 1.00},
            ]
        ).to_csv(crisis / "holdings.csv", index=False)

        cache = root / "cache_prices"
        cache.mkdir()
        _write_price(cache, "AAA", [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111])

        out = root / "out"
        metrics = run(
            latest_run=latest,
            price_cache=cache,
            output_dir=out,
            policy_id="fast_reentry",
            cost_bps=0.0,
        )
        assert metrics["status"] == "completed", metrics
        assert metrics["metric_mode"] == "broker_ledger_next_close", metrics
        assert metrics["candidate_id"] == "main_broker_crisis_reentry_fast_reentry", metrics
        assert metrics["target_book_months"] == 2, metrics
        target = pd.read_csv(out / "target_book.csv")
        assert set(target["policy_id"]) == {"fast_reentry"}
        assert (out / "trades.csv").exists()
        assert (out / "equity_curve.csv").exists()
    if not unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(
            unittest.defaultTestLoader.loadTestsFromTestCase(cls)
            for cls in (BlockedCrisisReportChecks,CrisisCallerLifecycleChecks,CrisisInputPreservationChecks))).wasSuccessful():
        return 1
    print("broker_crisis_reentry_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
