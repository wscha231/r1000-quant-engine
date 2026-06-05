#!/usr/bin/env python3
"""Smoke test for broker-ledger conversion of position-risk proxy rules."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_broker_position_risk_replay import RiskMeta, replay, risk_signal  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_prices(cache: Path, ticker: str, prices: list[tuple[str, float]]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "Open": [value for _, value in prices],
            "Close": [value for _, value in prices],
            "Adj Close": [value for _, value in prices],
        },
        index=pd.to_datetime([date for date, _ in prices]),
    )
    frame.to_parquet(cache / px_cache_name(ticker))


def test_broker_position_risk_replay_uses_next_close_risk_fills() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        dates = pd.bdate_range("2026-01-01", "2026-03-06")
        # Entry fills on 2026-01-02 at 100. The stop signal is observable after
        # the 2026-01-08 close at 91, then the account exits next close at 80.
        aaa_prices = []
        for date in dates:
            value = 100.0
            if date >= pd.Timestamp("2026-01-08"):
                value = 91.0
            if date >= pd.Timestamp("2026-01-09"):
                value = 80.0
            if date >= pd.Timestamp("2026-02-03"):
                value = 60.0
            aaa_prices.append((date.date().isoformat(), value))
        write_prices(cache, "AAA", aaa_prices)
        write_prices(cache, "SPY", [(date.date().isoformat(), 100.0) for date in dates])

        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-01", "ticker": "AAA", "weight": 1.0, "portfolio_monster_early_score": 0.0},
                {"rebalance_date": "2026-02-02", "ticker": "CASH", "weight": 1.0},
            ]
        ).to_csv(target, index=False)

        out = root / "out"
        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            hard_stop=-0.08,
            trailing_stop=-0.15,
            trailing_activation=0.15,
            relative_trim_threshold=-0.50,
            relative_exit_threshold=-0.60,
            cost_bps=0.0,
        )
        assert metrics["status"] == "completed"
        assert metrics["metric_mode"] == "broker_ledger_position_risk_next_close"
        assert metrics["valid_for_production"] is True
        actions = pd.read_csv(out / "risk_actions.csv")
        assert not actions.empty
        assert actions.iloc[0]["signal_date"] == "2026-01-08"
        assert actions.iloc[0]["fill_date"] == "2026-01-09"
        assert actions.iloc[0]["reason"] == "daily_hard_stop_exit"
        trades = pd.read_csv(out / "trades.csv")
        assert "period_forward_return" not in trades.columns
        assert (trades["reason"] == "daily_hard_stop_exit").any()
        assert (out / "account_state_latest.json").exists()


def test_distribution_exit_can_be_disabled_for_parabolic_replay() -> None:
    prices = {
        "SPY": pd.DataFrame(
            {"Close": [100.0]},
            index=pd.to_datetime(["2026-01-09"]),
        )
    }
    meta = RiskMeta(
        entry_price=100.0,
        entry_date=pd.Timestamp("2026-01-02"),
        peak_price=100.0,
        bench_entry_price=100.0,
        trim_done=False,
        row={
            "explosion_exit_score": 0.9,
            "stage2_overext_penalty": 0.0,
            "risk_penalty": 0.0,
            "rs_acceleration_score": -0.1,
        },
    )
    common = {
        "ticker": "AAA",
        "date": pd.Timestamp("2026-01-09"),
        "close_price": 97.0,
        "prices": prices,
        "benchmark_ticker": "SPY",
        "period_end": pd.Timestamp("2026-01-30"),
        "hard_stop": -9.0,
        "trailing_stop": -0.20,
        "trailing_activation": 0.50,
        "relative_trim_threshold": -9.0,
        "relative_exit_threshold": -9.0,
    }

    enabled = risk_signal(meta=meta, enable_distribution_exit=True, **common)
    assert enabled is not None
    assert enabled[1] == "weekly_distribution_exit"

    disabled_meta = RiskMeta(
        entry_price=100.0,
        entry_date=pd.Timestamp("2026-01-02"),
        peak_price=100.0,
        bench_entry_price=100.0,
        trim_done=False,
        row=meta.row,
    )
    disabled = risk_signal(meta=disabled_meta, enable_distribution_exit=False, **common)
    assert disabled is None


if __name__ == "__main__":
    test_broker_position_risk_replay_uses_next_close_risk_fills()
    test_distribution_exit_can_be_disabled_for_parabolic_replay()
    print("broker_position_risk_replay_smoke: PASS")
