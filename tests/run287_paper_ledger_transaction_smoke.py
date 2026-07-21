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
        security_lifecycle_events="",
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

        attested = run(ledger_args(root, date))
        assert attested["result_status"] == "LEGACY_ATTESTED"
        verified = verify_integrity_manifest(root / "paper", require=True)
        assert verified["status"] == "VERIFIED"
        after = directory_hashes(root / "paper")

        reused = run(ledger_args(root, date))
        assert reused["result_status"] == "SAME_SESSION_REUSE"
        assert directory_hashes(root / "paper") == after


def test_workflow_separates_failed_evidence_from_accepted_paper_state() -> None:
    import yaml

    workflow_path = ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["refresh"]["steps"]
    by_name = {str(step.get("name")): step for step in steps}
    operating = by_name["Build operating review outputs"]
    assert operating["id"] == "operating_review"
    script = operating["run"]
    assert 'cp "$SAME_CLOSE_DIR/same_close_main_target_book.csv"' not in script
    assert "--main-publish-target outputs/reports/operating_main_target_book.csv" in script
    assert "--concentrated-publish-target outputs/reports/operating_concentrated_target_book.csv" in script

    evidence_paths = by_name["Upload daily operating evidence artifact"]["with"]["path"]
    for forbidden in (
        "outputs/reports/operating_*_target_book.csv",
        "outputs/account_ledger_preview/",
        "outputs/daily_simulated_fill_ledger/",
    ):
        assert forbidden not in evidence_paths
    accepted = by_name["Upload accepted paper transaction artifact"]
    assert "steps.operating_review.outcome == 'success'" in str(accepted["if"])
    accepted_paths = accepted["with"]["path"]
    assert "outputs/account_ledger_preview/" in accepted_paths
    assert "outputs/daily_simulated_fill_ledger/" in accepted_paths
    assert "outputs/reports/operating_*_target_book.csv" in accepted_paths


def main() -> int:
    test_twenty_sessions_remain_continuous_and_same_session_is_byte_identical()
    test_failed_second_portfolio_and_interrupted_publish_change_zero_durable_files()
    test_duplicate_client_order_id_and_negative_cash_fail_closed()
    test_suppressed_preview_is_explicit_hash_bound_and_transition_safe()
    test_present_but_stale_preview_is_rebuilt_against_durable_account_and_target()
    test_interrupted_preview_only_publish_recovers_before_reuse()
    test_operating_targets_publish_in_same_atomic_bundle()
    test_legacy_same_session_snapshot_is_semantically_attested_once()
    test_workflow_separates_failed_evidence_from_accepted_paper_state()
    print("run287_paper_ledger_transaction_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
