#!/usr/bin/env python3
"""Spread/ADV/impact replay must be PIT, conservative, and fail closed."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.execution_cost_model import (  # noqa: E402
    EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
    ExecutionCostConfig,
    ExecutionCostModel,
    load_paper_slippage,
)
from tools.run_broker_ledger_replay import (  # noqa: E402
    LedgerState,
    execute_order,
    render_report,
)
from tools.run_execution_cost_capacity_sidecar import run  # noqa: E402
from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


def _write_ohlcv(
    cache_dir: Path,
    ticker: str,
    *,
    start: str = "2023-11-01",
    periods: int = 90,
    initial_close: float = 100.0,
    daily_step: float = 0.10,
    volume: int = 1_000_000,
    complete: bool = True,
) -> None:
    dates = pd.bdate_range(start, periods=periods)
    closes = [initial_close + daily_step * index for index in range(periods)]
    payload: dict[str, object] = {
        "Open": [value * 0.999 for value in closes],
        "Close": closes,
        "Adj Close": closes,
    }
    if complete:
        payload.update(
            {
                "High": [value * 1.005 for value in closes],
                "Low": [value * 0.995 for value in closes],
                "Volume": [volume] * periods,
            }
        )
    pd.DataFrame(payload, index=dates).to_parquet(cache_dir / px_cache_name(ticker))


def _write_targets(path: Path) -> None:
    rows: list[dict[str, object]] = []
    for index, date in enumerate(
        ["2024-01-02", "2024-01-09", "2024-01-16", "2024-01-23", "2024-01-30"]
    ):
        if index % 2 == 0:
            rows.extend(
                [
                    {"rebalance_date": date, "ticker": "AAA", "weight": 0.70},
                    {"rebalance_date": date, "ticker": "BBB", "weight": 0.20},
                ]
            )
        else:
            rows.extend(
                [
                    {"rebalance_date": date, "ticker": "AAA", "weight": 0.20},
                    {"rebalance_date": date, "ticker": "BBB", "weight": 0.70},
                ]
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_price_loader_preserves_adjusted_ohlcv_for_liquidity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        dates = pd.bdate_range("2024-01-02", periods=2)
        pd.DataFrame(
            {
                "Open": [98.0, 100.0],
                "High": [110.0, 112.0],
                "Low": [90.0, 92.0],
                "Close": [100.0, 102.0],
                "Adj Close": [50.0, 51.0],
                "Volume": [1_000_000, 2_000_000],
            },
            index=dates,
        ).to_parquet(cache / px_cache_name("AAA"))
        default_loaded = load_price_series(cache, "AAA")
        assert list(default_loaded.columns) == ["close", "open"]
        loaded = load_price_series(cache, "AAA", include_liquidity=True)
        assert list(loaded.columns) == [
            "close",
            "open",
            "high",
            "low",
            "volume",
            "dollar_volume",
        ]
        assert loaded.iloc[0]["close"] == 50.0
        assert loaded.iloc[0]["open"] == 49.0
        assert loaded.iloc[0]["high"] == 55.0
        assert loaded.iloc[0]["low"] == 45.0
        assert loaded.iloc[1]["volume"] == 2_000_000
        assert loaded.iloc[0]["dollar_volume"] == 100_000_000.0
        assert loaded.iloc[1]["dollar_volume"] == 204_000_000.0


def test_all_paper_date_aliases_use_new_york_trade_date() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for date_column in ("date", "fill_date", "executed_at"):
            path = Path(tmp) / f"{date_column}.csv"
            pd.DataFrame(
                [
                    {
                        date_column: "2024-01-04T01:00:00Z",
                        "ticker": "TIMESTAMP",
                        "side": "BUY",
                        "observed_slippage_bps": 12.0,
                    },
                    {
                        date_column: "2024-01-04",
                        "ticker": "PLAIN",
                        "side": "BUY",
                        "observed_slippage_bps": 13.0,
                    },
                ]
            ).to_csv(path, index=False)
            loaded = load_paper_slippage(path).set_index("ticker")
            assert loaded.loc["TIMESTAMP", "date"] == pd.Timestamp("2024-01-03")
            assert loaded.loc["PLAIN", "date"] == pd.Timestamp("2024-01-04")


def test_dynamic_affordability_solves_against_original_desired_quantity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        _write_ohlcv(
            cache,
            "AAA",
            periods=90,
            initial_close=100.0,
            daily_step=0.0,
            volume=10_000,
        )
        config = ExecutionCostConfig(
            mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
            impact_coefficient=5.0,
            maximum_market_impact_bps=5_000.0,
        )
        model = ExecutionCostModel(
            {"AAA": load_price_series(cache, "AAA", include_liquidity=True)},
            config,
        )
        fill_date = pd.Timestamp("2024-01-31")
        cash = 10_000.0
        price = 100.0
        desired = 100
        expected = 0
        for quantity in range(1, desired + 1):
            quote = model.quote(
                ticker="AAA",
                side="BUY",
                fill_date=fill_date,
                gross_value=quantity * price,
                fixed_cost_bps=25.0,
            )
            required = quantity * price * (
                1.0 + quote.total_cost_bps / 10_000.0
            )
            if required <= cash + 1e-9:
                expected = quantity
        assert 0 < expected < desired
        state = LedgerState(cash=cash)
        order = execute_order(
            state=state,
            ticker="AAA",
            side="BUY",
            desired_qty=float(desired),
            price=price,
            cost_bps=25.0,
            integer_shares=True,
            fill_date=fill_date,
            execution_cost_model=model,
        )
        assert order is not None
        assert int(order["quantity"]) == expected
        assert state.cash >= -1e-9


def test_asynchronous_transition_fill_dates_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "execution"
        cache.mkdir()
        _write_ohlcv(cache, "AAA", initial_close=100.0, volume=1_000_000)
        _write_ohlcv(cache, "BBB", initial_close=50.0, volume=500_000)
        bbb_path = cache / px_cache_name("BBB")
        bbb = pd.read_parquet(bbb_path)
        bbb = bbb.drop(index=pd.Timestamp("2024-01-03"))
        bbb.to_parquet(bbb_path)
        targets = root / "targets.csv"
        _write_targets(targets)
        paper = root / "paper.csv"
        pd.DataFrame(
            [
                {
                    "date": "2024-01-03",
                    "ticker": "BBB",
                    "side": "BUY",
                    "observed_slippage_bps": 5.0,
                },
                {
                    "date": "2024-01-04",
                    "ticker": "BBB",
                    "side": "BUY",
                    "observed_slippage_bps": 123.0,
                },
            ]
        ).to_csv(paper, index=False)

        payload = run(
            target_book=targets,
            price_cache=cache,
            output_dir=output,
            portfolio_kind="main",
            starting_capital=100_000.0,
            fill_mode="next_close",
            base_cost_bps=25.0,
            max_fill_lag_days=7,
            execution_cost_config=ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
                paper_slippage_path=paper,
            ),
        )

        assert payload["status"] == "blocked"
        assert payload["reason"] == "target_fill_coverage_incomplete"
        assert "target_fill_coverage_incomplete" in payload["promotion_blockers"]
        coverage = pd.read_csv(
            output / "spread_adv_impact" / "target_fill_coverage.csv"
        )
        first_bbb = coverage[
            coverage["ticker"].eq("BBB")
            & coverage["signal_date"].eq("2024-01-02")
        ].iloc[0]
        assert first_bbb["actual_fill_date"] == "2024-01-04"
        assert first_bbb["chronology_safe"] in {False, 0, "False", "false"}
        manifest = json.loads(
            (output / "source_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["transition_fill_chronology_safe"] is False
        assert manifest["target_fill_coverage_complete"] is False
        nested = json.loads(
            (output / "spread_adv_impact" / "metrics.json").read_text(
                encoding="utf-8"
            )
        )
        assert nested["performance_fields_redacted"] is True
        assert "cagr" not in nested
        assert not (output / "spread_adv_impact" / "trades.csv").exists()
        assert not (output / "spread_adv_impact" / "equity_curve.csv").exists()


def test_removed_target_requires_liquidation_fill_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "execution"
        cache.mkdir()
        _write_ohlcv(cache, "AAA")
        _write_ohlcv(
            cache,
            "EXIT",
            start="2023-11-01",
            periods=48,
            initial_close=50.0,
        )
        targets = root / "targets.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2024-01-02",
                    "ticker": "AAA",
                    "weight": 0.45,
                },
                {
                    "rebalance_date": "2024-01-02",
                    "ticker": "EXIT",
                    "weight": 0.45,
                },
                {
                    "rebalance_date": "2024-01-16",
                    "ticker": "AAA",
                    "weight": 0.90,
                },
            ]
        ).to_csv(targets, index=False)

        payload = run(
            target_book=targets,
            price_cache=cache,
            output_dir=output,
            portfolio_kind="main",
            starting_capital=100_000.0,
            fill_mode="next_close",
            base_cost_bps=25.0,
            max_fill_lag_days=7,
            execution_cost_config=ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
            ),
        )

        assert payload["status"] == "blocked"
        assert payload["reason"] == "target_fill_coverage_incomplete"
        coverage = pd.read_csv(
            output / "spread_adv_impact" / "target_fill_coverage.csv"
        )
        exit_row = coverage[
            coverage["signal_date"].eq("2024-01-16")
            & coverage["ticker"].eq("EXIT")
        ].iloc[0]
        assert exit_row["transition_action"] == "target_exit"
        assert exit_row["fillable"] in {False, 0, "False", "false"}
        assert exit_row["reason"] == "no_fill_within_lag"
        nested = json.loads(
            (output / "spread_adv_impact" / "metrics.json").read_text(
                encoding="utf-8"
            )
        )
        assert nested["performance_fields_redacted"] is True
        assert "cagr" not in nested


def test_realistic_cost_replay_is_pit_and_more_conservative() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "execution"
        cache.mkdir()
        _write_ohlcv(cache, "AAA", initial_close=100.0, volume=1_000_000)
        _write_ohlcv(cache, "BBB", initial_close=50.0, daily_step=0.03, volume=500_000)
        targets = root / "targets.csv"
        _write_targets(targets)
        paper = root / "paper_slippage.csv"
        pd.DataFrame(
            [
                {
                    "date": "2024-01-03",
                    "ticker": "AAA",
                    "side": "BUY",
                    "observed_slippage_bps": 200.0,
                }
            ]
        ).to_csv(paper, index=False)

        payload = run(
            target_book=targets,
            price_cache=cache,
            output_dir=output,
            portfolio_kind="main",
            starting_capital=100_000.0,
            fill_mode="next_close",
            base_cost_bps=25.0,
            max_fill_lag_days=7,
            execution_cost_config=ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
                paper_slippage_path=paper,
            ),
        )

        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["promotion_allowed"] is False
        fixed = payload["fixed_bps_control"]
        realistic = payload["realistic_execution_cost"]
        assert realistic["ending_capital_usd"] < fixed["ending_capital_usd"]
        assert realistic["total_fees_usd"] > fixed["total_fees_usd"]
        assert payload["execution_cost_summary"]["coverage_rate"] == 1.0
        assert payload["execution_cost_summary"]["paper_slippage_exceeds_model_count"] == 1
        assert "paper_slippage_exceeds_model_assumption" in payload["promotion_blockers"]

        scenarios = payload["capacity_scenarios"]
        assert [row["max_adv_participation"] for row in scenarios] == [0.001, 0.005, 0.01]
        capacities = [row["strict_capacity_usd"] for row in scenarios]
        assert capacities[0] < capacities[1] < capacities[2]

        trades = pd.read_csv(output / "spread_adv_impact" / "trades.csv")
        assert (trades["cost_data_status"] == "complete").all()
        assert (pd.to_datetime(trades["liquidity_history_end_date"]) < pd.to_datetime(trades["date"])).all()
        assert (trades["total_cost_bps"] >= 25.0).all()
        paper_trade = trades[
            trades["ticker"].eq("AAA")
            & trades["side"].eq("BUY")
            & trades["date"].eq("2024-01-03")
        ].iloc[0]
        assert paper_trade["observed_slippage_bps"] == 200.0
        assert paper_trade["effective_variable_cost_bps"] == 200.0
        assert paper_trade["total_cost_bps"] == 225.0
        json.loads((output / "summary.json").read_text(encoding="utf-8"))
        source_manifest = json.loads(
            (output / "source_manifest.json").read_text(encoding="utf-8")
        )
        assert source_manifest["price_source_coverage_complete"] is True
        assert source_manifest["target_fill_coverage_complete"] is True
        assert source_manifest["price_source_count"] == 2
        assert source_manifest["target_ticker_count"] == 2
        assert all(
            row["liquidity_ohlcv_loadable"]
            for row in source_manifest["price_sources"]
        )
        assert payload["source_manifest_sha256"] == source_manifest["manifest_sha256"]
        assert (output / "report.md").exists()


def test_missing_ohlcv_blocks_dynamic_cost_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "execution"
        cache.mkdir()
        _write_ohlcv(cache, "AAA", complete=False)
        _write_ohlcv(cache, "BBB", initial_close=50.0, complete=False)
        targets = root / "targets.csv"
        _write_targets(targets)

        payload = run(
            target_book=targets,
            price_cache=cache,
            output_dir=output,
            portfolio_kind="main",
            starting_capital=100_000.0,
            fill_mode="next_close",
            base_cost_bps=25.0,
            max_fill_lag_days=7,
            execution_cost_config=ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
            ),
        )

        assert payload["status"] == "blocked"
        assert payload["reason"] == "execution_cost_liquidity_coverage_incomplete"
        assert payload["realistic_execution_cost"]["performance_usable"] is False
        assert payload["realistic_execution_cost"]["cagr"] is None
        assert payload["deltas_vs_fixed_bps"] == {}
        summary = payload["execution_cost_summary"]
        assert summary["coverage_complete"] is False
        assert summary["coverage_rate"] == 0.0
        assert "paper_slippage_calibration_unavailable" in payload["promotion_blockers"]
        trades = pd.read_csv(output / "spread_adv_impact" / "trades.csv")
        assert (trades["cost_data_status"] == "blocked").all()
        # Missing data receives the configured conservative ceiling, never a
        # silent fixed-bps fallback.
        assert (trades["total_cost_bps"] == 625.0).all()
        for arm in ("fixed_bps_control", "spread_adv_impact"):
            nested = json.loads(
                (output / arm / "metrics.json").read_text(encoding="utf-8")
            )
            assert nested["performance_fields_redacted"] is True
            assert "cagr" not in nested
            assert "windows" not in nested
            assert not (output / arm / "equity_curve.csv").exists()
            assert not (output / arm / "account_state_latest.json").exists()


def test_missing_liquidity_uses_larger_observed_paper_slippage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        cache.mkdir()
        _write_ohlcv(cache, "AAA", complete=False)
        paper = root / "paper.csv"
        pd.DataFrame(
            [
                {
                    "date": "2024-01-03",
                    "ticker": "AAA",
                    "side": "BUY",
                    "observed_slippage_bps": 900.0,
                }
            ]
        ).to_csv(paper, index=False)
        model = ExecutionCostModel(
            {
                "AAA": load_price_series(
                    cache,
                    "AAA",
                    include_liquidity=True,
                )
            },
            ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
                paper_slippage_path=paper,
            ),
        )

        quote = model.quote(
            ticker="AAA",
            side="BUY",
            fill_date=pd.Timestamp("2024-01-03"),
            gross_value=10_000.0,
            fixed_cost_bps=25.0,
        )

        assert quote.status == "blocked"
        assert quote.estimated_variable_cost_bps == 600.0
        assert quote.observed_slippage_bps == 900.0
        assert quote.effective_variable_cost_bps == 900.0
        assert quote.total_cost_bps == 925.0
        assert quote.observed_exceeds_model is True


def test_implausible_paper_slippage_fails_closed_without_state_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "execution"
        cache.mkdir()
        _write_ohlcv(cache, "AAA", initial_close=100.0)
        _write_ohlcv(cache, "BBB", initial_close=50.0)
        targets = root / "targets.csv"
        _write_targets(targets)
        paper = root / "paper.csv"
        pd.DataFrame(
            [
                {
                    "date": "2024-01-10",
                    "ticker": "AAA",
                    "side": "SELL",
                    "observed_slippage_bps": 9_975.0,
                }
            ]
        ).to_csv(paper, index=False)

        model = ExecutionCostModel(
            {
                "AAA": load_price_series(
                    cache,
                    "AAA",
                    include_liquidity=True,
                )
            },
            ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
                paper_slippage_path=paper,
            ),
        )
        direct_state = LedgerState(
            cash=500.0,
            shares={"AAA": 10.0},
            cost_basis={"AAA": 100.0},
        )
        direct_order = execute_order(
            state=direct_state,
            ticker="AAA",
            side="SELL",
            desired_qty=10.0,
            price=100.0,
            cost_bps=25.0,
            integer_shares=True,
            fill_date=pd.Timestamp("2024-01-10"),
            execution_cost_model=model,
        )
        assert direct_order is None
        assert direct_state.cash == 500.0
        assert direct_state.shares == {"AAA": 10.0}

        payload = run(
            target_book=targets,
            price_cache=cache,
            output_dir=output,
            portfolio_kind="main",
            starting_capital=100_000.0,
            fill_mode="next_close",
            base_cost_bps=25.0,
            max_fill_lag_days=7,
            execution_cost_config=ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
                paper_slippage_path=paper,
            ),
        )

        assert payload["status"] == "blocked"
        assert payload["reason"] == "paper_slippage_out_of_bounds"
        assert "paper_slippage_out_of_bounds" in payload["promotion_blockers"]
        assert (
            "paper_slippage_calibration_unavailable"
            not in payload["promotion_blockers"]
        )
        assert payload["deltas_vs_fixed_bps"] == {}
        for arm in ("fixed_bps_control", "spread_adv_impact"):
            nested = json.loads(
                (output / arm / "metrics.json").read_text(encoding="utf-8")
            )
            assert nested["status"] == "blocked"
            assert nested["reason"] == "paper_slippage_out_of_bounds"
            assert nested["performance_fields_redacted"] is True
            assert "cagr" not in nested
            assert not (output / arm / "trades.csv").exists()
            assert not (output / arm / "equity_curve.csv").exists()
            assert not (output / arm / "account_state_latest.json").exists()
        realistic_nested = json.loads(
            (
                output / "spread_adv_impact" / "metrics.json"
            ).read_text(encoding="utf-8")
        )
        assert len(realistic_nested["paper_slippage_issues"]) == 1
        assert (
            realistic_nested["paper_slippage_issues"][0][
                "observed_slippage_bps"
            ]
            == 9_975.0
        )


def test_sidecar_pins_cash_carry_off_even_when_environment_enables_it() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "execution"
        cache.mkdir()
        _write_ohlcv(cache, "AAA", initial_close=100.0)
        _write_ohlcv(cache, "BBB", initial_close=50.0)
        targets = root / "targets.csv"
        _write_targets(targets)

        with patch.dict(
            os.environ,
            {"R1000_BROKER_CASH_CARRY_ENABLED": "1"},
            clear=False,
        ):
            payload = run(
                target_book=targets,
                price_cache=cache,
                output_dir=output,
                portfolio_kind="main",
                starting_capital=100_000.0,
                fill_mode="next_close",
                base_cost_bps=25.0,
                max_fill_lag_days=7,
                execution_cost_config=ExecutionCostConfig(
                    mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
                ),
            )

        assert payload["status"] == "completed"
        for arm in ("fixed_bps_control", "spread_adv_impact"):
            nested = json.loads(
                (output / arm / "metrics.json").read_text(encoding="utf-8")
            )
            assert "cash_carry_mode" not in nested
            assert "cash_interest_accrued_usd" not in nested
            assert "_cash_carry" not in str(nested["metric_mode"])


def test_concentrated_manifest_uses_replay_filtered_champion_tickers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        reports = root / "reports"
        output = root / "execution"
        cache.mkdir()
        reports.mkdir()
        for index, ticker in enumerate(("AAA", "BBB", "CCC", "DDD")):
            _write_ohlcv(
                cache,
                ticker,
                initial_close=100.0 + index * 10.0,
            )
        targets = reports / "concentrated_strategy_holdings.csv"
        rows = [
            {
                "rebalance_date": "2024-01-02",
                "ticker": ticker,
                "weight": 0.25,
                "target_stock_names": 4,
                "weighting_mode": "score_power",
                "active_rebalance_interval_months": 1,
            }
            for ticker in ("AAA", "BBB", "CCC", "DDD")
        ]
        rows.append(
            {
                "rebalance_date": "2024-01-02",
                "ticker": "MISSING",
                "weight": 1.0,
                "target_stock_names": 3,
                "weighting_mode": "score_power",
                "active_rebalance_interval_months": 1,
            }
        )
        pd.DataFrame(rows).to_csv(targets, index=False)
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
        ).to_csv(
            reports / "concentrated_strategy_comparison.csv",
            index=False,
        )

        payload = run(
            target_book=targets,
            price_cache=cache,
            output_dir=output,
            portfolio_kind="concentrated",
            starting_capital=100_000.0,
            fill_mode="next_close",
            base_cost_bps=25.0,
            max_fill_lag_days=7,
            execution_cost_config=ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
            ),
        )

        assert payload["status"] == "completed"
        manifest = json.loads(
            (output / "source_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["target_ticker_count"] == 4
        assert manifest["raw_target_ticker_count"] == 5
        assert manifest["replay_filtered_target_tickers"] == [
            "AAA",
            "BBB",
            "CCC",
            "DDD",
        ]
        assert manifest["excluded_raw_target_tickers"] == ["MISSING"]
        assert "MISSING" not in {
            row["ticker"] for row in manifest["price_sources"]
        }


def test_blocked_replay_report_never_fabricates_zero_performance() -> None:
    report = render_report(
        {
            "status": "blocked",
            "reason": "target_fill_coverage_incomplete",
            "performance_fields_redacted": True,
        }
    )
    assert "Performance metrics: unavailable" in report
    assert "CAGR:" not in report
    assert "Sharpe:" not in report
    assert "MaxDD:" not in report
    assert "0.00%" not in report
    assert "$0.00" not in report


def test_missing_target_price_source_blocks_manifest_even_without_trade() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "execution"
        cache.mkdir()
        _write_ohlcv(cache, "AAA")
        targets = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2024-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2024-01-02", "ticker": "MISSING", "weight": 0.40},
                {"rebalance_date": "2024-01-09", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2024-01-09", "ticker": "MISSING", "weight": 0.40},
            ]
        ).to_csv(targets, index=False)

        payload = run(
            target_book=targets,
            price_cache=cache,
            output_dir=output,
            portfolio_kind="main",
            starting_capital=100_000.0,
            fill_mode="next_close",
            base_cost_bps=25.0,
            max_fill_lag_days=7,
            execution_cost_config=ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
            ),
        )

        assert payload["status"] == "blocked"
        assert "price_source_manifest_incomplete" in payload["promotion_blockers"]
        assert payload["fixed_bps_control"]["performance_usable"] is False
        assert payload["fixed_bps_control"]["cagr"] is None
        assert payload["realistic_execution_cost"]["cagr"] is None
        assert payload["deltas_vs_fixed_bps"] == {}
        manifest = json.loads(
            (output / "source_manifest.json").read_text(encoding="utf-8")
        )
        missing = [
            row
            for row in manifest["price_sources"]
            if row["ticker"] == "MISSING"
        ]
        assert len(missing) == 1
        assert missing[0]["required_by_target_book"] is True
        assert missing[0]["present_in_realistic_trades"] is False
        assert missing[0]["sha256"] == ""
        assert missing[0]["liquidity_ohlcv_loadable"] is False


def test_stale_but_loadable_price_history_blocks_target_fill_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        output = root / "execution"
        cache.mkdir()
        _write_ohlcv(cache, "AAA")
        _write_ohlcv(
            cache,
            "STALE",
            start="2023-01-02",
            periods=20,
            initial_close=40.0,
        )
        targets = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2024-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2024-01-02", "ticker": "STALE", "weight": 0.40},
                {"rebalance_date": "2024-01-09", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2024-01-09", "ticker": "STALE", "weight": 0.40},
            ]
        ).to_csv(targets, index=False)
        for arm in ("fixed_bps_control", "spread_adv_impact"):
            stale_dir = output / arm
            stale_dir.mkdir(parents=True)
            (stale_dir / "equity_curve.csv").write_text(
                "date,equity_usd\n1999-01-01,999999\n",
                encoding="utf-8",
            )

        payload = run(
            target_book=targets,
            price_cache=cache,
            output_dir=output,
            portfolio_kind="main",
            starting_capital=100_000.0,
            fill_mode="next_close",
            base_cost_bps=25.0,
            max_fill_lag_days=7,
            execution_cost_config=ExecutionCostConfig(
                mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
            ),
        )

        assert payload["status"] == "blocked"
        assert "target_fill_coverage_incomplete" in payload["promotion_blockers"]
        manifest = json.loads(
            (output / "source_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["price_source_coverage_complete"] is True
        assert manifest["target_fill_coverage_complete"] is False
        assert manifest["required_target_fill_count"] == 4
        assert manifest["fillable_target_count"] == 2
        for arm in ("fixed_bps_control", "spread_adv_impact"):
            assert not (output / arm / "equity_curve.csv").exists()
            nested = json.loads(
                (output / arm / "metrics.json").read_text(encoding="utf-8")
            )
            assert nested["performance_fields_redacted"] is True
            assert "cagr" not in nested


def test_research_sidecar_is_wired_without_replacing_champion_metrics() -> None:
    sidecars = (REPO_ROOT / "tools" / "run_full_rebuild_sidecars.py").read_text(
        encoding="utf-8"
    )
    replay_workflow = (
        REPO_ROOT / ".github" / "workflows" / "alphaops_replay_sidecars_manual.yml"
    ).read_text(encoding="utf-8")
    full_workflow = (
        REPO_ROOT / ".github" / "workflows" / "full_rebuild_manual.yml"
    ).read_text(encoding="utf-8")
    for portfolio in ("main", "concentrated"):
        expected = (
            "tools/run_execution_cost_capacity_sidecar.py "
            f"--target-book outputs/reports/operating_{portfolio}_target_book.csv"
        )
        assert expected in sidecars
        assert expected in replay_workflow
        cleanup = f"rm -rf outputs/execution_cost_capacity/{portfolio}"
        assert cleanup in sidecars
        assert cleanup in replay_workflow
        assert replay_workflow.index(cleanup) < replay_workflow.index(
            expected
        )
    assert replay_workflow.count(
        '--max-fill-lag-days "$MAX_FILL_LAG_DAYS" '
        "--capacity-participation-rates"
    ) == 2
    assert "outputs/execution_cost_capacity/" in replay_workflow
    assert "outputs/execution_cost_capacity/" in full_workflow
    assert 'copy_dir_clean outputs/execution_cost_capacity "$DEST/execution_cost_capacity"' in full_workflow
    # The fixed 25bps broker replay remains the headline contract.
    assert "--output-dir outputs/broker_replay/main --fill-mode next_close --cost-bps 25" in sidecars
    assert "--output-dir outputs/execution_cost_capacity/main" in sidecars
    contract = json.loads(
        (
            REPO_ROOT / "docs" / "run287_execution_cost_capacity_contract.json"
        ).read_text(encoding="utf-8")
    )
    assert contract["status"] == "RESEARCH_ONLY_FAIL_CLOSED"
    assert contract["control_contract"]["unchanged_by_default"] is True
    assert contract["control_contract"]["cash_carry_mode"] == "none"
    assert (
        contract["control_contract"]["transition_fill_preflight"]
        == "BLOCK_BEFORE_STATE_MUTATION"
    )
    assert contract["governance"]["promotion_allowed"] is False
    assert contract["governance"]["fullrun_executed"] is False
    assert contract["capacity_contract"]["adv_participation_rates"] == [0.001, 0.005, 0.01]
    assert (
        contract["research_cost_contract"]["target_fill_coverage"][
            "incomplete_policy"
        ]
        == "BLOCK_AND_REDACT_PERFORMANCE"
    )
    assert (
        contract["research_cost_contract"]["paper_slippage"][
            "upper_bound_policy"
        ]
        == "BLOCK_BEFORE_STATE_MUTATION when observed_slippage_bps + base_cost_bps >= 10000"
    )


def main() -> int:
    test_price_loader_preserves_adjusted_ohlcv_for_liquidity()
    test_all_paper_date_aliases_use_new_york_trade_date()
    test_dynamic_affordability_solves_against_original_desired_quantity()
    test_asynchronous_transition_fill_dates_fail_closed()
    test_removed_target_requires_liquidation_fill_coverage()
    test_realistic_cost_replay_is_pit_and_more_conservative()
    test_missing_ohlcv_blocks_dynamic_cost_evidence()
    test_missing_liquidity_uses_larger_observed_paper_slippage()
    test_implausible_paper_slippage_fails_closed_without_state_artifacts()
    test_sidecar_pins_cash_carry_off_even_when_environment_enables_it()
    test_concentrated_manifest_uses_replay_filtered_champion_tickers()
    test_blocked_replay_report_never_fabricates_zero_performance()
    test_missing_target_price_source_blocks_manifest_even_without_trade()
    test_stale_but_loadable_price_history_blocks_target_fill_coverage()
    test_research_sidecar_is_wired_without_replacing_champion_metrics()
    print("execution_cost_capacity_sidecar_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
