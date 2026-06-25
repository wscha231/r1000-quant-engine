#!/usr/bin/env python3
"""Smoke test for right-tail drop counterfactual audit."""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_right_tail_drop_counterfactual_audit import run, segment_summary  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, start: float, step: float) -> None:
    dates = pd.bdate_range("2024-03-01", periods=150)
    values = [start + i * step for i in range(len(dates))]
    frame = pd.DataFrame({"Close": values, "Adj Close": values, "Open": values}, index=dates)
    cache.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache / px_cache_name(ticker))


def _write_fixture(root: Path) -> tuple[Path, Path]:
    latest = root / "latest"
    alphaops = latest / "alphaops_vnext"
    reports = latest / "reports"
    alphaops.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    target_rows = [
        {"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 0.25},
        {"rebalance_date": "2024-02-29", "ticker": "BBB", "weight": 0.25},
    ]
    for portfolio in ("main", "concentrated"):
        pd.DataFrame(target_rows).to_csv(alphaops / f"official_{portfolio}_target_book.csv", index=False)
    pd.DataFrame(
        [
            {
                "rebalance_date": "2024-02-29",
                "ticker": "AAA",
                "score": 99.0,
                "rs_benchmark_3m": 0.25,
                "rs_benchmark_6m": 0.40,
                "price_above_ma200": 1.0,
                "oneil_leadership_score": 0.90,
                "future_winner_scout_score": 0.95,
                "industry_group_strength_score": 0.80,
                "h6_dynamic_leader_score": 0.70,
                "eps_revision_score": 0.65,
                "actual_results_score": 0.85,
                "entry_quality_score": 0.75,
                "overheat_penalty": 0.0,
                "sector": "Information Technology",
                "industry_group": "Semiconductors",
                "portfolio_sleeve_label": "future_winner",
                "market_style_regime_label": "balanced",
                "regime_state": "bull",
                "period_forward_return": 9.99,
            },
            {
                "rebalance_date": "2024-02-29",
                "ticker": "BBB",
                "score": 5.0,
                "rs_benchmark_3m": -0.02,
                "period_forward_return": -9.99,
            },
        ]
    ).to_csv(reports / "candidate_replay_book.csv", index=False)
    cache = root / "cache_prices"
    _write_price(cache, "AAA", 100.0, 1.0)
    _write_price(cache, "SPY", 100.0, 0.05)
    _write_price(cache, "QQQ", 100.0, 0.05)
    _write_price(cache, "SMH", 100.0, 0.05)
    _write_price(cache, "SOXX", 100.0, 0.05)
    return latest, cache


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest, cache = _write_fixture(root)
        out = root / "out"
        payload = run(latest, cache, out, ("main", "concentrated"))
        assert payload["schema_version"] == "right-tail-drop-counterfactual-audit-v2"
        assert payload["research_only"] is True
        assert payload["used_forward_return_in_ranking"] is False
        assert (out / "summary.json").exists()
        assert (out / "drop_counterfactuals.csv").exists()
        assert (out / "segment_summary.csv").exists()
        assert (out / "report.md").exists()
        for portfolio in ("main", "concentrated"):
            block = payload["portfolios"][portfolio]
            assert block["status"] == "completed", block
            assert block["drop_event_count"] == 1, block
            assert block["skill_signal_drop_count"] == 1, block
            assert block["high_signal_drop_count"] == 1, block
            assert block["missed_rebound_63d_spy_count"] == 1, block
            assert block["missed_rebound_126d_spy_count"] == 1, block
            assert block["high_signal_missed_rebound_63d_spy_count"] == 1, block
            assert block["high_signal_missed_rebound_126d_spy_count"] == 1, block
            assert block["segment_summary_rows"] == 0, block
            rows = pd.read_csv(out / portfolio / "drop_counterfactuals.csv")
            assert rows.loc[0, "ticker"] == "AAA"
            assert rows.loc[0, "drop_date"] == "2024-02-29"
            assert rows.loc[0, "candidate_sector"] == "Information Technology"
            assert rows.loc[0, "candidate_industry_group"] == "Semiconductors"
            assert bool(rows.loc[0, "drop_skill_evidence_flag"]) is True
            assert bool(rows.loc[0, "missed_rebound_63d_spy_flag"]) is True
            assert bool(rows.loc[0, "used_forward_return_in_ranking"]) is False
            assert float(rows.loc[0, "fwd_63d_excess_spy"]) > 0.0
            assert "period_forward_return" not in rows.columns
            segments = pd.read_csv(out / portfolio / "segment_summary.csv")
            assert segments.empty
        combined = pd.read_csv(out / "drop_counterfactuals.csv")
        assert len(combined) == 2
        combined_segments = pd.read_csv(out / "segment_summary.csv")
        assert combined_segments.empty
        synthetic_segments = segment_summary(
            pd.DataFrame(
                [
                    {
                        "drop_skill_evidence_flag": True,
                        "candidate_rank_percentile": 0.95,
                        "drop_signal_stack_count": 7,
                        "candidate_sector": "Information Technology",
                        "candidate_industry_group": "Semiconductors",
                        "candidate_portfolio_sleeve_label": "future_winner",
                        "candidate_market_style_regime_label": "balanced",
                        "candidate_regime_state": "bull",
                        "fwd_63d_excess_spy": 0.10,
                        "fwd_126d_excess_spy": 0.20,
                    },
                    {
                        "drop_skill_evidence_flag": True,
                        "candidate_rank_percentile": 0.90,
                        "drop_signal_stack_count": 8,
                        "candidate_sector": "Information Technology",
                        "candidate_industry_group": "Semiconductors",
                        "candidate_portfolio_sleeve_label": "future_winner",
                        "candidate_market_style_regime_label": "balanced",
                        "candidate_regime_state": "bull",
                        "fwd_63d_excess_spy": 0.20,
                        "fwd_126d_excess_spy": 0.30,
                    },
                    {
                        "drop_skill_evidence_flag": True,
                        "candidate_rank_percentile": 0.85,
                        "drop_signal_stack_count": 7,
                        "candidate_sector": "Information Technology",
                        "candidate_industry_group": "Semiconductors",
                        "candidate_portfolio_sleeve_label": "future_winner",
                        "candidate_market_style_regime_label": "balanced",
                        "candidate_regime_state": "bull",
                        "fwd_63d_excess_spy": -0.05,
                        "fwd_126d_excess_spy": 0.10,
                    },
                ]
            )
        )
        high_signal = synthetic_segments[
            synthetic_segments["subset"].eq("high_signal")
            & synthetic_segments["group_column"].eq("candidate_sector")
        ]
        assert not high_signal.empty
        assert high_signal.iloc[0]["group_value"] == "Information Technology"
        assert abs(float(high_signal.iloc[0]["avg_126d_excess_spy"]) - 0.20) < 1e-9
        assert bool(high_signal.iloc[0]["used_forward_return_in_ranking"]) is False
    print("right-tail drop counterfactual audit smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
