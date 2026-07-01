#!/usr/bin/env python3
"""Smoke checks for research-only broker cash-carry accounting."""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_RISK_FREE,
    CashCarryConfig,
    LedgerState,
    accrue_cash_interest,
    replay,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    df = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def _write_rates(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def test_default_off_preserves_metric_mode_and_schema() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 101.0, 102.0, 103.0, 104.0])
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 0.50},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=25.0,
            integer_shares=True,
        )

        assert metrics["status"] == "completed"
        assert metrics["metric_mode"] == "broker_ledger_next_close"
        assert metrics["valid_for_production"] is True
        assert "cash_carry_mode" not in metrics
        curve = pd.read_csv(out / "equity_curve.csv")
        assert list(curve.columns) == [
            "date",
            "equity_usd",
            "cash_usd",
            "cash_weight",
            "stock_value_usd",
            "position_count",
            "fill_mode",
        ]


def test_cash_carry_uses_dgs3mo_percent_act365_and_one_day_lag() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "SPY", [100.0, 100.0, 100.0, 100.0, 100.0], start="2026-01-02")
        rate_path = root / "fred_dgs3mo_DGS3MO.csv"
        _write_rates(
            rate_path,
            [
                {"date": "2026-01-02", "value": 3.65},
            ],
        )
        target = root / "cash_targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 1.0},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cash_carry_config=CashCarryConfig(
                mode=CASH_CARRY_MODE_RISK_FREE,
                rate_path=rate_path,
                haircut_bps=50.0,
                day_count=365,
                rate_lag_days=1,
            ),
        )

        assert metrics["status"] == "completed"
        assert metrics["metric_mode"] == "broker_ledger_next_close_cash_carry"
        assert metrics["valid_for_production"] is False
        assert metrics["production_activation_allowed"] is False
        expected = 10_000.0 * ((0.0365 - 0.0050) * (3.0 / 365.0))
        assert math.isclose(metrics["cash_interest_accrued_usd"], expected, rel_tol=0.02)
        curve = pd.read_csv(out / "equity_curve.csv")
        assert {"cash_interest_daily", "cash_interest_accrued_to_date", "cash_rate_used", "cash_rate_available_from"}.issubset(curve.columns)
        assert len(curve) >= 2
        assert curve["cash_rate_available_from"].dropna().astype(str).iloc[-1] == "2026-01-05"


def test_replay_end_date_clamps_fresh_cache_window() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "SPY", [100.0, 100.0, 100.0, 100.0, 100.0], start="2026-01-02")
        rate_path = root / "fred_dgs3mo_DGS3MO.csv"
        _write_rates(rate_path, [{"date": "2026-01-02", "value": 4.0}])
        target = root / "cash_targets.csv"
        pd.DataFrame([{"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 1.0}]).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            replay_end_date="2026-01-06",
            official_baseline_end_date="2026-01-06",
            cash_carry_config=CashCarryConfig(
                mode=CASH_CARRY_MODE_RISK_FREE,
                rate_path=rate_path,
                haircut_bps=0.0,
                day_count=365,
                rate_lag_days=1,
            ),
        )

        assert metrics["status"] == "completed", metrics
        assert metrics["requested_replay_end_date"] == "2026-01-06"
        assert metrics["actual_equity_curve_end_date"] == "2026-01-06"
        assert metrics["official_baseline_end_date"] == "2026-01-06"
        assert metrics["end_date_matches_official"] is True
        assert metrics["replay_end_date_clamped"] is True
        curve = pd.read_csv(out / "equity_curve.csv")
        assert curve["date"].max() == "2026-01-06"


def test_replay_end_date_skips_next_close_rebalance_after_window() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [10.0, 10.0, 10.0, 10.0, 10.0, 10.0], start="2026-01-02")
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-06", "ticker": "AAA", "weight": 0.90},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            replay_end_date="2026-01-06",
            official_baseline_end_date="2026-01-06",
        )

        assert metrics["status"] == "completed", metrics
        assert metrics["actual_equity_curve_end_date"] == "2026-01-06"
        assert metrics["end_date_matches_official"] is True
        assert metrics["replay_end_skipped_rebalance_count"] == 1
        curve = pd.read_csv(out / "equity_curve.csv")
        assert curve["date"].max() == "2026-01-06"
        trades = pd.read_csv(out / "trades.csv")
        assert "2026-01-06" not in set(trades.get("signal_date", pd.Series(dtype=str)).astype(str))


def test_replay_end_date_filters_future_target_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [10.0, 10.0, 10.0, 10.0, 10.0, 10.0], start="2026-01-02")
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-07", "ticker": "AAA", "weight": 0.90},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            replay_end_date="2026-01-06",
            official_baseline_end_date="2026-01-06",
        )

        assert metrics["status"] == "completed", metrics
        assert metrics["actual_equity_curve_end_date"] == "2026-01-06"
        assert metrics["end_date_matches_official"] is True
        assert metrics["replay_end_filtered_target_date_count"] == 1
        assert metrics["replay_end_filtered_target_row_count"] == 1
        curve = pd.read_csv(out / "equity_curve.csv")
        assert curve["date"].max() == "2026-01-06"


def test_future_rate_is_not_used_before_available_from() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "SPY", [100.0, 100.0, 100.0], start="2026-01-02")
        rate_path = root / "rates.csv"
        _write_rates(rate_path, [{"date": "2026-01-06", "value": 99.0}])
        target = root / "cash_targets.csv"
        pd.DataFrame([{"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 1.0}]).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            cash_carry_config=CashCarryConfig(
                mode=CASH_CARRY_MODE_RISK_FREE,
                rate_path=rate_path,
                haircut_bps=0.0,
                day_count=365,
                rate_lag_days=1,
            ),
        )

        assert metrics["status"] == "completed"
        assert metrics["cash_interest_accrued_usd"] == 0.0


def test_negative_cash_does_not_accrue_interest() -> None:
    state = LedgerState(cash=-100.0)
    rates = pd.DataFrame(
        [
            {
                "rate_date": pd.Timestamp("2026-01-02"),
                "available_from": pd.Timestamp("2026-01-05"),
                "rate_pct": 5.0,
                "rate_source": "DGS3MO",
            }
        ]
    )
    cfg = CashCarryConfig(mode=CASH_CARRY_MODE_RISK_FREE, haircut_bps=0.0, day_count=365)
    accrue_cash_interest(state=state, mark_date=pd.Timestamp("2026-01-05"), cash_carry_config=cfg, cash_rate_table=rates)
    accrue_cash_interest(state=state, mark_date=pd.Timestamp("2026-01-06"), cash_carry_config=cfg, cash_rate_table=rates)
    assert state.cash == -100.0
    assert state.cash_interest_accrued == 0.0


def main() -> int:
    test_default_off_preserves_metric_mode_and_schema()
    test_cash_carry_uses_dgs3mo_percent_act365_and_one_day_lag()
    test_replay_end_date_clamps_fresh_cache_window()
    test_replay_end_date_skips_next_close_rebalance_after_window()
    test_replay_end_date_filters_future_target_rows()
    test_future_rate_is_not_used_before_available_from()
    test_negative_cash_does_not_accrue_interest()
    print("broker_cash_carry_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
