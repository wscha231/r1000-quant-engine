#!/usr/bin/env python3
"""Smoke checks for broker-ledger replay."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS, replay  # noqa: E402
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


def test_broker_replay_tracks_integer_shares_and_cash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 101.0, 110.0, 120.0, 130.0, 140.0, 150.0])
        _write_px(cache, "BBB", [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0])
        _write_px(cache, "SPY", [100.0, 100.0, 102.0, 103.0, 104.0, 104.0, 105.0])
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.60},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.30},
                {"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 1.00},
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
        assert metrics["benchmark_status"] == "completed"
        assert metrics["benchmark_ticker"] == "SPY"
        assert metrics["benchmark_metric_mode"] == "etf_adjusted_close_total_return_proxy"
        assert metrics["benchmark_cagr"] > 0.0
        assert "excess_cagr_vs_benchmark" in metrics
        assert metrics["benchmark_relative_risk_status"] == "completed"
        assert "benchmark_max_dd" in metrics
        assert "relative_max_dd_vs_benchmark" in metrics
        assert "down_capture_vs_benchmark" in metrics
        assert "beta_adjusted_alpha_annualized" in metrics
        assert metrics["benchmark_relative_gate_input"] is False
        assert metrics["benchmark_relative_public_claim_allowed"] is False
        assert metrics["absolute_mission_status"] == "completed"
        assert metrics["absolute_mission_pass"] is True
        assert metrics["benchmark_relative_can_override_absolute_mission"] is False
        assert metrics["valid_for_production"] is True
        assert metrics["ending_capital_usd"] > 10_000.0
        trades = pd.read_csv(out / "trades.csv")
        assert {"BUY", "SELL"}.intersection(set(trades["side"]))
        assert (trades["quantity"] % 1 == 0).all()
        cash = pd.read_csv(out / "cash_ledger.csv")
        assert cash["cash_usd"].min() >= -1e-6
        curve = pd.read_csv(out / "equity_curve.csv")
        assert curve["date"].min() >= "2026-01-02"
        assert (out / "holdings_daily.csv").exists()
        assert (out / "target_vs_actual_weights.csv").exists()
        assert (out / "account_state_latest.json").exists()
        assert (out / "positions_latest.csv").exists()


def test_broker_replay_blocks_contaminated_weight_book() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 101.0, 102.0])
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.80},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.80},
            ]
        ).to_csv(target, index=False)
        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
        )
        assert metrics["status"] == "blocked"
        assert metrics["invalid_weight_date_count"] == 1


def test_broker_replay_does_not_backdate_sparse_history_fill() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 105.0, 110.0, 115.0], start="2026-01-02")
        _write_px(cache, "LATE", [10.0, 11.0, 12.0], start="2026-03-02")
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-02", "ticker": "LATE", "weight": 0.40},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            max_fill_lag_days=7,
        )

        assert metrics["status"] == "completed"
        trades = pd.read_csv(out / "trades.csv")
        assert "LATE" not in set(trades["ticker"])


def test_concentrated_replay_uses_comparison_champion_filter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        reports = root / "reports"
        out = root / "broker"
        cache.mkdir()
        reports.mkdir()
        for ticker in ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]:
            _write_px(cache, ticker, [100.0, 101.0, 102.0, 103.0, 104.0])
        target = reports / "concentrated_strategy_holdings.csv"
        rows = [
            {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.40, "target_stock_names": 3, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.30, "target_stock_names": 3, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2026-01-02", "ticker": "CCC", "weight": 0.30, "target_stock_names": 3, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2026-01-02", "ticker": "DDD", "weight": 0.25, "target_stock_names": 4, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2026-01-02", "ticker": "EEE", "weight": 0.25, "target_stock_names": 4, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2026-01-02", "ticker": "FFF", "weight": 0.25, "target_stock_names": 4, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
            {"rebalance_date": "2026-01-02", "ticker": "GGG", "weight": 0.25, "target_stock_names": 4, "weighting_mode": "score_power", "active_rebalance_interval_months": 1},
        ]
        pd.DataFrame(rows).to_csv(target, index=False)
        pd.DataFrame(
            [
                {
                    "portfolio_mode": "concentrated_alpha",
                    "target_stock_names": 4,
                    "weighting_mode": "score_power",
                    "rebalance_interval_months": 1,
                    "strategy_cagr": 0.40,
                    "sharpe": 1.2,
                    "max_dd": -0.15,
                    "comparison_objective": 1.0,
                }
            ]
        ).to_csv(reports / "concentrated_strategy_comparison.csv", index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="concentrated",
            starting_capital=10_000.0,
        )

        assert metrics["status"] == "completed"
        assert metrics["target_book_filter"]["target_stock_names"] == "4"
        positions = pd.read_csv(out / "positions_latest.csv")
        assert set(positions["ticker"]) == {"DDD", "EEE", "FFF", "GGG"}


def test_concentrated_filter_disable_preserves_n5_target_book() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        for ticker in tickers:
            _write_px(cache, ticker, [100.0, 101.0, 102.0, 103.0, 104.0])
        target = root / "n5_targets.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": ticker,
                    "weight": 0.19,
                    "target_stock_names": 5,
                    "weighting_mode": "market_leader_score_power",
                    "active_rebalance_interval_months": 1,
                }
                for ticker in tickers
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="concentrated",
            starting_capital=100_000.0,
            concentrated_champion_filters=DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy(),
        )

        assert metrics["status"] == "completed"
        assert metrics["target_book_filter_source"] == "disabled_explicit"
        assert metrics.get("target_book_filter") in ({}, None)
        positions = pd.read_csv(out / "positions_latest.csv")
        assert len(positions) == 5


def test_alphaops_vnext_concentrated_book_auto_disables_legacy_filter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        reports = root / "reports"
        out = root / "broker"
        cache.mkdir()
        reports.mkdir()
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        for ticker in tickers:
            _write_px(cache, ticker, [100.0, 101.0, 102.0, 103.0, 104.0])
        target = reports / "operating_concentrated_target_book.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": ticker,
                    "weight": 0.19,
                    "target_stock_names": 5,
                    "weighting_mode": "alphaops_vnext_score_power",
                    "active_rebalance_interval_months": 1,
                    "production_policy": "alphaops_vnext_production",
                    "operating_target_source": "alphaops_vnext_policy_replay",
                }
                for ticker in tickers
            ]
        ).to_csv(target, index=False)
        pd.DataFrame(
            [
                {
                    "portfolio_mode": "concentrated_alpha",
                    "target_stock_names": 4,
                    "weighting_mode": "score_power",
                    "rebalance_interval_months": 1,
                    "strategy_cagr": 0.40,
                    "sharpe": 1.2,
                    "max_dd": -0.15,
                }
            ]
        ).to_csv(reports / "concentrated_strategy_comparison.csv", index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="concentrated",
            starting_capital=100_000.0,
        )

        assert metrics["status"] == "completed"
        assert metrics["target_book_filter_source"] == "alphaops_vnext_policy_target_book"
        assert metrics.get("target_book_filter") in ({}, None)
        positions = pd.read_csv(out / "positions_latest.csv")
        assert set(positions["ticker"]) == set(tickers)


def main() -> int:
    test_broker_replay_tracks_integer_shares_and_cash()
    test_broker_replay_blocks_contaminated_weight_book()
    test_broker_replay_does_not_backdate_sparse_history_fill()
    test_concentrated_replay_uses_comparison_champion_filter()
    test_concentrated_filter_disable_preserves_n5_target_book()
    test_alphaops_vnext_concentrated_book_auto_disables_legacy_filter()
    print("broker_ledger_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
