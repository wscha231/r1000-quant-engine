from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = ROOT / "research" / "theme_etf_runtime_v1"
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from strict import (  # noqa: E402
    ContractError,
    build_holding_events,
    compose_universe,
    compute_leadership,
    discover_terms,
    latest_asof_by_fund,
    normalize_snapshot,
    normalize_weight,
    validate_normalized_snapshot,
    validate_documents,
    validate_membership_events,
    validate_price_rows,
    resolve_memberships,
    run_payload,
)


def expect_error(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ContractError:
        return
    raise AssertionError("ContractError expected")


def full_snapshot(fund: str, rows, observed="2026-09-14T22:00:00Z", coverage="FULL", unit="PERCENT"):
    return normalize_snapshot({
        "fund_id": fund,
        "source_id": "fixture",
        "portfolio_scope": "PORTFOLIO",
        "coverage_kind": coverage,
        "weight_unit": unit,
        "holdings_as_of": "2026-09-14",
        "observed_at": observed,
        "validated_at": observed,
        "expected_unique_rows": len(rows),
        "rows": rows,
    })


def test_weight_units():
    assert abs(normalize_weight("0.5%", "PERCENT") - 0.005) < 1e-12
    assert abs(normalize_weight("1", "PERCENT") - 0.01) < 1e-12
    assert abs(normalize_weight("0.5", "FRACTION") - 0.5) < 1e-12
    expect_error(normalize_weight, 0.5, "UNKNOWN")
    expect_error(normalize_weight, True, "FRACTION")
    expect_error(normalize_weight, "0.5%", "FRACTION")


def test_normalized_snapshot_revalidates_hash_and_blocks_complete_claim():
    complete = full_snapshot("ETF1", [{"security_id": "A", "ticker": "A", "instrument": "COMMON", "identity_verified": True, "weight": 100}])
    expect_error(validate_normalized_snapshot, complete)
    partial = full_snapshot("ETF1", [{"security_id": "A", "ticker": "A", "instrument": "COMMON", "identity_verified": True, "weight": 50}], coverage="TOP_ONLY")
    assert validate_normalized_snapshot(partial)["complete"] is False
    forged = dict(partial)
    forged["weight_sum"] = 0.9
    expect_error(validate_normalized_snapshot, forged)


def test_partial_snapshot_does_not_prove_removal():
    prev = full_snapshot("ETF1", [
        {"security_id": "A", "ticker": "A", "instrument": "COMMON", "identity_verified": True, "weight": 50},
        {"security_id": "B", "ticker": "B", "instrument": "COMMON", "identity_verified": True, "weight": 50},
    ])
    cur = full_snapshot("ETF1", [
        {"security_id": "A", "ticker": "A", "instrument": "COMMON", "identity_verified": True, "weight": 100},
    ], observed="2026-09-15T22:00:00Z", coverage="TOP_ONLY")
    events = {e["security_id"]: e for e in build_holding_events(prev, cur)}
    assert events["B"]["event_type"] == "ABSENCE_UNCONFIRMED"
    assert events["B"]["sell_proven"] is False


def test_full_snapshot_can_confirm_removal():
    prev = full_snapshot("ETF1", [
        {"security_id": "A", "ticker": "A", "instrument": "COMMON", "identity_verified": True, "weight": 50},
        {"security_id": "B", "ticker": "B", "instrument": "COMMON", "identity_verified": True, "weight": 50},
    ])
    cur = full_snapshot("ETF1", [
        {"security_id": "A", "ticker": "A", "instrument": "COMMON", "identity_verified": True, "weight": 100},
    ], observed="2026-09-15T22:00:00Z")
    events = {e["security_id"]: e for e in build_holding_events(prev, cur)}
    assert events["B"]["event_type"] == "REMOVAL"
    assert events["B"]["trade_proven"] is False


def test_latest_asof_is_per_fund_not_global_timestamp():
    f1 = full_snapshot("ETF1", [{"security_id": "A", "ticker": "A", "instrument": "COMMON", "identity_verified": True, "weight": 100}], observed="2026-09-15T20:00:00Z")
    f2 = full_snapshot("ETF2", [{"security_id": "B", "ticker": "B", "instrument": "COMMON", "identity_verified": True, "weight": 100}], observed="2026-09-15T21:00:00Z")
    latest = latest_asof_by_fund([f1, f2], "2026-09-15T21:30:00Z")
    assert set(latest) == {"ETF1", "ETF2"}


def test_reviewed_membership_only_and_unlink():
    events = [
        {"event_id": "1", "theme_id": "T", "security_id": "A", "action": "LINK", "role": "DIRECT", "relevance": 0.9, "effective_at": "2026-09-10T00:00:00Z", "observed_at": "2026-09-10T01:00:00Z", "reviewed": False},
        {"event_id": "2", "theme_id": "T", "security_id": "B", "action": "LINK", "role": "ENABLER", "relevance": 0.8, "effective_at": "2026-09-10T00:00:00Z", "observed_at": "2026-09-10T01:00:00Z", "reviewed_at": "2026-09-10T02:00:00Z", "reviewed": True},
        {"event_id": "3", "theme_id": "T", "security_id": "B", "action": "UNLINK", "role": "ENABLER", "relevance": 0.0, "effective_at": "2026-09-16T00:00:00Z", "observed_at": "2026-09-10T01:00:00Z", "reviewed_at": "2026-09-10T02:00:00Z", "reviewed": True},
    ]
    state = resolve_memberships(events, "2026-09-15T00:00:00Z")
    assert set(state) == {"B"}


def test_universe_expansion_requires_verified_us_common_or_adr():
    memberships = {"NEW": {"security_id": "NEW"}, "FOREIGN": {"security_id": "FOREIGN"}}
    securities = [
        {"security_id": "NEW", "identity_verified": True, "listing_country": "US", "instrument": "COMMON", "exchange": "XNAS", "research_eligible": True},
        {"security_id": "FOREIGN", "identity_verified": True, "listing_country": "KR", "instrument": "COMMON", "exchange": "XKRX", "research_eligible": True},
    ]
    result = compose_universe(["BASE"], securities, memberships)
    assert result["research_universe_proposal"] == ["BASE", "NEW"]
    assert result["excluded"][0]["security_id"] == "FOREIGN"


def test_leadership_uses_log_relative_total_return():
    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(21):
        day = (start + timedelta(days=i)).date().isoformat()
        rows.append({"security_id": "SPY", "session": day, "available_at": day + "T23:00:00Z", "total_return_index": 100 + i})
        rows.append({"security_id": "ETF1", "session": day, "available_at": day + "T23:00:00Z", "total_return_index": 100 + 2 * i})
    out = compute_leadership(rows, "SPY", decision_at="2026-01-21T23:30:00Z")
    row = out[0]
    assert row["rs_log_20"] > 0
    assert row["return_20"] > 0


def test_discovery_deduplicates_documents_and_tracks_source_groups():
    docs = [
        {"document_id": "1", "source_group": "A", "available_at": "2026-09-15T10:00:00Z", "title": "co-packaged optics demand accelerates", "summary": "co-packaged optics"},
        {"document_id": "1", "source_group": "A", "available_at": "2026-09-15T10:01:00Z", "title": "duplicate", "summary": "duplicate"},
        {"document_id": "2", "source_group": "B", "available_at": "2026-09-15T10:02:00Z", "title": "co-packaged optics capacity", "summary": "co-packaged optics"},
    ]
    terms = discover_terms(docs, decision_at="2026-09-15T11:00:00Z")
    matching = [r for r in terms if r["term"] == "co-packaged optics"]
    assert matching and matching[0]["independent_source_groups"] == 2


def test_end_to_end_keeps_trading_disabled():
    rows = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for i in range(241):
        session = (start + timedelta(days=i)).date().isoformat()
        rows.append({"security_id": "SPY", "session": session, "available_at": session + "T23:00:00Z", "total_return_index": 100 + i * 0.1})
        rows.append({"security_id": "ETF1", "session": session, "available_at": session + "T23:00:00Z", "total_return_index": 100 + i * 0.2})
    payload = {
        "schema": "theme-etf-runtime-v1",
        "decision_at": "2026-09-15T22:00:00Z",
        "benchmark_id": "SPY",
        "base_universe": ["BASE"],
        "securities": [{"security_id": "NEW", "identity_verified": True, "listing_country": "US", "instrument": "ADR", "exchange": "XNYS", "research_eligible": True}],
        "membership_events": [{"event_id": "m1", "theme_id": "T", "security_id": "NEW", "action": "LINK", "role": "DIRECT", "relevance": 0.8, "effective_at": "2026-09-15T00:00:00Z", "observed_at": "2026-09-15T01:00:00Z", "reviewed_at": "2026-09-15T02:00:00Z", "reviewed": True}],
        "prices": rows,
        "documents": [],
        "etf_snapshots": [],
    }
    result = run_payload(payload)
    assert result["summary"]["orders_generated"] is False
    assert result["summary"]["target_book_changed"] is False
    assert result["summary"]["universe"]["research_universe_proposal"] == ["BASE", "NEW"]


def test_point_in_time_inputs_reject_future_or_duplicate_evidence():
    expect_error(validate_documents, [{"document_id": "d1", "available_at": "2026-09-16T00:00:00Z"}], "2026-09-15T22:00:00Z")
    expect_error(validate_membership_events, [{"event_id": "m1", "effective_at": "2026-09-14T00:00:00Z", "observed_at": "2026-09-16T00:00:00Z", "reviewed": False}], "2026-09-15T22:00:00Z")
    duplicate_prices = [
        {"security_id": "SPY", "session": "2026-09-15", "available_at": "2026-09-15T21:00:00Z", "total_return_index": 100},
        {"security_id": "SPY", "session": "2026-09-15", "available_at": "2026-09-15T21:00:00Z", "total_return_index": 100},
    ]
    expect_error(validate_price_rows, duplicate_prices, "2026-09-15T22:00:00Z")
    expect_error(validate_price_rows, [{"security_id": "SPY", "session": "2026-09-15", "available_at": "2026-09-14T21:00:00Z", "total_return_index": 100}], "2026-09-15T22:00:00Z")
    expect_error(validate_membership_events, [{"event_id": "m2", "effective_at": "2026-09-14T00:00:00Z", "observed_at": "2026-09-15T10:00:00Z", "reviewed_at": "2026-09-15T09:00:00Z", "reviewed": True}], "2026-09-15T22:00:00Z")


def main():
    tests = [name for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for name in tests:
        globals()[name]()
        print(f"PASS {name}")
    print(f"PASS_COUNT={len(tests)}")


if __name__ == "__main__":
    main()
