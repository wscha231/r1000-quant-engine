#!/usr/bin/env python3
"""Smoke checks for the review-only next-close forward paper ledger."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_daily_simulated_fill_ledger import (  # noqa: E402
    normalized_target,
    run,
    target_hash,
    validate_event_chain,
)
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


def args_for(
    root: Path, as_of_date: str, lifecycle: str = "", suppress_new_orders: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        state_dir=str(root / "paper"),
        price_cache=str(root / "cache_prices"),
        order_preview_root=str(root / "previews"),
        main_bootstrap_account=str(root / "seed" / "main.json"),
        concentrated_bootstrap_account=str(root / "seed" / "concentrated.json"),
        main_target=str(root / "targets" / "main.csv"),
        concentrated_target=str(root / "targets" / "concentrated.csv"),
        as_of_date=as_of_date,
        decision_time_utc=f"{as_of_date}T23:00:00Z",
        security_lifecycle_events=lifecycle,
        cost_bps=25.0,
        max_fill_lag_days=7,
        suppress_new_orders=suppress_new_orders,
    )


def directory_hashes(path: Path) -> dict[str, str]:
    return {
        file.relative_to(path).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(item for item in path.rglob("*") if item.is_file())
    }


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
            assert fills.iloc[0]["sell_taxonomy"] == "EXECUTION_RECONCILIATION"
            assert fills.iloc[1]["sell_taxonomy"] == "NOT_APPLICABLE"
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
        assert third["same_session_reused_portfolio_count"] == 2
        for portfolio in ("main", "concentrated"):
            fills = pd.read_csv(root / "paper" / portfolio / "fills.csv")
            assert len(fills) == 2
            assert fills["client_order_id"].is_unique
            assert third["portfolios"][portfolio]["same_session_reused"] is True

        main_dir = root / "paper" / "main"
        fills = pd.read_csv(main_dir / "fills.csv")
        rejection_path = main_dir / "rejections.csv"
        rejections = pd.read_csv(rejection_path) if rejection_path.read_text(encoding="utf-8").strip() else pd.DataFrame()
        validate_event_chain(fills, rejections)

        tampered = fills.copy()
        tampered.loc[tampered.index[0], "fill_price"] += 1.0
        try:
            validate_event_chain(tampered, rejections)
        except ValueError as exc:
            assert "hash mismatch" in str(exc)
        else:
            raise AssertionError("tampered forward fill chain was accepted")


def test_verified_cash_merger_settles_without_future_close_and_cancels_pending() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 103.0])
        write_prices(cache, "BBB", [50.0, 51.0, 52.0])
        lifecycle = root / "security_lifecycle.csv"
        pd.DataFrame(
            [
                {
                    "stable_security_id": "SECURITY:AAA",
                    "stable_issuer_id": "ISSUER:AAA",
                    "ticker": "AAA",
                    "aliases": "AAA",
                    "event_type": "cash_merger",
                    "available_from": "2026-01-06T13:00:00Z",
                    "effective_date": "2026-01-06",
                    "last_trading_date": "2026-01-05",
                    "predecessor_security_id": "",
                    "successor_security_id": "",
                    "successor_ticker": "",
                    "cash_consideration": "110.00",
                    "delisting_proceeds": "",
                    "currency": "USD",
                    "source_url": "https://example.test/filing/aaa",
                    "accession_number": "0000000000-26-000001",
                    "stable_event_id": "EVENT:AAA:20260106",
                    "source_sha256": "a" * 64,
                    "exact_available_from": "true",
                    "evidence_status": "verified",
                    "review_status": "approved",
                    "notes": "generic cash merger fixture",
                }
            ]
        ).to_csv(lifecycle, index=False)
        for portfolio in ("main", "concentrated"):
            write_seed(root / "seed" / f"{portfolio}.json", portfolio)
            write_target(root / "targets" / f"{portfolio}.csv")

        first = run(args_for(root, "2026-01-05", str(lifecycle)))
        assert first["status"] == "completed"

        aaa_path = cache / px_cache_name("AAA")
        aaa = pd.read_parquet(aaa_path)
        aaa.loc[pd.to_datetime(aaa.index).normalize() <= pd.Timestamp("2026-01-05")].to_parquet(aaa_path)
        second = run(args_for(root, "2026-01-06", str(lifecycle)))
        assert second["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            directory = root / "paper" / portfolio
            account = json.loads((directory / "account_state_latest.json").read_text(encoding="utf-8"))
            fills = pd.read_csv(directory / "fills.csv")
            rejections = pd.read_csv(directory / "rejections.csv")
            assert "AAA" not in {row["ticker"] for row in account["positions"]}
            settlement = fills[fills["event_type"] == "LIFECYCLE_SETTLEMENT"]
            assert len(settlement) == 1
            assert float(settlement.iloc[0]["fee_usd"]) == 0.0
            assert float(settlement.iloc[0]["gross_value"]) == 1_100.0
            assert "lifecycle_terminal_cancelled" in set(rejections["event_reason"])
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["security_lifecycle_actions"]["settled_positions"] == 1
            assert manifest["security_lifecycle_terminal_tickers"] == ["AAA"]
            validate_event_chain(fills, rejections)


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


def test_same_session_price_revision_reuses_frozen_state_and_input_change_fails_closed() -> None:
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
        assert first["same_session_reused_portfolio_count"] == 0
        before = {
            portfolio: directory_hashes(root / "paper" / portfolio)
            for portfolio in ("main", "concentrated")
        }

        write_prices(cache, "AAA", [100.0, 999.0, 103.0])
        revised = run(args_for(root, "2026-01-05"))
        assert revised["same_session_reused_portfolio_count"] == 2
        assert revised["same_session_preview_rebuilt_portfolio_count"] == 0
        for portfolio in ("main", "concentrated"):
            assert revised["portfolios"][portfolio]["same_session_reused"] is True
            assert revised["portfolios"][portfolio]["same_session_preview_rebuilt"] is False
            assert directory_hashes(root / "paper" / portfolio) == before[portfolio]

        for portfolio in ("main", "concentrated"):
            shutil.rmtree(root / "previews" / portfolio)
        rebuilt = run(args_for(root, "2026-01-05"))
        assert rebuilt["same_session_reused_portfolio_count"] == 2
        assert rebuilt["same_session_preview_rebuilt_portfolio_count"] == 2
        for portfolio in ("main", "concentrated"):
            assert rebuilt["portfolios"][portfolio]["same_session_preview_rebuilt"] is True
            assert directory_hashes(root / "paper" / portfolio) == before[portfolio]
            for name in (
                "preview_metrics.json",
                "order_batch_manifest.json",
                "orders_preview.csv",
                "target_weights.csv",
            ):
                assert (root / "previews" / portfolio / name).is_file()

        target = pd.read_csv(root / "targets" / "main.csv")
        target.loc[target["ticker"] == "AAA", "weight"] = 0.30
        target.to_csv(root / "targets" / "main.csv", index=False)
        try:
            run(args_for(root, "2026-01-05"))
        except ValueError as exc:
            assert "genesis identity changed" in str(exc) or "target_hash" in str(exc)
        else:
            raise AssertionError("same-session target mutation was silently accepted")
        for portfolio in ("main", "concentrated"):
            assert directory_hashes(root / "paper" / portfolio) == before[portfolio]


def test_suppressed_mark_can_transition_once_to_fresh_same_close_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 103.0])
        write_prices(cache, "BBB", [50.0, 51.0, 52.0])
        for portfolio in ("main", "concentrated"):
            seed_path = root / "seed" / f"{portfolio}.json"
            target_path = root / "targets" / f"{portfolio}.csv"
            write_seed(seed_path, portfolio)
            write_target(target_path)
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            original = normalized_target(target_path, portfolio, pd.Timestamp("2026-01-05"))
            seed["assumed_applied_target_hash"] = target_hash(original)
            seed["target_sha256"] = hashlib.sha256(target_path.read_bytes()).hexdigest()
            seed_path.write_text(json.dumps(seed), encoding="utf-8")

        suppressed = run(args_for(root, "2026-01-05", suppress_new_orders=True))
        assert suppressed["new_order_generation_suppressed"] is True
        for portfolio in ("main", "concentrated"):
            manifest = json.loads(
                (root / "paper" / portfolio / "manifest.json").read_text(encoding="utf-8")
            )
            assert manifest["new_order_generation_suppressed"] is True
            assert manifest["enqueued_this_run"] == 0

        for portfolio in ("main", "concentrated"):
            path = root / "targets" / f"{portfolio}.csv"
            target = pd.read_csv(path)
            target.loc[target["ticker"].eq("AAA"), "weight"] = 0.40
            target.loc[target["ticker"].eq("BBB"), "weight"] = 0.35
            target.to_csv(path, index=False)

        selected = run(args_for(root, "2026-01-05"))
        assert selected["new_order_generation_suppressed"] is False
        for portfolio in ("main", "concentrated"):
            manifest = selected["portfolios"][portfolio]
            assert manifest["new_order_generation_suppressed"] is False
            assert manifest["enqueued_this_run"] > 0
            pending = pd.read_csv(root / "paper" / portfolio / "pending_orders.csv")
            assert not pending.empty


def main() -> int:
    test_pending_resolves_once_at_next_close()
    test_verified_cash_merger_settles_without_future_close_and_cancels_pending()
    test_bootstrap_does_not_retrade_an_already_effective_target()
    test_same_session_price_revision_reuses_frozen_state_and_input_change_fails_closed()
    test_suppressed_mark_can_transition_once_to_fresh_same_close_target()
    print("daily_simulated_fill_ledger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
