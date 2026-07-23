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
    GENESIS_HASH,
    canonical_hash,
    event_payload_for_hash,
    materialize_lifecycle_adjusted_target,
    next_nyse_session_after,
    normalized_target,
    run,
    target_hash,
    validate_event_chain,
    validate_restored_snapshot,
)
from tools.run287_paper_ledger_integrity import (  # noqa: E402
    PaperLedgerIntegrityError,
)
from tools.reserve_asset_policy import (  # noqa: E402
    RESERVE_REASON_SOURCE_HASH_FIELD,
    reserve_reason_reconciliation,
    resolve_reserve_asset_policy,
)
from tools.security_lifecycle import empty_snapshot  # noqa: E402
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


def write_lifecycle(
    path: Path,
    *,
    event_type: str = "cash_merger",
    ticker: str = "AAA",
    successor_ticker: str = "",
    cash_consideration: str = "110.00",
) -> None:
    identity = event_type in {"ticker_change", "security_successor"}
    stable = f"SECURITY:{ticker}"
    successor = f"SECURITY:{successor_ticker}" if successor_ticker else ""
    pd.DataFrame(
        [
            {
                "stable_security_id": stable,
                "stable_issuer_id": f"ISSUER:{ticker}",
                "ticker": ticker,
                "aliases": "|".join(value for value in (ticker, successor_ticker) if value),
                "event_type": event_type,
                "available_from": "2026-01-06T13:00:00Z",
                "effective_date": "2026-01-06",
                "last_trading_date": "2026-01-05",
                "predecessor_security_id": stable if identity else "",
                "successor_security_id": (stable if event_type == "ticker_change" else successor) if identity else "",
                "successor_ticker": successor_ticker,
                "cash_consideration": cash_consideration if event_type == "cash_merger" else "",
                "delisting_proceeds": "",
                "currency": "USD",
                "source_url": f"https://example.test/filing/{ticker.lower()}",
                "accession_number": "0000000000-26-000001",
                "stable_event_id": f"EVENT:{ticker}:20260106",
                "source_sha256": "a" * 64,
                "exact_available_from": "true",
                "evidence_status": "verified",
                "review_status": "approved",
                "notes": "generic lifecycle fixture",
            }
        ]
    ).to_csv(path, index=False)


def args_for(
    root: Path, as_of_date: str, lifecycle: str | None = None, suppress_new_orders: bool = False
) -> SimpleNamespace:
    lifecycle_path = (
        str(ROOT / "data_static" / "run287_exact_packet" / "security_lifecycle_events.csv")
        if lifecycle is None
        else lifecycle
    )
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
        security_lifecycle_events=lifecycle_path,
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
            embedded_bootstrap = (
                root / "paper" / "bootstrap" / f"{portfolio}_account.json"
            )
            assert embedded_bootstrap.read_bytes() == (
                root / "seed" / f"{portfolio}.json"
            ).read_bytes()
            directory = root / "paper" / portfolio
            pending = pd.read_csv(directory / "pending_orders.csv")
            assert len(pending) == 2
            assert set(pending["pending_status"]) == {"PENDING_NEXT_CLOSE"}
            assert not (directory / "fills.csv").read_text(encoding="utf-8").strip()
            account = json.loads((directory / "account_state_latest.json").read_text(encoding="utf-8"))
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            preview_metrics = json.loads(
                (root / "previews" / portfolio / "preview_metrics.json").read_text(
                    encoding="utf-8"
                )
            )
            preview_manifest = json.loads(
                (root / "previews" / portfolio / "order_batch_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            assert account["review_only"] is True
            assert account["live_trading_enabled"] is False
            assert account["production_mutation_allowed"] is False
            reserve_source_hash = account[RESERVE_REASON_SOURCE_HASH_FIELD]
            assert len(reserve_source_hash) == 64
            assert manifest[RESERVE_REASON_SOURCE_HASH_FIELD] == reserve_source_hash
            assert preview_metrics[RESERVE_REASON_SOURCE_HASH_FIELD] == reserve_source_hash
            assert preview_manifest[RESERVE_REASON_SOURCE_HASH_FIELD] == reserve_source_hash
            assert account["position_count_total"] == (
                account["equity_position_count"] + account["reserve_position_count"]
            )
            assert account["position_count"] == account["equity_position_count"]

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


def test_next_close_uses_nyse_calendar_and_never_skips_missing_session() -> None:
    assert next_nyse_session_after(
        "2026-01-16", label="test.signal_date"
    ).date().isoformat() == "2026-01-20"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 103.0])
        write_prices(cache, "BBB", [50.0, 51.0, 52.0])
        for portfolio in ("main", "concentrated"):
            write_seed(root / "seed" / f"{portfolio}.json", portfolio)
            write_target(root / "targets" / f"{portfolio}.csv")
        run(args_for(root, "2026-01-05"))
        before = directory_hashes(root / "paper")

        dates = pd.to_datetime(
            ["2026-01-02", "2026-01-05", "2026-01-07"]
        )
        for ticker, closes in (
            ("AAA", [100.0, 102.0, 104.0]),
            ("BBB", [50.0, 51.0, 53.0]),
        ):
            pd.DataFrame(
                {
                    "Open": closes,
                    "Close": closes,
                    "Adj Close": closes,
                    "Volume": [1_000_000] * len(closes),
                },
                index=dates,
            ).to_parquet(cache / px_cache_name(ticker))
        try:
            run(args_for(root, "2026-01-07"))
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_MISSING_EXACT_CLOSE"
            assert "2026-01-06" in str(exc)
        else:
            raise AssertionError(
                "a later close replaced the missing next NYSE close"
            )
        assert directory_hashes(root / "paper") == before


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


def test_delayed_catchup_fills_before_terminal_settlement() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 103.0])
        write_prices(cache, "BBB", [50.0, 51.0, 52.0])
        lifecycle = root / "security_lifecycle.csv"
        write_lifecycle(lifecycle)
        for portfolio in ("main", "concentrated"):
            seed_path = root / "seed" / f"{portfolio}.json"
            write_seed(seed_path, portfolio)
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            seed["as_of_date"] = "2026-01-01"
            seed["positions"][0]["as_of_date"] = "2026-01-01"
            seed_path.write_text(json.dumps(seed), encoding="utf-8")
            target_path = root / "targets" / f"{portfolio}.csv"
            write_target(target_path)
            target = pd.read_csv(target_path)
            target["rebalance_date"] = "2026-01-02"
            target.to_csv(target_path, index=False)

        first = run(args_for(root, "2026-01-02", str(lifecycle)))
        assert first["status"] == "completed"
        second = run(args_for(root, "2026-01-06", str(lifecycle)))
        assert second["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            fills = pd.read_csv(root / "paper" / portfolio / "fills.csv").sort_values("event_sequence")
            aaa = fills[fills["ticker"].eq("AAA")]
            assert aaa["event_type"].tolist() == ["FILL", "LIFECYCLE_SETTLEMENT"]
            assert aaa["date"].tolist() == ["2026-01-05", "2026-01-06"]
            rejections_path = root / "paper" / portfolio / "rejections.csv"
            rejections = (
                pd.read_csv(rejections_path)
                if rejections_path.read_text(encoding="utf-8").strip()
                else pd.DataFrame()
            )
            assert rejections.empty or "lifecycle_terminal_cancelled" not in set(rejections["event_reason"])


def test_ticker_change_uses_successor_exact_close_after_last_trade() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 80.0])
        write_prices(cache, "NEW", [100.0, 105.0, 120.0])
        lifecycle = root / "security_lifecycle.csv"
        write_lifecycle(
            lifecycle,
            event_type="ticker_change",
            ticker="AAA",
            successor_ticker="NEW",
            cash_consideration="",
        )
        for portfolio in ("main", "concentrated"):
            write_seed(root / "seed" / f"{portfolio}.json", portfolio)
            (root / "targets").mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [
                    {"rebalance_date": "2026-01-05", "ticker": "AAA", "weight": 0.50},
                    {"rebalance_date": "2026-01-05", "ticker": "CASH", "weight": 0.50},
                ]
            ).to_csv(root / "targets" / f"{portfolio}.csv", index=False)

        result = run(args_for(root, "2026-01-06", str(lifecycle)))
        assert result["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            positions = pd.read_csv(root / "paper" / portfolio / "positions_latest.csv")
            assert float(positions.loc[positions["ticker"].eq("AAA"), "price"].iloc[0]) == 120.0


def test_post_cutover_exit_executes_against_predecessor_ledger_position() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
        pd.DataFrame(
            {"Open": [100.0, 101.0], "Close": [100.0, 101.0], "Adj Close": [100.0, 101.0]},
            index=dates,
        ).to_parquet(cache / px_cache_name("OLD"))
        successor_dates = pd.to_datetime(["2026-01-06", "2026-01-07"])
        pd.DataFrame(
            {"Open": [120.0, 121.0], "Close": [120.0, 121.0], "Adj Close": [120.0, 121.0]},
            index=successor_dates,
        ).to_parquet(cache / px_cache_name("NEW"))
        lifecycle = root / "lifecycle.csv"
        write_lifecycle(
            lifecycle,
            event_type="ticker_change",
            ticker="OLD",
            successor_ticker="NEW",
        )
        for portfolio in ("main", "concentrated"):
            seed_path = root / "seed" / f"{portfolio}.json"
            write_seed(seed_path, portfolio)
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
            seed["as_of_date"] = "2026-01-05"
            seed["positions"][0]["ticker"] = "OLD"
            seed_path.write_text(json.dumps(seed), encoding="utf-8")
            target_path = root / "targets" / f"{portfolio}.csv"
            target_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                [{"rebalance_date": "2026-01-06", "ticker": "CASH", "weight": 1.0}]
            ).to_csv(target_path, index=False)

        first = run(args_for(root, "2026-01-06", str(lifecycle)))
        assert first["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            pending = pd.read_csv(root / "paper" / portfolio / "pending_orders.csv")
            assert pending["ticker"].tolist() == ["OLD"]
            assert pending["execution_ticker"].tolist() == ["NEW"]

        second = run(args_for(root, "2026-01-07", str(lifecycle)))
        assert second["status"] == "completed"
        for portfolio in ("main", "concentrated"):
            account = json.loads(
                (root / "paper" / portfolio / "account_state_latest.json").read_text(
                    encoding="utf-8"
                )
            )
            assert not account["positions"]
            fills = pd.read_csv(root / "paper" / portfolio / "fills.csv")
            assert set(fills["ticker"]) == {"OLD"}
            assert set(fills["execution_ticker"]) == {"NEW"}
            source_path = (
                root
                / "paper"
                / portfolio
                / str(fills.iloc[0]["execution_price_source_path"])
            )
            source = json.loads(source_path.read_text(encoding="utf-8"))
            assert source["ticker"] == "OLD"
            assert source["execution_ticker"] == "NEW"
            assert source["fill_date"] == "2026-01-07"
            assert float(source["observations"][0]["close"]) == 121.0


def test_last_terminal_stock_materializes_explicit_all_cash_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 103.0])
        lifecycle = root / "security_lifecycle.csv"
        write_lifecycle(lifecycle)
        for portfolio in ("main", "concentrated"):
            write_seed(root / "seed" / f"{portfolio}.json", portfolio)
            (root / "targets").mkdir(parents=True, exist_ok=True)
            target = pd.DataFrame(
                [
                    {"rebalance_date": "2026-01-05", "ticker": "AAA", "weight": 0.50},
                    {"rebalance_date": "2026-01-05", "ticker": "CASH", "weight": 0.50},
                ]
            )
            source_reconciliation = reserve_reason_reconciliation(
                target,
                policy=resolve_reserve_asset_policy(context="current_paper"),
                weight_col="weight",
            )
            target[RESERVE_REASON_SOURCE_HASH_FIELD] = source_reconciliation[
                RESERVE_REASON_SOURCE_HASH_FIELD
            ]
            target.to_csv(root / "targets" / f"{portfolio}.csv", index=False)
        run(args_for(root, "2026-01-05", str(lifecycle)))
        run(args_for(root, "2026-01-06", str(lifecycle)))
        for portfolio in ("main", "concentrated"):
            target = pd.read_csv(root / "paper" / portfolio / "effective_target_latest.csv")
            assert target["ticker"].tolist() == ["CASH"]
            assert float(target.iloc[0]["weight"]) == 1.0
            assert target[RESERVE_REASON_SOURCE_HASH_FIELD].nunique() == 1
            assert target.iloc[0][RESERVE_REASON_SOURCE_HASH_FIELD] != source_reconciliation[
                RESERVE_REASON_SOURCE_HASH_FIELD
            ]


def test_empty_source_target_never_synthesizes_all_cash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "empty_target.csv"
        pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(
            source, index=False
        )
        try:
            materialize_lifecycle_adjusted_target(
                source_target_path=source,
                output_path=root / "effective.csv",
                portfolio="main",
                as_of_date=pd.Timestamp("2026-01-06"),
                lifecycle=empty_snapshot(
                    session_date=pd.Timestamp("2026-01-06"),
                    decision_time_utc=pd.Timestamp("2026-01-06T23:00:00Z"),
                ),
                reserve_policy=resolve_reserve_asset_policy(),
                reserve_mode_explicit=False,
            )
        except Exception as exc:
            assert getattr(exc, "status", "") == "BLOCKED_TARGET_EVIDENCE"
        else:
            raise AssertionError("empty target was converted to CASH=1.0")


def test_same_session_reuse_without_lifecycle_source_hash_blocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir(parents=True)
        write_prices(cache, "AAA", [100.0, 102.0, 103.0])
        write_prices(cache, "BBB", [50.0, 51.0, 52.0])
        for portfolio in ("main", "concentrated"):
            write_seed(root / "seed" / f"{portfolio}.json", portfolio)
            write_target(root / "targets" / f"{portfolio}.csv")
        run(args_for(root, "2026-01-05", ""))
        try:
            run(args_for(root, "2026-01-05", ""))
        except Exception as exc:
            assert getattr(exc, "status", "") == "BLOCKED_LIFECYCLE_EVIDENCE"
            assert "source hash" in str(exc)
        else:
            raise AssertionError("exact bundle reuse without lifecycle source hash was accepted")


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
            assert (
                "genesis identity changed" in str(exc)
                or "target_hash" in str(exc)
                or "target weight exceeds one" in str(exc)
            )
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
            preview_manifest = json.loads(
                (root / "previews" / portfolio / "order_batch_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            preview_target = pd.read_csv(
                root / "previews" / portfolio / "target_weights.csv"
            )
            assert RESERVE_REASON_SOURCE_HASH_FIELD in preview_target.columns
            assert set(preview_target[RESERVE_REASON_SOURCE_HASH_FIELD]) == {
                preview_manifest[RESERVE_REASON_SOURCE_HASH_FIELD]
            }

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


def _write_standard_fixture_inputs(root: Path) -> None:
    cache = root / "cache_prices"
    cache.mkdir(parents=True)
    write_prices(cache, "AAA", [100.0, 102.0, 103.0])
    write_prices(cache, "BBB", [50.0, 51.0, 52.0])
    for portfolio in ("main", "concentrated"):
        write_seed(root / "seed" / f"{portfolio}.json", portfolio)
        write_target(root / "targets" / f"{portfolio}.csv")


def _reseal_fill_chain(portfolio_dir: Path) -> None:
    fills_path = portfolio_dir / "fills.csv"
    fills = pd.read_csv(fills_path).sort_values("event_sequence")
    previous = GENESIS_HASH
    rows: list[dict] = []
    for row in fills.to_dict("records"):
        row["previous_event_hash"] = previous
        row["event_hash"] = canonical_hash(event_payload_for_hash(row))
        previous = str(row["event_hash"])
        rows.append(row)
    pd.DataFrame(rows).to_csv(fills_path, index=False)
    try:
        rejections = pd.read_csv(portfolio_dir / "rejections.csv")
    except pd.errors.EmptyDataError:
        rejections = pd.DataFrame()
    sequence, chain_hash, _client_ids = validate_event_chain(
        pd.read_csv(fills_path),
        rejections,
    )
    for name in ("manifest.json", "state_meta.json"):
        path = portfolio_dir / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["event_sequence"] = sequence
        payload["event_chain_hash"] = chain_hash
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_restored_snapshot_rejects_resealed_impossible_fill() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_standard_fixture_inputs(root)
        run(args_for(root, "2026-01-05"))
        run(args_for(root, "2026-01-06"))
        directory = root / "paper" / "main"
        validate_restored_snapshot(
            directory,
            "main",
            bootstrap_path=root / "seed" / "main.json",
        )

        fills_path = directory / "fills.csv"
        fills = pd.read_csv(fills_path).sort_values("event_sequence")
        fills.loc[fills.index[0], "cash_delta"] = 1_000_000_000.0
        fills.to_csv(fills_path, index=False)
        _reseal_fill_chain(directory)
        try:
            validate_restored_snapshot(
                directory,
                "main",
                bootstrap_path=root / "seed" / "main.json",
            )
        except PaperLedgerIntegrityError as exc:
            assert "cash_delta_mismatch" in str(exc)
        else:
            raise AssertionError(
                "hash-resealed economically impossible fill was accepted"
            )


def test_restored_snapshot_binds_fill_to_attested_execution_close() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_standard_fixture_inputs(root)
        run(args_for(root, "2026-01-05"))
        run(args_for(root, "2026-01-06"))
        directory = root / "paper" / "main"
        fills_path = directory / "fills.csv"
        fills = pd.read_csv(fills_path).sort_values("event_sequence")
        first = fills.iloc[0]
        source_relative = str(first["execution_price_source_path"])
        source_path = directory / source_relative
        source = json.loads(source_path.read_text(encoding="utf-8"))
        assert source["execution_ticker"] == first["execution_ticker"]
        assert source["fill_date"] == first["date"]
        assert float(source["observations"][0]["close"]) == float(
            first["fill_price"]
        )
        integrity = json.loads(
            (root / "paper" / "snapshot_integrity.json").read_text(
                encoding="utf-8"
            )
        )
        integrity_key = f"main/{source_relative}"
        assert (
            integrity["files"][integrity_key]
            == hashlib.sha256(source_path.read_bytes()).hexdigest()
            == first["execution_price_source_sha256"]
        )

        # Mutating the frozen source and resealing both its event reference and
        # the event-chain manifests must still fail exact-close semantic replay.
        source["observations"][0]["close"] = (
            float(source["observations"][0]["close"]) + 1.0
        )
        source_path.write_text(json.dumps(source), encoding="utf-8")
        fills.loc[
            fills.index[0], "execution_price_source_sha256"
        ] = hashlib.sha256(source_path.read_bytes()).hexdigest()
        fills.to_csv(fills_path, index=False)
        _reseal_fill_chain(directory)
        try:
            validate_restored_snapshot(
                directory,
                "main",
                bootstrap_path=root / "seed" / "main.json",
            )
        except PaperLedgerIntegrityError as exc:
            assert "execution_price_exact_close_mismatch" in str(exc)
        else:
            raise AssertionError(
                "hash-resealed mutated execution close was accepted"
            )


def test_execution_price_source_chronology_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_standard_fixture_inputs(root)
        run(args_for(root, "2026-01-05"))
        run(args_for(root, "2026-01-06"))
        directory = root / "paper" / "main"
        fills_path = directory / "fills.csv"
        fills = pd.read_csv(fills_path).sort_values("event_sequence")
        source_path = (
            directory / str(fills.iloc[0]["execution_price_source_path"])
        )
        originals = {
            path: path.read_bytes()
            for path in (
                fills_path,
                directory / "manifest.json",
                directory / "state_meta.json",
                source_path,
            )
        }

        def restore() -> tuple[pd.DataFrame, dict]:
            for path, payload in originals.items():
                path.write_bytes(payload)
            return (
                pd.read_csv(fills_path).sort_values("event_sequence"),
                json.loads(source_path.read_text(encoding="utf-8")),
            )

        for mode in ("same_day", "stale", "future"):
            candidate_fills, source = restore()
            if mode == "same_day":
                event_date = str(candidate_fills.iloc[0]["date"])
                candidate_fills.loc[
                    candidate_fills.index[0], "signal_date"
                ] = event_date
                source["signal_date"] = event_date
                source["first_eligible_date"] = (
                    pd.Timestamp(event_date) + pd.Timedelta(days=1)
                ).date().isoformat()
            elif mode == "stale":
                source["observations"][0]["date"] = source["signal_date"]
            else:
                source["captured_through"] = (
                    pd.Timestamp(source["fill_date"]) + pd.Timedelta(days=1)
                ).date().isoformat()
            source_path.write_text(json.dumps(source), encoding="utf-8")
            candidate_fills.loc[
                candidate_fills.index[0],
                "execution_price_source_sha256",
            ] = hashlib.sha256(source_path.read_bytes()).hexdigest()
            candidate_fills.to_csv(fills_path, index=False)
            _reseal_fill_chain(directory)
            try:
                validate_restored_snapshot(
                    directory,
                    "main",
                    bootstrap_path=root / "seed" / "main.json",
                )
            except PaperLedgerIntegrityError as exc:
                if mode == "stale":
                    assert "execution_price_exact_close_mismatch" in str(exc)
                else:
                    assert (
                        "execution_price_source_chronology_invalid"
                        in str(exc)
                    )
            else:
                raise AssertionError(
                    f"{mode} execution price source was accepted"
                )


def test_restored_snapshot_rejects_pending_schema_and_domain_tampering() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_standard_fixture_inputs(root)
        run(args_for(root, "2026-01-05"))
        directory = root / "paper" / "main"
        seed = root / "seed" / "main.json"
        validate_restored_snapshot(
            directory, "main", bootstrap_path=seed
        )
        pending_path = directory / "pending_orders.csv"
        original = pending_path.read_bytes()

        pending = pd.read_csv(pending_path)
        pending["broker_order_sent"] = True
        pending.to_csv(pending_path, index=False)
        try:
            validate_restored_snapshot(
                directory, "main", bootstrap_path=seed
            )
        except PaperLedgerIntegrityError as exc:
            assert "pending:schema_mismatch" in str(exc)
        else:
            raise AssertionError("pending order schema expansion was accepted")

        pending_path.write_bytes(original)
        pending = pd.read_csv(pending_path)
        pending.loc[pending.index[0], "quantity"] = -1
        pending.to_csv(pending_path, index=False)
        try:
            validate_restored_snapshot(
                directory, "main", bootstrap_path=seed
            )
        except PaperLedgerIntegrityError as exc:
            assert "positive_integer_required" in str(exc)
        else:
            raise AssertionError("negative pending order quantity was accepted")


def test_restored_snapshot_rejects_fill_schema_tampering() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_standard_fixture_inputs(root)
        run(args_for(root, "2026-01-05"))
        run(args_for(root, "2026-01-06"))
        directory = root / "paper" / "main"
        fills_path = directory / "fills.csv"
        fills = pd.read_csv(fills_path).drop(columns=["execution_ticker"])
        fills.to_csv(fills_path, index=False)
        _reseal_fill_chain(directory)

        try:
            validate_restored_snapshot(
                directory,
                "main",
                bootstrap_path=root / "seed" / "main.json",
            )
        except PaperLedgerIntegrityError as exc:
            assert "fills:schema_mismatch" in str(exc)
            assert "execution_ticker" in str(exc)
        else:
            raise AssertionError("hash-resealed incomplete fill schema was accepted")


def test_restored_snapshot_rejects_zero_fill_account_totals_tampering() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_standard_fixture_inputs(root)
        run(args_for(root, "2026-01-05"))
        directory = root / "paper" / "main"
        account_path = directory / "account_state_latest.json"
        account = json.loads(account_path.read_text(encoding="utf-8"))
        assert account["forward_fill_count"] == 0
        account["total_fees_usd"] = 123.0
        account["forward_fill_count"] = 7
        account_path.write_text(json.dumps(account), encoding="utf-8")

        try:
            validate_restored_snapshot(
                directory,
                "main",
                bootstrap_path=root / "seed" / "main.json",
            )
        except PaperLedgerIntegrityError as exc:
            assert "account.fill_totals:replay_mismatch" in str(exc)
        else:
            raise AssertionError("zero-fill account totals tampering was accepted")


def main() -> int:
    test_pending_resolves_once_at_next_close()
    test_next_close_uses_nyse_calendar_and_never_skips_missing_session()
    test_verified_cash_merger_settles_without_future_close_and_cancels_pending()
    test_delayed_catchup_fills_before_terminal_settlement()
    test_ticker_change_uses_successor_exact_close_after_last_trade()
    test_post_cutover_exit_executes_against_predecessor_ledger_position()
    test_last_terminal_stock_materializes_explicit_all_cash_target()
    test_empty_source_target_never_synthesizes_all_cash()
    test_same_session_reuse_without_lifecycle_source_hash_blocks()
    test_bootstrap_does_not_retrade_an_already_effective_target()
    test_same_session_price_revision_reuses_frozen_state_and_input_change_fails_closed()
    test_suppressed_mark_can_transition_once_to_fresh_same_close_target()
    test_restored_snapshot_rejects_resealed_impossible_fill()
    test_restored_snapshot_binds_fill_to_attested_execution_close()
    test_execution_price_source_chronology_fails_closed()
    test_restored_snapshot_rejects_pending_schema_and_domain_tampering()
    test_restored_snapshot_rejects_fill_schema_tampering()
    test_restored_snapshot_rejects_zero_fill_account_totals_tampering()
    print("daily_simulated_fill_ledger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
