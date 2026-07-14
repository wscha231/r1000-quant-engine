#!/usr/bin/env python3
"""Smoke checks for the review-only next-close forward paper ledger."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_daily_simulated_fill_ledger import run, validate_event_chain  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_prices(cache: Path, ticker: str, closes: list[float]) -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=dates,
    ).to_parquet(cache / px_cache_name(ticker))


def write_seed(path: Path, portfolio: str) -> None:
    payload = {
        "schema_version": "account-ledger-v1",
        "portfolio_kind": portfolio,
        "as_of_date": "2026-01-02",
        "starting_capital_usd": 2_000.0,
        "equity_usd": 2_000.0,
        "cash_usd": 1_000.0,
        "cash_weight": 0.5,
        "stock_value_usd": 1_000.0,
        "position_count": 1,
        "fill_mode": "next_close",
        "cost_bps_per_side": 25.0,
        "integer_shares": True,
        "positions": [
            {
                "as_of_date": "2026-01-02",
                "ticker": "AAA",
                "shares": 10.0,
                "price": 100.0,
                "market_value_usd": 1_000.0,
                "weight": 0.5,
                "cost_basis": 90.0,
            }
        ],
        "realized_pnl_by_ticker": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_target(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"rebalance_date": "2026-01-05", "ticker": "AAA", "weight": 0.25},
            {"rebalance_date": "2026-01-05", "ticker": "BBB", "weight": 0.50},
            {"rebalance_date": "2026-01-05", "ticker": "CASH", "weight": 0.25},
        ]
    ).to_csv(path, index=False)


def args_for(root: Path, as_of_date: str) -> SimpleNamespace:
    return SimpleNamespace(
        state_dir=str(root / "paper"),
        price_cache=str(root / "cache_prices"),
        order_preview_root=str(root / "previews"),
        main_bootstrap_account=str(root / "seed" / "main.json"),
        concentrated_bootstrap_account=str(root / "seed" / "concentrated.json"),
        main_target=str(root / "targets" / "main.csv"),
        concentrated_target=str(root / "targets" / "concentrated.csv"),
        as_of_date=as_of_date,
        cost_bps=25.0,
        max_fill_lag_days=7,
    )


def test_pending_resolves_once_at_next_close() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 103.0])
        write_prices(cache, "BBB", [50.0, 51.0, 52.0])
        for portfolio in ("main", "concentrated"):
            write_seed(root / "seed" / f"{portfolio}.json", portfolio)
            write_target(root / "targets" / f"{portfolio}.csv")

        first = run(args_for(root, "2026-01-05"))
        assert first["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            directory = root / "paper" / portfolio
            pending = pd.read_csv(directory / "pending_orders.csv")
            assert len(pending) == 2
            assert set(pending["pending_status"]) == {"PENDING_NEXT_CLOSE"}
            assert not (directory / "fills.csv").read_text(encoding="utf-8").strip()
            account = json.loads((directory / "account_state_latest.json").read_text(encoding="utf-8"))
            assert account["review_only"] is True
            assert account["live_trading_enabled"] is False
            assert account["production_mutation_allowed"] is False

        second = run(args_for(root, "2026-01-06"))
        assert second["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            directory = root / "paper" / portfolio
            fills = pd.read_csv(directory / "fills.csv").sort_values("event_sequence")
            pending = pd.read_csv(directory / "pending_orders.csv") if (directory / "pending_orders.csv").stat().st_size else pd.DataFrame()
            account = json.loads((directory / "account_state_latest.json").read_text(encoding="utf-8"))
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            assert len(fills) == 2
            assert pending.empty
            assert fills.iloc[0]["side"] == "SELL"
            assert fills.iloc[1]["side"] == "BUY"
            assert set(fills["date"]) == {"2026-01-06"}
            assert set(fills["fill_mode"]) == {"next_close"}
            assert set(fills["record_type"]) == {"FORWARD_PAPER"}
            assert set(fills["execution_status"]) == {"SIMULATED_FILL"}
            assert float(account["cash_usd"]) >= 0.0
            assert account["pending_order_count"] == 0
            assert manifest["event_sequence"] == 2
            assert manifest["forward_metrics"]["cagr_status"] == "UNDERPOWERED"
            assert manifest["historical_cagr_mdd_replacement_allowed"] is False

        third = run(args_for(root, "2026-01-06"))
        assert third["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            fills = pd.read_csv(root / "paper" / portfolio / "fills.csv")
            assert len(fills) == 2
            assert fills["client_order_id"].is_unique

        main_dir = root / "paper" / "main"
        pending_path = main_dir / "pending_orders.csv"
        pd.DataFrame(
            [
                {
                    "portfolio_kind": "main",
                    "signal_date": "2026-01-06",
                    "ticker": "MISSING",
                    "side": "BUY",
                    "quantity": 1,
                    "reference_price": 10,
                    "target_weight": 0.01,
                    "reason": "fixture_missing_price",
                    "fill_mode": "next_close",
                    "cost_bps_per_side": 25,
                    "client_order_id": "fixture-missing-price",
                    "idempotency_key": "fixture-missing-price",
                    "order_batch_id": "fixture",
                    "target_hash": "fixture",
                    "priority": 1,
                    "pending_status": "PENDING_NEXT_CLOSE",
                    "created_at_utc": "2026-01-06T22:00:00+00:00",
                }
            ]
        ).to_csv(pending_path, index=False)
        late = run(args_for(root, "2026-01-20"))
        assert late["status"] == "completed"
        rejections = pd.read_csv(main_dir / "rejections.csv")
        assert len(rejections) == 1
        assert rejections.iloc[0]["event_reason"] == "missing_next_close_after_max_lag"
        fills = pd.read_csv(main_dir / "fills.csv")
        validate_event_chain(fills, rejections)

        tampered = fills.copy()
        tampered.loc[tampered.index[0], "fill_price"] += 1.0
        try:
            validate_event_chain(tampered, rejections)
        except ValueError as exc:
            assert "hash mismatch" in str(exc)
        else:
            raise AssertionError("tampered forward fill chain was accepted")


def test_bootstrap_does_not_retrade_an_already_effective_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 103.0])
        write_prices(cache, "BBB", [50.0, 51.0, 52.0])
        for portfolio in ("main", "concentrated"):
            seed_path = root / "seed" / f"{portfolio}.json"
            write_seed(seed_path, portfolio)
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            seed["as_of_date"] = "2026-01-05"
            seed_path.write_text(json.dumps(seed), encoding="utf-8")
            write_target(root / "targets" / f"{portfolio}.csv")

        payload = run(args_for(root, "2026-01-05"))
        assert payload["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            directory = root / "paper" / portfolio
            pending = pd.read_csv(directory / "pending_orders.csv")
            meta = json.loads((directory / "state_meta.json").read_text(encoding="utf-8"))
            assert pending.empty
            assert meta["last_enqueue_status"] == "BOOTSTRAP_TARGET_ASSUMED_APPLIED"


def main() -> int:
    test_pending_resolves_once_at_next_close()
    test_bootstrap_does_not_retrade_an_already_effective_target()
    print("daily_simulated_fill_ledger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
