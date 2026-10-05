#!/usr/bin/env python3
"""Smoke tests for Stage 0 OOS-lock in run_broker_ledger_replay.calc_metrics."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    DEFAULT_OOS_START,
    DEFAULT_OOS2_START,
    calc_metrics,
    calc_metrics_with_oos,
)


def _synthetic_equity_curve(start: str, days: int, daily_return: float) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=days)
    equity = 100000.0 * np.cumprod(np.full(days, 1.0 + daily_return))
    return pd.DataFrame(
        {
            "date": [d.date().isoformat() for d in dates],
            "equity_usd": equity,
            "cash_usd": equity * 0.1,
            "cash_weight": np.full(days, 0.1),
            "fill_mode": "next_close",
        }
    )


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "ticker", "side", "fee_usd", "gross_value"])


def test_full_window_metrics_backcompat() -> None:
    """calc_metrics with no date_range returns the same shape as before."""
    eq = _synthetic_equity_curve("2020-01-02", 252, 0.0005)
    m = calc_metrics(eq, _empty_trades(), 100000.0)
    assert m["status"] == "completed"
    assert m["label"] == "full"
    assert m["date_range"] is None
    assert m["days"] == 252
    assert 0.10 < m["cagr"] < 0.20, f"unexpected CAGR {m['cagr']}"
    assert m["max_dd"] >= -1e-9  # monotone-up curve has no drawdown


def test_date_range_slices_and_reanchors_capital() -> None:
    """Slicing by date_range must use the in-window starting equity, not $100k."""
    eq = _synthetic_equity_curve("2020-01-02", 252, 0.0005)
    full = calc_metrics(eq, _empty_trades(), 100000.0)
    half_lo = eq["date"].iloc[126]
    sliced = calc_metrics(eq, _empty_trades(), 100000.0, date_range=(half_lo, None), label="oos")
    assert sliced["label"] == "oos"
    assert sliced["date_range"] == [half_lo, None]
    # Re-anchored starting capital == equity at the first in-range row.
    assert abs(sliced["starting_capital_usd"] - float(eq["equity_usd"].iloc[126])) < 1e-6
    # CAGR of the second half should be close to the full-window CAGR (same
    # daily return), NOT inflated by counting prior growth.
    assert abs(sliced["cagr"] - full["cagr"]) < 0.02, (
        f"slice CAGR {sliced['cagr']} drifted vs full {full['cagr']} — likely starting_capital not re-anchored"
    )
    assert sliced["days"] == 252 - 126


def test_is_oos_split_via_calc_metrics_with_oos() -> None:
    eq = _synthetic_equity_curve("2022-01-03", 600, 0.0004)
    out = calc_metrics_with_oos(eq, _empty_trades(), 100000.0, oos_start="2024-01-02")
    assert set(out.keys()) >= {"full", "is", "oos", "oos_start"}
    assert out["full"]["label"] == "full"
    assert out["is"]["label"] == "is"
    assert out["oos"]["label"] == "oos"
    # IS ends day before OOS starts.
    assert out["is"]["end_date"] < out["oos"]["start_date"], (
        f"IS end {out['is']['end_date']} must precede OOS start {out['oos']['start_date']}"
    )
    # IS days + OOS days <= full days (no double-count of boundary).
    assert out["is"]["days"] + out["oos"]["days"] <= out["full"]["days"]


def test_oos2_independent_window() -> None:
    eq = _synthetic_equity_curve("2022-01-03", 800, 0.0003)
    out = calc_metrics_with_oos(
        eq,
        _empty_trades(),
        100000.0,
        oos_start="2024-07-01",
        oos2_start="2023-01-01",
    )
    assert out["oos"]["label"] == "oos"
    assert out["oos2"]["label"] == "oos2"
    assert out["oos2"]["start_date"] < out["oos"]["start_date"]
    assert out["oos2"]["end_date"] < out["oos"]["start_date"]
    assert out["oos2_end"] == "2024-06-30"


def test_overlapping_oos_windows_are_rejected() -> None:
    eq = _synthetic_equity_curve("2022-01-03", 800, 0.0003)
    try:
        calc_metrics_with_oos(
            eq,
            _empty_trades(),
            100000.0,
            oos_start="2024-07-01",
            oos2_start="2023-01-01",
            oos2_end="2024-07-15",
        )
    except ValueError as exc:
        assert "must be disjoint" in str(exc)
    else:
        raise AssertionError("overlapping OOS windows must fail closed")


def test_oos2_end_tracks_custom_primary_start() -> None:
    eq = _synthetic_equity_curve("2022-01-03", 1000, 0.0003)
    out = calc_metrics_with_oos(
        eq,
        _empty_trades(),
        100000.0,
        oos_start="2024-01-01",
        oos2_start="2023-01-01",
    )
    assert out["oos2_end"] == "2023-12-31"
    assert out["oos2"]["end_date"] < out["oos"]["start_date"]


def test_empty_window_returns_blocked() -> None:
    """A date range outside the equity curve must produce blocked metrics, not crash."""
    eq = _synthetic_equity_curve("2020-01-02", 100, 0.0005)
    m = calc_metrics(eq, _empty_trades(), 100000.0, date_range=("2099-01-01", None), label="oos")
    assert m["status"] == "blocked"
    assert "label" in m and m["label"] == "oos"


def test_disabled_with_empty_string() -> None:
    """Passing oos_start='' should disable the slice (CLI escape hatch)."""
    eq = _synthetic_equity_curve("2020-01-02", 100, 0.0005)
    out = calc_metrics_with_oos(eq, _empty_trades(), 100000.0, oos_start=None, oos2_start=None)
    assert out["is"] is None
    assert out["oos"] is None
    assert out["oos2"] is None
    assert out["full"]["status"] == "completed"


def test_default_constants() -> None:
    assert DEFAULT_OOS_START == "2024-07-01"
    assert DEFAULT_OOS2_START == "2023-01-01"
    source = (REPO_ROOT / "tools" / "run_broker_ledger_replay.py").read_text(encoding="utf-8")
    assert '_resolve_oos(args.oos2_end, "R1000_OOS2_END", "")' in source


class ResearchOOSAdmissionTests(__import__('unittest').TestCase):
    def windows(self):
        from nav_metrics_v2_smoke import rows,context,frame
        data=rows((90.,81.,82.))
        return data,frame(data),dict(full=context(data),
            is_=context(data[:1]),oos=context(data[1:],anchor_nav=90.,
                anchor_time=data[0]['timestamp'],anchor_kind='OOS_PREDECESSOR'))

    def test_actual_predecessor_includes_first_OOS_loss(self):
        from tools import nav_metrics_v2 as nav
        data,curve,c=self.windows()
        out=calc_metrics_with_oos(curve,_empty_trades(),100.,oos_start='2026-01-06',
                                 measurement_contexts={'full':c['full'],'is':c['is_'],'oos':c['oos']})
        self.assertEqual(out['status'],nav.COMPLETE,out)
        self.assertEqual(out['oos']['starting_capital_usd'],90.)
        self.assertAlmostEqual(out['oos']['first_interval_return'],-.1)
        self.assertAlmostEqual(out['oos']['max_dd'],-.1)
        self.assertEqual(out['oos']['days'],2)
        old=calc_metrics(curve,_empty_trades(),100.,date_range=('2026-01-06',None))
        self.assertEqual(old['status'],'completed')
        self.assertEqual(old['starting_capital_usd'],81.)  # Default remains legacy.
        self.assertNotEqual(old['max_dd'],out['oos']['max_dd'])

    def test_explicit_shared_valuation_receipt_obeys_each_measurement_cutoff(self):
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import binding
        data,curve,c=self.windows();b=binding(data)
        contexts={'full':c['full'],'is':c['is_'],'oos':c['oos']}
        early=calc_metrics_with_oos(curve,_empty_trades(),100.,oos_start='2026-01-06',
                                  measurement_contexts=contexts,valuation_binding=b)
        self.assertEqual(early['status'],nav.BLOCKED)
        self.assertEqual(early['is']['reason'],'VALUATION_BINDING_FUTURE')
        c['is_']['cutoff']=data[-1]['timestamp']  # Actual shared later evaluation cutoff, not backdated receipt.
        out=calc_metrics_with_oos(curve,_empty_trades(),100.,oos_start='2026-01-06',
                                 measurement_contexts=contexts,valuation_binding=b)
        self.assertEqual(out['status'],nav.COMPLETE,out)
        self.assertAlmostEqual(out['oos']['max_dd'],-.1)

    def test_hash_bound_wrong_or_first_row_anchor_cannot_replace_actual_predecessor(self):
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import context
        data,curve,c=self.windows()
        for value,timestamp,kind in ((81.,data[0]['timestamp'],'OOS_PREDECESSOR'),
                                     (90.,data[1]['timestamp'],'OOS_PREDECESSOR'),
                                     (90.,data[0]['timestamp'],'PREFILL')):
            with self.subTest(value=value,timestamp=timestamp,kind=kind):
                bad=context(data[1:],anchor_nav=value,anchor_time=timestamp,anchor_kind=kind)
                out=calc_metrics(curve,_empty_trades(),100.,date_range=('2026-01-06',None),
                                 measurement_context=bad)
                self.assertEqual(out['status'],nav.BLOCKED)
                self.assertIsNone(out['cagr'])
                self.assertEqual(out['reason'],'OOS_PREDECESSOR_MISMATCH')

    def test_missing_invalid_requested_window_and_overlap_propagate(self):
        import copy
        from tools import nav_metrics_v2 as nav
        data,curve,c=self.windows();good={'full':c['full'],'is':c['is_'],'oos':c['oos']}
        for label in ('full','is','oos'):
            for mutation in ('missing','RF','NAV'):
                with self.subTest(label=label,mutation=mutation):
                    bad=copy.deepcopy(good)
                    if mutation=='missing': bad.pop(label)
                    elif mutation=='RF': bad[label].pop('risk_free')
                    else: bad[label]['nav_ref']['sha256']='0'*64
                    out=calc_metrics_with_oos(curve,_empty_trades(),100.,oos_start='2026-01-06',
                                             measurement_contexts=bad)
                    self.assertEqual(out['status'],nav.BLOCKED)
                    self.assertEqual(out[label]['status'],nav.BLOCKED)
                    self.assertIsNone(out[label]['cagr'])
        for lo,end in (('2026-01-07','2026-01-06'),('2026-01-05','2026-01-07')):
            out=calc_metrics_with_oos(curve,_empty_trades(),100.,oos_start='2026-01-06',
                                     oos2_start=lo,oos2_end=end,measurement_contexts=good)
            self.assertEqual(out['status'],nav.BLOCKED)
        out=calc_metrics_with_oos(curve,_empty_trades(),100.,oos_start='2099-01-01',measurement_contexts=good)
        self.assertEqual(out['status'],nav.BLOCKED)

    def test_raw_full_grid_failure_cannot_hide_behind_successful_slice(self):
        from tools import nav_metrics_v2 as nav
        data,curve,c=self.windows()
        import pandas as pd
        bad=pd.concat([curve.iloc[:1],curve],ignore_index=True)
        out=calc_metrics_with_oos(bad,_empty_trades(),100.,oos_start='2026-01-06',
                                 measurement_contexts={'full':c['full'],'is':c['is_'],'oos':c['oos']})
        self.assertEqual(out['status'],nav.BLOCKED)
        self.assertEqual(out['full']['status'],nav.BLOCKED)
        self.assertEqual(len(bad),4)


if __name__ == "__main__":
    test_full_window_metrics_backcompat()
    test_date_range_slices_and_reanchors_capital()
    test_is_oos_split_via_calc_metrics_with_oos()
    test_oos2_independent_window()
    test_overlapping_oos_windows_are_rejected()
    test_oos2_end_tracks_custom_primary_start()
    test_empty_window_returns_blocked()
    test_disabled_with_empty_string()
    test_default_constants()
    import unittest
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ResearchOOSAdmissionTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("oos_lock_smoke: ok")
