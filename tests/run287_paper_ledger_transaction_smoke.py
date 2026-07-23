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


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run287_paper_ledger_integrity import (  # noqa: E402
    PaperLedgerIntegrityError,
    directory_hashes,
    install_verified_snapshot,
    require_state_descends_from,
    verify_integrity_manifest,
    write_integrity_manifest,
)
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
            }
        ],
        "realized_pnl_by_ticker": {},
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

        mark_only = run(ledger_args(root, date, suppress_new_orders=True))
        assert mark_only["result_status"] == "NO_NEW_ORDER_PREVIEW"
        assert directory_hashes(root / "paper") == selected_state
        for portfolio in ("main", "concentrated"):
            preview_dir = root / "previews" / portfolio
            manifest = json.loads((preview_dir / "order_batch_manifest.json").read_text(encoding="utf-8"))
            assert manifest["preview_mode"] == "NO_NEW_ORDER"
            assert pd.read_csv(preview_dir / "orders_preview.csv").empty


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


def test_legacy_same_session_snapshot_is_semantically_attested_once() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        date = "2026-04-08"
        prepare(root, [date])
        run(ledger_args(root, date))
        (root / "paper" / "snapshot_integrity.json").unlink()
        (root / "paper" / "accepted_publication.json").unlink()
        provenance_path = root / "legacy_migration_provenance.json"
        provenance_path.write_text(
            json.dumps(
                {
                    "schema_version": "run287-legacy-drive-paper-migration-v1",
                    "status": "PENDING_SEMANTIC_ATTESTATION",
                    "source": "GDRIVE_LEGACY_UNATTESTED",
                    "legacy_as_of_date": date,
                    "requested_as_of_date": date,
                    "remote_snapshot_integrity_present": False,
                    "verified_cross_source_anchor_present": False,
                    "legacy_semantic_attestation_required": True,
                    "accepted_for_use": False,
                    "review_only": True,
                    "live_trading_enabled": False,
                    "production_mutation_allowed": False,
                    "remote_tree_sha256": canonical_hash(
                        directory_hashes(root / "paper")
                    ),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        args = ledger_args(root, date, suppress_new_orders=True)
        args.legacy_migration_provenance = str(provenance_path)

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
        assert attestation["source"] == "GDRIVE_LEGACY_UNATTESTED"
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

        attested = run(
            ledger_args(root, dates[2], suppress_new_orders=True)
        )
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
            run(ledger_args(root, dates[1], suppress_new_orders=True))
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
                run(
                    ledger_args(
                        root,
                        dates[1],
                        suppress_new_orders=True,
                    )
                )
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


def test_workflow_separates_failed_evidence_from_accepted_paper_state() -> None:
    import yaml

    workflow_path = ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["refresh"]["steps"]
    by_name = {str(step.get("name")): step for step in steps}
    transaction = by_name["Run transactional paper ledger and same-close selector"]
    assert transaction["id"] == "paper_transaction"
    script = transaction["run"]
    assert 'cp "$SAME_CLOSE_DIR/same_close_main_target_book.csv"' not in script
    assert "--main-publish-target outputs/reports/operating_main_target_book.csv" in script
    assert "--concentrated-publish-target outputs/reports/operating_concentrated_target_book.csv" in script
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
    accepted_paths = accepted["with"]["path"]
    assert "outputs/account_ledger_preview/" in accepted_paths
    assert "outputs/daily_simulated_fill_ledger/" in accepted_paths
    assert "outputs/reports/operating_*_target_book.csv" in accepted_paths
    assert "outputs/run287_decision_observation_archive/" in accepted_paths
    assert "outputs/run287_risk_outcome_price_cache/" in accepted_paths
    assert "daily_paper_legacy_drive_migration.json" in accepted_paths
    step_names = [str(step.get("name")) for step in steps]
    persist_index = step_names.index(
        "Persist validated forward paper ledger state"
    )
    assert persist_index < step_names.index(
        "Upload accepted paper transaction artifact"
    )
    assert persist_index < step_names.index(
        "Save validated forward paper state cache"
    )
    assert persist_index < step_names.index(
        "Sync accepted paper transaction to Google Drive"
    )


def test_workflow_legacy_drive_migration_is_one_time_and_quarantined() -> None:
    import yaml

    workflow_path = ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["refresh"]["steps"]
    by_name = {str(step.get("name")): step for step in steps}
    restore = by_name["Restore persistent data and operating outputs"]["run"]
    transaction = by_name["Run transactional paper ledger and same-close selector"]["run"]
    persist = by_name["Persist validated forward paper ledger state"]["run"]

    # Only a manifest-absent, structurally complete completed-NYSE-session
    # source with no cache/local or immutable-head anchor can migrate.
    assert 'PAPER_HAS_IMMUTABLE_HEAD=no' in restore
    assert '[ "$PAPER_HAS_IMMUTABLE_HEAD" = "no" ]' in restore
    assert '[ ! -e "$PAPER_REMOTE_CANDIDATE/snapshot_integrity.json" ]' in restore
    assert '[ ! -d "$PAPER_CACHE_ANCHOR" ]' in restore
    assert '"status": "PENDING_SEMANTIC_ATTESTATION"' in restore
    assert '"accepted_for_use": False' in restore
    assert '"legacy_semantic_attestation_required": True' in restore
    assert '"production_mutation_allowed": False' in restore
    assert 'summary.get("simulated") is not True' in restore
    assert 'manifest.get("production_mutation_allowed") is not False' in restore
    assert 'meta.get("production_mutation_allowed") is not False' in restore
    assert 'account.get("human_approval_required_for_live_orders")' in restore
    assert 'manifest.get("historical_cagr_mdd_replacement_allowed")' in restore
    assert "accepted publication exists without snapshot integrity" in restore
    assert '"positions_latest.csv"' in restore
    assert 'summary.get("portfolios", {}).get(portfolio) != manifest' in restore
    assert 'PAPER_LEGACY_MIGRATION_PENDING=yes' in restore
    assert "immutable Drive head exists; legacy manifest-free candidate cannot replace" in restore
    assert "completed NYSE session at or before the requested session" in restore
    assert "pandas_market_calendars as mcal" in restore
    assert "legacy_snapshot_semantic_attestation_mode" in transaction
    assert '"FORWARD_REPLAY"' in transaction
    assert "matching immutable Drive head after cache loss" in restore
    assert "verified cache/local or immutable-head cross-source continuity anchor" in restore
    assert '--install-source "$PAPER_REMOTE_CANDIDATE"' in restore
    assert '--require-install-continuity' in restore

    # Quarantine is not acceptance: same-session reuse and forward replay are
    # the only explicit legacy-attestation outcomes.
    assert '("LEGACY_ATTESTED", "SAME_SESSION_REUSE")' in transaction
    assert '("RESTORED_CONTINUATION", "FORWARD_REPLAY")' in transaction
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
    assert '--require-state-descends-from "$PAPER_REMOTE_PERSIST_ANCHOR"' in persist
    assert 'if [ -n "$ANCHOR_SNAPSHOT_HASH" ]' in persist
    assert "BLOCKED: no checksum-verified cross-source continuity anchor" in restore


def main() -> int:
    test_twenty_sessions_remain_continuous_and_same_session_is_byte_identical()
    test_failed_second_portfolio_and_interrupted_publish_change_zero_durable_files()
    test_duplicate_client_order_id_and_negative_cash_fail_closed()
    test_suppressed_preview_is_explicit_hash_bound_and_transition_safe()
    test_present_but_stale_preview_is_rebuilt_against_durable_account_and_target()
    test_interrupted_preview_only_publish_recovers_before_reuse()
    test_overlapping_recovery_prefers_newer_state_bundle()
    test_operating_targets_publish_in_same_atomic_bundle()
    test_legacy_same_session_snapshot_is_semantically_attested_once()
    test_legacy_prior_session_snapshot_is_semantically_attested_by_forward_replay()
    test_legacy_migration_blocks_orders_partial_state_and_unsafe_metadata()
    test_verified_matching_immutable_head_recovers_after_cache_loss()
    test_workflow_separates_failed_evidence_from_accepted_paper_state()
    test_workflow_legacy_drive_migration_is_one_time_and_quarantined()
    print("run287_paper_ledger_transaction_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
