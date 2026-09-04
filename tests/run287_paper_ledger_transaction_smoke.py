#!/usr/bin/env python3
"""Transactional, exact-close, and continuity acceptance checks for Run287 P0."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pandas_market_calendars as mcal


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run287_paper_ledger_integrity import (  # noqa: E402
    PaperLedgerIntegrityError,
    directory_hashes,
    install_verified_snapshot,
    reconcile_immutable_paper_head_cache,
    require_state_descends_from,
    select_verified_immutable_paper_head,
    verify_integrity_manifest,
    write_integrity_manifest,
)
from tools.run_daily_simulated_fill_ledger import (  # noqa: E402
    GENESIS_HASH,
    LEGACY_SCHEMA_PROFILE_CURRENT_V2,
    LEGACY_SCHEMA_PROFILE_V1_ZERO_EVENT,
    canonical_hash,
    ensure_genesis_identity,
    event_payload_for_hash,
    file_hash,
    run,
    validate_target_handoff,
    validate_event_chain,
)
from tools.prepare_run287_legacy_paper_migration import (  # noqa: E402
    prepare_migration,
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
        "schema_version": "run287-daily-paper-bootstrap-account-v1",
        "portfolio_kind": portfolio,
        "as_of_date": date,
        "seed_as_of_date": date,
        "starting_capital_usd": 2_000.0,
        "seed_equity_usd": 2_000.0,
        "equity_usd": 2_000.0,
        "cash_usd": cash,
        "cash_weight": cash / 2_000.0,
        "stock_value_usd": 1_000.0,
        "position_count": 1,
        "fill_mode": "next_close",
        "cost_bps_per_side": 25.0,
        "integer_shares": True,
        "cash_carry_mode": "none",
        "assumed_applied_target_hash": ("a" if portfolio == "main" else "b") * 64,
        "target_sha256": ("c" if portfolio == "main" else "d") * 64,
        "positions": [
            {
                "as_of_date": date,
                "ticker": ticker,
                "shares": 10.0,
                "price": 100.0,
                "market_value_usd": 1_000.0,
                "weight": 0.5,
                "cost_basis": 100.0,
                "seed_position_assumption": (
                    "target_assumed_applied_at_exact_close"
                ),
            }
        ],
        "realized_pnl_by_ticker": {},
        "bootstrap_method": (
            "exact_close_target_snapshot_without_historical_trade_backfill"
        ),
        "historical_trade_backfill_claimed": False,
        "portfolio_weights_changed": False,
        "review_only": True,
        "simulated_broker_ledger": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "human_approval_required_for_live_orders": True,
        "created_at_utc": f"{date}T23:00:00+00:00",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_target(
    path: Path,
    portfolio: str,
    ticker: str,
    date: str,
    *,
    stock_weight: float = 0.50,
    eligible_close_date: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "rebalance_date": date,
                "ticker": ticker,
                "weight": stock_weight,
                "portfolio_kind": portfolio,
                "target_effective_date": date,
                "order_eligible_close_date": eligible_close_date or date,
            },
            {
                "rebalance_date": date,
                "ticker": "CASH",
                "weight": 1.0 - stock_weight,
                "portfolio_kind": portfolio,
                "target_effective_date": date,
                "order_eligible_close_date": eligible_close_date or date,
            },
        ]
    ).to_csv(path, index=False)


def ledger_args(
    root: Path,
    date: str,
    *,
    failpoint: str = "",
    suppress_new_orders: bool = False,
    publish_targets: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        state_dir=str(root / "paper"),
        price_cache=str(root / "prices"),
        order_preview_root=str(root / "previews"),
        main_bootstrap_account=str(root / "seed" / "main.json"),
        concentrated_bootstrap_account=str(root / "seed" / "concentrated.json"),
        main_target=str(root / "targets" / "main.csv"),
        concentrated_target=str(root / "targets" / "concentrated.csv"),
        as_of_date=date,
        decision_time_utc=f"{date}T23:00:00Z",
        security_lifecycle_events=str(
            ROOT / "data_static" / "run287_exact_packet" / "security_lifecycle_events.csv"
        ),
        cost_bps=25.0,
        max_fill_lag_days=7,
        transaction_failpoint=failpoint,
        suppress_new_orders=suppress_new_orders,
        main_publish_target=str(root / "published" / "operating_main_target_book.csv") if publish_targets else "",
        concentrated_publish_target=str(root / "published" / "operating_concentrated_target_book.csv") if publish_targets else "",
    )


def test_same_close_target_handoff_is_hash_pinned() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        date = "2026-01-05"
        targets = {
            "main": root / "targets" / "main.csv",
            "concentrated": root / "targets" / "concentrated.csv",
        }
        for portfolio, path in targets.items():
            write_target(path, portfolio, "AAA", date)
        status_path = root / "same_close" / "status.json"
        status_path.parent.mkdir(parents=True)
        status = {
            "schema_version": "run287-same-close-target-books-v1",
            "status": "READY_SAME_CLOSE_PAPER_TARGETS",
            "valuation_close_date": date,
            "target_book_file_written": True,
            "orders_generated": False,
            "paper_only": True,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "fullrun_executed": False,
            "outputs": {
                f"{portfolio}_target_book": {
                    "path": str(path.resolve()),
                    "sha256": file_hash(path),
                }
                for portfolio, path in targets.items()
            },
        }
        status_path.write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args = SimpleNamespace(
            target_handoff_manifest=str(status_path),
            expected_target_handoff_sha256=file_hash(status_path),
            main_target_sha256=file_hash(targets["main"]),
            concentrated_target_sha256=file_hash(targets["concentrated"]),
        )
        audit = validate_target_handoff(
            args=args,
            target_paths=targets,
            as_of_date=pd.Timestamp(date),
        )
        assert audit["manifest_sha256"] == file_hash(status_path)

        targets["main"].write_bytes(
            targets["main"].read_bytes() + b"\n"
        )
        try:
            validate_target_handoff(
                args=args,
                target_paths=targets,
                as_of_date=pd.Timestamp(date),
            )
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_TARGET_HANDOFF"
        else:
            raise AssertionError("changed same-close target must block ledger handoff")


def pinned_legacy_args(
    root: Path,
    requested_date: str,
    *,
    profile: str = LEGACY_SCHEMA_PROFILE_CURRENT_V2,
) -> SimpleNamespace:
    paper = root / "paper"
    summary = json.loads(
        (paper / "summary.json").read_text(encoding="utf-8")
    )
    tree_sha256 = canonical_hash(directory_hashes(paper))
    provenance_path = root / (
        f"legacy_migration_{requested_date.replace('-', '')}.json"
    )
    provenance_path.write_text(
        json.dumps(
            {
                "schema_version": "run287-legacy-drive-paper-migration-v1",
                "status": "PENDING_SEMANTIC_ATTESTATION",
                "source": "GITHUB_ACTIONS_ARTIFACT_TREE_SHA256_PIN",
                "source_artifact_run_id": "1",
                "source_artifact_id": "2",
                "source_artifact_digest": f"sha256:{'e' * 64}",
                "legacy_as_of_date": summary["as_of_date"],
                "requested_as_of_date": requested_date,
                "remote_snapshot_integrity_present": False,
                "verified_cross_source_anchor_present": True,
                "legacy_semantic_attestation_required": True,
                "legacy_schema_profile": profile,
                "accepted_for_use": False,
                "review_only": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "remote_tree_file_count": len(directory_hashes(paper)),
                "expected_source_tree_sha256": tree_sha256,
                "remote_tree_sha256": tree_sha256,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    args = ledger_args(
        root,
        requested_date,
        suppress_new_orders=True,
    )
    args.legacy_migration_provenance = str(provenance_path)
    args.legacy_migration_expected_source_tree_sha256 = tree_sha256
    return args


def prepare(root: Path, dates: list[str]) -> None:
    write_prices(root / "prices", "AAA", dates, [100.0 + index for index in range(len(dates))])
    write_prices(root / "prices", "BBB", dates, [100.0 + 2 * index for index in range(len(dates))])
    write_seed(root / "seed" / "main.json", "main", "AAA", dates[0])
    write_seed(root / "seed" / "concentrated.json", "concentrated", "BBB", dates[0])
    write_target(root / "targets" / "main.csv", "main", "AAA", dates[0])
    write_target(root / "targets" / "concentrated.csv", "concentrated", "BBB", dates[0])


def write_replay_price_manifest(
    root: Path,
    session_date: str,
    *,
    tickers: tuple[str, ...] = ("AAA", "BBB"),
) -> Path:
    cache = root / "prices"
    price_files = []
    for ticker in sorted(tickers):
        path = cache / px_cache_name(ticker)
        source = pd.read_parquet(path)
        source.index = pd.to_datetime(source.index)
        row = source.loc[pd.Timestamp(session_date)]
        close = float(row.get("Adj Close", row.get("Close")))
        pd.DataFrame(
            {
                "Open": [close],
                "High": [close],
                "Low": [close],
                "Close": [close],
                "Adj Close": [close],
                "Volume": [float(row.get("Volume", 0.0))],
            },
            index=pd.DatetimeIndex(
                [pd.Timestamp(session_date)],
                name="Date",
            ),
        ).to_parquet(path)
        price_files.append(
            {
                "ticker": ticker,
                "path": path.name,
                "rows": 1,
                "session_date": session_date,
                "bytes": path.stat().st_size,
                "sha256": file_hash(path),
                "reference_ohlc_anomaly_codes": [],
            }
        )
    manifest = {
        "schema_version": "run287-catchup-price-cache-manifest-v1",
        "status": "READY_RUN287_CATCHUP_PRICE_EVIDENCE_REPLAY_ONLY",
        "selected_session_date": session_date,
        "official_market_close_utc": (
            f"{session_date}T20:00:00+00:00"
        ),
        "source_generated_at_utc": (
            f"{session_date}T21:00:00+00:00"
        ),
        "artifact_captured_at_utc": (
            f"{session_date}T22:00:00+00:00"
        ),
        "ingested_at_utc": f"{session_date}T23:00:00+00:00",
        "artifact": {
            "run_id": "29801446668",
            "artifact_id": "8484210406",
            "artifact_name": (
                "daily-operating-selection-refresh-29801446668"
            ),
            "expected_zip_sha256": "a" * 64,
            "api_digest": f"sha256:{'a' * 64}",
            "workflow_id": "296748480",
            "workflow_path": (
                ".github/workflows/"
                "daily_operating_selection_refresh.yml"
            ),
            "head_branch": "master",
            "head_sha": "b" * 40,
            "workflow_event": "schedule",
            "workflow_status": "completed",
            "workflow_conclusion": "failure",
            "workflow_run_attempt": "1",
            "repository": "wscha231/r1000-quant-engine",
            "head_repository": "wscha231/r1000-quant-engine",
            "default_branch": "master",
            "current_default_head_sha": "c" * 40,
            "origin_verification_mode": "DEFAULT_BRANCH_ANCESTOR",
            "workflow_identity_verified": True,
            "repository_identity_verified": True,
            "head_lineage_verified": True,
            "run_id_verified_against_artifact_root": True,
        },
        "required_tickers": list(sorted(tickers)),
        "ticker_count": len(tickers),
        "price_files": price_files,
        "price_usage_scope": "REPLAY_MARK_AND_NEXT_CLOSE_FILL_ONLY",
        "ohlc_execution_eligible": False,
        "reference_ohlc_anomaly_count": 0,
        "reference_ohlc_anomalies": [],
        "replay_only": True,
        "forward_promotion_eligible": False,
        "review_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
    }
    path = cache / "manifest.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def replay_ledger_args(root: Path, session_date: str) -> SimpleNamespace:
    args = ledger_args(root, session_date, suppress_new_orders=True)
    args.replay_only = True
    args.price_evidence_manifest = str(
        write_replay_price_manifest(root, session_date)
    )
    return args


def downgrade_to_legacy_v1_zero_event(root: Path, date: str) -> None:
    paper = root / "paper"
    for name in (
        "snapshot_integrity.json",
        "accepted_publication.json",
        "genesis_identity.json",
        "legacy_migration_attestation.json",
    ):
        path = paper / name
        if path.exists():
            path.unlink()

    account_keys = {
        "schema_version",
        "portfolio_kind",
        "as_of_date",
        "seed_as_of_date",
        "seed_equity_usd",
        "seed_account_sha256",
        "starting_capital_usd",
        "equity_usd",
        "cash_usd",
        "cash_weight",
        "stock_value_usd",
        "position_count",
        "fill_mode",
        "cost_bps_per_side",
        "integer_shares",
        "cash_carry_mode",
        "cash_carry_note",
        "positions",
        "realized_pnl_by_ticker",
        "total_realized_pnl_usd",
        "total_fees_usd",
        "forward_fill_count",
        "pending_order_count",
        "review_only",
        "simulated_broker_ledger",
        "live_trading_enabled",
        "production_mutation_allowed",
        "human_approval_required_for_live_orders",
    }
    bootstrap_keys = {
        "schema_version",
        "portfolio_kind",
        "as_of_date",
        "seed_as_of_date",
        "starting_capital_usd",
        "seed_equity_usd",
        "equity_usd",
        "cash_usd",
        "cash_weight",
        "stock_value_usd",
        "position_count",
        "fill_mode",
        "cost_bps_per_side",
        "integer_shares",
        "cash_carry_mode",
        "positions",
        "realized_pnl_by_ticker",
        "target_sha256",
        "assumed_applied_target_hash",
        "bootstrap_method",
        "historical_trade_backfill_claimed",
        "portfolio_weights_changed",
        "review_only",
        "simulated_broker_ledger",
        "live_trading_enabled",
        "production_mutation_allowed",
        "human_approval_required_for_live_orders",
        "created_at_utc",
    }
    manifest_keys = {
        "schema_version",
        "portfolio_kind",
        "as_of_date",
        "seeded_this_run",
        "fill_mode",
        "cost_bps_per_side",
        "integer_shares",
        "max_fill_lag_days",
        "target_hash",
        "target_effective_date",
        "target_sha256",
        "seed_account_sha256",
        "event_sequence",
        "event_chain_hash",
        "resolved_fills_this_run",
        "resolved_rejections_this_run",
        "enqueued_this_run",
        "pending_order_count",
        "fill_count",
        "rejection_count",
        "forward_metrics",
        "review_only",
        "simulated",
        "live_trading_enabled",
        "production_mutation_allowed",
        "historical_cagr_mdd_replacement_allowed",
    }
    meta_keys = {
        "schema_version",
        "portfolio_kind",
        "as_of_date",
        "event_sequence",
        "event_chain_hash",
        "pending_order_count",
        "fill_count",
        "rejection_count",
        "last_enqueued_target_hash",
        "last_enqueued_signal_date",
        "last_order_batch_id",
        "last_enqueue_status",
        "last_enqueue_count",
        "review_only",
        "live_trading_enabled",
        "production_mutation_allowed",
        "updated_at_utc",
    }
    summary = json.loads((paper / "summary.json").read_text(encoding="utf-8"))
    manifests: dict[str, dict] = {}
    for portfolio in ("main", "concentrated"):
        portfolio_dir = paper / portfolio
        for extra in ("effective_target_latest.csv",):
            path = portfolio_dir / extra
            if path.exists():
                path.unlink()
        execution_sources = portfolio_dir / "execution_price_sources"
        if execution_sources.exists():
            shutil.rmtree(execution_sources)

        manifest_path = portfolio_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = "daily-simulated-fill-ledger-manifest-v1"
        manifest["target_sha256"] = file_hash(
            root / "targets" / f"{portfolio}.csv"
        )
        manifest = {
            key: value
            for key, value in manifest.items()
            if key in manifest_keys
        }

        bootstrap_path = paper / "bootstrap" / f"{portfolio}_account.json"
        bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
        bootstrap["schema_version"] = "run287-daily-paper-bootstrap-account-v1"
        bootstrap["assumed_applied_target_hash"] = manifest["target_hash"]
        bootstrap = {
            key: value
            for key, value in bootstrap.items()
            if key in bootstrap_keys
        }
        for position in bootstrap.get("positions", []):
            position.pop("reserve_asset", None)
        bootstrap_path.write_text(
            json.dumps(bootstrap, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (root / "seed" / f"{portfolio}.json").write_bytes(
            bootstrap_path.read_bytes()
        )
        seed_sha = directory_hashes(paper / "bootstrap")[
            f"{portfolio}_account.json"
        ]
        manifest["seed_account_sha256"] = seed_sha

        account_path = portfolio_dir / "account_state_latest.json"
        account = json.loads(account_path.read_text(encoding="utf-8"))
        account["seed_account_sha256"] = seed_sha
        account = {
            key: value
            for key, value in account.items()
            if key in account_keys
        }
        for position in account.get("positions", []):
            position.pop("reserve_asset", None)
        account_path.write_text(
            json.dumps(account, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        pd.DataFrame(account["positions"])[
            [
                "as_of_date",
                "ticker",
                "shares",
                "price",
                "market_value_usd",
                "weight",
                "cost_basis",
                "unrealized_pnl_usd",
                "realized_pnl_usd",
            ]
        ].to_csv(portfolio_dir / "positions_latest.csv", index=False)

        meta_path = portfolio_dir / "state_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["schema_version"] = "daily-simulated-fill-ledger-state-v1"
        meta["last_enqueued_target_hash"] = manifest["target_hash"]
        meta["last_enqueued_signal_date"] = bootstrap["seed_as_of_date"]
        meta["last_order_batch_id"] = ""
        meta["last_enqueue_status"] = "BOOTSTRAP_TARGET_ASSUMED_APPLIED"
        meta["last_enqueue_count"] = 0
        meta = {
            key: value
            for key, value in meta.items()
            if key in meta_keys
        }
        meta_path.write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifests[portfolio] = manifest

        pd.DataFrame(
            columns=[
                "portfolio_kind",
                "signal_date",
                "ticker",
                "side",
                "quantity",
                "reference_price",
                "target_weight",
                "reason",
                "fill_mode",
                "cost_bps_per_side",
                "client_order_id",
                "idempotency_key",
                "order_batch_id",
                "target_hash",
                "priority",
                "pending_status",
                "created_at_utc",
            ]
        ).to_csv(portfolio_dir / "pending_orders.csv", index=False)
        (portfolio_dir / "fills.csv").write_text("\n", encoding="utf-8")
        (portfolio_dir / "rejections.csv").write_text("\n", encoding="utf-8")
        curve_path = portfolio_dir / "equity_curve.csv"
        pd.read_csv(curve_path)[
            [
                "date",
                "equity_usd",
                "cash_usd",
                "cash_weight",
                "stock_value_usd",
                "position_count",
                "record_type",
            ]
        ].to_csv(curve_path, index=False)

    legacy_summary = {
        "schema_version": "daily-simulated-fill-ledger-summary-v1",
        "status": "completed",
        "as_of_date": date,
        "portfolios": manifests,
        "review_only": True,
        "simulated": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "historical_cagr_mdd_replacement_allowed": False,
        "generated_at_utc": summary.get("generated_at_utc"),
    }
    (paper / "summary.json").write_text(
        json.dumps(legacy_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (paper / "bootstrap" / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "run287-daily-paper-bootstrap-v1",
                "status": "READY_REVIEW_ONLY_PAPER_BOOTSTRAP",
                "as_of_date": date,
                "expected_seed_date": json.loads(
                    (
                        paper / "bootstrap" / "main_account.json"
                    ).read_text(encoding="utf-8")
                )["seed_as_of_date"],
                "starting_capital_usd": 2_000.0,
                "cost_bps_per_side": 25.0,
                "created_account_count": 0,
                "results": {
                    portfolio: {
                        "status": "RESTORED_STATE_PRESENT",
                        "account_path": str(
                            paper
                            / portfolio
                            / "account_state_latest.json"
                        ),
                        "account_sha256": file_hash(
                            paper
                            / portfolio
                            / "account_state_latest.json"
                        ),
                    }
                    for portfolio in ("main", "concentrated")
                },
                "historical_trade_backfill_claimed": False,
                "fullrun_executed": False,
                "target_books_changed": False,
                "portfolio_weights_changed": False,
                "orders_placed": False,
                "review_only": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "generated_at_utc": summary.get("generated_at_utc"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_twenty_sessions_remain_continuous_and_same_session_is_byte_identical() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = [
            date.date().isoformat()
            for date in mcal.get_calendar("NYSE")
            .schedule(start_date="2026-01-02", end_date="2026-02-03")
            .index[:20]
        ]
        prepare(root, dates)
        statuses: list[str] = []
        for index, date in enumerate(dates):
            result = run(ledger_args(root, date))
            statuses.append(str(result["result_status"]))
            if index == 0:
                assert "legacy_snapshot_semantically_validated" not in result
                assert "legacy_snapshot_semantic_attestation_mode" not in result
                shutil.copytree(root / "paper", root / "first_snapshot")
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
        shutil.copytree(root / "first_snapshot", root / "restored_snapshot")
        installed = install_verified_snapshot(
            root / "paper",
            root / "restored_snapshot",
            require_continuity=True,
        )
        assert installed["install_status"] == "INSTALLED_VERIFIED_DESCENDANT"
        assert (
            verify_integrity_manifest(
                root / "restored_snapshot", require=True
            )["snapshot_hash"]
            == verified["snapshot_hash"]
        )
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


def test_session_gap_requires_chronological_catchup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = ["2026-02-02", "2026-02-03", "2026-02-04"]
        prepare(root, dates)
        run(ledger_args(root, dates[0], suppress_new_orders=True))
        state_before = directory_hashes(root / "paper")
        preview_before = directory_hashes(root / "previews")
        try:
            run(
                ledger_args(
                    root,
                    dates[-1],
                    suppress_new_orders=True,
                )
            )
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_SESSION_GAP"
            assert f"expected_next={dates[1]}" in str(exc)
        else:
            raise AssertionError("paper ledger skipped a required NYSE session")
        assert directory_hashes(root / "paper") == state_before
        assert directory_hashes(root / "previews") == preview_before


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


def test_suppressed_preview_is_explicit_hash_bound_and_transition_safe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-01"
        prepare(root, [date])

        first = run(ledger_args(root, date, suppress_new_orders=True))
        assert first["new_order_generation_suppressed"] is True
        for portfolio in ("main", "concentrated"):
            preview_dir = root / "previews" / portfolio
            manifest = json.loads((preview_dir / "order_batch_manifest.json").read_text(encoding="utf-8"))
            metrics = json.loads((preview_dir / "preview_metrics.json").read_text(encoding="utf-8"))
            orders = pd.read_csv(preview_dir / "orders_preview.csv")
            assert manifest["preview_mode"] == "NO_NEW_ORDER"
            assert metrics["preview_mode"] == "NO_NEW_ORDER"
            assert manifest["accepted_account_sha256"] == directory_hashes(root / "paper")[f"{portfolio}/account_state_latest.json"]
            assert len(manifest["accepted_account_sha256"]) == 64
            assert len(manifest["source_target_sha256"]) == 64
            assert len(manifest["effective_target_sha256"]) == 64
            assert len(manifest["preview_identity_hash"]) == 64
            assert manifest["as_of_date"] == date
            assert "order_eligible_close_date" in manifest
            assert orders.empty

        write_target(root / "targets" / "main.csv", "main", "AAA", date, stock_weight=0.60)
        write_target(root / "targets" / "concentrated.csv", "concentrated", "BBB", date, stock_weight=0.60)
        selected = run(ledger_args(root, date))
        assert selected["result_status"] in {"RESTORED_CONTINUATION", "GENESIS"}
        selected_state = directory_hashes(root / "paper")
        selected_hash = json.loads(
            (root / "paper" / "snapshot_integrity.json").read_text(
                encoding="utf-8"
            )
        )["snapshot_hash"]

        mark_only = run(ledger_args(root, date, suppress_new_orders=True))
        assert mark_only["result_status"] == "NO_NEW_ORDER_PREVIEW"
        assert directory_hashes(root / "paper") == selected_state
        assert json.loads(
            (root / "paper" / "accepted_publication.json").read_text(
                encoding="utf-8"
            )
        )["transaction_mode"] == "SELECTED_TARGET"
        assert json.loads(
            (root / "paper" / "snapshot_integrity.json").read_text(
                encoding="utf-8"
            )
        )["snapshot_hash"] == selected_hash
        for portfolio in ("main", "concentrated"):
            preview_dir = root / "previews" / portfolio
            manifest = json.loads((preview_dir / "order_batch_manifest.json").read_text(encoding="utf-8"))
            assert manifest["preview_mode"] == "NO_NEW_ORDER"
            assert pd.read_csv(preview_dir / "orders_preview.csv").empty


def test_mark_only_parent_and_selected_child_form_complete_immutable_chain() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-01"
        prepare(root, [date])

        run(ledger_args(root, date, suppress_new_orders=True))
        mark_publication = json.loads(
            (root / "paper" / "accepted_publication.json").read_text(
                encoding="utf-8"
            )
        )
        assert mark_publication["transaction_mode"] == "MARK_ONLY"
        parent_integrity = json.loads(
            (root / "paper" / "snapshot_integrity.json").read_text(
                encoding="utf-8"
            )
        )
        parent_hash = parent_integrity["snapshot_hash"]
        heads = root / "heads"
        shutil.copytree(root / "paper", heads / parent_hash)

        write_target(
            root / "targets" / "main.csv",
            "main",
            "AAA",
            date,
            stock_weight=0.60,
        )
        write_target(
            root / "targets" / "concentrated.csv",
            "concentrated",
            "BBB",
            date,
            stock_weight=0.60,
        )
        run(ledger_args(root, date))
        selected_publication = json.loads(
            (root / "paper" / "accepted_publication.json").read_text(
                encoding="utf-8"
            )
        )
        assert selected_publication["transaction_mode"] == "SELECTED_TARGET"
        child_integrity = json.loads(
            (root / "paper" / "snapshot_integrity.json").read_text(
                encoding="utf-8"
            )
        )
        child_hash = child_integrity["snapshot_hash"]
        assert child_hash != parent_hash
        assert child_integrity["previous_snapshot_hash"] == parent_hash
        shutil.copytree(root / "paper", heads / child_hash)

        selection = select_verified_immutable_paper_head(heads)
        assert selection["chain_snapshot_hashes"] == [
            parent_hash,
            child_hash,
        ]
        assert selection["selected_snapshot_hash"] == child_hash

        shutil.rmtree(heads / parent_hash)
        try:
            select_verified_immutable_paper_head(heads)
        except PaperLedgerIntegrityError as exc:
            assert "immutable paper head parent is missing" in str(exc)
        else:
            raise AssertionError("selected child was accepted without MARK_ONLY parent")


def test_present_but_stale_preview_is_rebuilt_against_durable_account_and_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-02"
        prepare(root, [date])
        run(ledger_args(root, date))
        state_before = directory_hashes(root / "paper")

        stale_path = root / "previews" / "main" / "order_batch_manifest.json"
        stale = json.loads(stale_path.read_text(encoding="utf-8"))
        stale["accepted_account_sha256"] = "0" * 64
        stale_path.write_text(json.dumps(stale), encoding="utf-8")

        repaired = run(ledger_args(root, date))
        assert repaired["result_status"] == "PREVIEW_REBUILT"
        assert directory_hashes(root / "paper") == state_before
        fixed = json.loads(stale_path.read_text(encoding="utf-8"))
        assert fixed["accepted_account_sha256"] == state_before["main/account_state_latest.json"]
        assert fixed["preview_mode"] == "EXECUTABLE_CANDIDATE"


def test_interrupted_preview_only_publish_recovers_before_reuse() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-05"
        prepare(root, [date])
        run(ledger_args(root, date))
        preview_root = root / "previews"
        before = directory_hashes(preview_root)
        backup = root / ".previews.recovery-crash-fixture"
        preview_root.rename(backup)
        preview_root.mkdir()
        (preview_root / "crash_sentinel.txt").write_text("uncommitted", encoding="utf-8")
        journal = root / ".previews.preview-transaction.json"
        journal.write_text(
            json.dumps(
                {
                    "schema_version": "run287-paper-directory-transaction-v1",
                    "status": "PREPARED",
                    "entries": [
                        {
                            "destination": str(preview_root.resolve()),
                            "backup": str(backup.resolve()),
                            "destination_existed": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        reused = run(ledger_args(root, date))
        assert reused["result_status"] == "SAME_SESSION_REUSE"
        assert directory_hashes(preview_root) == before
        assert not journal.exists()
        assert not backup.exists()
        assert not (preview_root / "crash_sentinel.txt").exists()


def test_overlapping_recovery_prefers_newer_state_bundle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-05"
        prepare(root, [date])
        run(ledger_args(root, date))
        preview_root = root / "previews"
        before = directory_hashes(preview_root)
        older_backup = root / ".previews.recovery-older-preview"
        newer_backup = root / ".previews.recovery-newer-state-bundle"
        shutil.copytree(preview_root, older_backup)
        (older_backup / "older_uncommitted.txt").write_text("older", encoding="utf-8")
        shutil.copytree(preview_root, newer_backup)
        shutil.rmtree(preview_root)
        preview_root.mkdir()
        (preview_root / "latest_uncommitted.txt").write_text("candidate", encoding="utf-8")

        entry = lambda backup: {
            "destination": str(preview_root.resolve()),
            "backup": str(backup.resolve()),
            "destination_existed": True,
        }
        (root / ".previews.preview-transaction.json").write_text(
            json.dumps(
                {
                    "schema_version": "run287-paper-directory-transaction-v1",
                    "status": "PREPARED",
                    "entries": [entry(older_backup)],
                }
            ),
            encoding="utf-8",
        )
        (root / ".paper.transaction.json").write_text(
            json.dumps(
                {
                    "schema_version": "run287-paper-directory-transaction-v1",
                    "status": "PREPARED",
                    "entries": [entry(newer_backup)],
                }
            ),
            encoding="utf-8",
        )

        reused = run(ledger_args(root, date))
        assert reused["result_status"] == "SAME_SESSION_REUSE"
        assert directory_hashes(preview_root) == before
        assert not (preview_root / "older_uncommitted.txt").exists()
        assert not (preview_root / "latest_uncommitted.txt").exists()


def test_operating_targets_publish_in_same_atomic_bundle() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = ["2026-04-06", "2026-04-07"]
        prepare(root, dates)
        published_main = root / "published" / "operating_main_target_book.csv"
        published_concentrated = root / "published" / "operating_concentrated_target_book.csv"
        write_target(published_main, "main", "AAA", dates[0], stock_weight=0.40)
        write_target(published_concentrated, "concentrated", "BBB", dates[0], stock_weight=0.40)
        run(ledger_args(root, dates[0]))
        before_state = directory_hashes(root / "paper")
        before_preview = directory_hashes(root / "previews")
        before_main = published_main.read_bytes()
        before_concentrated = published_concentrated.read_bytes()

        write_target(root / "targets" / "main.csv", "main", "AAA", dates[1], stock_weight=0.65)
        write_target(root / "targets" / "concentrated.csv", "concentrated", "BBB", dates[1], stock_weight=0.65)
        try:
            run(ledger_args(root, dates[1], publish_targets=True, failpoint="after_publish_2"))
        except RuntimeError as exc:
            assert "injected transaction interruption" in str(exc)
        else:
            raise AssertionError("target publication failpoint did not interrupt")
        assert directory_hashes(root / "paper") == before_state
        assert directory_hashes(root / "previews") == before_preview
        assert published_main.read_bytes() == before_main
        assert published_concentrated.read_bytes() == before_concentrated

        completed = run(ledger_args(root, dates[1], publish_targets=True))
        assert completed["status"] == "completed"
        assert published_main.read_bytes() == (root / "targets" / "main.csv").read_bytes()
        assert published_concentrated.read_bytes() == (root / "targets" / "concentrated.csv").read_bytes()
        publication = json.loads((root / "paper" / "accepted_publication.json").read_text(encoding="utf-8"))
        assert publication["status"] == "ACCEPTED_ATOMIC_PUBLICATION"
        assert publication["portfolios"]["main"]["published_target_sha256"] == directory_hashes(root / "published")["operating_main_target_book.csv"]


def test_genesis_identity_prefers_sealed_bootstrap_target_identity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-08"
        write_seed(root / "seed" / "main.json", "main", "AAA", date)
        write_seed(
            root / "seed" / "concentrated.json",
            "concentrated",
            "BBB",
            date,
        )
        write_target(root / "targets" / "main.csv", "main", "AAA", date)
        ambiguous_rows: list[dict[str, object]] = []
        for variant in range(9):
            ambiguous_rows.extend(
                [
                    {
                        "rebalance_date": date,
                        "ticker": "BBB",
                        "weight": 0.5,
                        "experiment_variant": variant,
                    },
                    {
                        "rebalance_date": date,
                        "ticker": "CASH",
                        "weight": 0.5,
                        "experiment_variant": variant,
                    },
                ]
            )
        pd.DataFrame(ambiguous_rows).to_csv(
            root / "targets" / "concentrated.csv",
            index=False,
        )
        identity = ensure_genesis_identity(
            state_root=root / "paper",
            bootstrap_paths={
                "main": root / "seed" / "main.json",
                "concentrated": root / "seed" / "concentrated.json",
            },
            target_paths={
                "main": root / "targets" / "main.csv",
                "concentrated": root / "targets" / "concentrated.csv",
            },
            cost_bps=25.0,
            max_fill_lag_days=7,
        )
        assert identity["portfolios"]["main"]["target_hash"] == "a" * 64
        assert (
            identity["portfolios"]["concentrated"]["target_hash"]
            == "b" * 64
        )
        assert (
            identity["portfolios"]["main"]["target_sha256"]
            == "c" * 64
        )
        assert (
            identity["portfolios"]["concentrated"]["target_sha256"]
            == "d" * 64
        )


def test_legacy_v1_zero_event_snapshot_is_recomputed_into_v2_head() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = ["2026-04-08", "2026-04-09"]
        date = dates[-1]
        prepare(root, dates)
        run(ledger_args(root, dates[0], suppress_new_orders=True))
        run(ledger_args(root, date, suppress_new_orders=True))
        downgrade_to_legacy_v1_zero_event(root, date)

        corrupt = root / "corrupt_v1"
        shutil.copytree(root / "paper", corrupt)
        corrupt_account_path = corrupt / "main" / "account_state_latest.json"
        corrupt_account = json.loads(
            corrupt_account_path.read_text(encoding="utf-8")
        )
        corrupt_account["cash_usd"] = float(corrupt_account["cash_usd"]) + 1.0
        corrupt_account_path.write_text(
            json.dumps(corrupt_account, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        corrupt_before = directory_hashes(corrupt)
        try:
            prepare_migration(
                state_dir=corrupt,
                requested_as_of_date=date,
                expected_source_tree_sha256=canonical_hash(
                    directory_hashes(corrupt)
                ),
            )
        except PaperLedgerIntegrityError as exc:
            assert "economic state" in str(exc) or "account_arithmetic" in str(exc)
        else:
            raise AssertionError("economically divergent legacy v1 state was accepted")
        assert directory_hashes(corrupt) == corrupt_before

        approved_tree_sha256 = canonical_hash(
            directory_hashes(root / "paper")
        )
        provenance = prepare_migration(
            state_dir=root / "paper",
            requested_as_of_date=date,
            expected_source_tree_sha256=approved_tree_sha256,
            source_artifact_run_id="1",
            source_artifact_id="2",
            source_artifact_digest=f"sha256:{'e' * 64}",
        )
        assert (
            provenance["legacy_schema_profile"]
            == LEGACY_SCHEMA_PROFILE_V1_ZERO_EVENT
        )
        assert provenance["accepted_for_use"] is False
        provenance_path = root / "legacy_v1_migration_provenance.json"
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        legacy_hash = provenance["remote_tree_sha256"]
        args = ledger_args(root, date, suppress_new_orders=True)
        args.legacy_migration_provenance = str(provenance_path)
        args.legacy_migration_expected_source_tree_sha256 = (
            approved_tree_sha256
        )
        migrated = run(args)
        assert migrated["result_status"] == "LEGACY_SCHEMA_UPGRADE"
        assert (
            migrated["legacy_snapshot_semantic_attestation_mode"]
            == "SAME_SESSION_SCHEMA_UPGRADE"
        )
        assert (
            migrated["legacy_schema_profile"]
            == LEGACY_SCHEMA_PROFILE_V1_ZERO_EVENT
        )
        assert migrated["new_order_generation_suppressed"] is True
        verified = verify_integrity_manifest(root / "paper", require=True)
        assert verified["status"] == "VERIFIED"
        attestation = json.loads(
            (root / "paper" / "legacy_migration_attestation.json").read_text(
                encoding="utf-8"
            )
        )
        assert attestation["remote_tree_sha256"] == legacy_hash
        assert (
            attestation["legacy_schema_profile"]
            == LEGACY_SCHEMA_PROFILE_V1_ZERO_EVENT
        )
        for portfolio in ("main", "concentrated"):
            manifest = json.loads(
                (root / "paper" / portfolio / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            meta = json.loads(
                (root / "paper" / portfolio / "state_meta.json").read_text(
                    encoding="utf-8"
                )
            )
            account = json.loads(
                (
                    root / "paper" / portfolio / "account_state_latest.json"
                ).read_text(encoding="utf-8")
            )
            assert (
                manifest["schema_version"]
                == "daily-simulated-fill-ledger-manifest-v2"
            )
            assert (
                meta["schema_version"]
                == "daily-simulated-fill-ledger-state-v2"
            )
            assert account["reserve_reason_source_hash"]
            assert account["position_count_total"] == len(account["positions"])
            assert manifest["new_order_generation_suppressed"] is True
            assert (
                manifest["legacy_same_session_price_revision_audit"][
                    "accepted_mark_preserved"
                ]
                is True
            )


def test_legacy_v1_pin_schema_price_and_provenance_fail_closed() -> None:
    date = "2026-04-09"
    dates = ["2026-04-08", date]
    artifact = {
        "source_artifact_run_id": "1",
        "source_artifact_id": "2",
        "source_artifact_digest": f"sha256:{'e' * 64}",
    }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prepare(root, dates)
        run(ledger_args(root, dates[0], suppress_new_orders=True))
        run(ledger_args(root, date, suppress_new_orders=True))
        downgrade_to_legacy_v1_zero_event(root, date)
        before = directory_hashes(root / "paper")
        try:
            prepare_migration(
                state_dir=root / "paper",
                requested_as_of_date=date,
                expected_source_tree_sha256="f" * 64,
                **artifact,
            )
        except ValueError as exc:
            assert "operator-pinned cross-source tree" in str(exc)
        else:
            raise AssertionError("wrong operator tree pin was accepted")
        assert directory_hashes(root / "paper") == before

        account_path = root / "paper" / "main" / "account_state_latest.json"
        account = json.loads(account_path.read_text(encoding="utf-8"))
        account["forward_promotion_eligible"] = True
        account_path.write_text(
            json.dumps(account, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        smuggled = directory_hashes(root / "paper")
        try:
            prepare_migration(
                state_dir=root / "paper",
                requested_as_of_date=date,
                expected_source_tree_sha256=canonical_hash(smuggled),
                **artifact,
            )
        except PaperLedgerIntegrityError as exc:
            assert "schema_keys_mismatch" in str(exc)
        else:
            raise AssertionError("legacy v1 schema smuggling was accepted")
        assert directory_hashes(root / "paper") == smuggled

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prepare(root, dates)
        run(ledger_args(root, dates[0], suppress_new_orders=True))
        run(ledger_args(root, date, suppress_new_orders=True))
        downgrade_to_legacy_v1_zero_event(root, date)
        account_path = root / "paper" / "main" / "account_state_latest.json"
        positions_path = root / "paper" / "main" / "positions_latest.csv"
        curve_path = root / "paper" / "main" / "equity_curve.csv"
        account = json.loads(account_path.read_text(encoding="utf-8"))
        forged_price = float(account["positions"][0]["price"]) * 1.10
        forged_value = float(account["positions"][0]["shares"]) * forged_price
        forged_equity = float(account["cash_usd"]) + forged_value
        account["positions"][0].update(
            price=forged_price,
            market_value_usd=forged_value,
            unrealized_pnl_usd=(
                forged_value
                - float(account["positions"][0]["shares"])
                * float(account["positions"][0]["cost_basis"])
            ),
            weight=forged_value / forged_equity,
        )
        account.update(
            stock_value_usd=forged_value,
            equity_usd=forged_equity,
            cash_weight=float(account["cash_usd"]) / forged_equity,
        )
        account_path.write_text(
            json.dumps(account, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        positions = pd.read_csv(positions_path)
        positions.loc[0, "price"] = forged_price
        positions.loc[0, "market_value_usd"] = forged_value
        positions.loc[0, "unrealized_pnl_usd"] = (
            forged_value
            - float(positions.loc[0, "shares"])
            * float(positions.loc[0, "cost_basis"])
        )
        positions.loc[0, "weight"] = forged_value / forged_equity
        positions.to_csv(positions_path, index=False)
        curve = pd.read_csv(curve_path)
        curve.loc[curve.index[-1], "equity_usd"] = forged_equity
        curve.loc[curve.index[-1], "stock_value_usd"] = forged_value
        curve.loc[curve.index[-1], "cash_weight"] = (
            float(account["cash_usd"]) / forged_equity
        )
        curve.to_csv(curve_path, index=False)

        approved_tree_sha256 = canonical_hash(
            directory_hashes(root / "paper")
        )
        provenance = prepare_migration(
            state_dir=root / "paper",
            requested_as_of_date=date,
            expected_source_tree_sha256=approved_tree_sha256,
            **artifact,
        )
        provenance_path = root / "forged_price_provenance.json"
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args = ledger_args(root, date, suppress_new_orders=True)
        args.legacy_migration_provenance = str(provenance_path)
        args.legacy_migration_expected_source_tree_sha256 = (
            approved_tree_sha256
        )
        before = directory_hashes(root / "paper")
        try:
            run(args)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_PRICE_REVISION"
            assert "differs materially" in str(exc)
        else:
            raise AssertionError("material legacy accepted-close forgery was accepted")
        assert directory_hashes(root / "paper") == before

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prepare(root, [dates[0]])
        run(ledger_args(root, dates[0], suppress_new_orders=True))
        (root / "paper" / "snapshot_integrity.json").unlink()
        (root / "paper" / "accepted_publication.json").unlink()
        args = pinned_legacy_args(root, dates[0])
        provenance_path = Path(args.legacy_migration_provenance)
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["forward_promotion_eligible"] = True
        provenance_path.write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        before = directory_hashes(root / "paper")
        try:
            run(args)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_INTEGRITY"
            assert "schema" in str(exc)
        else:
            raise AssertionError("unknown migration provenance key was accepted")
        assert directory_hashes(root / "paper") == before


def test_legacy_same_session_snapshot_is_semantically_attested_once() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-08"
        prepare(root, [date])
        run(ledger_args(root, date))
        (root / "paper" / "snapshot_integrity.json").unlink()
        (root / "paper" / "accepted_publication.json").unlink()
        provenance_path = root / "legacy_migration_provenance.json"
        approved_tree_sha256 = canonical_hash(
            directory_hashes(root / "paper")
        )
        provenance_path.write_text(
            json.dumps(
                {
                    "schema_version": "run287-legacy-drive-paper-migration-v1",
                    "status": "PENDING_SEMANTIC_ATTESTATION",
                    "source": "GITHUB_ACTIONS_ARTIFACT_TREE_SHA256_PIN",
                    "source_artifact_run_id": "1",
                    "source_artifact_id": "2",
                    "source_artifact_digest": f"sha256:{'e' * 64}",
                    "legacy_as_of_date": date,
                    "requested_as_of_date": date,
                    "remote_snapshot_integrity_present": False,
                    "verified_cross_source_anchor_present": True,
                    "legacy_semantic_attestation_required": True,
                    "legacy_schema_profile": LEGACY_SCHEMA_PROFILE_CURRENT_V2,
                    "accepted_for_use": False,
                    "review_only": True,
                    "live_trading_enabled": False,
                    "production_mutation_allowed": False,
                    "remote_tree_file_count": len(
                        directory_hashes(root / "paper")
                    ),
                    "expected_source_tree_sha256": approved_tree_sha256,
                    "remote_tree_sha256": approved_tree_sha256,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        args = ledger_args(root, date, suppress_new_orders=True)
        args.legacy_migration_provenance = str(provenance_path)
        args.legacy_migration_expected_source_tree_sha256 = (
            approved_tree_sha256
        )

        attested = run(args)
        assert attested["result_status"] == "LEGACY_ATTESTED"
        assert attested["new_order_generation_suppressed"] is True
        assert all(
            row["enqueued_this_run"] == 0
            and row["resolved_fills_this_run"] == 0
            and row["resolved_rejections_this_run"] == 0
            and row["new_order_generation_suppressed"] is True
            for row in attested["portfolios"].values()
        )
        verified = verify_integrity_manifest(root / "paper", require=True)
        assert verified["status"] == "VERIFIED"
        attestation = json.loads(
            (
                root / "paper" / "legacy_migration_attestation.json"
            ).read_text(encoding="utf-8")
        )
        assert attestation["status"] == "SEMANTIC_ATTESTATION_VERIFIED"
        assert (
            attestation["source"]
            == "GITHUB_ACTIONS_ARTIFACT_TREE_SHA256_PIN"
        )
        assert attestation["accepted_for_use"] is True
        assert (
            verified["files"]["legacy_migration_attestation.json"]
            == directory_hashes(root / "paper")[
                "legacy_migration_attestation.json"
            ]
        )
        after = directory_hashes(root / "paper")

        reused = run(ledger_args(root, date, suppress_new_orders=True))
        assert reused["result_status"] == "NO_NEW_ORDER_PREVIEW"
        assert directory_hashes(root / "paper") == after
        migration_anchor = root / "migration_anchor"
        shutil.copytree(root / "paper", migration_anchor)
        anchor_manifest = verify_integrity_manifest(
            migration_anchor, require=True
        )

        selected = run(ledger_args(root, date))
        final_attestation_sha = directory_hashes(root / "paper")[
            "legacy_migration_attestation.json"
        ]
        assert (
            selected["legacy_migration_attestation_sha256"]
            == final_attestation_sha
        )
        assert (
            verify_integrity_manifest(root / "paper", require=True)["files"][
                "legacy_migration_attestation.json"
            ]
            == final_attestation_sha
        )
        assert require_state_descends_from(
            root / "paper", migration_anchor
        )["continuity_status"] == "CANDIDATE_DESCENDS_FROM_ANCHOR"
        forged = root / "forged_migration_descendant"
        shutil.copytree(root / "paper", forged)
        forged_attestation_path = (
            forged / "legacy_migration_attestation.json"
        )
        forged_attestation = json.loads(
            forged_attestation_path.read_text(encoding="utf-8")
        )
        forged_attestation["semantic_attestation_result"] = "FORGED"
        forged_attestation_path.write_text(
            json.dumps(forged_attestation, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (forged / "snapshot_integrity.json").unlink()
        write_integrity_manifest(
            forged,
            as_of_date=date,
            previous_snapshot_hash=anchor_manifest["snapshot_hash"],
        )
        try:
            require_state_descends_from(forged, migration_anchor)
        except PaperLedgerIntegrityError as exc:
            assert "durable legacy migration attestation" in str(exc)
        else:
            raise AssertionError("migration attestation mutation was accepted")


def test_legacy_prior_session_snapshot_is_semantically_attested_by_forward_replay() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = ["2026-04-08", "2026-04-09", "2026-04-10"]
        prepare(root, dates)
        run(ledger_args(root, dates[0]))
        write_target(
            root / "targets" / "main.csv",
            "main",
            "AAA",
            dates[1],
            stock_weight=0.75,
        )
        write_target(
            root / "targets" / "concentrated.csv",
            "concentrated",
            "BBB",
            dates[1],
            stock_weight=0.75,
        )
        seeded = run(ledger_args(root, dates[1]))
        assert sum(
            row["enqueued_this_run"]
            for row in seeded["portfolios"].values()
        ) > 0
        (root / "paper" / "snapshot_integrity.json").unlink()
        (root / "paper" / "accepted_publication.json").unlink()

        approved_tree_sha256 = canonical_hash(
            directory_hashes(root / "paper")
        )
        provenance_path = root / "forward_legacy_migration_provenance.json"
        provenance_path.write_text(
            json.dumps(
                {
                    "schema_version": "run287-legacy-drive-paper-migration-v1",
                    "status": "PENDING_SEMANTIC_ATTESTATION",
                    "source": "GITHUB_ACTIONS_ARTIFACT_TREE_SHA256_PIN",
                    "source_artifact_run_id": "1",
                    "source_artifact_id": "2",
                    "source_artifact_digest": f"sha256:{'e' * 64}",
                    "legacy_as_of_date": dates[1],
                    "requested_as_of_date": dates[2],
                    "remote_snapshot_integrity_present": False,
                    "verified_cross_source_anchor_present": True,
                    "legacy_semantic_attestation_required": True,
                    "legacy_schema_profile": LEGACY_SCHEMA_PROFILE_CURRENT_V2,
                    "accepted_for_use": False,
                    "review_only": True,
                    "live_trading_enabled": False,
                    "production_mutation_allowed": False,
                    "remote_tree_file_count": len(
                        directory_hashes(root / "paper")
                    ),
                    "expected_source_tree_sha256": approved_tree_sha256,
                    "remote_tree_sha256": approved_tree_sha256,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        args = ledger_args(root, dates[2], suppress_new_orders=True)
        args.legacy_migration_provenance = str(provenance_path)
        args.legacy_migration_expected_source_tree_sha256 = (
            approved_tree_sha256
        )
        attested = run(args)
        assert attested["result_status"] == "RESTORED_CONTINUATION"
        assert attested["legacy_snapshot_semantically_validated"] is True
        assert attested["legacy_snapshot_semantic_attestation_mode"] == "FORWARD_REPLAY"
        assert attested["new_order_generation_suppressed"] is True
        assert sum(
            row["resolved_fills_this_run"]
            for row in attested["portfolios"].values()
        ) > 0
        assert (
            root / "paper" / "legacy_migration_attestation.json"
        ).is_file()
        assert verify_integrity_manifest(root / "paper", require=True)["status"] == "VERIFIED"


def test_legacy_migration_blocks_orders_partial_state_and_unsafe_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = ["2026-04-08", "2026-04-09"]
        prepare(root, dates)
        run(ledger_args(root, dates[0]))
        (root / "paper" / "snapshot_integrity.json").unlink()
        (root / "paper" / "accepted_publication.json").unlink()
        before = directory_hashes(root / "paper")

        try:
            run(ledger_args(root, dates[1]))
        except PaperLedgerIntegrityError as exc:
            assert "requires a mark-only transaction" in str(exc)
        else:
            raise AssertionError("legacy migration generated orders")
        assert directory_hashes(root / "paper") == before

        shutil.rmtree(root / "paper" / "concentrated")
        partial = directory_hashes(root / "paper")
        try:
            run(ledger_args(root, dates[1], suppress_new_orders=True))
        except PaperLedgerIntegrityError as exc:
            assert "partial paper ledger account state" in str(exc)
        else:
            raise AssertionError("partial legacy ledger was reseeded")
        assert directory_hashes(root / "paper") == partial

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dates = ["2026-04-08", "2026-04-09"]
        prepare(root, dates)
        run(ledger_args(root, dates[0]))
        (root / "paper" / "snapshot_integrity.json").unlink()
        (root / "paper" / "accepted_publication.json").unlink()
        summary_path = root / "paper" / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for portfolio in ("main", "concentrated"):
            manifest_path = root / "paper" / portfolio / "manifest.json"
            meta_path = root / "paper" / portfolio / "state_meta.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            manifest["production_mutation_allowed"] = True
            meta["production_mutation_allowed"] = True
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            meta_path.write_text(
                json.dumps(meta, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            summary["portfolios"][portfolio] = manifest
        summary_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        unsafe = directory_hashes(root / "paper")
        try:
            run(pinned_legacy_args(root, dates[1]))
        except PaperLedgerIntegrityError as exc:
            assert "production_mutation" in str(exc)
        else:
            raise AssertionError("unsafe legacy metadata was rewritten as safe")
        assert directory_hashes(root / "paper") == unsafe

    for unsafe_field in (
        "manifest_historical_replacement",
        "account_human_approval",
        "accepted_publication_without_integrity",
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = ["2026-04-08", "2026-04-09"]
            prepare(root, dates)
            run(ledger_args(root, dates[0]))
            (root / "paper" / "snapshot_integrity.json").unlink()
            if unsafe_field != "accepted_publication_without_integrity":
                (
                    root / "paper" / "accepted_publication.json"
                ).unlink()
            summary_path = root / "paper" / "summary.json"
            summary = json.loads(
                summary_path.read_text(encoding="utf-8")
            )
            if unsafe_field == "manifest_historical_replacement":
                for portfolio in ("main", "concentrated"):
                    manifest_path = (
                        root / "paper" / portfolio / "manifest.json"
                    )
                    manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    manifest[
                        "historical_cagr_mdd_replacement_allowed"
                    ] = True
                    manifest_path.write_text(
                        json.dumps(
                            manifest, indent=2, sort_keys=True
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    summary["portfolios"][portfolio] = manifest
                summary_path.write_text(
                    json.dumps(summary, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            elif unsafe_field == "account_human_approval":
                for portfolio in ("main", "concentrated"):
                    account_path = (
                        root
                        / "paper"
                        / portfolio
                        / "account_state_latest.json"
                    )
                    account = json.loads(
                        account_path.read_text(encoding="utf-8")
                    )
                    account[
                        "human_approval_required_for_live_orders"
                    ] = False
                    account_path.write_text(
                        json.dumps(
                            account, indent=2, sort_keys=True
                        )
                        + "\n",
                        encoding="utf-8",
                    )
            before_unsafe = directory_hashes(root / "paper")
            try:
                run(pinned_legacy_args(root, dates[1]))
            except PaperLedgerIntegrityError:
                pass
            else:
                raise AssertionError(
                    f"unsafe legacy field was rewritten:{unsafe_field}"
                )
            assert directory_hashes(root / "paper") == before_unsafe


def test_verified_matching_immutable_head_recovers_after_cache_loss() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-08"
        prepare(root, [date])
        run(ledger_args(root, date))
        canonical = root / "canonical"
        immutable_head = root / "immutable_head"
        recovered = root / "recovered"
        shutil.copytree(root / "paper", canonical)
        shutil.copytree(root / "paper", immutable_head)
        canonical_manifest = verify_integrity_manifest(canonical, require=True)
        head_manifest = verify_integrity_manifest(immutable_head, require=True)
        assert head_manifest["snapshot_hash"] == canonical_manifest["snapshot_hash"]

        installed = install_verified_snapshot(immutable_head, recovered)
        assert installed["install_status"] == "INSTALLED_VERIFIED_SNAPSHOT"
        continuity = require_state_descends_from(recovered, canonical)
        assert continuity["continuity_status"] == "SAME_SNAPSHOT"


def test_replay_price_evidence_revalidates_parquet_and_is_transactional() -> None:
    session_date = "2026-04-08"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prepare(root, [session_date])
        accepted = run(replay_ledger_args(root, session_date))
        assert accepted["replay_only"] is True
        assert accepted["forward_promotion_eligible"] is False
        assert accepted["new_order_generation_suppressed"] is True
        durable_relative = (
            accepted["price_evidence"]["durable_snapshot_path"]
        )
        assert durable_relative == (
            f"replay_price_evidence/{session_date}"
        )
        durable_root = root / "paper" / durable_relative
        assert durable_root.is_dir()
        assert directory_hashes(durable_root) == directory_hashes(
            root / "prices"
        )
        integrity = verify_integrity_manifest(root / "paper", require=True)
        assert any(
            relative.startswith(durable_relative + "/")
            for relative in integrity["files"]
        )
        durable_target_relative = (
            accepted["target_source_evidence"][
                "durable_snapshot_path"
            ]
        )
        assert durable_target_relative == (
            f"replay_target_source/{session_date}"
        )
        durable_target_root = root / "paper" / durable_target_relative
        assert directory_hashes(durable_target_root) == {
            "concentrated.csv": file_hash(
                root / "targets" / "concentrated.csv"
            ),
            "main.csv": file_hash(root / "targets" / "main.csv"),
        }
        assert accepted["target_source_evidence"]["targets"] == {
            portfolio: {
                "path": (
                    f"{durable_target_relative}/{portfolio}.csv"
                ),
                "sha256": file_hash(
                    root / "targets" / f"{portfolio}.csv"
                ),
                "bytes": (
                    root / "targets" / f"{portfolio}.csv"
                ).stat().st_size,
            }
            for portfolio in ("main", "concentrated")
        }
        assert any(
            relative.startswith(durable_target_relative + "/")
            for relative in integrity["files"]
        )

        pre_field = root / "pre_field_replay_head"
        shutil.copytree(root / "paper", pre_field)
        shutil.rmtree(pre_field / "replay_target_source")
        pre_field_summary_path = pre_field / "summary.json"
        pre_field_summary = json.loads(
            pre_field_summary_path.read_text(encoding="utf-8")
        )
        pre_field_summary.pop("target_source_evidence")
        pre_field_summary_path.write_text(
            json.dumps(pre_field_summary, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        pre_field_integrity = json.loads(
            (pre_field / "snapshot_integrity.json").read_text(
                encoding="utf-8"
            )
        )
        (pre_field / "snapshot_integrity.json").unlink()
        write_integrity_manifest(
            pre_field,
            as_of_date=session_date,
            previous_snapshot_hash=str(
                pre_field_integrity.get("previous_snapshot_hash") or ""
            ),
        )
        verified_pre_field = reconcile_immutable_paper_head_cache(
            root / "pre_field_heads",
            add_head_sources=(pre_field,),
        )
        assert verified_pre_field["cache_status"] == (
            "RECONCILED_IMMUTABLE_PAPER_HEAD_CACHE"
        )

        missing_target_files = root / "missing_replay_target_files"
        shutil.copytree(root / "paper", missing_target_files)
        shutil.rmtree(
            missing_target_files / "replay_target_source"
        )
        missing_summary_path = missing_target_files / "summary.json"
        missing_summary = json.loads(
            missing_summary_path.read_text(encoding="utf-8")
        )
        missing_summary["target_source_evidence"]["targets"] = None
        missing_summary_path.write_text(
            json.dumps(missing_summary, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        (missing_target_files / "snapshot_integrity.json").unlink()
        write_integrity_manifest(
            missing_target_files,
            as_of_date=session_date,
            previous_snapshot_hash="",
        )
        try:
            reconcile_immutable_paper_head_cache(
                root / "missing_target_heads",
                add_head_sources=(missing_target_files,),
            )
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_INTEGRITY"
            assert "target source evidence" in str(exc)
        else:
            raise AssertionError(
                "null replay target evidence passed verification"
            )

        mismatched_target_source = (
            root / "mismatched_replay_target_source"
        )
        shutil.copytree(root / "paper", mismatched_target_source)
        mismatched_main = (
            mismatched_target_source
            / durable_target_relative
            / "main.csv"
        )
        mismatched_main.write_bytes(
            mismatched_main.read_bytes() + b"\n"
        )
        mismatched_summary_path = (
            mismatched_target_source / "summary.json"
        )
        mismatched_summary = json.loads(
            mismatched_summary_path.read_text(encoding="utf-8")
        )
        mismatched_record = mismatched_summary[
            "target_source_evidence"
        ]["targets"]["main"]
        mismatched_record["sha256"] = file_hash(mismatched_main)
        mismatched_record["bytes"] = mismatched_main.stat().st_size
        mismatched_summary_path.write_text(
            json.dumps(
                mismatched_summary, indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        (mismatched_target_source / "snapshot_integrity.json").unlink()
        write_integrity_manifest(
            mismatched_target_source,
            as_of_date=session_date,
            previous_snapshot_hash="",
        )
        try:
            reconcile_immutable_paper_head_cache(
                root / "mismatched_target_heads",
                add_head_sources=(mismatched_target_source,),
            )
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_INTEGRITY"
            assert "target source evidence" in str(exc)
        else:
            raise AssertionError(
                "replay target evidence was not bound to source hash"
            )

        retry_sources = root / "retry_sources"
        retry_sources.mkdir()
        for portfolio in ("main", "concentrated"):
            shutil.copy2(
                durable_target_root / f"{portfolio}.csv",
                retry_sources / f"{portfolio}.csv",
            )
        retry_args = replay_ledger_args(root, session_date)
        retry_args.main_target = str(retry_sources / "main.csv")
        retry_args.concentrated_target = str(
            retry_sources / "concentrated.csv"
        )
        retried = run(retry_args)
        assert retried["result_status"] in {
            "NO_NEW_ORDER_PREVIEW",
            "SAME_SESSION_REUSE",
        }
        assert retried["same_session_reused_portfolio_count"] == 2
        for portfolio in ("main", "concentrated"):
            assert (
                retried["portfolios"][portfolio][
                    "source_target_sha256"
                ]
                == accepted["portfolios"][portfolio][
                    "source_target_sha256"
                ]
            )
        after_retry = directory_hashes(root / "paper")
        assert after_retry

        with (retry_sources / "main.csv").open(
            "a", encoding="utf-8"
        ) as handle:
            handle.write("\n")
        conflicting_args = replay_ledger_args(root, session_date)
        conflicting_args.main_target = str(
            retry_sources / "main.csv"
        )
        conflicting_args.concentrated_target = str(
            retry_sources / "concentrated.csv"
        )
        try:
            run(conflicting_args)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_TARGET_EVIDENCE"
            assert "conflicts with the accepted session" in str(exc)
        else:
            raise AssertionError(
                "same-session replay replaced its durable target source"
            )
        assert directory_hashes(root / "paper") == after_retry

        anchor = root / "replay_anchor"
        forged = root / "replay_forged_descendant"
        forged_target = root / "replay_forged_target_descendant"
        shutil.copytree(root / "paper", anchor)
        write_prices(
            root / "prices",
            "AAA",
            ["2026-04-09"],
            [101.0],
        )
        write_prices(
            root / "prices",
            "BBB",
            ["2026-04-09"],
            [102.0],
        )
        run(replay_ledger_args(root, "2026-04-09"))
        shutil.copytree(root / "paper", forged)
        shutil.copytree(root / "paper", forged_target)
        prior_bar = (
            forged
            / "replay_price_evidence"
            / session_date
            / px_cache_name("AAA")
        )
        prior_bar.write_bytes(prior_bar.read_bytes() + b"tamper")
        (forged / "snapshot_integrity.json").unlink()
        write_integrity_manifest(
            forged,
            as_of_date="2026-04-09",
            previous_snapshot_hash=integrity["snapshot_hash"],
        )
        try:
            require_state_descends_from(forged, anchor)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_CONTINUITY"
            assert "replay price evidence changed" in str(exc)
        else:
            raise AssertionError(
                "descendant rewrote a prior replay price evidence bar"
            )
        prior_target = (
            forged_target
            / "replay_target_source"
            / session_date
            / "main.csv"
        )
        prior_target.write_bytes(prior_target.read_bytes() + b"\n")
        (forged_target / "snapshot_integrity.json").unlink()
        write_integrity_manifest(
            forged_target,
            as_of_date="2026-04-09",
            previous_snapshot_hash=integrity["snapshot_hash"],
        )
        try:
            require_state_descends_from(forged_target, anchor)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_CONTINUITY"
            assert "replay target source changed" in str(exc)
        else:
            raise AssertionError(
                "descendant rewrote a prior replay target source"
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prepare(root, [session_date])
        args = replay_ledger_args(root, session_date)
        aaa = root / "prices" / px_cache_name("AAA")
        aaa.write_bytes(aaa.read_bytes() + b"tamper")
        before = directory_hashes(root / "paper")
        try:
            run(args)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_PRICE_EVIDENCE"
            assert "file mismatch" in str(exc)
        else:
            raise AssertionError("hash-tampered replay price evidence was accepted")
        assert directory_hashes(root / "paper") == before

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prepare(root, [session_date])
        manifest_path = write_replay_price_manifest(
            root,
            session_date,
        )
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        manifest["artifact"]["head_branch"] = "untrusted-feature"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args = ledger_args(
            root,
            session_date,
            suppress_new_orders=True,
        )
        args.replay_only = True
        args.price_evidence_manifest = str(manifest_path)
        before = directory_hashes(root / "paper")
        try:
            run(args)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_PRICE_EVIDENCE"
            assert "not from the default branch" in str(exc)
        else:
            raise AssertionError(
                "self-asserted untrusted artifact provenance was accepted"
            )
        assert directory_hashes(root / "paper") == before

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        future_date = "2026-04-09"
        prepare(root, [session_date])
        manifest_path = write_replay_price_manifest(root, session_date)
        write_prices(
            root / "prices",
            "AAA",
            [session_date, future_date],
            [100.0, 101.0],
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        aaa_path = root / "prices" / px_cache_name("AAA")
        aaa_row = next(
            row
            for row in manifest["price_files"]
            if row["ticker"] == "AAA"
        )
        aaa_row["bytes"] = aaa_path.stat().st_size
        aaa_row["sha256"] = file_hash(aaa_path)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args = ledger_args(root, session_date, suppress_new_orders=True)
        args.replay_only = True
        args.price_evidence_manifest = str(manifest_path)
        before = directory_hashes(root / "paper")
        try:
            run(args)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_PRICE_EVIDENCE"
            assert "parquet contract" in str(exc)
        else:
            raise AssertionError(
                "self-consistent future-row replay price evidence was accepted"
            )
        assert directory_hashes(root / "paper") == before


def test_workflow_separates_failed_evidence_from_accepted_paper_state() -> None:
    import yaml

    workflow_path = ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["refresh"]["steps"]
    by_name = {str(step.get("name")): step for step in steps}
    step_names = [str(step.get("name")) for step in steps]
    freshness = by_name["Validate freshness contract"]
    assert "--strict-selection" in freshness["run"]
    assert "--minimum-core-candidate-coverage 0.98" not in freshness["run"]
    assert (
        'core_coverage.get("required_for_target_mutation") is not False'
        in freshness["run"]
    )
    assert (
        step_names.index("Validate freshness contract")
        < step_names.index("Run transactional paper ledger and same-close selector")
    ), "blocked freshness must stop before the first paper-ledger mutation"
    transaction = by_name["Run transactional paper ledger and same-close selector"]
    assert transaction["id"] == "paper_transaction"
    script = transaction["run"]
    assert "--freshness-status outputs/data_freshness_contract/status.json" in script
    assert (
        "--freshness-snapshot-manifest "
        "outputs/data_freshness_contract/data_snapshot_manifest.json"
        in script
    )
    assert "--upstream-status \"$UPSTREAM_STATUS\"" in script
    assert "UPSTREAM_READY=no" in script
    assert "REGISTRY_READY=no" in script
    assert "PRODUCER_READY=no" in script
    assert "clear_previous_materialization(Path(sys.argv[1]))" in script
    assert 'if [ "$UPSTREAM_READY" = "yes" ]; then' in script
    assert 'if [ "$REGISTRY_READY" = "yes" ]; then' in script
    assert 'if [ "$PRODUCER_READY" = "yes" ]; then' in script
    assert "--previous-status \"$PREVIOUS_PRODUCER_STATUS\"" in script
    assert "current.replace(previous)" in script
    assert "Path(sys.argv[1]).unlink(missing_ok=True)" in script
    assert "current_upstream_not_ready" in script
    assert "current_registry_not_ready" in script
    assert "current_producer_not_ready" in script
    registry_call = script[
        script.index("python tools/build_run287_exact_packet_input_registry.py"):
        script.index('if [ "$REGISTRY_READY" = "yes" ]; then')
    ]
    producer_call = script[
        script.index("python tools/run_run287_exact_packet_producer.py"):
        script.index('if [ "$REGISTRY_READY" != "yes" ]; then')
    ]
    assert "--allow-missing" not in registry_call
    assert "--allow-missing" not in producer_call
    assert (
        script.index("clear_previous_materialization(Path(sys.argv[1]))")
        < script.index("python tools/run_run287_exact_packet_upstream.py")
        < script.index("python tools/build_run287_exact_packet_input_registry.py")
        < script.index("python tools/run_run287_exact_packet_producer.py")
        < script.index("python tools/build_run287_same_close_target_books.py")
    )
    assert 'cp "$SAME_CLOSE_DIR/same_close_main_target_book.csv"' not in script
    assert "--main-publish-target outputs/reports/operating_main_target_book.csv" in script
    assert "--concentrated-publish-target outputs/reports/operating_concentrated_target_book.csv" in script
    assert '--target-handoff-manifest "$SAME_CLOSE_DIR/status.json"' in script
    assert '--expected-target-handoff-sha256 "$TARGET_HANDOFF_SHA"' in script
    assert '--main-target-sha256 "$MAIN_TARGET_SHA"' in script
    assert (
        '--concentrated-target-sha256 "$CONCENTRATED_TARGET_SHA"'
        in script
    )
    assert (
        script.index("read -r TARGET_HANDOFF_SHA")
        < script.index(
            "python tools/run_daily_simulated_fill_ledger.py",
            script.index("read -r TARGET_HANDOFF_SHA"),
        )
    )
    mark_only_preserve = script.index(
        'PAPER_MARK_ONLY_TRANSACTION_HEAD="$RUNNER_TEMP/'
        'run287_daily_simulated_fill_ledger_mark_only_head"'
    )
    first_transaction = script.index(
        "python tools/run_daily_simulated_fill_ledger.py"
    )
    second_transaction = script.index(
        "python tools/run_daily_simulated_fill_ledger.py",
        mark_only_preserve,
    )
    assert first_transaction < mark_only_preserve < second_transaction
    pre_transaction = script.index(
        'PAPER_PRE_TRANSACTION_HEAD="$RUNNER_TEMP/'
        'run287_daily_simulated_fill_ledger_pre_transaction"'
    )
    assert pre_transaction < first_transaction
    assert 'mode = publication.get("transaction_mode")' in script
    assert 'mode == "MARK_ONLY"' in script
    assert 'mode == "SELECTED_TARGET"' in script
    assert 'disposition = "PRESERVE_MARK_ONLY"' in script
    assert 'disposition = "REUSE_SELECTED_TARGET"' in script
    assert 'set(portfolios) != {"main", "concentrated"}' in script
    assert (
        'PAPER_FIRST_TRANSACTION_FIELDS < <(python - "$PAPER_AS_OF"'
        in script
    )
    assert (
        'summary.get("new_order_generation_suppressed") is True'
        in script
    )
    assert 'row.get("enqueued_this_run") == 0' in script
    assert (
        'summary.get("as_of_date") == sys.argv[1]'
        in script
    )
    assert 'publication.get("as_of_date") == sys.argv[1]' in script
    assert (
        '"$PAPER_FIRST_TRANSACTION_HASH" != '
        '"$PAPER_PRE_TRANSACTION_HASH"'
        in script
    )
    assert (
        'PAPER_MARK_ONLY_TRANSACTION_HEAD=$PAPER_MARK_ONLY_TRANSACTION_HEAD'
        in script
    )
    assert (
        "outputs/daily_simulated_fill_ledger \\\n"
        '    "$PAPER_PRE_TRANSACTION_HEAD"'
        in script
    )
    assert (
        "outputs/daily_simulated_fill_ledger/. \\\n"
        '      "$PAPER_MARK_ONLY_TRANSACTION_HEAD/"'
        in script
    )
    assert (
        'PAPER_MARK_ONLY_COPY_HASH" != '
        '"$PAPER_FIRST_TRANSACTION_HASH"'
        in script
    )
    assert (
        "outputs/daily_simulated_fill_ledger \\\n"
        '         "$PAPER_MARK_ONLY_TRANSACTION_HEAD"'
        in script
    )
    reports = by_name["Build post-gate operating reports"]
    assert reports["id"] == "operating_review"

    evidence_paths = by_name["Upload daily operating evidence artifact"]["with"]["path"]
    for forbidden in (
        "outputs/reports/operating_*_target_book.csv",
        "outputs/account_ledger_preview/",
        "outputs/daily_simulated_fill_ledger/",
    ):
        assert forbidden not in evidence_paths
    accepted = by_name["Upload accepted paper transaction artifact"]
    assert "steps.paper_transaction.outcome == 'success'" in str(accepted["if"])
    assert "steps.operating_review.outcome == 'success'" in str(accepted["if"])
    assert "steps.paper_persist.outcome == 'success'" in str(accepted["if"])
    assert (
        "steps.default_head_publication_gate.outcome == 'success'"
        in str(accepted["if"])
    )
    accepted_paths = accepted["with"]["path"]
    assert "outputs/account_ledger_preview/" in accepted_paths
    assert "outputs/daily_simulated_fill_ledger/" in accepted_paths
    assert "outputs/run287_paper_immutable_head_bundles/" in accepted_paths
    assert "outputs/reports/operating_*_target_book.csv" in accepted_paths
    assert "outputs/run287_decision_observation_archive/" in accepted_paths
    assert "outputs/run287_risk_outcome_price_cache/" in accepted_paths
    assert "daily_paper_legacy_drive_migration.json" in accepted_paths
    persist_index = step_names.index(
        "Persist validated forward paper ledger state"
    )
    publication_gate = by_name[
        "Reverify default head before accepted publication and cache"
    ]
    assert publication_gate["id"] == "default_head_publication_gate"
    assert (
        "steps.paper_persist.outcome == 'success'"
        in str(publication_gate["if"])
    )
    assert (
        "default branch advanced before accepted publication or cache save"
        in publication_gate["run"]
    )
    publication_gate_index = step_names.index(
        "Reverify default head before accepted publication and cache"
    )
    assert persist_index < publication_gate_index
    assert (
        publication_gate_index
        < step_names.index("Upload accepted paper transaction artifact")
    )
    cache_gate = by_name[
        "Reverify default head immediately before accepted cache saves"
    ]
    assert cache_gate["id"] == "default_head_cache_gate"
    cache_gate_index = step_names.index(
        "Reverify default head immediately before accepted cache saves"
    )
    assert (
        step_names.index("Upload accepted paper transaction artifact")
        < cache_gate_index
        < step_names.index("Save validated forward paper state cache")
    )
    accepted_sync = by_name[
        "Sync accepted paper transaction to Google Drive"
    ]
    assert accepted_sync["run"].count("assert_current_default_head") >= 4
    assert (
        "assert_current_default_head\nrclone copy "
        "outputs/run287_accepted_publication"
        in accepted_sync["run"]
    )
    final_gate = by_name[
        "Reverify default head after accepted publication"
    ]
    assert final_gate["id"] == "final_default_head_gate"
    assert (
        step_names.index("Sync accepted paper transaction to Google Drive")
        < step_names.index(
            "Reverify default head after accepted publication"
        )
        < step_names.index("Save refreshed GitHub cache")
    )
    assert (
        "steps.final_default_head_gate.outcome == 'success'"
        in str(by_name["Save refreshed GitHub cache"]["if"])
    )
    assert persist_index < step_names.index(
        "Upload accepted paper transaction artifact"
    )
    assert persist_index < step_names.index(
        "Save validated forward paper state cache"
    )
    assert persist_index < step_names.index(
        "Save validated cross-mode paper continuity cache"
    )
    assert persist_index < step_names.index(
        "Sync accepted paper transaction to Google Drive"
    )


def test_workflow_legacy_drive_migration_is_one_time_and_quarantined() -> None:
    import yaml

    workflow_path = ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    assert (
        workflow["jobs"]["refresh"]["environment"]
        == "run287-paper-durable"
    )
    steps = workflow["jobs"]["refresh"]["steps"]
    by_name = {str(step.get("name")): step for step in steps}
    assert (
        "steps.market.outputs.catchup_mode != 'yes'"
        in str(
            by_name["Restore validated forward paper state cache"]["if"]
        )
    )
    catchup_restore = by_name[
        "Restore validated cross-mode paper continuity cache"
    ]
    assert (
        "steps.market.outputs.ready == 'yes'"
        in str(catchup_restore["if"])
    )
    assert (
        "daily-paper-continuity-v1-"
        in catchup_restore["with"]["key"]
    )
    assert (
        "outputs/run287_paper_immutable_head_bundles"
        in catchup_restore["with"]["path"]
    )
    restore = by_name["Restore persistent data and operating outputs"]["run"]
    transaction = by_name["Run transactional paper ledger and same-close selector"]["run"]
    persist = by_name["Persist validated forward paper ledger state"]["run"]
    assert (
        'case "${PAPER_FIRST_TRANSACTION_DISPOSITION:-}" in'
        in persist
    )
    assert "PRESERVE_MARK_ONLY)" in persist
    assert "REUSE_SELECTED_TARGET)" in persist
    assert (
        'OBSERVED_MARK_ONLY_HASH" != '
        '"$PAPER_FIRST_TRANSACTION_HASH"'
        in persist
    )
    assert (
        '"$PAPER_FIRST_TRANSACTION_HASH" != "$LOCAL_SNAPSHOT_HASH"'
        in persist
    )
    mark_only_install = persist.index(
        'install_prospective_head "$PAPER_MARK_ONLY_TRANSACTION_HEAD"'
    )
    final_install = persist.index(
        "install_prospective_head outputs/daily_simulated_fill_ledger"
    )
    selection = persist.index(
        'select_head_set "$PAPER_PROSPECTIVE_HEADS"'
    )
    assert mark_only_install < final_install < selection
    assert persist.count("assert_current_default_head") >= 8
    assert "assert_current_default_head\n  rclone copyto" in persist
    preparer = (
        ROOT / "tools" / "prepare_run287_legacy_paper_migration.py"
    ).read_text(encoding="utf-8")
    ledger = (
        ROOT / "tools" / "run_daily_simulated_fill_ledger.py"
    ).read_text(encoding="utf-8")

    # Only a manifest-absent, structurally complete completed-NYSE-session
    # source with no cache/local or immutable-head anchor can migrate.
    assert 'PAPER_HAS_IMMUTABLE_HEAD=no' in restore
    assert '[ "$PAPER_HAS_IMMUTABLE_HEAD" = "no" ]' in restore
    assert '[ ! -e "$PAPER_REMOTE_CANDIDATE/snapshot_integrity.json" ]' in restore
    assert '[ ! -d "$PAPER_CACHE_ANCHOR" ]' in restore
    assert "prepare_run287_legacy_paper_migration.py" in restore
    assert '--state-dir "$PAPER_REMOTE_CANDIDATE"' in restore
    assert '--requested-as-of-date "$LAST_NYSE_SESSION_DATE"' in restore
    assert '"status": "PENDING_SEMANTIC_ATTESTATION"' in preparer
    assert '"accepted_for_use": False' in preparer
    assert '"legacy_semantic_attestation_required": True' in preparer
    assert '"production_mutation_allowed": False' in preparer
    assert "validate_legacy_root_snapshot(root)" in preparer
    assert "legacy snapshot must end on an NYSE session" in preparer
    assert "LEGACY_SCHEMA_PROFILE_V1_ZERO_EVENT" in ledger
    assert "legacy v1 migration permits only a zero-event snapshot" in ledger
    assert "legacy v1 economic state is not a zero-event bootstrap descendant" in ledger
    assert "legacy v1 paper snapshot file set mismatch" in ledger
    assert "daily-simulated-fill-ledger-manifest-v1" in ledger
    assert "daily-simulated-fill-ledger-state-v1" in ledger
    assert 'PAPER_LEGACY_MIGRATION_PENDING=yes' in restore
    assert "immutable Drive head exists; legacy manifest-free candidate cannot replace" in restore
    assert "legacy_snapshot_semantic_attestation_mode" in transaction
    assert '"FORWARD_REPLAY"' in transaction
    assert '"SAME_SESSION_SCHEMA_UPGRADE"' in transaction
    assert '"V1_ZERO_EVENT_SEMANTIC_REPLAY"' in transaction
    assert 'summary.get("legacy_schema_profile")' in transaction
    assert "matching immutable Drive head after cache loss" in restore
    assert "verified cache/local or immutable-head cross-source continuity anchor" in restore
    assert '--install-source "$PAPER_REMOTE_CANDIDATE"' in restore
    assert '--require-install-continuity' in restore

    # Quarantine is not acceptance: every legacy profile has an explicit
    # semantic outcome and v1 is restricted to a same-session schema upgrade.
    assert '("LEGACY_ATTESTED", "SAME_SESSION_REUSE")' in transaction
    assert '"LEGACY_SCHEMA_UPGRADE"' in transaction
    assert '"SAME_SESSION_SCHEMA_UPGRADE"' in transaction
    assert '("RESTORED_CONTINUATION", "FORWARD_REPLAY")' in transaction
    assert "requires the exact accepted" in preparer
    assert 'summary.get("legacy_snapshot_semantically_validated") is not True' in transaction
    assert "--legacy-migration-provenance" in transaction
    assert "legacy_migration_attestation.json" in transaction
    assert '"INCLUDED_IN_PAPER_SNAPSHOT_INTEGRITY"' in transaction
    assert 'verified_snapshot_integrity_sha256' in transaction
    assert 'summary.get("new_order_generation_suppressed") is not True' in transaction
    assert 'row.get("enqueued_this_run") != 0' in transaction
    assert 'not isinstance(row.get("resolved_fills_this_run"), int)' in transaction

    # Subsequent/verified state retains the normal source comparison.  The
    # one-time route compares the remote tree before replacing it and never
    # supplies a manifest-free source as a continuity anchor.
    assert 'assert_legacy_drive_source_matches "$RUNNER_TEMP/run287_daily_simulated_fill_ledger_remote"' in persist
    assert 'assert_legacy_drive_source_matches "$PAPER_REMOTE_CAS_CHECK"' in persist
    assert 'install_prospective_head "$PAPER_REMOTE_PERSIST_ANCHOR"' in persist
    assert 'install_prospective_head "$PAPER_CACHE_ANCHOR"' in persist
    assert 'select_head_set "$PAPER_PROSPECTIVE_HEADS"' in persist
    assert '"$PAPER_REMOTE_HEADS_POSTCOMMIT"' in persist
    assert '"$PAPER_REMOTE_HEADS_POSTMIRROR"' in persist
    assert "local snapshot is not the prospective unique terminal" in persist
    assert 'if [ -n "$ANCHOR_SNAPSHOT_HASH" ]' in persist
    assert "accepted immutable ancestor retained=" in persist
    assert 'rclone purge "$HEADS/' not in persist
    assert "BLOCKED: no checksum-verified cross-source continuity anchor" in restore


def test_workflow_catchup_is_explicit_mark_only_and_chronological() -> None:
    import yaml

    workflow_path = (
        ROOT
        / ".github"
        / "workflows"
        / "daily_operating_selection_refresh.yml"
    )
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert inputs["session_date"]["default"] == ""
    steps = workflow["jobs"]["refresh"]["steps"]
    by_name = {str(step.get("name")): step for step in steps}
    market = by_name["Check latest NYSE close"]["run"]
    assert '--session-date "$SELECTED_SESSION_DATE"' in market
    transaction = by_name[
        "Run transactional paper ledger and same-close selector"
    ]["run"]
    assert '"BLOCKED_CATCHUP_MARK_ONLY"' in transaction
    assert (
        "exact-packet recomputation and new orders are disabled"
        in transaction
    )
    assert (
        "price_only_capture_pattern_evidence_unavailable"
        in transaction
    )
    assert (
        "OHLCV pattern memory remains BLOCKED and proposal-ineligible"
        in transaction
    )
    assert (
        'elif [ "$CATCHUP_SOURCE_LAYOUT" = '
        '"LEGACY_SINGLE_SESSION_DAILY_ARTIFACT" ]; then'
        in transaction
    )
    assert transaction.index(
        '"MULTI_SESSION_READ_ONLY_CAPTURE"'
    ) < transaction.index("PATTERN_EVIDENCE_DIRS")
    assert 'if [ "${PAPER_CATCHUP_MODE:-no}" = "yes" ]' in transaction
    assert (
        'CATCHUP_TARGET_SOURCE_DIR="outputs/run287_catchup_target_source/${PAPER_AS_OF}"'
        in transaction
    )
    assert (
        'PAPER_MAIN_TARGET="$CATCHUP_TARGET_SOURCE_DIR/main.csv"'
        in transaction
    )
    assert (
        'PAPER_CONCENTRATED_TARGET="$CATCHUP_TARGET_SOURCE_DIR/concentrated.csv"'
        in transaction
    )
    assert (
        'DURABLE_TARGET_SOURCE_DIR="outputs/daily_simulated_fill_ledger/replay_target_source/${PAPER_AS_OF}"'
        in transaction
    )
    assert 'if [ "$PAPER_STATE_AS_OF" = "$PAPER_AS_OF" ]; then' in transaction
    assert (
        'if [ -s "$DURABLE_TARGET_SOURCE_DIR/main.csv" ]'
        in transaction
    )
    assert (
        'SOURCE_MAIN_TARGET="$DURABLE_TARGET_SOURCE_DIR/main.csv"'
        in transaction
    )
    assert (
        'SOURCE_CONCENTRATED_TARGET="$DURABLE_TARGET_SOURCE_DIR/concentrated.csv"'
        in transaction
    )
    assert (
        "pre-field replay target source backfill blocked:"
        in transaction
    )
    assert 'manifest.get("source_target_sha256")' in transaction
    assert transaction.count("cmp -s") >= 2
    source_snapshot_index = transaction.index(
        'CATCHUP_TARGET_SOURCE_DIR="outputs/run287_catchup_target_source/${PAPER_AS_OF}"'
    )
    ledger_index = transaction.index(
        "python tools/run_daily_simulated_fill_ledger.py"
    )
    assert source_snapshot_index < ledger_index
    cleanup_index = transaction.index(
        "clear_previous_materialization(Path(sys.argv[1]))"
    )
    catchup_marker_index = transaction.index("BLOCKED_CATCHUP_MARK_ONLY")
    assert cleanup_index < catchup_marker_index
    for name in (
        "Build daily market snapshot",
        "Build operating target books",
        "Ensure review-only forward paper bootstrap",
        "Refresh daily macro snapshot",
        "Validate freshness contract",
        "Resolve append-only forward outcomes",
        "Evaluate single promotion and rollback gate",
        "Verify accepted publication manifest",
    ):
        assert (
            "steps.market.outputs.catchup_mode != 'yes'"
            in str(by_name[name]["if"])
        )
    catchup_artifact = by_name[
        "Upload accepted chronological catch-up artifact"
    ]
    assert (
        "steps.market.outputs.catchup_mode == 'yes'"
        in str(catchup_artifact["if"])
    )
    assert (
        "steps.default_head_publication_gate.outcome == 'success'"
        in str(catchup_artifact["if"])
    )
    assert (
        "outputs/daily_simulated_fill_ledger/"
        in catchup_artifact["with"]["path"]
    )
    assert (
        "outputs/run287_paper_immutable_head_bundles/"
        in catchup_artifact["with"]["path"]
    )
    assert (
        "outputs/run287_catchup_target_source/"
        in catchup_artifact["with"]["path"]
    )
    catchup_cache = by_name[
        "Save validated cross-mode paper continuity cache"
    ]
    assert (
        "daily-paper-continuity-v1-"
        in catchup_cache["with"]["key"]
    )
    assert (
        "outputs/run287_paper_immutable_head_bundles"
        in catchup_cache["with"]["path"]
    )
    assert (
        "steps.default_head_publication_gate.outcome == 'success'"
        in str(catchup_cache["if"])
    )
    assert (
        "steps.default_head_cache_gate.outcome == 'success'"
        in str(catchup_cache["if"])
    )
    ledger = (
        ROOT / "tools" / "run_daily_simulated_fill_ledger.py"
    ).read_text(encoding="utf-8")
    assert '"BLOCKED_SESSION_GAP"' in ledger
    assert "expected_next=" in ledger


def main() -> int:
    test_same_close_target_handoff_is_hash_pinned()
    test_twenty_sessions_remain_continuous_and_same_session_is_byte_identical()
    test_failed_second_portfolio_and_interrupted_publish_change_zero_durable_files()
    test_session_gap_requires_chronological_catchup()
    test_duplicate_client_order_id_and_negative_cash_fail_closed()
    test_suppressed_preview_is_explicit_hash_bound_and_transition_safe()
    test_mark_only_parent_and_selected_child_form_complete_immutable_chain()
    test_present_but_stale_preview_is_rebuilt_against_durable_account_and_target()
    test_interrupted_preview_only_publish_recovers_before_reuse()
    test_overlapping_recovery_prefers_newer_state_bundle()
    test_operating_targets_publish_in_same_atomic_bundle()
    test_genesis_identity_prefers_sealed_bootstrap_target_identity()
    test_legacy_v1_zero_event_snapshot_is_recomputed_into_v2_head()
    test_legacy_v1_pin_schema_price_and_provenance_fail_closed()
    test_legacy_same_session_snapshot_is_semantically_attested_once()
    test_legacy_prior_session_snapshot_is_semantically_attested_by_forward_replay()
    test_legacy_migration_blocks_orders_partial_state_and_unsafe_metadata()
    test_verified_matching_immutable_head_recovers_after_cache_loss()
    test_replay_price_evidence_revalidates_parquet_and_is_transactional()
    test_workflow_separates_failed_evidence_from_accepted_paper_state()
    test_workflow_legacy_drive_migration_is_one_time_and_quarantined()
    test_workflow_catchup_is_explicit_mark_only_and_chronological()
    print("run287_paper_ledger_transaction_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
