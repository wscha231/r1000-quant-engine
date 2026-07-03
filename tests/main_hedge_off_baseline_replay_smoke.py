#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_main_hedge_off_baseline_replay import remove_hedge_to_cash, run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


class Args:
    pass


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


def _book() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50, "target_weight": 0.50},
            {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.30, "target_weight": 0.30},
            {"rebalance_date": "2026-01-02", "ticker": "SH", "weight": 0.075, "target_weight": 0.075},
            {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.125, "target_weight": 0.125},
            {"rebalance_date": "2026-01-09", "ticker": "AAA", "weight": 0.60, "target_weight": 0.60},
            {"rebalance_date": "2026-01-09", "ticker": "CASH", "weight": 0.40, "target_weight": 0.40},
        ]
    )


def test_remove_hedge_moves_weight_to_cash() -> None:
    out, audit, summary = remove_hedge_to_cash(_book(), hedge_ticker="SH", portfolio_kind="main")
    assert summary["status"] == "completed"
    assert summary["removed_hedge_rows"] == 1
    assert summary["hedge_signal_dates"] == 1
    assert "SH" not in set(out["ticker"])
    day = out[out["rebalance_date"].eq("2026-01-02")]
    assert abs(float(day.loc[day["ticker"].eq("CASH"), "weight"].sum()) - 0.20) < 1e-9
    assert abs(float(day["weight"].sum()) - 1.0) < 1e-9
    assert int(audit["hedge_rows_removed"].sum()) == 1


def test_cli_runs_hedge_on_and_off_replays() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        for ticker, closes in {
            "AAA": [100, 101, 102, 103, 104, 105, 106],
            "BBB": [50, 51, 52, 53, 54, 55, 56],
            "SH": [20, 19, 18, 18, 19, 20, 21],
        }.items():
            _write_px(cache, ticker, [float(x) for x in closes])
        target = root / "target_book.csv"
        _book().to_csv(target, index=False)
        args = Args()
        args.target_book = str(target)
        args.price_cache = str(cache)
        args.output_dir = str(root / "out")
        args.official_metrics = ""
        args.portfolio_kind = "main"
        args.hedge_ticker = "SH"
        args.replay_end_date = "2026-01-12"
        args.official_baseline_end_date = "2026-01-12"
        args.cash_rate_path = ""
        args.cash_rate_source = "DGS3MO"
        args.cost_bps = 25.0
        args.max_fill_lag_days = 7
        payload = run(args)
        assert payload["status"] == "completed", payload
        assert payload["production_activation_allowed"] is False
        arms = {(row["arm"], row["cash_carry_mode"]): row for row in payload["arms"]}
        assert arms[("hedge_on", "none")]["status"] == "completed"
        assert arms[("hedge_off", "none")]["status"] == "completed"
        assert arms[("hedge_off", "none")]["delta_cagr_vs_hedge_on"] != ""
        assert (root / "out" / "hedge_on_vs_off.csv").exists()
        assert (root / "out" / "hedge_off_target_book.csv").exists()


def main() -> int:
    test_remove_hedge_moves_weight_to_cash()
    test_cli_runs_hedge_on_and_off_replays()
    print("main_hedge_off_baseline_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
