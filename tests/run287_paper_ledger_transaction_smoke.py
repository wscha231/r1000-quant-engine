#!/usr/bin/env python3
"""Transactional, exact-close, and continuity acceptance checks for Run287 P0."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run287_paper_ledger_integrity import directory_hashes, verify_integrity_manifest  # noqa: E402
from tools.run_daily_simulated_fill_ledger import (  # noqa: E402
    GENESIS_HASH,
    canonical_hash,
    event_payload_for_hash,
    run,
    validate_event_chain,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


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


def write_seed(path: Path, portfolio: str, ticker: str, date: str, *, cash: float = 1_000.0) -> None:
    payload = {
        "schema_version": "account-ledger-v1",
        "portfolio_kind": portfolio,
        "as_of_date": date,
        "starting_capital_usd": 2_000.0,
        "equity_usd": 2_000.0,
        "cash_usd": cash,
        "cash_weight": cash / 2_000.0,
        "stock_value_usd": 1_000.0,
        "position_count": 1,
        "fill_mode": "next_close",
        "cost_bps_per_side": 25.0,
        "integer_shares": True,
        "positions": [
            {
                "as_of_date": date,
                "ticker": ticker,
                "shares": 10.0,
                "price": 100.0,
                "market_value_usd": 1_000.0,
                "weight": 0.5,
                "cost_basis": 100.0,
            }
        ],
        "realized_pnl_by_ticker": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_target(path: Path, portfolio: str, ticker: str, date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"rebalance_date": date, "ticker": ticker, "weight": 0.50, "portfolio_kind": portfolio},
            {"rebalance_date": date, "ticker": "CASH", "weight": 0.50, "portfolio_kind": portfolio},
        ]
    ).to_csv(path, index=False)


def ledger_args(root: Path, date: str, *, failpoint: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        state_dir=str(root / "paper"),
        price_cache=str(root / "prices"),
        order_preview_root=str(root / "previews"),
        main_bootstrap_account=str(root / "seed" / "main.json"),
        concentrated_bootstrap_account=str(root / "seed" / "concentrated.json"),
        main_target=str(root / "targets" / "main.csv"),
        concentrated_target=str(root / "targets" / "concentrated.csv"),
        as_of_date=date,
        cost_bps=25.0,
        max_fill_lag_days=7,
        transaction_failpoint=failpoint,
    )


def prepare(root: Path, dates: list[str]) -> None:
    write_prices(root / "prices", "AAA", dates, [100.0 + index for index in range(len(dates))])
    write_prices(root / "prices", "BBB", dates, [100.0 + 2 * index for index in range(len(dates))])
    write_seed(root / "seed" / "main.json", "main", "AAA", dates[0])
    write_seed(root / "seed" / "concentrated.json", "concentrated", "BBB", dates[0])
    write_target(root / "targets" / "main.csv", "main", "AAA", dates[0])
    write_target(root / "targets" / "concentrated.csv", "concentrated", "BBB", dates[0])


def test_twenty_sessions_remain_continuous_and_same_session_is_byte_identical() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = [date.date().isoformat() for date in pd.bdate_range("2026-01-02", periods=20)]
        prepare(root, dates)
        statuses: list[str] = []
        for date in dates:
            statuses.append(str(run(ledger_args(root, date))["result_status"]))
        assert statuses[0] == "GENESIS"
        assert statuses[1:] == ["RESTORED_CONTINUATION"] * 19
        for portfolio in ("main", "concentrated"):
            curve = pd.read_csv(root / "paper" / portfolio / "equity_curve.csv")
            account = json.loads((root / "paper" / portfolio / "account_state_latest.json").read_text(encoding="utf-8"))
            assert len(curve) == 20
            assert account["seed_as_of_date"] == dates[0]
            assert account["as_of_date"] == dates[-1]
            assert account["starting_capital_usd"] == 2_000.0
        verified = verify_integrity_manifest(root / "paper", require=True)
        assert verified["status"] == "VERIFIED"
        before = directory_hashes(root / "paper")
        rerun = run(ledger_args(root, dates[-1]))
        assert rerun["result_status"] == "SAME_SESSION_REUSE"
        assert directory_hashes(root / "paper") == before


def test_failed_second_portfolio_and_interrupted_publish_change_zero_durable_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = [date.date().isoformat() for date in pd.bdate_range("2026-02-02", periods=4)]
        prepare(root, dates)
        run(ledger_args(root, dates[0]))
        state_before = directory_hashes(root / "paper")
        preview_before = directory_hashes(root / "previews")

        # Main has the exact close, while Concentrated/BBB is stale.  Validation
        # fails after Main was computed in staging, but nothing durable changes.
        write_prices(root / "prices", "BBB", dates[:1], [100.0])
        try:
            run(ledger_args(root, dates[1]))
        except ValueError as exc:
            assert "BLOCKED_MISSING_EXACT_CLOSE" in str(exc)
        else:
            raise AssertionError("stale Concentrated close was accepted")
        assert directory_hashes(root / "paper") == state_before
        assert directory_hashes(root / "previews") == preview_before

        write_prices(root / "prices", "BBB", dates, [100.0 + 2 * index for index in range(len(dates))])
        try:
            run(ledger_args(root, dates[1], failpoint="after_publish_0"))
        except RuntimeError as exc:
            assert "injected transaction interruption" in str(exc)
        else:
            raise AssertionError("transaction failpoint did not interrupt publication")
        assert directory_hashes(root / "paper") == state_before
        assert directory_hashes(root / "previews") == preview_before
        assert not (root / ".paper.transaction.json").exists()


def test_duplicate_client_order_id_and_negative_cash_fail_closed() -> None:
    first = {
        "event_sequence": 1,
        "event_id": "event-1",
        "client_order_id": "duplicate-client-id",
        "previous_event_hash": GENESIS_HASH,
        "event_type": "FILL",
    }
    first["event_hash"] = canonical_hash(event_payload_for_hash(first))
    second = {
        "event_sequence": 2,
        "event_id": "event-2",
        "client_order_id": "duplicate-client-id",
        "previous_event_hash": first["event_hash"],
        "event_type": "FILL",
    }
    second["event_hash"] = canonical_hash(event_payload_for_hash(second))
    try:
        validate_event_chain(pd.DataFrame([first, second]), pd.DataFrame())
    except ValueError as exc:
        assert "client order id is duplicated" in str(exc)
    else:
        raise AssertionError("duplicate client order id was accepted")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = ["2026-03-02"]
        prepare(root, dates)
        write_seed(root / "seed" / "main.json", "main", "AAA", dates[0], cash=-1.0)
        try:
            run(ledger_args(root, dates[0]))
        except ValueError as exc:
            assert "negative cash" in str(exc)
        else:
            raise AssertionError("negative-cash genesis was accepted")
        assert not (root / "paper").exists()


def main() -> int:
    test_twenty_sessions_remain_continuous_and_same_session_is_byte_identical()
    test_failed_second_portfolio_and_interrupted_publish_change_zero_durable_files()
    test_duplicate_client_order_id_and_negative_cash_fail_closed()
    print("run287_paper_ledger_transaction_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
