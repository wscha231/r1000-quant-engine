from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_reentry_timing_whipsaw_screen import main, screen  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_price_cache(root: Path, ticker: str, prices: list[float]) -> None:
    dates = pd.bdate_range("2020-01-01", periods=len(prices))
    frame = pd.DataFrame({"Close": prices, "Open": prices}, index=dates)
    frame.to_parquet(root / px_cache_name(ticker))


def _trades() -> pd.DataFrame:
    rows = [
        {
            "ticker": "WIN",
            "side": "SELL",
            "quantity": 10,
            "fill_price": 100.0,
            "date": "2020-01-02",
            "reason": "target_exit",
        },
        {
            "ticker": "WIN",
            "side": "BUY",
            "quantity": 10,
            "fill_price": 125.0,
            "date": "2020-01-17",
            "reason": "target_rebalance",
        },
        {
            "ticker": "LOSE",
            "side": "SELL",
            "quantity": 10,
            "fill_price": 100.0,
            "date": "2020-01-02",
            "reason": "target_exit",
        },
    ]
    d = pd.DataFrame(rows)
    d["date"] = pd.to_datetime(d["date"])
    return d


def test_screen_fires_from_price_path_and_keeps_forward_audit_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        _write_price_cache(cache, "WIN", [100, 99, 98, 101, 106, 110, 115, 120, 125, 130] + [130] * 70)
        _write_price_cache(cache, "LOSE", [100, 99, 98, 101, 106, 96, 90, 88, 85, 84] + [84] * 70)
        events, summary, payload = screen(
            trades=_trades(),
            price_cache=cache,
            cooldown_trading_days=2,
            max_horizon_trading_days=20,
            triggers=["reclaim_5pct"],
        )
        assert payload["forward_columns_used_for_trigger"] is False
        assert int(events["trigger_hit"].sum()) == 2
        row = events[(events["ticker"].eq("WIN")) & (events["trigger_hit"].eq(True))].iloc[0]
        assert row["saved_premium_vs_actual_rebuy_audit_only"] > 0
        assert "forward_20d_return_audit_only" in events.columns
        trigger_summary = summary.iloc[0].to_dict()
        assert trigger_summary["trigger_count"] == 2
        assert trigger_summary["saved_premium_positive_rate"] == 1.0


def test_cli_writes_screen_outputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_price_cache(cache, "WIN", [100, 99, 98, 101, 106, 110, 115, 120, 125, 130] + [130] * 70)
        trades = root / "trades.csv"
        _trades()[_trades()["ticker"].eq("WIN")].to_csv(trades, index=False)
        output = root / "out"
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "run_reentry_timing_whipsaw_screen.py",
                "--trades",
                str(trades),
                "--price-cache",
                str(cache),
                "--output-dir",
                str(output),
                "--triggers",
                "reclaim_5pct",
                "--cooldown-trading-days",
                "2",
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        assert (output / "summary.json").exists()
        assert (output / "reentry_trigger_events.csv").exists()
        assert (output / "reentry_trigger_summary.csv").exists()


if __name__ == "__main__":
    test_screen_fires_from_price_path_and_keeps_forward_audit_only()
    test_cli_writes_screen_outputs()
    print("reentry_timing_whipsaw_screen_smoke: PASS")
