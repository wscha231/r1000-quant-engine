#!/usr/bin/env python3
"""Smoke checks for broker-ledger replay."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    DISABLE_CONCENTRATED_CHAMPION_FILTERS,
    filter_concentrated_champion,
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


def test_broker_replay_tracks_integer_shares_and_cash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 101.0, 110.0, 120.0, 130.0, 140.0, 150.0])
        _write_px(cache, "BBB", [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0])
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


def test_partial_resize_two_signal_confirmation_is_narrow_and_research_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        control_out = root / "control"
        arm_out = root / "arm"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0] * 24)
        _write_px(cache, "BBB", [100.0] * 24)
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.40},
                {"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 0.70},
                {"rebalance_date": "2026-01-16", "ticker": "AAA", "weight": 0.80},
                {"rebalance_date": "2026-01-23", "ticker": "AAA", "weight": 0.60},
            ]
        ).to_csv(target, index=False)

        control = replay(
            target_book=target,
            price_cache=cache,
            output_dir=control_out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            cost_bps=25.0,
            integer_shares=True,
        )
        arm = replay(
            target_book=target,
            price_cache=cache,
            output_dir=arm_out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            cost_bps=25.0,
            integer_shares=True,
            partial_resize_two_signal_confirmation=True,
        )

        assert control["status"] == "completed"
        assert arm["status"] == "completed"
        assert arm["execution_policy"] == "partial_resize_two_signal_confirmation"
        assert arm["research_only"] is True
        assert arm["valid_for_production"] is False
        assert arm["partial_resize_deferred_count"] >= 1
        assert arm["partial_resize_confirmed_count"] >= 1
        assert arm["risk_cut_immediate_count"] >= 1
        assert arm["target_exit_immediate_count"] == 1

        decisions = pd.read_csv(arm_out / "partial_resize_decisions.csv")
        aaa = decisions[decisions["ticker"].eq("AAA")]
        assert "partial_resize_first_signal" in set(aaa["reason"])
        assert "partial_resize_second_signal_confirmed" in set(aaa["reason"])
        assert "partial_resize_risk_cut_immediate" in set(aaa["reason"])
        bbb = decisions[decisions["ticker"].eq("BBB")]
        assert "target_exit_immediate" in set(bbb["reason"])

        trades = pd.read_csv(arm_out / "trades.csv")
        bbb_sells = trades[(trades["ticker"].eq("BBB")) & (trades["side"].eq("SELL"))]
        assert len(bbb_sells) == 1
        assert pd.read_csv(arm_out / "cash_ledger.csv")["cash_usd"].min() >= -1e-6


def test_explicitly_disabled_partial_resize_mode_preserves_control_parity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        first_out = root / "first"
        second_out = root / "second"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-06", "ticker": "AAA", "weight": 0.70},
            ]
        ).to_csv(target, index=False)

        first = replay(
            target_book=target,
            price_cache=cache,
            output_dir=first_out,
            portfolio_kind="main",
            starting_capital=10_000.0,
        )
        second = replay(
            target_book=target,
            price_cache=cache,
            output_dir=second_out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            partial_resize_two_signal_confirmation=False,
        )

        for key in ("cagr", "max_dd", "sharpe", "trade_count", "total_fees_usd", "gross_traded_usd"):
            assert first[key] == second[key], key
        pd.testing.assert_frame_equal(
            pd.read_csv(first_out / "trades.csv"),
            pd.read_csv(second_out / "trades.csv"),
            check_dtype=False,
        )


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

        assert metrics["status"] == "blocked"
        assert metrics["reason"] == "target_fill_coverage_incomplete"
        coverage = pd.read_csv(out / "target_fill_coverage.csv")
        late = coverage[coverage["ticker"].eq("LATE")].iloc[0]
        assert late["fillable"] in {False, 0, "False", "false"}
        assert late["reason"] == "no_fill_within_lag"
        assert not (out / "trades.csv").exists()
        assert not (out / "equity_curve.csv").exists()


def test_concentrated_replay_ignores_unaccepted_in_run_comparison() -> None:
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
        assert metrics["target_book_filter"]["target_stock_names"] == "3"
        assert metrics["target_book_filter_source"] == "registered_static_contract"
        assert "unaccepted in-run comparison ignored" in metrics["target_book_filter_warning"]
        positions = pd.read_csv(out / "positions_latest.csv")
        assert set(positions["ticker"]) == {"AAA", "BBB", "CCC"}


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


def test_registered_concentrated_filter_fails_on_missing_column_or_unmatched_value() -> None:
    missing_column = pd.DataFrame(
        [{"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 1.0}]
    )
    try:
        filter_concentrated_champion(missing_column, "concentrated")
    except ValueError as exc:
        assert "filter column is missing" in str(exc)
    else:
        raise AssertionError("missing registered filter column must fail closed")

    n5 = pd.DataFrame(
        [
            {
                "rebalance_date": "2026-01-02",
                "ticker": ticker,
                "weight": 0.2,
                "target_stock_names": 5,
                "weighting_mode": "score_power",
                "active_rebalance_interval_months": 1,
            }
            for ticker in ["AAA", "BBB", "CCC", "DDD", "EEE"]
        ]
    )
    try:
        filter_concentrated_champion(n5, "concentrated")
    except ValueError as exc:
        assert "target_stock_names=3" in str(exc)
    else:
        raise AssertionError("N=5 must not masquerade as the registered N=3 champion")


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
    test_partial_resize_two_signal_confirmation_is_narrow_and_research_only()
    test_explicitly_disabled_partial_resize_mode_preserves_control_parity()
    test_broker_replay_blocks_contaminated_weight_book()
    test_broker_replay_does_not_backdate_sparse_history_fill()
    test_concentrated_replay_ignores_unaccepted_in_run_comparison()
    test_concentrated_filter_disable_preserves_n5_target_book()
    test_registered_concentrated_filter_fails_on_missing_column_or_unmatched_value()
    test_alphaops_vnext_concentrated_book_auto_disables_legacy_filter()
    print("broker_ledger_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
