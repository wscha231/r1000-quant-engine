#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_main_stress_condition_cap_broker_ab import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, *, extended: bool) -> None:
    dates = pd.bdate_range("2019-01-01", periods=430)
    base = np.linspace(100.0, 160.0 if extended else 112.0, len(dates))
    if extended:
        base[-120:] *= np.linspace(1.0, 1.55, 120)
    close = base + np.sin(np.arange(len(dates)) / (3.0 if extended else 13.0)) * (3.0 if extended else 0.5)
    frame = pd.DataFrame({"Close": close, "Adj Close": close}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_main_stress_condition_cap_broker_ab_runs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_price(cache, "BIG", extended=True)
        _write_price(cache, "MID", extended=False)
        _write_price(cache, "LOW", extended=False)

        target = root / "target.csv"
        rows = []
        for dt in ["2020-02-28", "2020-03-31", "2020-04-30"]:
            rows.extend(
                [
                    {
                        "rebalance_date": dt,
                        "ticker": "CASH",
                        "Name": "Cash",
                        "sector": "Cash",
                        "target_weight": 0.30,
                        "weight": 0.30,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "BIG",
                        "Name": "Big Extended",
                        "sector": "Technology",
                        "industry_group": "Software",
                        "target_weight": 0.24,
                        "weight": 0.24,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "MID",
                        "Name": "Mid",
                        "sector": "Technology",
                        "industry_group": "Hardware",
                        "target_weight": 0.23,
                        "weight": 0.23,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "LOW",
                        "Name": "Low",
                        "sector": "Industrials",
                        "industry_group": "Machinery",
                        "target_weight": 0.23,
                        "weight": 0.23,
                    },
                ]
            )
        pd.DataFrame(rows).to_csv(target, index=False)

        crisis = root / "daily_crisis_state.csv"
        pd.DataFrame(
            [
                {"date": "2020-02-28", "crisis_state": "WATCH", "spy_drawdown": -0.05},
                {"date": "2020-03-31", "crisis_state": "WATCH", "spy_drawdown": -0.04},
                {"date": "2020-04-30", "crisis_state": "GREEN", "spy_drawdown": -0.01},
            ]
        ).to_csv(crisis, index=False)

        out = root / "out"
        summary = run(
            target_book=target,
            price_cache=cache,
            crisis_state=crisis,
            output_dir=out,
            arms=("baseline", "large_ext_cap10", "large_ext_weak_cap10"),
            max_receive_weight=0.50,
            oos_start="2020-03-15",
            oos2_start="2020-03-01",
        )

        assert summary["research_only"] is True
        assert summary["production_activation_allowed"] is False
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()
        metrics = pd.read_csv(out / "arm_metrics.csv")
        assert set(metrics["arm"]) == {"baseline", "large_ext_cap10", "large_ext_weak_cap10"}
        assert metrics[metrics["arm"].eq("large_ext_cap10")]["applied_rows"].iloc[0] > 0
        changes = pd.read_csv(out / "arm_weight_changes.csv")
        assert not changes.empty
        capped = changes[(changes["arm"].eq("large_ext_cap10")) & (changes["predicate_matched"].astype(str).str.lower().eq("true"))]
        assert not capped.empty
        assert float(capped["adjusted_weight"].max()) <= 0.1000001


if __name__ == "__main__":
    test_main_stress_condition_cap_broker_ab_runs()
    print("main_stress_condition_cap_broker_ab_smoke: PASS")
