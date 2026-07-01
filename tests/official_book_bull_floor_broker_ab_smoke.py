#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_official_book_bull_floor_broker_ab import apply_bull_floor_lift_only, run  # noqa: E402
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
    rows = []
    for ticker in ["AAA", "BBB"]:
        rows.append(
            {
                "rebalance_date": "2026-01-02",
                "ticker": ticker,
                "weight": 0.25,
                "target_weight": 0.25,
                "regime_state": "bull",
                "effective_single_weight_cap": 0.50,
            }
        )
    rows.append(
        {
            "rebalance_date": "2026-01-02",
            "ticker": "CASH",
            "weight": 0.50,
            "target_weight": 0.50,
            "regime_state": "bull",
            "effective_single_weight_cap": 1.0,
        }
    )
    return pd.DataFrame(rows)


def test_lift_only_control_preserves_weights() -> None:
    out, summary, audit = apply_bull_floor_lift_only(_book(), portfolio_kind="concentrated", floor=0.0)
    stock = out[~out["ticker"].isin(["CASH", "__CASH__"])]
    cash = out[out["ticker"].isin(["CASH", "__CASH__"])]
    assert summary["rebalance_dates_bull_floor_lifted"] == 0
    assert abs(float(stock["weight"].sum()) - 0.50) < 1e-9
    assert abs(float(cash["weight"].sum()) - 0.50) < 1e-9


def test_lift_only_raises_bull_stock_floor_without_dampening() -> None:
    out, summary, audit = apply_bull_floor_lift_only(_book(), portfolio_kind="concentrated", floor=0.80)
    stock = out[~out["ticker"].isin(["CASH", "__CASH__"])]
    cash = out[out["ticker"].isin(["CASH", "__CASH__"])]
    assert summary["rebalance_dates_bull_floor_lifted"] == 1
    assert abs(float(stock["weight"].sum()) - 0.80) < 1e-9
    assert abs(float(cash["weight"].sum()) - 0.20) < 1e-9
    assert bool(out["official_book_bull_floor_lift_applied"].any())


def test_cli_runs_broker_replay_for_control_and_lifted_arm() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        for ticker in ["AAA", "BBB"]:
            _write_px(cache, ticker, [10.0, 10.0, 10.0, 10.0, 10.0])
        target = root / "target_book.csv"
        _book().to_csv(target, index=False)

        args = Args()
        args.target_book = str(target)
        args.price_cache = str(cache)
        args.output_dir = str(root / "ab")
        args.portfolio_kind = "concentrated"
        args.floors = "0.0,0.8"
        args.cost_bps = 25.0
        args.max_fill_lag_days = 7
        args.replay_end_date = "2026-01-08"
        args.official_baseline_end_date = "2026-01-08"
        args.cash_carry_mode = "none"
        args.cash_rate_source = "DGS3MO"
        args.cash_rate_path = ""
        args.cash_rate_lag_days = 1
        args.cash_carry_haircut_bps = 50.0
        args.cash_carry_day_count = 365

        payload = run(args)
        assert payload["status"] == "completed", payload
        assert payload["production_activation_allowed"] is False
        arms = {row["floor"]: row for row in payload["arms"]}
        assert arms[0.0]["broker_status"] == "completed"
        assert arms[0.8]["broker_status"] == "completed"
        assert arms[0.0]["overlay_rebalance_dates_bull_floor_lifted"] == 0
        assert arms[0.8]["overlay_rebalance_dates_bull_floor_lifted"] == 1
        assert (Path(args.output_dir) / "arm_metrics.csv").exists()


def main() -> int:
    test_lift_only_control_preserves_weights()
    test_lift_only_raises_bull_stock_floor_without_dampening()
    test_cli_runs_broker_replay_for_control_and_lifted_arm()
    print("official_book_bull_floor_broker_ab_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
