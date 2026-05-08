#!/usr/bin/env python3
"""Smoke checks for weekly mark-to-market evaluation sidecar."""
from __future__ import annotations

import tempfile
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_weekly_evaluation import px_cache_name, run


def _write_px(cache_dir: Path, ticker: str, start: str = "2026-01-02", periods: int = 70, step: float = 0.01) -> None:
    idx = pd.bdate_range(start=start, periods=periods)
    base = 100.0
    close = [base * ((1.0 + step) ** i) for i in range(periods)]
    df = pd.DataFrame(
        {
            "Open": close,
            "Close": close,
            "Adj Close": close,
            "Volume": [1_000_000] * periods,
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def test_weekly_evaluation_marks_to_weekly_and_reports_staleness() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        out = root / "weekly"
        reports.mkdir(parents=True)
        cache.mkdir()

        for ticker in ["AAA", "BBB", "SPY", "QQQ"]:
            _write_px(cache, ticker)

        pd.DataFrame(
            [
                {"ticker": "AAA", "rebalance_date": "2026-01-30", "weight": 0.60, "Name": "AAA Inc", "sector": "Tech"},
                {"ticker": "BBB", "rebalance_date": "2026-01-30", "weight": 0.30, "Name": "BBB Inc", "sector": "Tech"},
                {"ticker": "AAA", "rebalance_date": "2026-02-27", "weight": 0.50, "Name": "AAA Inc", "sector": "Tech"},
                {"ticker": "BBB", "rebalance_date": "2026-02-27", "weight": 0.40, "Name": "BBB Inc", "sector": "Tech"},
            ]
        ).to_csv(reports / "main_monthly_weights.csv", index=False)
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-30", "next_rebalance_date": "2026-02-27"},
                {"rebalance_date": "2026-02-27", "next_rebalance_date": "2026-03-31"},
            ]
        ).to_csv(reports / "regime_by_month.csv", index=False)

        pd.DataFrame(
            [
                {"ticker": "AAA", "rebalance_date": "2026-01-30", "weight": 0.50},
                {"ticker": "BBB", "rebalance_date": "2026-02-27", "weight": 0.50},
            ]
        ).to_csv(reports / "concentrated_strategy_holdings.csv", index=False)
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-30", "next_rebalance_date": "2026-02-27"},
                {"rebalance_date": "2026-02-27", "next_rebalance_date": "2026-03-31"},
            ]
        ).to_csv(reports / "concentrated_strategy_monthly.csv", index=False)
        pd.DataFrame([{"ticker": "AAA", "rebalance_date": "2026-04-15", "feature_date": "2026-04-15"}]).to_csv(
            latest / "scored_latest.csv",
            index=False,
        )

        payload = run(latest, out, cache, stale_days_threshold=10)
        assert payload["status"] == "stale"
        assert payload["latest_scored_date"] == "2026-04-15"
        assert payload["primary_weekly_eval_date"] == "2026-03-31"
        assert payload["scored_vs_weekly_eval_lag_days"] == 15
        assert (out / "weekly_equity_curve.csv").exists()
        assert (out / "weekly_freshness_audit.json").exists()
        assert (out / "weekly_freshness_audit.md").exists()

        curve = pd.read_csv(out / "weekly_equity_curve.csv")
        assert {"main", "concentrated"}.issubset(set(curve["portfolio_kind"]))
        assert curve["week_end_date"].max() == "2026-03-31"


def main() -> int:
    test_weekly_evaluation_marks_to_weekly_and_reports_staleness()
    print("weekly evaluation smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
