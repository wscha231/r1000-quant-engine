#!/usr/bin/env python3
"""Smoke tests for the cost-sensitivity sidecar.

Verifies that the sidecar:
  * runs 4 cost levels and emits one row per level
  * computes baseline-relative deltas
  * shows higher costs erode CAGR / ending capital monotonically
  * publishes the schema fields the auto policy challenger looks for
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_cost_sensitivity_sidecar import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2024-01-02") -> None:
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


def test_cost_sensitivity_sweep_emits_four_levels_and_monotonic_cost_drag() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "cost_sensitivity"
        cache.mkdir()
        # 60 business days of steadily-rising synthetic prices with weekly
        # rotation so trades happen at every rebalance regardless of cost.
        rising = [100.0 + i * 0.30 for i in range(60)]
        slow = [50.0 + i * 0.05 for i in range(60)]
        _write_px(cache, "AAA", rising, start="2024-01-02")
        _write_px(cache, "BBB", slow, start="2024-01-02")

        target = root / "targets.csv"
        rows = []
        # Alternate weighting every week to force turnover so cost drag is visible.
        rebalance_dates = [
            "2024-01-02", "2024-01-09", "2024-01-16", "2024-01-23",
            "2024-01-30", "2024-02-06", "2024-02-13", "2024-02-20",
        ]
        for i, dt in enumerate(rebalance_dates):
            if i % 2 == 0:
                rows.append({"rebalance_date": dt, "ticker": "AAA", "weight": 0.70})
                rows.append({"rebalance_date": dt, "ticker": "BBB", "weight": 0.20})
            else:
                rows.append({"rebalance_date": dt, "ticker": "AAA", "weight": 0.20})
                rows.append({"rebalance_date": dt, "ticker": "BBB", "weight": 0.70})
        pd.DataFrame(rows).to_csv(target, index=False)

        payload = run(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            cost_bps_list=[25.0, 50.0, 75.0, 100.0],
            starting_capital=10_000.0,
            fill_mode="next_close",
            max_fill_lag_days=7,
            baseline_cost_bps=25.0,
        )

        assert payload["schema_version"] == "cost-sensitivity-sidecar-v1"
        assert payload["portfolio_kind"] == "main"
        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        levels = payload["levels"]
        assert len(levels) == 4
        # Levels sorted ascending by cost.
        assert [lv["cost_bps"] for lv in levels] == [25.0, 50.0, 75.0, 100.0]
        # Higher cost should not produce higher ending capital, given the
        # same target book and a non-zero-turnover policy.
        endings = [lv["ending_capital_usd"] for lv in levels]
        assert endings[0] >= endings[1] >= endings[2] >= endings[3], endings
        # Baseline row reports zero delta against itself; later levels are non-positive.
        assert levels[0]["cagr_delta_pp_vs_baseline"] == 0.0
        for lv in levels[1:]:
            assert lv["cagr_delta_pp_vs_baseline"] <= 0.0 + 1e-6, lv
            assert lv["total_fees_usd"] >= levels[0]["total_fees_usd"]
        # Output files exist and are valid JSON / non-empty markdown.
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["portfolio_kind"] == "main"
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "Cost Sensitivity Sidecar" in report
        assert "Cost bps" in report


def test_cost_sensitivity_handles_single_level() -> None:
    """Edge case: a single cost level produces one row and no monotonicity claim."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "cost_sensitivity"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0] * 20, start="2024-01-02")
        target = root / "targets.csv"
        pd.DataFrame([{"rebalance_date": "2024-01-02", "ticker": "AAA", "weight": 1.0}]).to_csv(target, index=False)

        payload = run(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            cost_bps_list=[50.0],
            starting_capital=10_000.0,
            fill_mode="next_close",
            max_fill_lag_days=7,
            baseline_cost_bps=25.0,
        )
        assert len(payload["levels"]) == 1
        assert payload["levels"][0]["cost_bps"] == 50.0


def main() -> int:
    test_cost_sensitivity_sweep_emits_four_levels_and_monotonic_cost_drag()
    test_cost_sensitivity_handles_single_level()
    print("cost_sensitivity_sidecar_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
