#!/usr/bin/env python3
"""Generic contract tests for the shared point-in-time lifecycle component."""

from __future__ import annotations

import tempfile
from pathlib import Path
import re
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.security_lifecycle import (
    BLOCKED_STATUS,
    SecurityLifecycleError,
    filter_terminal_tickers,
    resolve_security_lifecycle,
    verified_settlement_by_ticker,
)


def event(**overrides: str) -> dict[str, str]:
    row = {
        "stable_security_id": "SECURITY:ACQ",
        "stable_issuer_id": "ISSUER:ACQ",
        "ticker": "ACQ",
        "aliases": "ACQ",
        "event_type": "cash_merger",
        "available_from": "2026-01-06T13:00:00Z",
        "effective_date": "2026-01-06",
        "last_trading_date": "2026-01-05",
        "predecessor_security_id": "",
        "successor_security_id": "",
        "successor_ticker": "",
        "cash_consideration": "25.50",
        "delisting_proceeds": "",
        "currency": "USD",
        "source_url": "https://example.test/filing/acq",
        "accession_number": "0000000000-26-000001",
        "stable_event_id": "EVENT:ACQ:20260106",
        "source_sha256": "a" * 64,
        "exact_available_from": "true",
        "evidence_status": "verified",
        "review_status": "approved",
        "notes": "generic fixture",
    }
    row.update(overrides)
    return row


def resolve(rows: list[dict[str, str]], *, session: str, decision: str, active: set[str]):
    holder = tempfile.TemporaryDirectory()
    path = Path(holder.name) / "lifecycle.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    try:
        snapshot = resolve_security_lifecycle(
            path,
            session_date=pd.Timestamp(session),
            decision_time_utc=pd.Timestamp(decision),
            active_tickers=active,
        )
    except Exception:
        holder.cleanup()
        raise
    return holder, snapshot


def test_verified_cash_merger_is_actionable_and_ordinary_ticker_is_untouched() -> None:
    holder, snapshot = resolve(
        [event()],
        session="2026-01-06",
        decision="2026-01-06T23:00:00Z",
        active={"ACQ", "KEEP"},
    )
    try:
        assert snapshot.terminal_tickers == frozenset({"ACQ"})
        assert verified_settlement_by_ticker(snapshot)["ACQ"]["verified_proceeds"] == 25.5
        frame = pd.DataFrame({"ticker": ["ACQ", "KEEP"]})
        assert filter_terminal_tickers(frame, snapshot)["ticker"].tolist() == ["KEEP"]
        assert snapshot.audit()["survivorship_coverage_claimed"] is False
    finally:
        holder.cleanup()


def test_event_after_decision_time_and_before_effective_date_do_not_rewrite_history() -> None:
    holder, not_known = resolve(
        [event()],
        session="2026-01-06",
        decision="2026-01-06T12:59:59Z",
        active={"ACQ"},
    )
    try:
        assert not not_known.terminal_tickers
    finally:
        holder.cleanup()
    holder, not_effective = resolve(
        [event(available_from="2026-01-05T13:00:00Z")],
        session="2026-01-05",
        decision="2026-01-05T23:00:00Z",
        active={"ACQ"},
    )
    try:
        assert not not_effective.terminal_tickers
    finally:
        holder.cleanup()


def test_duplicate_active_terminal_event_fails_closed() -> None:
    rows = [event(), event(stable_event_id="EVENT:ACQ:SECOND", source_sha256="b" * 64)]
    try:
        resolve(
            rows,
            session="2026-01-06",
            decision="2026-01-06T23:00:00Z",
            active={"ACQ"},
        )
    except SecurityLifecycleError as exc:
        assert exc.status == BLOCKED_STATUS
        assert "duplicate_active_terminal_events" in str(exc)
    else:
        raise AssertionError("duplicate terminal events were accepted")


def test_bankruptcy_and_cash_merger_without_verified_proceeds_fail_closed() -> None:
    for row in (
        event(
            event_type="bankruptcy",
            cash_consideration="",
            delisting_proceeds="",
        ),
        event(cash_consideration=""),
    ):
        try:
            resolve(
                [row],
                session="2026-01-06",
                decision="2026-01-06T23:00:00Z",
                active={"ACQ"},
            )
        except SecurityLifecycleError as exc:
            assert "missing_verified_proceeds" in str(exc)
        else:
            raise AssertionError("terminal event without proceeds was accepted")


def test_ticker_rename_and_predecessor_successor_are_linked_only_when_known() -> None:
    rename = event(
        stable_security_id="SECURITY:REN",
        stable_issuer_id="ISSUER:REN",
        ticker="OLD",
        aliases="OLD|NEW",
        event_type="ticker_change",
        predecessor_security_id="SECURITY:REN",
        successor_security_id="SECURITY:REN",
        successor_ticker="NEW",
        cash_consideration="",
        stable_event_id="EVENT:REN:20260106",
    )
    successor = event(
        stable_security_id="SECURITY:PRE",
        stable_issuer_id="ISSUER:PRE",
        ticker="PRE",
        aliases="PRE|POST",
        event_type="security_successor",
        predecessor_security_id="SECURITY:PRE",
        successor_security_id="SECURITY:POST",
        successor_ticker="POST",
        cash_consideration="",
        stable_event_id="EVENT:SUCCESSOR:20260106",
        source_sha256="b" * 64,
    )
    holder, snapshot = resolve(
        [rename, successor],
        session="2026-01-06",
        decision="2026-01-06T23:00:00Z",
        active={"OLD", "PRE"},
    )
    try:
        assert snapshot.provider_symbol_overrides == {"OLD": "NEW", "PRE": "POST"}
        assert not snapshot.terminal_tickers
    finally:
        holder.cleanup()


def test_weak_evidence_malformed_identity_and_hash_fail_closed() -> None:
    variants = (
        event(exact_available_from="false"),
        event(stable_security_id="bad id"),
        event(source_sha256="not-a-hash"),
    )
    for row in variants:
        try:
            resolve(
                [row],
                session="2026-01-06",
                decision="2026-01-06T23:00:00Z",
                active={"ACQ"},
            )
        except SecurityLifecycleError as exc:
            assert exc.status == BLOCKED_STATUS
        else:
            raise AssertionError("weak or malformed lifecycle evidence was accepted")


def test_scorer_and_ledger_share_component_without_ticker_branches() -> None:
    consumers = (
        ROOT / "tools" / "run_run287_scored_latest_refresh.py",
        ROOT / "tools" / "run_daily_simulated_fill_ledger.py",
        ROOT / "tools" / "run_run287_exact_packet_upstream.py",
    )
    for path in consumers:
        text = path.read_text(encoding="utf-8")
        assert "security_lifecycle" in text
        for actual_ticker in ("GTLS", "IAC", "PPLI"):
            assert not re.search(
                rf"\b{actual_ticker}\b", text
            ), f"ticker-specific branch in {path.name}"


if __name__ == "__main__":
    test_verified_cash_merger_is_actionable_and_ordinary_ticker_is_untouched()
    test_event_after_decision_time_and_before_effective_date_do_not_rewrite_history()
    test_duplicate_active_terminal_event_fails_closed()
    test_bankruptcy_and_cash_merger_without_verified_proceeds_fail_closed()
    test_ticker_rename_and_predecessor_successor_are_linked_only_when_known()
    test_weak_evidence_malformed_identity_and_hash_fail_closed()
    test_scorer_and_ledger_share_component_without_ticker_branches()
    print("security lifecycle smoke: PASS")
