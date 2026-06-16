#!/usr/bin/env python3
"""Smoke for tools/run_is_attribution.py.

Anchors the year-classifier semantics so future tweaks don't silently
relabel the 27498401423 conc 2021/2023 underinvestment leak as something
else. Without this, a tag-rename would erase the only signal we have for the
14pp IS gap.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_is_attribution import _classify_leak, _yearly_equity, run_for_portfolio  # noqa: E402


def _equity_curve(start_eq: float, end_eq: float, days: int, year: int, cash_w: float = 0.2) -> pd.DataFrame:
    dates = [date(year, 1, 1) + timedelta(days=i) for i in range(days)]
    # linear interpolation for the smoke test
    eqs = [start_eq + (end_eq - start_eq) * i / max(days - 1, 1) for i in range(days)]
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "equity_usd": eqs,
        "cash_usd": [e * cash_w for e in eqs],
        "cash_weight": [cash_w] * days,
        "stock_value_usd": [e * (1 - cash_w) for e in eqs],
        "position_count": [5] * days,
        "fill_mode": ["next_close"] * days,
        "year": [year] * days,
    })


def test_structural_underinvestment_bull_tag() -> None:
    """The 27498401423 conc 2021 shape: 58% bull regime, 57% stock weight,
    only +2.4% return. Must classify as structural_underinvestment_bull."""
    row = {
        "year_return": 0.0245,
        "avg_cash_weight": 0.367,
        "avg_stock_weight_sum": 0.573,
        "regime_dist": "bull=58%; neutral=42%",
    }
    assert _classify_leak(row) == "structural_underinvestment_bull"


def test_structural_underinvestment_bull_2023_shape() -> None:
    """The 27498401423 conc 2023 shape: 46% bull, 54% stock weight, +11.77%."""
    row = {
        "year_return": 0.1177,
        "avg_cash_weight": 0.521,
        "avg_stock_weight_sum": 0.541,
        "regime_dist": "bull=46%; neutral=36%; bear=18%",
    }
    assert _classify_leak(row) == "structural_underinvestment_bull"


def test_over_defense_bear_ok_tag() -> None:
    """The 27498401423 2022 shape: bear regime, 81% cash, only -10.7%."""
    row = {
        "year_return": -0.107,
        "avg_cash_weight": 0.812,
        "avg_stock_weight_sum": 0.187,
        "regime_dist": "bear=80%; neutral=20%",
    }
    assert _classify_leak(row) == "over_defense_bear_ok"


def test_healthy_tag() -> None:
    """2025 conc: +96% return, invested 70%."""
    row = {
        "year_return": 0.96,
        "avg_cash_weight": 0.32,
        "avg_stock_weight_sum": 0.695,
        "regime_dist": "neutral=50%; bull=33%; bear=17%",
    }
    assert _classify_leak(row) == "healthy"


def test_flat_alpha_invested_tag() -> None:
    """Hypothetical: invested 80% but only +5% — selection problem."""
    row = {
        "year_return": 0.05,
        "avg_cash_weight": 0.10,
        "avg_stock_weight_sum": 0.85,
        "regime_dist": "bull=60%; neutral=40%",
    }
    assert _classify_leak(row) == "flat_alpha_invested"


def test_yearly_equity_handles_single_year_cleanly() -> None:
    eq = _equity_curve(100_000, 200_000, days=365, year=2020, cash_w=0.30)
    out = _yearly_equity(eq)
    assert len(out) == 1
    r = out.iloc[0]
    assert r["year"] == 2020
    assert abs(r["year_return"] - 1.0) < 1e-6
    assert r["max_dd_in_year"] <= 0.0


def test_end_to_end_writes_outputs() -> None:
    eq = pd.concat([
        _equity_curve(100_000, 130_000, days=365, year=2020),
        _equity_curve(130_000, 132_000, days=365, year=2021, cash_w=0.40),
        _equity_curve(132_000, 250_000, days=365, year=2025, cash_w=0.20),
    ], ignore_index=True)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "broker_replay/concentrated").mkdir(parents=True)
        eq.to_csv(td / "broker_replay/concentrated/equity_curve.csv", index=False)
        out_dir = td / "out"
        summary = run_for_portfolio(td, out_dir, "concentrated")
        assert (out_dir / "concentrated_yearly.csv").exists()
        assert (out_dir / "concentrated_summary.json").exists()
        assert (out_dir / "concentrated_summary.md").exists()
        # 2020/2021/2025 each ~365d -> roughly 30%/1.5%/89% returns
        assert summary.get("status") != "missing_equity_curve"
        assert summary.get("portfolio") == "concentrated"
        loaded = json.loads((out_dir / "concentrated_summary.json").read_text())
        assert loaded["portfolio"] == "concentrated"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(tests)}/{len(tests)} passed")
