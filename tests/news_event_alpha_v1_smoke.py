#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.news_event_alpha_v1.runtime import (  # noqa: E402
    POWER_MINIMUMS,
    build_challenger_proposal,
    normalize_events,
    run_payload,
)
from research.news_event_alpha_v1.walk_forward import (  # noqa: E402
    build_walk_forward_impact_estimates,
)


def sessions(n: int = 430) -> list[dict]:
    out = []
    current = date(2024, 1, 2)
    while len(out) < n:
        if current.weekday() < 5:
            close = datetime(current.year, current.month, current.day, 21, 0, tzinfo=timezone.utc)
            out.append({"session": current.isoformat(), "market_close_utc": close.isoformat()})
        current += timedelta(days=1)
    return out


def fixture():
    cal = sessions()
    event_i = 100
    prices = []
    ids = ["SPY", "GNRC", "PSQL", "P1", "P2", "P3", "P4"]
    tri = {x: 100.0 for x in ids}
    for i, s in enumerate(cal):
        spy_r = 0.001
        for sec in ids:
            if sec == "SPY":
                r = spy_r
            elif sec == "GNRC":
                r = 0.0002 if i < event_i else (0.012 if i <= event_i + 10 else 0.002)
            elif sec == "PSQL":
                r = 0.0001 if i < event_i else -0.001
            else:
                r = 0.0005 if i < event_i else (0.004 if i <= event_i + 20 else 0.0015)
            tri[sec] *= 1 + r
            volume = 350_000.0 if sec == "GNRC" and i == event_i else 100_000.0
            prices.append({
                "security_id": sec,
                "session": s["session"],
                "total_return_index": tri[sec],
                "volume": volume,
            })
    available = cal[event_i]["market_close_utc"]
    after_close = (datetime.fromisoformat(available) + timedelta(minutes=5)).isoformat()
    events = [
        {
            "event_id": "gnrc-wire",
            "economic_event_id": "gnrc-amzn-contract",
            "security_id": "GNRC",
            "issuer_id": "GNRC",
            "available_at": available,
            "instrument": "COMMON",
            "exchange": "XNAS",
            "listing_country": "US",
            "eligibility_verified_asof": True,
            "event_type": "CONTRACT",
            "role": "DIRECT",
            "source_tier": "TIER1_NEWS",
            "official_evidence": False,
            "business_relation_new": True,
            "economic_amount_usd": 2_400_000_000,
            "economic_amount_kind": "EXPECTED_DELIVERIES",
            "theme_peer_ids": ["P1", "P2", "P3", "P4"],
            "independent_source_groups": ["wire"],
            "sample_origin": "FORWARD_SHADOW",
            "dilution_risk": 0.2,
        },
        {
            "event_id": "gnrc-8k",
            "economic_event_id": "gnrc-amzn-contract",
            "security_id": "GNRC",
            "issuer_id": "GNRC",
            "available_at": available,
            "instrument": "COMMON",
            "exchange": "XNAS",
            "listing_country": "US",
            "eligibility_verified_asof": True,
            "event_type": "CONTRACT",
            "role": "DIRECT",
            "source_tier": "OFFICIAL",
            "official_evidence": True,
            "business_relation_new": True,
            "economic_amount_usd": 2_400_000_000,
            "economic_amount_kind": "EXPECTED_DELIVERIES",
            "theme_peer_ids": ["P1", "P2", "P3", "P4"],
            "independent_source_groups": ["sec"],
            "sample_origin": "FORWARD_SHADOW",
            "dilution_risk": 0.2,
        },
        {
            "event_id": "psql-rnd",
            "economic_event_id": "psql-rnd",
            "security_id": "PSQL",
            "available_at": after_close,
            "instrument": "COMMON",
            "exchange": "XNAS",
            "listing_country": "US",
            "eligibility_verified_asof": True,
            "event_type": "RND_PARTNERSHIP",
            "role": "ENABLER",
            "source_tier": "PRIMARY",
            "official_evidence": False,
            "business_relation_new": True,
            "economic_value_confirmed": False,
            "theme_peer_ids": ["P1", "P2", "P3", "P4"],
            "sample_origin": "FORWARD_SHADOW",
            "cashflow_risk": 0.8,
        },
    ]
    return cal, prices, events, event_i


def test_source_reprints_do_not_double_count():
    _, _, events, _ = fixture()
    normalized = normalize_events(events)
    assert len(normalized) == 2
    gnrc = next(x for x in normalized if x["security_id"] == "GNRC")
    assert gnrc["official_evidence"] is True
    assert gnrc["source_record_count"] == 2
    assert gnrc["independent_source_groups"] == ["sec", "wire"]


def test_checkpoint_timing_and_combo_separate_gnrc_from_psql():
    cal, prices, events, event_i = fixture()
    result = run_payload({
        "schema": "news-event-alpha-v1",
        "events": events,
        "prices": prices,
        "market_sessions": cal,
        "benchmark_id": "SPY",
        "report_top_n": 5,
        "report_checkpoint": 5,
        "promotion_checkpoint": 5,
    })
    gnrc5 = next(r for r in result["checkpoint_rows"] if r["security_id"] == "GNRC" and r["checkpoint"] == 5)
    psql5 = next(r for r in result["checkpoint_rows"] if r["security_id"] == "PSQL" and r["checkpoint"] == 5)
    assert gnrc5["pre_rs60"] < 0
    assert gnrc5["post_rs_checkpoint"] > 0
    assert gnrc5["theme_breadth_checkpoint"] == 1.0
    assert gnrc5["confirmed_combo"] is True
    assert psql5["confirmed_combo"] is False
    assert psql5["event_session"] == cal[event_i + 1]["session"]

    row = next(r for r in result["outcomes"] if r["security_id"] == "GNRC" and r["checkpoint"] == 5 and r["horizon"] == 21)
    assert row["checkpoint_session"] == cal[event_i + 5]["session"]
    assert row["outcome_end_session"] == cal[event_i + 26]["session"]
    assert row["excess_return"] is not None


def test_top_report_is_bounded_and_gate_is_fail_closed():
    cal, prices, events, _ = fixture()
    result = run_payload({
        "schema": "news-event-alpha-v1",
        "events": events,
        "prices": prices,
        "market_sessions": cal,
        "benchmark_id": "SPY",
        "report_top_n": 1,
        "report_checkpoint": 5,
        "promotion_checkpoint": 5,
    })
    assert len(result["top_current_events"]) == 1
    assert result["top_current_events"][0]["security_id"] == "GNRC"
    proposal = result["challenger_proposal"]
    assert proposal["status"] == "UNDERPOWERED_OR_BLOCKED"
    assert proposal["selector_eligible"] is False
    assert proposal["automatic_promotion_allowed"] is False


def powered_summary(origin: str, horizon: int) -> dict:
    return {
        "sample_origin": origin,
        "checkpoint": 5,
        "horizon": horizon,
        "arm": "CONFIRMED_COMBO",
        "event_type": "ALL",
        "n": POWER_MINIMUMS[horizon] + 10,
        "distinct_years": 4 if origin == "HISTORICAL_BACKFILL" else 3,
        "distinct_issuers": 40,
        "mean_excess": 0.06,
        "median_excess": 0.04,
        "win_rate_excess_gt0": 0.63,
        "hit_rate_excess_gt5pct": 0.52,
        "hit_rate_excess_gt10pct": 0.40,
        "q25_excess": -0.01,
        "q75_excess": 0.12,
        "ci95_mean_low": 0.01,
        "ci95_mean_high": 0.11,
        "issuer_year_cluster_n": 40,
        "issuer_year_cluster_mean_excess": 0.05,
        "issuer_year_cluster_median_excess": 0.04,
        "issuer_year_cluster_ci95_mean_low": 0.01,
        "issuer_year_cluster_ci95_mean_high": 0.09,
    }


def test_gate_can_propose_manual_challenger_but_never_activate():
    rows = [
        powered_summary(origin, horizon)
        for origin in ("HISTORICAL_BACKFILL", "FORWARD_SHADOW")
        for horizon in (21, 63, 126)
    ]
    proposal = build_challenger_proposal(rows, checkpoint=5)
    assert proposal["status"] == "RESEARCH_CHALLENGER_REVIEW_ELIGIBLE"
    assert proposal["manual_review_required"] is True
    assert proposal["selector_eligible"] is False
    assert proposal["production_activation_allowed"] is False
    assert proposal["automatic_promotion_allowed"] is False


def test_cli_ledger_is_immutable_and_writes_manifest():
    cal, prices, events, _ = fixture()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        event_path = root / "events.jsonl"
        price_path = root / "prices.jsonl"
        session_path = root / "sessions.jsonl"
        for path, rows in ((event_path, events), (price_path, prices), (session_path, cal)):
            path.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
        out = root / "out"
        cmd = [
            sys.executable,
            str(ROOT / "tools/run_news_event_alpha_v1.py"),
            "--events", str(event_path),
            "--prices", str(price_path),
            "--market-sessions", str(session_path),
            "--output-dir", str(out),
            "--mode", "FORWARD_SHADOW",
            "--top-n", "1",
            "--source-commit", "synthetic",
        ]
        subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["research_only"] is True
        assert manifest["counts"]["ledger_events"] == 2
        assert manifest["counts"]["top_reported_events"] == 1

        changed = [dict(events[0])]
        changed[0]["economic_amount_usd"] = 9_999
        changed_path = root / "changed.jsonl"
        changed_path.write_text(json.dumps(changed[0]) + "\n", encoding="utf-8")
        conflict = cmd.copy()
        conflict[conflict.index(str(event_path))] = str(changed_path)
        conflict.extend(["--existing-ledger", str(out / "event_ledger.jsonl")])
        proc = subprocess.run(conflict, cwd=ROOT, capture_output=True, text=True)
        assert proc.returncode != 0
        assert "immutable event conflict" in (proc.stderr + proc.stdout)



def test_non_us_or_unverified_listing_fails_closed():
    _, _, events, _ = fixture()
    bad = [dict(events[0])]
    bad[0]["economic_event_id"] = "bad-korea"
    bad[0]["event_id"] = "bad-korea"
    bad[0]["listing_country"] = "KR"
    try:
        normalize_events(bad)
    except Exception as exc:
        assert "non-US listing" in str(exc)
    else:
        raise AssertionError("non-US listing was accepted")


def test_historical_cli_requires_verified_receipt():
    cal, prices, events, _ = fixture()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        paths = {}
        for name, rows in (("events", events), ("prices", prices), ("sessions", cal)):
            path = root / f"{name}.jsonl"
            path.write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
            paths[name] = path
        cmd = [
            sys.executable, str(ROOT / "tools/run_news_event_alpha_v1.py"),
            "--events", str(paths["events"]),
            "--prices", str(paths["prices"]),
            "--market-sessions", str(paths["sessions"]),
            "--output-dir", str(root / "out"),
            "--mode", "HISTORICAL_BACKFILL",
            "--source-commit", "abcdef1",
        ]
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        assert proc.returncode != 0
        assert "verified 64-hex" in (proc.stderr + proc.stdout)


def test_walk_forward_excludes_not_yet_resolved_training_outcomes():
    current = {
        "economic_event_id": "current",
        "security_id": "CUR",
        "issuer_id": "CUR",
        "event_type": "CONTRACT",
        "checkpoint": 5,
        "checkpoint_session": "2025-06-30",
        "confirmed_combo": True,
        "official_direct": True,
        "business_substance": True,
    }
    outcomes = []
    for i in range(60):
        outcomes.append({
            "economic_event_id": f"old-{i}",
            "security_id": f"T{i}",
            "issuer_id": f"I{i}",
            "event_type": "CONTRACT",
            "checkpoint": 5,
            "horizon": 63,
            "outcome_status": "RESOLVED",
            "outcome_end_session": f"2025-{1 + (i // 28):02d}-{1 + (i % 28):02d}",
            "excess_return": 0.02 + (i % 5) * 0.005,
            "confirmed_combo": True,
            "official_direct": True,
            "business_substance": True,
            "event_session": "2024-12-01",
        })
    # This spectacular result is not fully known at the current checkpoint and
    # must not enter the analogue distribution.
    outcomes.append({
        "economic_event_id": "future-outcome",
        "security_id": "FUT",
        "issuer_id": "FUT",
        "event_type": "CONTRACT",
        "checkpoint": 5,
        "horizon": 63,
        "outcome_status": "RESOLVED",
        "outcome_end_session": "2025-07-15",
        "excess_return": 9.99,
        "confirmed_combo": True,
        "official_direct": True,
        "business_substance": True,
        "event_session": "2025-04-01",
    })
    estimates = build_walk_forward_impact_estimates(
        [current],
        outcomes,
        min_event_type_arm_n=15,
        min_arm_n=30,
        min_all_n=50,
    )
    row = next(x for x in estimates if x["horizon"] == 63)
    assert row["analogue_status"] == "AVAILABLE"
    assert row["training_n"] == 60
    assert row["training_latest_outcome_end_session"] < current["checkpoint_session"]
    assert row["analogue_median_excess"] < 0.1

def main() -> int:
    test_source_reprints_do_not_double_count()
    test_checkpoint_timing_and_combo_separate_gnrc_from_psql()
    test_top_report_is_bounded_and_gate_is_fail_closed()
    test_gate_can_propose_manual_challenger_but_never_activate()
    test_cli_ledger_is_immutable_and_writes_manifest()
    test_non_us_or_unverified_listing_fails_closed()
    test_historical_cli_requires_verified_receipt()
    test_walk_forward_excludes_not_yet_resolved_training_outcomes()
    print("news_event_alpha_v1_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
