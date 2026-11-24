#!/usr/bin/env python3
"""Focused helper checks for the Run287 P5 bounded evaluator."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.evaluate_run287_hold_exit_replacement import (  # noqa: E402
    attach_trade_taxonomy,
    contribution_concentration,
    counterfactuals,
    summarize_counterfactuals,
    embargo_metrics,
    holding_statistics,
)
from research.er_horizon_v1 import session63_exposure
from tools.run_free_data_forward_paper_ledger import load_nyse_sessions
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_prices(cache: Path, ticker: str, start: float) -> None:
    dates = load_nyse_sessions(pd.Timestamp("2022-12-01"), pd.Timestamp("2024-12-31"))
    closes = [start + index * 0.2 for index in range(len(dates))]
    pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Adj Close": closes, "Volume": 1_000_000},
        index=dates,
    ).to_parquet(cache / px_cache_name(ticker))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        cache.mkdir()
        write_prices(cache, "AAA", 100.0)
        write_prices(cache, "BBB", 100.0)
        decisions = pd.DataFrame([
            {
                "rebalance_date": "2023-01-31", "portfolio": "main",
                "incumbent_ticker": "AAA", "challenger_ticker": "BBB",
                "action": "RETAIN_INCUMBENT", "retained_weight": 0.10,
            }
        ])
        counter = counterfactuals(decisions, cache)
        assert len(counter) == 1
        assert pd.notna(counter.iloc[0]["incumbent_return_126d"])

        decision = decisions.assign(action="ALLOW_REPLACEMENT")
        reference = session63_exposure("2023-01-31")
        if (counter.at[0, "start_date_63d"], counter.at[0, "end_date_63d"]) != (
                reference["entry_at"][:10], reference["mark_at"][:10]):
            raise AssertionError("63 held NYSE intervals from the next close")
        if summarize_counterfactuals(counter)["paired_count_126d"] != 1:
            raise AssertionError("complete paired path")
        a = cache / px_cache_name("AAA")
        b = cache / px_cache_name("BBB")
        first = pd.Timestamp(counter.at[0, "start_date_21d"])
        original_a, original_b = pd.read_parquet(a), pd.read_parquet(b)
        original_b.drop(first).to_parquet(b)
        incomplete = counterfactuals(decision, cache)
        if pd.isna(incomplete.at[0, "incumbent_return_126d"]) or incomplete.at[0, "paired_dates_match_21d"]:
            raise AssertionError("unaligned challenger entry")
        if pd.notna(incomplete.at[0, "incumbent_minus_challenger_126d"]):
            raise AssertionError("no pair without both paths")
        missing_day = pd.Timestamp("2023-02-08")
        original_a.drop(missing_day).to_parquet(a)
        original_b.drop(missing_day).to_parquet(b)
        both_missing = counterfactuals(decision, cache)
        if both_missing.at[0, "paired_dates_match_21d"] or pd.notna(both_missing.at[0, "incumbent_return_21d"]):
            raise AssertionError("identical incomplete grids must not become a matched pair")
        contribution, _ = contribution_concentration(
            decisions, [pd.Timestamp("2023-01-31"), pd.Timestamp("2023-02-28")], cache)
        if len(contribution) != 1 or contribution["weighted_incremental_contribution"].notna().any():
            raise AssertionError("incomplete interval must not contribute")
        original_a.to_parquet(a)
        original_b.loc[:pd.Timestamp(counter.at[0, "end_date_63d"])].to_parquet(b)
        short = counterfactuals(decision, cache)
        if not short.at[0, "paired_dates_match_63d"] or short.at[0, "paired_dates_match_126d"]:
            raise AssertionError("each horizon matures independently")
        for invalid in (incomplete.assign(incumbent_minus_challenger_126d=1.0),
                        counter.assign(action="ALLOW_REPLACEMENT", end_date_126d="2023-12-31"),
                        counter.drop(columns="counterfactual_clock")):
            stats = summarize_counterfactuals(invalid)
            if stats["paired_count_126d"] or stats["premature_sell_regret_positive_count_126d"]:
                raise AssertionError("legacy or wrong-clock difference entered paired summary")
        original_b.to_parquet(b)

        replay_dir = root / "replay"
        replay_dir.mkdir()
        dates = pd.bdate_range("2023-01-02", periods=400)
        curve = pd.DataFrame({
            "date": dates, "equity_usd": [100000 + index * 100 for index in range(len(dates))],
            "cash_usd": 10000.0, "cash_weight": 0.10, "fill_mode": "next_close",
        })
        curve.to_csv(replay_dir / "equity_curve.csv", index=False)
        pd.DataFrame(columns=["date", "fee_usd", "gross_value"]).to_csv(replay_dir / "trades.csv", index=False)
        embargo = embargo_metrics(replay_dir, "2023-01-02")
        assert embargo["status"] == "completed", embargo
        assert embargo["embargo_sessions"] == 126

        trades = pd.DataFrame([
            {"date": "2023-01-03", "signal_date": "2023-01-02", "ticker": "AAA", "side": "BUY", "quantity": 10},
            {"date": "2024-02-01", "signal_date": "2024-01-31", "ticker": "AAA", "side": "SELL", "quantity": 10},
        ])
        intents = pd.DataFrame([
            {"signal_date": "2024-01-31", "ticker": "AAA", "sell_taxonomy": "REPLACEMENT_EXIT", "sell_taxonomy_reason": "fixed"}
        ])
        tagged = attach_trade_taxonomy(trades, intents)
        assert tagged.loc[tagged["side"].eq("SELL"), "sell_taxonomy"].iloc[0] == "REPLACEMENT_EXIT"
        holds = holding_statistics(trades, cache)
        assert holds["completed_lot_count"] == 1
        assert holds["pct_held_365d_plus"] == 1.0
    print("run287_hold_exit_evaluation_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
