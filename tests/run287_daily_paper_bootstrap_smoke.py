#!/usr/bin/env python3
"""Smoke checks for the fail-closed Run287 daily paper bootstrap."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.bootstrap_run287_daily_paper_accounts import run as run_bootstrap  # noqa: E402
from tools.run_daily_simulated_fill_ledger import run as run_ledger  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_prices(cache: Path, ticker: str, dates: list[str], closes: list[float]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=pd.to_datetime(dates),
    ).to_parquet(cache / px_cache_name(ticker))


def write_target(path: Path, date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"rebalance_date": date, "ticker": "AAA", "weight": 0.60},
            {"rebalance_date": date, "ticker": "CASH", "weight": 0.40},
        ]
    ).to_csv(path, index=False)


def bootstrap_args(root: Path, as_of_date: str) -> SimpleNamespace:
    return SimpleNamespace(
        state_dir=str(root / "paper"),
        price_cache=str(root / "prices"),
        main_target=str(root / "targets" / "main.csv"),
        concentrated_target=str(root / "targets" / "concentrated.csv"),
        as_of_date=as_of_date,
        expected_seed_date=as_of_date,
        starting_capital=2_000.0,
        cost_bps=25.0,
    )


def ledger_args(root: Path, as_of_date: str) -> SimpleNamespace:
    return SimpleNamespace(
        state_dir=str(root / "paper"),
        price_cache=str(root / "prices"),
        order_preview_root=str(root / "previews"),
        main_bootstrap_account=str(root / "paper" / "bootstrap" / "main_account.json"),
        concentrated_bootstrap_account=str(root / "paper" / "bootstrap" / "concentrated_account.json"),
        main_target=str(root / "targets" / "main.csv"),
        concentrated_target=str(root / "targets" / "concentrated.csv"),
        as_of_date=as_of_date,
        cost_bps=25.0,
        max_fill_lag_days=7,
    )


def test_bootstrap_is_exact_close_idempotent_and_ledger_compatible() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_prices(root / "prices", "AAA", ["2026-07-13", "2026-07-14"], [100.0, 101.0])
        for portfolio in ("main", "concentrated"):
            write_target(root / "targets" / f"{portfolio}.csv", "2026-07-14")

        first = run_bootstrap(bootstrap_args(root, "2026-07-14"))
        assert first["status"] == "READY_REVIEW_ONLY_PAPER_BOOTSTRAP"
        assert first["created_account_count"] == 2
        assert first["fullrun_executed"] is False
        assert first["portfolio_weights_changed"] is False
        hashes: dict[str, str] = {}
        for portfolio in ("main", "concentrated"):
            path = root / "paper" / "bootstrap" / f"{portfolio}_account.json"
            account = json.loads(path.read_text(encoding="utf-8"))
            hashes[portfolio] = digest(path)
            assert account["review_only"] is True
            assert account["live_trading_enabled"] is False
            assert account["production_mutation_allowed"] is False
            assert account["historical_trade_backfill_claimed"] is False
            assert account["positions"][0]["shares"] == 11
            assert account["positions"][0]["price"] == 101.0
            assert abs(account["cash_usd"] - 889.0) < 1e-9

        second = run_bootstrap(bootstrap_args(root, "2026-07-14"))
        assert second["created_account_count"] == 0
        assert {second["results"][p]["status"] for p in ("main", "concentrated")} == {"REUSED_FROZEN_BOOTSTRAP"}
        for portfolio in ("main", "concentrated"):
            path = root / "paper" / "bootstrap" / f"{portfolio}_account.json"
            assert digest(path) == hashes[portfolio]

        ledger = run_ledger(ledger_args(root, "2026-07-14"))
        assert ledger["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            meta = json.loads((root / "paper" / portfolio / "state_meta.json").read_text(encoding="utf-8"))
            account = json.loads((root / "paper" / portfolio / "account_state_latest.json").read_text(encoding="utf-8"))
            assert meta["last_enqueue_status"] == "BOOTSTRAP_TARGET_ASSUMED_APPLIED"
            assert meta["pending_order_count"] == 0
            assert account["review_only"] is True
            assert account["forward_fill_count"] == 0


def test_bootstrap_rejects_non_exact_close_and_incomplete_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_prices(root / "prices", "AAA", ["2026-07-13"], [100.0])
        for portfolio in ("main", "concentrated"):
            write_target(root / "targets" / f"{portfolio}.csv", "2026-07-14")
        try:
            run_bootstrap(bootstrap_args(root, "2026-07-14"))
        except ValueError as exc:
            assert "missing exact completed-session close" in str(exc)
        else:
            raise AssertionError("bootstrap accepted a prior-session price")

        write_prices(root / "prices", "AAA", ["2026-07-13", "2026-07-14"], [100.0, 101.0])
        run_bootstrap(bootstrap_args(root, "2026-07-14"))
        main_dir = root / "paper" / "main"
        main_dir.mkdir(parents=True, exist_ok=True)
        (main_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
        try:
            run_bootstrap(bootstrap_args(root, "2026-07-14"))
        except ValueError as exc:
            assert "refusing bootstrap reset" in str(exc)
        else:
            raise AssertionError("bootstrap reset an incomplete ledger state")


def test_bootstrap_refuses_late_reseed_and_wrong_restored_seed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_prices(root / "prices", "AAA", ["2026-07-13", "2026-07-16"], [100.0, 95.0])
        for portfolio in ("main", "concentrated"):
            write_target(root / "targets" / f"{portfolio}.csv", "2026-07-13")

        late_args = bootstrap_args(root, "2026-07-16")
        late_args.expected_seed_date = "2026-07-13"
        try:
            run_bootstrap(late_args)
        except ValueError as exc:
            assert "refusing late bootstrap" in str(exc)
        else:
            raise AssertionError("bootstrap silently replaced the canonical paper seed")

        seed_args = bootstrap_args(root, "2026-07-13")
        seed_args.expected_seed_date = "2026-07-13"
        run_bootstrap(seed_args)
        run_ledger(ledger_args(root, "2026-07-13"))
        state_path = root / "paper" / "main" / "account_state_latest.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["seed_as_of_date"] = "2026-07-16"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        try:
            run_bootstrap(late_args)
        except ValueError as exc:
            assert "paper seed date mismatch" in str(exc)
        else:
            raise AssertionError("bootstrap accepted a restored account with the wrong seed date")


def main() -> int:
    test_bootstrap_is_exact_close_idempotent_and_ledger_compatible()
    test_bootstrap_rejects_non_exact_close_and_incomplete_state()
    test_bootstrap_refuses_late_reseed_and_wrong_restored_seed()
    print("run287_daily_paper_bootstrap_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
