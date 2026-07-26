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
    DEFAULT_OOS2_END,
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
    assert DEFAULT_OOS2_END == "2024-06-30"


if __name__ == "__main__":
    test_full_window_metrics_backcompat()
    test_date_range_slices_and_reanchors_capital()
    test_is_oos_split_via_calc_metrics_with_oos()
    test_oos2_independent_window()
    test_overlapping_oos_windows_are_rejected()
    test_empty_window_returns_blocked()
    test_disabled_with_empty_string()
    test_default_constants()
    print("oos_lock_smoke: ok")
