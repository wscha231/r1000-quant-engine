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


DATE = "2026-07-16"
DECISION_TIME = "2026-07-17T04:15:00+00:00"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


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
            "ticker": ["OLD", "NEW", "KEEP", "RISKY"],
            "market_breadth_above_ma200": [0.62] * 4,
            "market_breadth_above_ma150": [0.67] * 4,
            "market_sector_participation": [0.58] * 4,
            "market_leadership_narrowing": [0.20] * 4,
        }
    ).to_parquet(selection_context, index=False)
    write_json(
        decision,
        {
            "status": "READY_COMPLETE_CURRENT_DECISION_FRAME",
            "valuation_price_cutoff_date": DATE,
            "decision_time_utc": DECISION_TIME,
            "feature_available_from": "2026-07-17T04:10:00+00:00",
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
            "status": "READY_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY",
            "exact_packet_ready": True,
            "valuation_price_cutoff_date": DATE,
            "selector_manifest": record(selector),
            "candidate_risk_summary": record(risk),
            "source_inputs": {"crisis_manifest": record(crisis)},
        },
    )
    return argparse.Namespace(
        producer_status=str(producer),
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


def main() -> int:
    test_ready_deterministic_risk_intersection_and_cost_contract()
    test_revaluation_only_or_inactive_head_writes_no_target()
    test_future_feature_and_date_mismatch_fail_closed()
    test_rejected_crisis_policy_is_shadow_only()
    print("run287_same_close_target_books_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
