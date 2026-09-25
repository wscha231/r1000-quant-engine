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

from tools.run_main_stress_window_attribution import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, *, fragile: bool) -> None:
    dates = pd.bdate_range("2020-01-01", periods=220)
    close = np.full(len(dates), 100.0)
    close *= 1.0 + np.linspace(0.0, 0.20, len(dates))
    if fragile:
        close += np.sin(np.arange(len(dates)) / 2.0) * 8.0
        close[(dates >= "2020-02-20") & (dates <= "2020-03-18")] *= 0.65
        close[(dates >= "2020-05-20") & (dates <= "2020-06-18")] *= 0.65
    else:
        close += np.sin(np.arange(len(dates)) / 10.0) * 1.0
        close[(dates >= "2020-02-20") & (dates <= "2020-03-18")] *= 0.95
        close[(dates >= "2020-05-20") & (dates <= "2020-06-18")] *= 0.95
    frame = pd.DataFrame({"Close": close, "Adj Close": close}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_stress_window_attribution_reports_predicates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_price(cache, "FRAG", fragile=True)
        _write_price(cache, "CALM", fragile=False)
        target = root / "target.csv"
        rows = []
        for dt in ["2020-01-31", "2020-04-30"]:
            rows.extend(
                [
                    {
                        "rebalance_date": dt,
                        "ticker": "FRAG",
                        "target_weight": 0.20,
                        "sector": "Consumer Discretionary",
                        "industry_group": "Gaming",
                        "rs_benchmark_3m": 0.20,
                        "atr14_pct": 0.10,
                        "price_above_ma200": 1.0,
                    },
                    {
                        "rebalance_date": dt,
                        "ticker": "CALM",
                        "target_weight": 0.20,
                        "sector": "Information Technology",
                        "industry_group": "Software",
                        "rs_benchmark_3m": 0.10,
                        "atr14_pct": 0.01,
                        "price_above_ma200": 1.0,
                    },
                ]
            )
        pd.DataFrame(rows).to_csv(target, index=False)
        crisis = root / "daily_crisis_state.csv"
        pd.DataFrame(
            [
                {"date": "2020-01-31", "crisis_state": "GREEN", "spy_drawdown": 0.0},
                {"date": "2020-04-30", "crisis_state": "GREEN", "spy_drawdown": 0.0},
            ]
        ).to_csv(crisis, index=False)
        out = root / "out"
        summary = run(
            target_book=target,
            price_cache=cache,
            crisis_state=crisis,
            output_dir=out,
            stress_windows="2020-02-19:2020-03-18,2020-05-19:2020-06-18",
            min_windows=2,
        )

        assert summary["research_only"] is True
        assert summary["production_activation_allowed"] is False
        assert summary["stress_rows"] > 0
        assert (out / "predicate_report.csv").exists()
        report = pd.read_csv(out / "predicate_report.csv")
        assert not report.empty
        assert "predicate" in report.columns


if __name__ == "__main__":
    test_stress_window_attribution_reports_predicates()
    print("main_stress_window_attribution_smoke: PASS")
