#!/usr/bin/env python3
"""Smoke checks for account-ledger order preview."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_account_order_preview import normalize_target, run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


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


class Args:
    pass


def test_order_preview_builds_sell_first_orders() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 100.0, 100.0])
        _write_px(cache, "BBB", [50.0, 50.0, 50.0])
        account = {
            "as_of_date": "2026-01-02",
            "cash_usd": 1000.0,
            "positions": [
                {"ticker": "AAA", "shares": 80.0, "cost_basis": 90.0},
            ],
        }
        account_path = root / "account_state_latest.json"
        account_path.write_text(json.dumps(account), encoding="utf-8")
        target = root / "target.csv"
        pd.DataFrame(
            [
                {"ticker": "AAA", "weight": 0.30},
                {"ticker": "BBB", "weight": 0.60},
            ]
        ).to_csv(target, index=False)
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = ""
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["account_state_as_of_date"] == "2026-01-02"
        assert payload["as_of_date"] == "2026-01-06"
        orders = pd.read_csv(out / "orders_preview.csv")
        assert not orders.empty
        assert orders.iloc[0]["side"] == "SELL"
        assert {"SELL", "BUY"}.issubset(set(orders["side"]))
        assert (orders["quantity"] % 1 == 0).all()
        assert "client_order_id" in orders.columns
        assert "idempotency_key" in orders.columns
        assert orders["client_order_id"].is_unique
        assert (out / "positions_current.csv").exists()
        assert (out / "target_price_coverage.csv").exists()
        assert (out / "projected_positions_after_orders.csv").exists()
        assert (out / "preview_metrics.json").exists()
        coverage = pd.read_csv(out / "target_price_coverage.csv")
        bbb = coverage.loc[coverage["ticker"].eq("BBB")].iloc[0]
        assert bool(bbb["target_only_new_buy"]) is True
        assert bbb["price_status"] == "ok"
        assert float(bbb["reference_price"]) == 50.0
        assert "projected_cash_weight" in payload
        assert "target_cash_weight" in payload
        assert abs(payload["target_cash_weight"] - 0.10) < 1e-9
        projected = pd.read_csv(out / "projected_positions_after_orders.csv")
        assert "projected_weight" in projected.columns
        assert "CASH" in set(projected["ticker"])
        manifest = json.loads((out / "order_batch_manifest.json").read_text(encoding="utf-8"))
        assert manifest["order_count"] == len(orders)
        assert manifest["order_batch_id"] == payload["order_batch_id"]


def test_concentrated_target_normalization_does_not_force_n3() -> None:
    frame = pd.DataFrame(
        [
            {"rebalance_date": "2026-06-01", "ticker": "AAA", "target_weight": 0.30, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "BBB", "target_weight": 0.25, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "CCC", "target_weight": 0.20, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "DDD", "target_weight": 0.15, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "EEE", "target_weight": 0.10, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "OLD", "target_weight": 1.00, "target_stock_names": 3},
            {"rebalance_date": "2026-06-01", "ticker": "CASH", "target_weight": 0.00, "target_stock_names": 5},
        ]
    )
    out = normalize_target(frame, "concentrated")
    assert set(out["ticker"]) == {"AAA", "BBB", "CCC", "DDD", "EEE"}
    assert abs(float(out["target_weight"].sum()) - 1.0) < 1e-9


def test_order_preview_uses_explicit_cash_target_weight() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 100.0, 100.0])
        account = {
            "as_of_date": "2026-01-02",
            "cash_usd": 6000.0,
            "positions": [{"ticker": "AAA", "shares": 40.0, "cost_basis": 90.0}],
        }
        account_path = root / "account_state_latest.json"
        account_path.write_text(json.dumps(account), encoding="utf-8")
        target = root / "target.csv"
        pd.DataFrame(
            [
                {"ticker": "CASH", "target_weight": 0.60},
                {"ticker": "AAA", "target_weight": 0.40},
            ]
        ).to_csv(target, index=False)
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = ""
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        payload = run(args)
        assert payload["status"] == "completed"
        assert abs(payload["target_cash_weight"] - 0.60) < 1e-9
        assert abs(payload["target_stock_weight"] - 0.40) < 1e-9


def main() -> int:
    test_order_preview_builds_sell_first_orders()
    test_concentrated_target_normalization_does_not_force_n3()
    test_order_preview_uses_explicit_cash_target_weight()
    print("account_order_preview_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
