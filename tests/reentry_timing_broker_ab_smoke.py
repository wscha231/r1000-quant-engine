#!/usr/bin/env python3
"""Smoke checks for the re-entry timing broker A/B harness."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_reentry_timing_broker_ab import Arm, generate_reentry_target_book, main  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2020-01-01") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    frame = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    frame.to_parquet(cache_dir / px_cache_name(ticker))


def test_generate_reentry_target_book_uses_cash_and_resets_on_official_rebalance() -> None:
    base = pd.DataFrame(
        [
            {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
            {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.50},
            {"rebalance_date": "2026-01-30", "ticker": "AAA", "weight": 0.60},
            {"rebalance_date": "2026-01-30", "ticker": "CASH", "weight": 0.40},
        ]
    )
    base["rebalance_date"] = pd.to_datetime(base["rebalance_date"])
    events = pd.DataFrame(
        [
            {
                "sell_date": "2026-01-02",
                "trigger_date": "2026-01-05",
                "ticker": "BBB",
                "trigger": "reclaim_5pct",
                "trigger_hit": True,
                "trigger_above_ma200": True,
            },
            {
                "sell_date": "2026-01-02",
                "trigger_date": "2026-01-05",
                "ticker": "CCC",
                "trigger": "reclaim_5pct",
                "trigger_hit": True,
                "trigger_above_ma200": True,
            },
        ]
    )
    arm = Arm(
        name="smoke",
        trigger="reclaim_5pct",
        reentry_weight=0.10,
        max_additions_per_date=1,
        min_cash_after=0.03,
    )
    generated, applied, summary = generate_reentry_target_book(base, events, arm)

    assert summary["applied_count"] == 1
    assert len(applied) == 1
    added = generated[generated["rebalance_date"].eq("2026-01-05")]
    assert float(added.loc[added["ticker"].eq("BBB"), "weight"].iloc[0]) == 0.10
    assert float(added.loc[added["ticker"].eq("CASH"), "weight"].iloc[0]) == 0.40
    reset = generated[generated["rebalance_date"].eq("2026-01-30")]
    assert "BBB" not in set(reset["ticker"])

    gated = Arm(
        name="market_gated",
        trigger="reclaim_5pct",
        reentry_weight=0.10,
        require_market_above_ma200=True,
    )
    _, gated_applied, gated_summary = generate_reentry_target_book(
        base,
        events,
        gated,
        market_above_ma200={pd.Timestamp("2026-01-05"): False},
    )
    assert gated_summary["applied_count"] == 0
    assert gated_applied.empty


def test_cli_runs_broker_ab_on_synthetic_data() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        # BBB is sold at 100, then reclaims +5% after the cooldown while above
        # a populated MA200.  The trigger is PIT-only; later returns are audit.
        dates = pd.bdate_range("2020-01-01", periods=260)
        bbb_prices = [100.0] * 150 + [99.0, 100.0, 104.0, 106.0, 108.0] + [110.0] * (260 - 155)
        aaa_prices = [100.0 + i * 0.05 for i in range(260)]
        _write_px(cache, "AAA", aaa_prices)
        _write_px(cache, "BBB", bbb_prices)
        target = root / "target.csv"
        pd.DataFrame(
            [
                {"rebalance_date": dates[145].date().isoformat(), "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": dates[145].date().isoformat(), "ticker": "CASH", "weight": 0.50},
            ]
        ).to_csv(target, index=False)
        trades = root / "trades.csv"
        pd.DataFrame(
            [
                {
                    "ticker": "BBB",
                    "side": "SELL",
                    "quantity": 10,
                    "fill_price": 100.0,
                    "date": dates[150].date().isoformat(),
                    "reason": "target_exit",
                }
            ]
        ).to_csv(trades, index=False)
        output = root / "out"
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "run_reentry_timing_broker_ab.py",
                "--target-book",
                str(target),
                "--trades",
                str(trades),
                "--price-cache",
                str(cache),
                "--output-dir",
                str(output),
                "--arms",
                "smoke:reclaim_5pct:0.05:market:AAA",
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        payload = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert payload["production_activation_allowed"] is False
        assert payload["status"] == "completed"
        metrics = pd.read_csv(output / "arm_metrics.csv")
        assert set(metrics["arm"]) == {"baseline", "smoke"}
        assert int(metrics.loc[metrics["arm"].eq("smoke"), "applied_count"].iloc[0]) > 0
        assert (output / "smoke" / "broker" / "metrics.json").exists()


if __name__ == "__main__":
    test_generate_reentry_target_book_uses_cash_and_resets_on_official_rebalance()
    test_cli_runs_broker_ab_on_synthetic_data()
    print("reentry_timing_broker_ab_smoke: PASS")
