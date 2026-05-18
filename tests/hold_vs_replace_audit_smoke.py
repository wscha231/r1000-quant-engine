#!/usr/bin/env python3
"""Smoke checks for hold-vs-replace audit."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_hold_vs_replace_audit import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float]) -> None:
    idx = pd.bdate_range("2026-01-02", periods=len(closes))
    pd.DataFrame(
        {"Open": closes, "Close": closes, "Adj Close": closes, "Volume": [1_000_000] * len(closes)},
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def test_hold_vs_replace_audit_flags_wrong_substitution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        trades_dir = latest / "broker_replay" / "main"
        trades_dir.mkdir(parents=True)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_px(cache, "AAA", [100, 100, 110, 120, 130, 140, 150, 160, 170, 180])
        _write_px(cache, "BBB", [100, 100, 98, 97, 95, 94, 93, 92, 91, 90])
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "side": "SELL",
                    "quantity": 10,
                    "fill_price": 100,
                    "gross_value": 1000,
                    "date": "2026-01-05",
                    "signal_date": "2026-01-02",
                },
                {
                    "ticker": "BBB",
                    "side": "BUY",
                    "quantity": 10,
                    "fill_price": 100,
                    "gross_value": 1000,
                    "date": "2026-01-05",
                    "signal_date": "2026-01-02",
                },
            ]
        ).to_csv(trades_dir / "trades.csv", index=False)
        out = root / "out"
        payload = run(
            argparse.Namespace(
                latest_run=str(latest),
                price_cache=str(cache),
                output_dir=str(out),
                portfolios="main",
                trades="",
                horizon_days=10,
                max_pair_lag_days=3,
                wrong_substitution_threshold=0.05,
            )
        )
        assert payload["status"] == "completed"
        summary = payload["portfolios"][0]
        assert summary["wrong_substitution_count"] == 1
        frame = pd.read_csv(out / "main" / "wrong_substitution.csv")
        assert bool(frame["wrong_substitution"].iloc[0])
        assert frame["sold_ticker"].iloc[0] == "AAA"
        assert frame["replacement_ticker"].iloc[0] == "BBB"
        assert frame["diagnostic_only"].iloc[0]


def main() -> int:
    test_hold_vs_replace_audit_flags_wrong_substitution()
    print("hold_vs_replace_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
