#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_concentrated_cap_replacement_broker_counterfactual import (  # noqa: E402
    portfolio_concentration_delta,
    portfolio_concentration_metrics,
    run,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_counterfactual_swaps_existing_slots_without_cash_reduction() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        for ticker, closes in {
            "AAA": [100.0] * 80,
            "BBB": [100.0] * 80,
            "CCC": [100.0 + i for i in range(80)],
            "DDD": [80.0 + i * 0.5 for i in range(80)],
        }.items():
            _write_px(cache, ticker, closes)

        target = root / "target_book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.30, "target_weight": 0.30, "alphaops_vnext_score": 1.0, "production_policy": "alphaops_vnext_production"},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.20, "target_weight": 0.20, "alphaops_vnext_score": 0.2, "production_policy": "alphaops_vnext_production"},
                {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.50, "target_weight": 0.50, "production_policy": "alphaops_vnext_production"},
                {"rebalance_date": "2026-02-02", "ticker": "AAA", "weight": 0.30, "target_weight": 0.30, "alphaops_vnext_score": 1.0, "production_policy": "alphaops_vnext_production"},
                {"rebalance_date": "2026-02-02", "ticker": "BBB", "weight": 0.20, "target_weight": 0.20, "alphaops_vnext_score": 0.2, "production_policy": "alphaops_vnext_production"},
                {"rebalance_date": "2026-02-02", "ticker": "CASH", "weight": 0.50, "target_weight": 0.50, "production_policy": "alphaops_vnext_production"},
            ]
        ).to_csv(target, index=False)

        missed = root / "missed_leaders_audit.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "portfolio": "concentrated",
                    "rejection_reason": "cap_or_replacement",
                    "ticker": "CCC",
                    "leader_rank_ex_ante": 4,
                    "rs_spy_3m": 0.35,
                    "revenue_growth": 0.12,
                    "historical_valid": True,
                    "ex_ante_source_valid": True,
                    "missed_leader_historical_audit_allowed": True,
                    "used_forward_return_in_ranking": False,
                    "forward_126d_excess": 0.5,
                    "sector": "Technology",
                },
                {
                    "rebalance_date": "2026-02-02",
                    "portfolio": "concentrated",
                    "rejection_reason": "cap_or_replacement",
                    "ticker": "DDD",
                    "leader_rank_ex_ante": 12,
                    "rs_spy_3m": 0.22,
                    "revenue_growth": 0.03,
                    "historical_valid": True,
                    "ex_ante_source_valid": True,
                    "missed_leader_historical_audit_allowed": True,
                    "used_forward_return_in_ranking": False,
                    "forward_126d_excess": 0.2,
                    "sector": "Industrials",
                },
            ]
        ).to_csv(missed, index=False)

        baseline = root / "baseline_metrics.json"
        baseline_payload = {
            "status": "completed",
            "end_date": "2026-03-31",
            "cagr": 0.10,
            "max_dd": -0.20,
            "sharpe": 0.5,
            "windows": {
                "full": {"status": "completed", "cagr": 0.10, "max_dd": -0.20, "sharpe": 0.5},
                "is": {"status": "completed", "cagr": 0.05, "max_dd": -0.10, "sharpe": 0.4},
                "oos": {"status": "completed", "cagr": 0.08, "max_dd": -0.12, "sharpe": 0.5},
                "oos2": {"status": "completed", "cagr": 0.09, "max_dd": -0.14, "sharpe": 0.45},
            },
        }
        baseline.write_text(json.dumps(baseline_payload), encoding="utf-8")

        args = argparse.Namespace(
            target_book=str(target),
            missed_leaders=str(missed),
            price_cache=str(cache),
            baseline_metrics=str(baseline),
            source_doc=str(root / "source.md"),
            output_dir=str(root / "out"),
            arms="rank_top15,rs3_ge30",
            max_swaps_per_date=1,
            starting_capital=10000.0,
            cost_bps=25.0,
            fractional_shares=False,
            max_fill_lag_days=7,
            max_reasonable_weight_sum=1.05,
            replay_end_date="2026-03-31",
            oos_start="2026-02-01",
            oos_end="",
            oos2_start="2026-01-15",
            oos2_end="",
            cash_carry_mode="none",
            cash_rate_source=None,
            cash_rate_path=None,
            cash_rate_lag_days=None,
            cash_carry_haircut_bps=None,
            cash_carry_day_count=None,
        )
        payload = run(args)
        assert payload["status"] == "completed", payload
        assert payload["cash_carry_mode"] == "none"
        assert payload["baseline_cash_carry_mode"] == "none"
        assert payload["baseline_cash_carry_comparable"] is True
        assert payload["research_only"] is True
        assert payload["fullrun_executed"] is False
        assert payload["production_mutation_allowed"] is False
        assert payload["forward_labels_used_for_ranking"] is False

        arms = {arm["rule"]: arm for arm in payload["arms"]}
        assert arms["rank_top15"]["status"] == "completed", arms["rank_top15"]
        assert arms["rank_top15"]["swap_count"] == 2
        assert arms["rank_top15"]["cash_weight_max_abs_delta"] == 0.0
        assert arms["rank_top15"]["broad_cash_reduction"] is False
        assert arms["rank_top15"]["cap_breach"] is False
        assert arms["rank_top15"]["metric_deltas"]["full"]["status"] == "completed"
        assert arms["rank_top15"]["concentration"]["unique_added_ticker_count"] == 2

        rs30_swaps = pd.read_csv(root / "out" / "rs3_ge30" / "swaps.csv")
        assert set(rs30_swaps["added_ticker"]) == {"CCC"}
        challenger = pd.read_csv(root / "out" / "rank_top15" / "target_book.csv")
        cash = challenger[challenger["ticker"].eq("CASH")].groupby("rebalance_date")["weight"].sum()
        assert (cash == 0.50).all()
        assert (root / "out" / "arm_metrics.csv").exists()
        assert "Forward returns remain audit labels only" in (root / "out" / "report.md").read_text(encoding="utf-8")


def test_portfolio_concentration_metrics_from_holdings_daily() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        challenger = root / "challenger"
        baseline.mkdir()
        challenger.mkdir()
        pd.DataFrame(
            [
                {"date": "2026-01-02", "ticker": "AAA", "weight": 0.35},
                {"date": "2026-01-02", "ticker": "BBB", "weight": 0.25},
                {"date": "2026-01-02", "ticker": "CASH", "weight": 0.40},
                {"date": "2026-01-03", "ticker": "AAA", "weight": 0.40},
                {"date": "2026-01-03", "ticker": "BBB", "weight": 0.20},
                {"date": "2026-01-03", "ticker": "CASH", "weight": 0.40},
            ]
        ).to_csv(baseline / "holdings_daily.csv", index=False)
        pd.DataFrame(
            [
                {"date": "2026-01-03", "ticker": "CCC", "weight": 0.46},
                {"date": "2026-01-03", "ticker": "BBB", "weight": 0.20},
                {"date": "2026-01-03", "ticker": "CASH", "weight": 0.34},
            ]
        ).to_csv(challenger / "holdings_daily.csv", index=False)

        base = portfolio_concentration_metrics(baseline)
        chal = portfolio_concentration_metrics(challenger)
        delta = portfolio_concentration_delta(base, chal)
        expected_hhi = (0.46 / 0.66) ** 2 + (0.20 / 0.66) ** 2
        assert chal["status"] == "completed"
        assert chal["latest_top_ticker"] == "CCC"
        assert abs(chal["latest_stock_hhi"] - expected_hhi) < 1e-12
        assert abs(delta["latest_top1_delta"] - 0.06) < 1e-12
        assert delta["latest_top_ticker_changed"] is True
        assert delta["portfolio_concentration_warning"] is True


def main() -> int:
    test_counterfactual_swaps_existing_slots_without_cash_reduction()
    test_portfolio_concentration_metrics_from_holdings_daily()
    print("concentrated_cap_replacement_broker_counterfactual_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
