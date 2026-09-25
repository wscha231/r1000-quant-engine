#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_main_event_defense_broker_ab import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    frame = pd.DataFrame({"Open": closes, "Close": closes, "Adj Close": closes, "Volume": [1_000_000] * len(closes)}, index=idx)
    frame.to_parquet(cache_dir / px_cache_name(ticker))


def test_main_event_defense_broker_ab_runs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_px(cache, "AAA", [100, 99, 88, 86, 83, 82, 84, 85, 86, 88, 91, 93, 94, 96, 98, 101])
        _write_px(cache, "BBB", [50, 50, 51, 51, 52, 52, 53, 53, 54, 54, 55, 55, 56, 57, 58, 59])
        _write_px(cache, "SPY", [400, 398, 390, 385, 380, 379, 381, 384, 386, 390, 394, 397, 399, 402, 405, 407])

        target = root / "main_target.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50, "target_weight": 0.50, "sector": "Technology", "industry_group": "Software"},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.45, "target_weight": 0.45, "sector": "Industrials", "industry_group": "Machinery"},
                {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.05, "target_weight": 0.05, "sector": "Cash", "industry_group": ""},
                {"rebalance_date": "2026-01-16", "ticker": "BBB", "weight": 0.95, "target_weight": 0.95, "sector": "Industrials", "industry_group": "Machinery"},
                {"rebalance_date": "2026-01-16", "ticker": "CASH", "weight": 0.05, "target_weight": 0.05, "sector": "Cash", "industry_group": ""},
            ]
        ).to_csv(target, index=False)

        crisis = root / "daily_crisis_state.csv"
        pd.DataFrame(
            [
                {"date": "2026-01-02", "crisis_state": "GREEN", "crisis_score": 0.0},
                {"date": "2026-01-06", "crisis_state": "DEFENSE_REVIEW", "crisis_score": 0.7},
                {"date": "2026-01-09", "crisis_state": "GREEN", "crisis_score": 0.0},
            ]
        ).to_csv(crisis, index=False)

        out = root / "out"
        summary = run(
            target_book=target,
            price_cache=cache,
            crisis_state=crisis,
            output_dir=out,
            arms=("baseline_monthly", "event_default", "crisis_cash_preserve_strict"),
            oos_start="2026-01-08",
            oos2_start="2026-01-05",
        )

        assert summary["research_only"] is True
        assert summary["production_activation_allowed"] is False
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()
        arm_metrics = pd.read_csv(out / "arm_metrics.csv")
        assert set(arm_metrics["arm"]) == {"baseline_monthly", "event_default", "crisis_cash_preserve_strict"}
        assert arm_metrics[arm_metrics["arm"].eq("baseline_monthly")]["verdict"].iloc[0] == "reference"
        assert int(arm_metrics[arm_metrics["arm"].eq("event_default")]["event_count"].iloc[0]) > 0
        assert int(arm_metrics[arm_metrics["arm"].eq("crisis_cash_preserve_strict")]["daily_crisis_event_count"].iloc[0]) > 0
        assert (out / "event_default" / "target_book.csv").exists()
        assert (out / "event_default" / "broker" / "metrics.json").exists()


if __name__ == "__main__":
    test_main_event_defense_broker_ab_runs()
    print("main_event_defense_broker_ab_smoke: PASS")
