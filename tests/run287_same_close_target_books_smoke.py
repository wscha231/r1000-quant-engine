#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_same_close_target_books as gate  # noqa: E402
from tools.reserve_asset_policy import RESERVE_REASON_SOURCE_HASH_FIELD  # noqa: E402


DATE = "2026-07-16"
DECISION_TIME = "2026-07-17T04:15:00+00:00"
FEATURE_AVAILABLE_TIME = "2026-07-17T04:10:00+00:00"
SOURCE_RUN_ID = "123456789"
SOURCE_COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
SOURCE_BRANCH = "master"
SOURCE_ARTIFACT_NAME = f"daily-operating-selection-refresh-{SOURCE_RUN_ID}"
CANDIDATE_TICKERS = (
    "OLD",
    "NEW",
    "KEEP",
    "RISKY",
    *(f"T{index:03d}" for index in range(96)),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def scored_candidate_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, ticker in enumerate(CANDIDATE_TICKERS):
        rows.append(
            {
                "ticker": ticker,
                "px": 100.0 + index,
                "score_total": 1.0 - index / 200.0,
                "mom_1m": 0.01 + index / 10000.0,
                "mom_3m": 0.03 + index / 10000.0,
                "mom_6m": 0.06 + index / 10000.0,
                "mom_12m": (
                    ""
                    if index >= len(CANDIDATE_TICKERS) - 2
                    else 0.12 + index / 10000.0
                ),
                "relative_strength_composite": 0.50 + index / 1000.0,
                "valuation_price_cutoff_date": DATE,
                "feature_available_from": FEATURE_AVAILABLE_TIME,
            }
        )
    return pd.DataFrame(rows)


def actual_core_coverage(root: Path) -> tuple[dict[str, object], list[str]]:
    return gate.core_candidate_coverage_for_path(
        root / "scored_latest.csv",
        minimum_ratio=gate.MINIMUM_CORE_CANDIDATE_COVERAGE,
        expected_row_count=len(CANDIDATE_TICKERS),
        expected_valuation_date=DATE,
        decision_time_utc=DECISION_TIME,
        expected_ticker_set_sha256=gate.core_candidate_ticker_set_sha256(
            CANDIDATE_TICKERS
        ),
    )


def bind_price_manifest(root: Path, *, recompute_core: bool = True) -> None:
    price_path = root / "price_manifest.json"
    price = json.loads(price_path.read_text(encoding="utf-8"))
    price["outputs"]["scored_latest.csv"] = record(root / "scored_latest.csv")
    if recompute_core:
        price["core_candidate_coverage"], _ = actual_core_coverage(root)
    write_json(price_path, price)
    selector_path = root / "selector.json"
    selector = json.loads(selector_path.read_text(encoding="utf-8"))
    selector.setdefault("source_inputs", {})["price_manifest"] = record(price_path)
    write_json(selector_path, selector)
    refresh_producer(root)


def fixture(root: Path) -> argparse.Namespace:
    activity = root / "prediction_activity.csv"
    pd.DataFrame(
        [
            {
                "prediction": head,
                "row_count": 3,
                "finite_count": 3,
                "unique_count": 3,
                "maximum_absolute_value": 0.3,
                "standard_deviation": 0.1,
                "nonzero_nonconstant_pass": True,
            }
            for head in sorted(gate.ACTIVE_HEADS)
        ]
    ).to_csv(activity, index=False)
    score = root / "score.json"
    write_json(
        score,
        {
            "status": gate.SCORE_STATUS,
            "valuation_price_cutoff_date": DATE,
            "fresh_prediction_passthrough_verified": True,
            "stale_prediction_columns_removed_before_join": True,
            "outputs": {"prediction_activity_audit": record(activity)},
        },
    )
    decision = root / "decision.json"
    selection_context = root / "selection_context.parquet"
    pd.DataFrame(
        {
            "ticker": CANDIDATE_TICKERS,
            "market_breadth_above_ma200": [0.62] * len(CANDIDATE_TICKERS),
            "market_breadth_above_ma150": [0.67] * len(CANDIDATE_TICKERS),
            "market_sector_participation": [0.58] * len(CANDIDATE_TICKERS),
            "market_leadership_narrowing": [0.20] * len(CANDIDATE_TICKERS),
        }
    ).to_parquet(selection_context, index=False)
    write_json(
        decision,
        {
            "status": "READY_COMPLETE_CURRENT_DECISION_FRAME",
            "valuation_price_cutoff_date": DATE,
            "decision_time_utc": DECISION_TIME,
            "feature_available_from": FEATURE_AVAILABLE_TIME,
            "outputs": {"selection_context": record(selection_context)},
        },
    )
    crisis_row = root / "current_crisis_state.csv"
    pd.DataFrame(
        [
            {
                "date": DATE,
                "crisis_state": "GREEN",
                "crisis_score": 0.10,
                "market_trend_damage_score": 0.10,
                "qqq_below_ma200": 0.0,
                "hy_oas_zscore_252d": 0.1,
                "vix_zscore_252d": 0.1,
                "liquidity_confirmation_score": 0.1,
                "rate_shock_score": 0.1,
                "reentry_score": 0.8,
                "reentry_multiplier": 1.0,
            }
        ]
    ).to_csv(crisis_row, index=False)
    crisis = root / "crisis.json"
    write_json(
        crisis,
        {
            "status": "READY_CURRENT_CRISIS_STATE_NONSELECTING",
            "valuation_price_cutoff_date": DATE,
            "feature_contract": {"future_labels_used_for_state": False},
            "outputs": {"current_crisis_state": record(crisis_row)},
        },
    )
    projection = root / "projection.csv"
    pd.DataFrame(
        [
            ["main", "prior_hold_transition_bridge", "OLD", 0.60],
            ["main", "prior_hold_transition_bridge", "NEW", 0.30],
            ["main", "prior_hold_transition_bridge", "CASH", 0.10],
            ["concentrated", "strict_registered_current", "KEEP", 0.70],
            ["concentrated", "strict_registered_current", "RISKY", 0.20],
            ["concentrated", "strict_registered_current", "CASH", 0.10],
        ],
        columns=["portfolio_kind", "scenario", "ticker", "advisory_weight"],
    ).to_csv(projection, index=False)
    comparison = root / "comparison.csv"
    pd.DataFrame(
        [
            ["main", "prior_hold_transition_bridge", "OLD", 0.50, "WATCH", "FREEZE_INCREMENTAL_BUY"],
            ["main", "prior_hold_transition_bridge", "NEW", 0.00, "", ""],
            ["main", "prior_hold_transition_bridge", "CASH", 0.50, "", ""],
            ["concentrated", "strict_registered_current", "KEEP", 0.70, "NORMAL", "HOLD"],
            ["concentrated", "strict_registered_current", "RISKY", 0.00, "", ""],
            ["concentrated", "strict_registered_current", "CASH", 0.30, "", ""],
        ],
        columns=[
            "portfolio_kind",
            "scenario",
            "ticker",
            "marked_weight",
            "held_risk_state",
            "held_risk_advisory_action",
        ],
    ).to_csv(comparison, index=False)
    timestamp = gate.timestamp_contract(
        valuation_date=DATE, decision_time=pd.Timestamp(DECISION_TIME)
    )
    scored_latest = root / "scored_latest.csv"
    scored_candidate_frame().to_csv(scored_latest, index=False)
    core_coverage, core_blockers = actual_core_coverage(root)
    assert not core_blockers
    assert core_coverage["complete_row_count"] == 98
    assert core_coverage["coverage_ratio"] == 0.98
    assert core_coverage["passed"] is True
    assert core_coverage["source_sha256"] == sha(scored_latest)
    assert core_coverage["ticker_set_sha256"] == gate.core_candidate_ticker_set_sha256(
        CANDIDATE_TICKERS
    )
    assert core_coverage["ticker_set_matches_expected"] is True
    price = root / "price_manifest.json"
    write_json(
        price,
        {
            "schema_version": "run287-scored-latest-refresh-v4",
            "status": "READY_RESEARCH_SCORED_LATEST",
            "session_date": DATE,
            "decision_time_utc": DECISION_TIME,
            "score_available_from": DECISION_TIME,
            "coverage": {
                "pre_lifecycle_context_count": len(CANDIDATE_TICKERS),
                "post_lifecycle_context_count": len(CANDIDATE_TICKERS),
                "lifecycle_excluded_count": 0,
                "current_context_count": len(CANDIDATE_TICKERS),
                "exact_session_close_count": len(CANDIDATE_TICKERS),
            },
            "core_candidate_coverage": core_coverage,
            "outputs": {"scored_latest.csv": record(scored_latest)},
        },
    )
    selector = root / "selector.json"
    write_json(
        selector,
        {
            "status": gate.SELECTOR_STATUS,
            "selector_no_write_passed": True,
            "valuation_price_cutoff_date": DATE,
            "same_close_selector_recomputed": True,
            "timestamp_contract": timestamp,
            "source_inputs": {
                "score_stack_manifest": record(score),
                "decision_manifest": record(decision),
                "price_manifest": record(price),
            },
            "outputs": {
                "advisory_policy_projection": record(projection),
                "marked_official_advisory_comparison": record(comparison),
            },
        },
    )
    risk_rows = root / "candidate_risk.csv"
    pd.DataFrame(
        [
            {"ticker": "NEW", "risk_state": "NORMAL"},
            {"ticker": "RISKY", "risk_state": "ALERT"},
        ]
    ).to_csv(risk_rows, index=False)
    risk = root / "risk.json"
    write_json(
        risk,
        {
            "status": "READY_CANDIDATE_RISK_REVIEW_ONLY",
            "candidate_risk_watch_passed": True,
            "as_of_date": DATE,
            "available_from": DECISION_TIME,
            "outputs": {"candidate_risk_watch": record(risk_rows)},
        },
    )
    producer = root / "producer.json"
    write_json(
        producer,
        {
            "schema_version": "run287-exact-packet-producer-v1",
            "status": "READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY",
            "exact_packet_ready": True,
            "valuation_price_cutoff_date": DATE,
            "selector_manifest": record(selector),
            "candidate_risk_summary": record(risk),
            "source_inputs": {"crisis_manifest": record(crisis)},
        },
    )
    freshness_snapshot = root / "freshness_snapshot.json"
    restored_scored_latest = root / "restored_scored_latest.csv"
    scored_candidate_frame().head(1).to_csv(restored_scored_latest, index=False)
    diagnostic_coverage, diagnostic_blockers = (
        gate.core_candidate_coverage_for_path(
            restored_scored_latest,
            minimum_ratio=0.0,
        )
    )
    assert not diagnostic_blockers
    assert diagnostic_coverage["required_for_target_mutation"] is False
    identity = {
        "source_run_id": SOURCE_RUN_ID,
        "source_commit_sha": SOURCE_COMMIT_SHA,
        "source_branch": SOURCE_BRANCH,
        "source_artifact_name": SOURCE_ARTIFACT_NAME,
    }
    write_json(
        freshness_snapshot,
        {
            "schema_version": gate.FRESHNESS_SNAPSHOT_SCHEMA_VERSION,
            **identity,
            "core_candidate_coverage": diagnostic_coverage,
            "files": [
                {
                    **record(restored_scored_latest),
                    "exists": True,
                }
            ],
        },
    )
    freshness_status = root / "freshness_status.json"
    write_json(
        freshness_status,
        {
            "schema_version": gate.FRESHNESS_SCHEMA_VERSION,
            "status": "pass",
            "asof_date": DATE,
            "selection_allowed": True,
            "blockers": [],
            "source_context": "daily_operating_refresh",
            "freshness_contract_non_fatal": False,
            **identity,
            "core_candidate_coverage": diagnostic_coverage,
            "outputs": {
                "data_snapshot_manifest_json": str(freshness_snapshot),
            },
        },
    )
    return argparse.Namespace(
        producer_status=str(producer),
        freshness_status=str(freshness_status),
        freshness_snapshot_manifest=str(freshness_snapshot),
        expected_source_run_id=SOURCE_RUN_ID,
        expected_source_commit_sha=SOURCE_COMMIT_SHA,
        expected_source_branch=SOURCE_BRANCH,
        expected_source_artifact_name=SOURCE_ARTIFACT_NAME,
        valuation_date=DATE,
        output_dir=str(root / "out"),
    )


def refresh_producer(root: Path) -> None:
    producer_path = root / "producer.json"
    producer = json.loads(producer_path.read_text(encoding="utf-8"))
    producer["selector_manifest"] = record(root / "selector.json")
    producer["candidate_risk_summary"] = record(root / "risk.json")
    producer.setdefault("source_inputs", {})["crisis_manifest"] = record(
        root / "crisis.json"
    )
    write_json(producer_path, producer)


def test_ready_deterministic_risk_intersection_and_cost_contract() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="same_close_", dir=scratch) as temp:
        root = Path(temp)
        args = fixture(root)
        first = gate.build(args)
        assert first["status"] == gate.READY_STATUS
        assert first["same_close_selector_recomputed"] is True
        main_path = Path(first["outputs"]["main_target_book"]["path"])
        conc_path = Path(first["outputs"]["concentrated_target_book"]["path"])
        main = pd.read_csv(main_path)
        conc = pd.read_csv(conc_path)
        assert main[RESERVE_REASON_SOURCE_HASH_FIELD].nunique() == 1
        assert len(str(main[RESERVE_REASON_SOURCE_HASH_FIELD].iloc[0])) == 64
        assert conc[RESERVE_REASON_SOURCE_HASH_FIELD].nunique() == 1
        assert abs(float(main.loc[main["ticker"].eq("OLD"), "weight"].iloc[0]) - 0.50) < 1e-12
        assert abs(float(main.loc[main["ticker"].eq("CASH"), "weight"].iloc[0]) - 0.20) < 1e-12
        assert "RISKY" not in set(conc["ticker"])
        assert abs(float(conc.loc[conc["ticker"].eq("CASH"), "weight"].iloc[0]) - 0.30) < 1e-12
        assert main["order_eligible_close_date"].eq("2026-07-17").all()
        cost = first["turnover_and_cost"]["main"]
        assert cost["cash_included_in_turnover"] is True
        assert cost["cash_excluded_from_fees"] is True
        hashes_before = {name: sha(Path(row["path"])) for name, row in first["outputs"].items()}
        second = gate.build(args)
        hashes_after = {name: sha(Path(row["path"])) for name, row in second["outputs"].items()}
        assert hashes_before == hashes_after
        assert first["target_hashes"] == second["target_hashes"]
        assert first["source_inputs"]["freshness_status"]["sha256"] == sha(
            root / "freshness_status.json"
        )
        assert (
            first["selector_input_hashes"]["freshness_snapshot_manifest"]
            == sha(root / "freshness_snapshot.json")
        )


def test_revaluation_only_or_inactive_head_writes_no_target() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="same_close_block_", dir=scratch) as temp:
        root = Path(temp)
        args = fixture(root)
        selector_path = root / "selector.json"
        selector = json.loads(selector_path.read_text(encoding="utf-8"))
        selector["timestamp_contract"]["same_close_selector_recomputed"] = False
        write_json(selector_path, selector)
        refresh_producer(root)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert blocked["target_book_file_written"] is False
        assert not list(Path(args.output_dir).glob("same_close_*_target_book.csv"))

    with tempfile.TemporaryDirectory(prefix="same_close_zero_", dir=scratch) as temp:
        root = Path(temp)
        args = fixture(root)
        activity = pd.read_csv(root / "prediction_activity.csv")
        activity["nonzero_nonconstant_pass"] = False
        activity.to_csv(root / "prediction_activity.csv", index=False)
        score = json.loads((root / "score.json").read_text(encoding="utf-8"))
        score["outputs"]["prediction_activity_audit"] = record(root / "prediction_activity.csv")
        write_json(root / "score.json", score)
        selector = json.loads((root / "selector.json").read_text(encoding="utf-8"))
        selector["source_inputs"]["score_stack_manifest"] = record(root / "score.json")
        write_json(root / "selector.json", selector)
        refresh_producer(root)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert "prediction_head_inactive" in blocked["contract_failures"]
        assert not list(Path(args.output_dir).glob("same_close_*_target_book.csv"))


def test_forged_or_legacy_producer_marker_writes_no_target() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="same_close_producer_contract_", dir=scratch
    ) as temp:
        root = Path(temp)
        for case, field, value, expected_failure in (
            (
                "legacy_schema",
                "schema_version",
                "run287-exact-packet-producer-v0",
                "producer_schema_mismatch",
            ),
            (
                "blocked_status",
                "status",
                "BLOCKED_EXACT_PACKET_PRODUCER",
                "producer_status_not_ready",
            ),
        ):
            case_root = root / case
            case_root.mkdir(parents=True, exist_ok=True)
            args = fixture(case_root)
            producer_path = Path(args.producer_status)
            producer = json.loads(producer_path.read_text(encoding="utf-8"))
            producer[field] = value
            producer["exact_packet_ready"] = True
            write_json(producer_path, producer)
            blocked = gate.build(args)
            assert blocked["status"] == gate.BLOCKED_STATUS
            assert expected_failure in blocked["contract_failures"]
            assert blocked["target_book_file_written"] is False
            assert not list(
                Path(args.output_dir).glob("same_close_*_target_book.csv")
            )


def test_future_feature_and_date_mismatch_fail_closed() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="same_close_future_", dir=scratch) as temp:
        root = Path(temp)
        args = fixture(root)
        decision = json.loads((root / "decision.json").read_text(encoding="utf-8"))
        decision["feature_available_from"] = "2026-07-17T05:00:00+00:00"
        decision["valuation_price_cutoff_date"] = "2026-07-15"
        write_json(root / "decision.json", decision)
        selector = json.loads((root / "selector.json").read_text(encoding="utf-8"))
        selector["source_inputs"]["decision_manifest"] = record(root / "decision.json")
        write_json(root / "selector.json", selector)
        refresh_producer(root)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert "future_or_invalid_feature_available_from" in blocked["contract_failures"]
        assert "date_mismatch:decision" in blocked["contract_failures"]


def test_rejected_crisis_policy_is_shadow_only() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="same_close_crisis_shadow_", dir=scratch) as temp:
        root = Path(temp)
        args = fixture(root)
        crisis_rows = pd.read_csv(root / "current_crisis_state.csv")
        crisis_rows["crisis_state"] = "CRISIS"
        crisis_rows["crisis_score"] = 0.90
        crisis_rows.to_csv(root / "current_crisis_state.csv", index=False)
        crisis = json.loads((root / "crisis.json").read_text(encoding="utf-8"))
        crisis["outputs"]["current_crisis_state"] = record(
            root / "current_crisis_state.csv"
        )
        write_json(root / "crisis.json", crisis)
        refresh_producer(root)
        result = gate.build(args)
        assert result["status"] == gate.READY_STATUS
        assert result["crisis_policy_applied_to_operating_target"] is False
        operating = pd.read_csv(result["outputs"]["main_target_book"]["path"])
        shadow = pd.read_csv(
            result["outputs"]["main_crisis_shadow_target_book"]["path"]
        )
        assert abs(float(operating.loc[operating["ticker"].ne("CASH"), "weight"].sum()) - 0.80) < 1e-12
        assert abs(float(shadow.loc[shadow["ticker"].ne("CASH"), "weight"].sum()) - 0.50) < 1e-12
        assert result["crisis_policy_promotion_status"] == "REJECTED_HISTORICAL_FIXED_BOOK"


def test_blocked_or_mismatched_freshness_writes_no_target() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="same_close_freshness_", dir=scratch) as temp:
        root = Path(temp)
        args = fixture(root)
        status_path = root / "freshness_status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["status"] = "blocked"
        status["selection_allowed"] = False
        status["blockers"] = ["core candidate coverage below floor"]
        write_json(status_path, status)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert "freshness_status_not_pass" in blocked["contract_failures"]
        assert "freshness_selection_not_allowed" in blocked["contract_failures"]
        assert not list(Path(args.output_dir).glob("same_close_*_target_book.csv"))

    with tempfile.TemporaryDirectory(prefix="same_close_freshness_hash_", dir=scratch) as temp:
        root = Path(temp)
        args = fixture(root)
        snapshot_path = root / "freshness_snapshot.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot["core_candidate_coverage"]["coverage_ratio"] = 0.50
        write_json(snapshot_path, snapshot)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert (
            "freshness_core_candidate_coverage_snapshot_mismatch"
            in blocked["contract_failures"]
        )
        assert not list(Path(args.output_dir).glob("same_close_*_target_book.csv"))

    with tempfile.TemporaryDirectory(
        prefix="same_close_freshness_source_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        restored = pd.read_csv(root / "restored_scored_latest.csv")
        restored.loc[0, "px"] = 101.0
        restored.to_csv(root / "restored_scored_latest.csv", index=False)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert "freshness_source_00_fingerprint" in blocked["contract_failures"]
        assert not list(Path(args.output_dir).glob("same_close_*_target_book.csv"))


def test_current_score_coverage_metadata_and_universe_fail_closed() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="same_close_legacy_score_schema_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        price_path = root / "price_manifest.json"
        price = json.loads(price_path.read_text(encoding="utf-8"))
        price["schema_version"] = "run287-scored-latest-refresh-v3"
        write_json(price_path, price)
        bind_price_manifest(root, recompute_core=False)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert "current_score_manifest_schema" in blocked["contract_failures"]

    with tempfile.TemporaryDirectory(
        prefix="same_close_forged_coverage_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        price_path = root / "price_manifest.json"
        price = json.loads(price_path.read_text(encoding="utf-8"))
        price["core_candidate_coverage"]["coverage_ratio"] = 1.0
        price["core_candidate_coverage"]["complete_row_count"] = 100
        price["core_candidate_coverage"]["invalid_row_count"] = 0
        price["core_candidate_coverage"]["invalid_by_column"] = {}
        write_json(price_path, price)
        bind_price_manifest(root, recompute_core=False)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert (
            "current_core_candidate_coverage_manifest_mismatch"
            in blocked["contract_failures"]
        )

    with tempfile.TemporaryDirectory(
        prefix="same_close_below_coverage_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        scored = pd.read_csv(root / "scored_latest.csv")
        scored.loc[2, "mom_12m"] = float("nan")
        scored.to_csv(root / "scored_latest.csv", index=False)
        bind_price_manifest(root)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert any(
            failure.startswith(
                "current_core_candidate_coverage:core candidate coverage 0.970000"
            )
            for failure in blocked["contract_failures"]
        )
        assert "current_core_candidate_coverage_not_passed" in blocked[
            "contract_failures"
        ]

    with tempfile.TemporaryDirectory(
        prefix="same_close_ticker_substitution_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        scored = pd.read_csv(root / "scored_latest.csv")
        scored.loc[scored["ticker"].eq("OLD"), "ticker"] = "SUBSTITUTED"
        scored.to_csv(root / "scored_latest.csv", index=False)
        bind_price_manifest(root)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert (
            "current_core_candidate_coverage:core candidate ticker set does not "
            "match the expected universe"
        ) in blocked["contract_failures"]
        assert (
            "current_core_candidate_decision_ticker_set"
            in blocked["contract_failures"]
        )

    with tempfile.TemporaryDirectory(
        prefix="same_close_future_score_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        price_path = root / "price_manifest.json"
        price = json.loads(price_path.read_text(encoding="utf-8"))
        price["score_available_from"] = "2026-07-17T04:16:00+00:00"
        write_json(price_path, price)
        bind_price_manifest(root, recompute_core=False)
        blocked = gate.build(args)
        assert blocked["status"] == gate.BLOCKED_STATUS
        assert "current_score_availability_contract" in blocked["contract_failures"]


def test_success_then_block_clears_only_materialized_outputs() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="same_close_success_then_block_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        ready = gate.build(args)
        assert ready["status"] == gate.READY_STATUS
        output_dir = Path(args.output_dir)
        ledger_sentinel = output_dir / "paper_ledger.json"
        canonical_sentinel = output_dir / "canonical_target.csv"
        ledger_sentinel.write_bytes(b'{"accepted_state":"preserve"}\n')
        canonical_sentinel.write_bytes(b"ticker,weight\nKEEP,1.0\n")
        sentinels = {
            path: (sha(path), path.read_bytes())
            for path in (ledger_sentinel, canonical_sentinel)
        }

        status_path = root / "freshness_status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["status"] = "blocked"
        status["selection_allowed"] = False
        status["blockers"] = ["forced regression blocker"]
        write_json(status_path, status)
        blocked = gate.build(args)

        assert blocked["status"] == gate.BLOCKED_STATUS
        assert blocked["target_book_file_written"] is False
        assert (output_dir / "status.json").is_file()
        for name in gate.MATERIALIZED_OUTPUT_NAMES:
            if name != "status.json":
                assert not (output_dir / name).exists()
        for path, (expected_sha, expected_bytes) in sentinels.items():
            assert sha(path) == expected_sha
            assert path.read_bytes() == expected_bytes


def test_projection_change_after_read_blocks_target_publication() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="same_close_projection_race_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        projection_path = root / "projection.csv"
        original = gate.turnover_summary
        changed = False

        def mutate_after_read(*call_args, **call_kwargs):
            nonlocal changed
            if not changed:
                projection_path.write_bytes(projection_path.read_bytes() + b"\n")
                changed = True
            return original(*call_args, **call_kwargs)

        gate.turnover_summary = mutate_after_read
        try:
            blocked = gate.build(args)
        finally:
            gate.turnover_summary = original

        assert blocked["status"] == gate.BLOCKED_STATUS
        assert (
            "input_changed_before_target_write:selector_projection"
            in blocked["contract_failures"]
        )
        assert not list(Path(args.output_dir).glob("same_close_*_target_book.csv"))


def test_projection_change_during_target_write_blocks_ready_marker() -> None:
    scratch = ROOT / "_tmp_tests"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="same_close_publish_race_", dir=scratch
    ) as temp:
        root = Path(temp)
        args = fixture(root)
        projection_path = root / "projection.csv"
        original = pd.DataFrame.to_csv
        changed = False

        def mutate_during_write(frame, path_or_buf=None, *call_args, **call_kwargs):
            nonlocal changed
            result = original(frame, path_or_buf, *call_args, **call_kwargs)
            if (
                not changed
                and path_or_buf is not None
                and Path(path_or_buf).name == "same_close_main_target_book.csv"
            ):
                projection_path.write_bytes(
                    projection_path.read_bytes() + b"\n"
                )
                changed = True
            return result

        pd.DataFrame.to_csv = mutate_during_write
        try:
            blocked = gate.build(args)
        finally:
            pd.DataFrame.to_csv = original

        assert blocked["status"] == gate.BLOCKED_STATUS
        assert (
            "input_changed_before_target_publish:selector_projection"
            in blocked["contract_failures"]
        )
        assert not list(Path(args.output_dir).glob("same_close_*_target_book.csv"))
        assert not (Path(args.output_dir) / "decision_snapshot.json").exists()


def main() -> int:
    test_ready_deterministic_risk_intersection_and_cost_contract()
    test_revaluation_only_or_inactive_head_writes_no_target()
    test_forged_or_legacy_producer_marker_writes_no_target()
    test_future_feature_and_date_mismatch_fail_closed()
    test_rejected_crisis_policy_is_shadow_only()
    test_blocked_or_mismatched_freshness_writes_no_target()
    test_current_score_coverage_metadata_and_universe_fail_closed()
    test_success_then_block_clears_only_materialized_outputs()
    test_projection_change_after_read_blocks_target_publication()
    test_projection_change_during_target_write_blocks_ready_marker()
    print("run287_same_close_target_books_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
