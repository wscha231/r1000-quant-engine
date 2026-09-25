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

from tools.run_main_crash_fragility_screen import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price(cache: Path, ticker: str, start: float, *, crash: bool = False) -> None:
    dates = pd.bdate_range("2020-01-01", periods=260)
    drift = np.linspace(0.0, 0.30 if not crash else 0.10, len(dates))
    noise = np.sin(np.arange(len(dates)) / (3.0 if crash else 11.0)) * (0.08 if crash else 0.015)
    close = start * (1.0 + drift + noise)
    if crash:
        close[80:120] *= np.linspace(1.0, 0.60, 40)
        close[120:] *= 0.60
    frame = pd.DataFrame({"Close": close, "Adj Close": close}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_main_crash_fragility_screen_outputs_research_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_price(cache, "FRAG", 100.0, crash=True)
        _write_price(cache, "CALM", 100.0, crash=False)
        target = root / "target.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2020-04-30",
                    "ticker": "FRAG",
                    "target_weight": 0.20,
                    "sector": "Consumer Discretionary",
                    "industry_group": "Gaming",
                    "rs_benchmark_3m": -0.20,
                    "atr14_pct": 0.09,
                    "price_above_ma200": 0.0,
                },
                {
                    "rebalance_date": "2020-04-30",
                    "ticker": "CALM",
                    "target_weight": 0.20,
                    "sector": "Information Technology",
                    "industry_group": "Software",
                    "rs_benchmark_3m": 0.20,
                    "atr14_pct": 0.02,
                    "price_above_ma200": 1.0,
                },
            ]
        ).to_csv(target, index=False)
        crisis = root / "daily_crisis_state.csv"
        pd.DataFrame(
            [
                {"date": "2020-04-29", "crisis_state": "WATCH", "spy_drawdown": -0.08},
                {"date": "2020-04-30", "crisis_state": "WATCH", "spy_drawdown": -0.09},
            ]
        ).to_csv(crisis, index=False)

        out = root / "out"
        summary = run(target_book=target, price_cache=cache, crisis_state=crisis, output_dir=out)

        assert summary["research_only"] is True
        assert summary["production_activation_allowed"] is False
        assert summary["rows"] == 2
        assert (out / "summary.json").exists()
        assert (out / "fragility_rows.csv").exists()
        assert (out / "fragility_bucket_report.csv").exists()
        rows = pd.read_csv(out / "fragility_rows.csv")
        assert "main_crash_fragility_score" in rows.columns
        assert "audit_forward_return_42d" in rows.columns
        frag = rows[rows["ticker"].eq("FRAG")]["main_crash_fragility_score"].iloc[0]
        calm = rows[rows["ticker"].eq("CALM")]["main_crash_fragility_score"].iloc[0]
        assert frag > calm


if __name__ == "__main__":
    test_main_crash_fragility_screen_outputs_research_artifacts()
    print("main_crash_fragility_screen_smoke: PASS")
