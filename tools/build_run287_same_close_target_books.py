#!/usr/bin/env python3
"""Materialize fail-closed Run287 paper targets from one exact-close packet.

This is the boundary between advisory selection and the forward paper ledger.
It accepts only a hash-pinned selector plus candidate-risk packet for one
completed NYSE session.  Restored historical targets are never accepted as a
substitute for a freshly recomputed selector.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run287_crisis_policy import (  # noqa: E402
    SCHEMA_VERSION as CRISIS_POLICY_SCHEMA_VERSION,
    adapt_crisis_state,
    apply_selective_defense,
    availability_records,
    component_availability,
)
from tools.reserve_asset_policy import (  # noqa: E402
    DEFAULT_CURRENT_PAPER_MODE,
    RESERVE_REASONS,
    RESERVE_REASON_SOURCE_HASH_FIELD,
    reserve_reason_reconciliation,
    resolve_reserve_asset_policy,
)


SCHEMA_VERSION = "run287-same-close-target-books-v1"
READY_STATUS = "READY_SAME_CLOSE_PAPER_TARGETS"
BLOCKED_STATUS = "BLOCKED_SAME_CLOSE_SELECTOR"
SELECTOR_STATUS = "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED"
SCORE_STATUS = "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING"
ACTIVE_HEADS = {
    "pred_lin_ret",
    "pred_lin_p",
    "pred_future_winner_ret",
    "pred_future_winner_p",
    "pred_cat_ret",
    "pred_cat_p",
}
SCENARIOS = {
    "main": "prior_hold_transition_bridge",
    "concentrated": "strict_registered_current",
}
TIMESTAMP_FIELDS = (
    "signal_source_date",
    "feature_as_of_date",
    "valuation_close_date",
    "selector_decision_time_utc",
    "target_effective_date",
    "order_eligible_close_date",
    "same_close_selector_recomputed",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": ""}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def resolve_path(raw: str, owner: Path) -> Path:
    direct = Path(raw)
    if direct.exists():
        return direct.resolve()
    relative = owner.parent / direct
    if not direct.is_absolute() and relative.exists():
        return relative.resolve()
    normalized = raw.replace("\\", "/")
    for anchor in ("outputs/", "cache_prices/", "data_pit/", "data_raw/"):
        if anchor in normalized:
            candidate = REPO_ROOT / normalized[normalized.index(anchor) :]
            if candidate.exists():
                return candidate.resolve()
    return direct


def verified_record(
    owner: Path, record: Mapping[str, Any], label: str
) -> tuple[Path, dict[str, Any]]:
    path = resolve_path(str(record.get("path") or ""), owner)
    expected = str(record.get("sha256") or "").lower()
    audit = fingerprint(path)
    audit.update(
        label=label,
        expected_sha256=expected,
        hash_matches=bool(expected and audit.get("sha256") == expected),
    )
    if audit["hash_matches"] is not True:
        raise ValueError(f"hash mismatch: {label}")
    return path, audit


def verified_output(
    owner: Path, manifest: Mapping[str, Any], key: str
) -> tuple[Path, dict[str, Any]]:
    return verified_record(owner, (manifest.get("outputs") or {}).get(key) or {}, key)


def iso_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else pd.Timestamp(parsed).date().isoformat()


def utc_timestamp(value: Any) -> pd.Timestamp:
    return pd.to_datetime(value, errors="coerce", utc=True)


def next_nyse_session(valuation_date: str) -> str:
    start = pd.Timestamp(valuation_date).normalize()
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=start, end_date=start + pd.Timedelta(days=10)
    )
    sessions = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    future = sessions[sessions > start]
    if future.empty:
        raise ValueError("next NYSE session unavailable")
    return pd.Timestamp(future[0]).date().isoformat()


def canonical_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def target_hash(frame: pd.DataFrame) -> str:
    rows = [
        {"ticker": str(row.ticker), "target_weight": round(float(row.weight), 12)}
        for row in frame.sort_values("ticker").itertuples(index=False)
    ]
    return canonical_hash({"schema": "run287-forward-target-v1", "rows": rows})


def timestamp_contract(
    *,
    valuation_date: str,
    decision_time: pd.Timestamp,
) -> dict[str, Any]:
    return {
        "signal_source_date": valuation_date,
        "feature_as_of_date": valuation_date,
        "valuation_close_date": valuation_date,
        "selector_decision_time_utc": decision_time.isoformat(),
        "target_effective_date": valuation_date,
        "order_eligible_close_date": next_nyse_session(valuation_date),
        "same_close_selector_recomputed": True,
    }


def validate_timestamp_contract(
    *,
    selector: Mapping[str, Any],
    score: Mapping[str, Any],
    decision: Mapping[str, Any],
    candidate_risk: Mapping[str, Any],
    valuation_date: str,
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    decision_time = utc_timestamp(decision.get("decision_time_utc"))
    available = utc_timestamp(decision.get("feature_available_from"))
    if pd.isna(decision_time) or pd.isna(available) or available > decision_time:
        failures.append("future_or_invalid_feature_available_from")
        decision_time = pd.Timestamp(f"{valuation_date}T23:59:59Z")
    selector_contract = selector.get("timestamp_contract") or {}
    selector_time = utc_timestamp(selector_contract.get("selector_decision_time_utc"))
    if pd.isna(selector_time) or selector_time < decision_time:
        failures.append("selector_decision_time_invalid")
        selector_time = decision_time
    contract = timestamp_contract(
        valuation_date=valuation_date, decision_time=pd.Timestamp(selector_time)
    )
    for field in TIMESTAMP_FIELDS:
        expected = contract[field]
        actual = selector_contract.get(field)
        if field == "same_close_selector_recomputed":
            if actual is not True:
                failures.append(f"selector_timestamp:{field}")
        elif iso_date(actual) != iso_date(expected) and field != "selector_decision_time_utc":
            failures.append(f"selector_timestamp:{field}")
        elif field == "selector_decision_time_utc" and utc_timestamp(actual) != selector_time:
            failures.append(f"selector_timestamp:{field}")
    date_sources = {
        "selector": selector.get("valuation_price_cutoff_date"),
        "score": score.get("valuation_price_cutoff_date"),
        "decision": decision.get("valuation_price_cutoff_date"),
        "candidate_risk": candidate_risk.get("as_of_date"),
    }
    for label, value in date_sources.items():
        if iso_date(value) != valuation_date:
            failures.append(f"date_mismatch:{label}")
    risk_available = utc_timestamp(candidate_risk.get("available_from"))
    if pd.isna(risk_available) or risk_available > selector_time:
        failures.append("candidate_risk_not_available_at_decision")
    if score.get("fresh_prediction_passthrough_verified") is not True:
        failures.append("fresh_prediction_passthrough_not_verified")
    if score.get("stale_prediction_columns_removed_before_join") is not True:
        failures.append("stale_prediction_columns_not_removed")
    return contract, failures


def activity_gate(
    score_path: Path, score: Mapping[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    failures: list[str] = []
    try:
        activity_path, audit = verified_output(score_path, score, "prediction_activity_audit")
        activity = pd.read_csv(activity_path, low_memory=False)
    except Exception as exc:
        return pd.DataFrame(), {}, [f"prediction_activity:{type(exc).__name__}:{exc}"]
    observed = set(activity.get("prediction", pd.Series(dtype=str)).astype(str))
    if observed != ACTIVE_HEADS:
        failures.append("prediction_head_set")
    if len(activity) != len(ACTIVE_HEADS):
        failures.append("prediction_head_count")
    passed = activity.get("nonzero_nonconstant_pass", pd.Series(dtype=bool))
    if len(passed) != len(activity) or not bool(passed.fillna(False).astype(bool).all()):
        failures.append("prediction_head_inactive")
    for column in ("row_count", "finite_count", "unique_count"):
        if column not in activity.columns:
            failures.append(f"prediction_activity_column:{column}")
    if {"row_count", "finite_count"}.issubset(activity.columns):
        rows = pd.to_numeric(activity["row_count"], errors="coerce")
        finite = pd.to_numeric(activity["finite_count"], errors="coerce")
        if rows.isna().any() or not bool(rows.eq(finite).all()):
            failures.append("prediction_head_nonfinite")
    return activity, audit, failures


def canonical_crisis_context(
    *,
    crisis_row: Mapping[str, Any],
    selection_context: pd.DataFrame,
    decision_time: Any,
    available_from: Any,
) -> dict[str, Any]:
    values = dict(crisis_row)
    for field in (
        "market_breadth_above_ma200",
        "market_breadth_above_ma150",
        "market_sector_participation",
        "market_leadership_narrowing",
    ):
        if field in selection_context.columns:
            observed = pd.to_numeric(selection_context[field], errors="coerce").dropna()
            if not observed.empty:
                values[field] = float(observed.median())
    availability = component_availability(
        values,
        decision_time=decision_time,
        available_from=available_from,
    )
    missing_critical = [
        row.component
        for row in availability
        if row.critical and (not row.available or not row.fresh)
    ]
    source_state = adapt_crisis_state(
        values.get("crisis_state"), values.get("reentry_stage")
    )
    state = "DEGRADED_DATA" if missing_critical else source_state
    def numeric(name: str, default: float) -> float:
        value = pd.to_numeric(values.get(name), errors="coerce")
        return default if pd.isna(value) else float(value)

    return {
        "schema_version": CRISIS_POLICY_SCHEMA_VERSION,
        "state": state,
        "source_state": source_state,
        "crisis_score": numeric("crisis_score", 0.0),
        "reentry_score": numeric("reentry_score", 0.0),
        "reentry_multiplier": numeric("reentry_multiplier", 1.0),
        "component_availability": availability_records(availability),
        "missing_critical_components": missing_critical,
        "future_labels_excluded": True,
        "universe_breadth_source": "decision_selection_context_cross_section",
    }


def apply_risk_intersection(
    selected: pd.DataFrame,
    comparison: pd.DataFrame,
    candidate_risk: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    out = selected.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out["advisory_weight"], errors="coerce")
    out = out[["ticker", "weight"]].copy()
    risk = candidate_risk.copy()
    if not risk.empty:
        risk["ticker"] = risk["ticker"].astype(str).str.upper().str.strip()
        risk = risk.drop_duplicates("ticker", keep=False).set_index("ticker")
    comp = comparison.copy()
    comp["ticker"] = comp["ticker"].astype(str).str.upper().str.strip()
    comp = comp.drop_duplicates("ticker", keep=False).set_index("ticker")
    actions: list[dict[str, Any]] = []
    released = 0.0
    for index, row in out.loc[out["ticker"].ne("CASH")].iterrows():
        ticker = str(row["ticker"])
        proposed = float(row["weight"])
        detail = comp.loc[ticker] if ticker in comp.index else pd.Series(dtype=object)
        marked = float(pd.to_numeric(detail.get("marked_weight", 0.0), errors="coerce") or 0.0)
        is_new = marked <= 1e-12
        held_state = str(detail.get("held_risk_state") or "").upper()
        held_action = str(detail.get("held_risk_advisory_action") or "").upper()
        allowed = proposed
        reason = "UNCHANGED"
        candidate_state = ""
        if is_new:
            if ticker not in risk.index:
                allowed = 0.0
                reason = "NEW_ENTRY_MISSING_CANDIDATE_RISK"
            else:
                candidate_state = str(risk.loc[ticker].get("risk_state") or "").upper()
                if candidate_state != "NORMAL":
                    allowed = 0.0
                    reason = f"NEW_ENTRY_{candidate_state or 'UNKNOWN'}_VETO"
        elif proposed > marked + 1e-12 and (
            held_state in {"ALERT", "WATCH"} or "FREEZE_INCREMENTAL_BUY" in held_action
        ):
            allowed = min(proposed, marked)
            reason = "HELD_INCREMENTAL_BUY_VETO"
        released += max(0.0, proposed - allowed)
        out.loc[index, "weight"] = allowed
        actions.append(
            {
                "ticker": ticker,
                "proposed_weight": proposed,
                "marked_weight": marked,
                "final_weight": allowed,
                "candidate_risk_state": candidate_state,
                "held_risk_state": held_state,
                "action": reason,
            }
        )
    cash_mask = out["ticker"].eq("CASH")
    if cash_mask.any():
        out.loc[cash_mask, "weight"] = float(out.loc[cash_mask, "weight"].sum()) + released
        out = out.drop_duplicates("ticker", keep="first")
    else:
        out = pd.concat(
            [out, pd.DataFrame([{"ticker": "CASH", "weight": released}])],
            ignore_index=True,
        )
    out = out.loc[out["weight"].gt(1e-12)].copy()
    if not math.isclose(float(out["weight"].sum()), 1.0, abs_tol=1e-9):
        raise ValueError("risk-intersected weight conservation failure")
    return out.sort_values(["weight", "ticker"], ascending=[False, True]).reset_index(drop=True), actions


def turnover_summary(
    target: pd.DataFrame, comparison: pd.DataFrame, portfolio: str
) -> dict[str, Any]:
    marked = comparison[["ticker", "marked_weight"]].copy()
    marked["ticker"] = marked["ticker"].astype(str).str.upper().str.strip()
    marked["marked_weight"] = pd.to_numeric(marked["marked_weight"], errors="coerce").fillna(0.0)
    merged = marked.merge(target, on="ticker", how="outer").fillna(0.0)
    merged["delta"] = merged["weight"] - merged["marked_weight"]
    assets = merged["ticker"].ne("CASH")
    asset_abs = float(merged.loc[assets, "delta"].abs().sum())
    row: dict[str, Any] = {
        "portfolio_kind": portfolio,
        "cash_included_in_turnover": True,
        "cash_excluded_from_fees": True,
        "one_way_turnover_vs_marked": 0.5 * float(merged["delta"].abs().sum()),
        "asset_absolute_trade_weight": asset_abs,
        "cash_delta_vs_marked": float(merged.loc[~assets, "delta"].sum()),
    }
    for bps in (25, 50, 100):
        row[f"estimated_cost_drag_fraction_{bps}bps"] = asset_abs * bps / 10000.0
    return row


def blocked_payload(
    *, output_dir: Path, valuation_date: str, failures: list[str], inputs: Mapping[str, Any]
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "valuation_close_date": valuation_date,
        "same_close_selector_recomputed": False,
        "target_book_file_written": False,
        "orders_generated": False,
        "contract_failures": failures,
        "source_inputs": dict(inputs),
        "research_only": True,
        "paper_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
    }
    write_json(output_dir / "status.json", payload)
    return payload


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    valuation_date = pd.Timestamp(args.valuation_date).date().isoformat()
    producer_path = repo_path(args.producer_status)
    contract_path = repo_path(
        getattr(args, "contract", "docs/run287_same_close_target_contract.json")
    )
    inputs: dict[str, Any] = {
        "producer_status": fingerprint(producer_path),
        "same_close_contract": fingerprint(contract_path),
    }
    failures: list[str] = []
    try:
        declared_contract = read_json(contract_path)
    except Exception as exc:
        declared_contract = {}
        failures.append(f"same_close_contract:{type(exc).__name__}:{exc}")
    if declared_contract.get("schema_version") != "run287-same-close-target-contract-v1":
        failures.append("same_close_contract_schema")
    if declared_contract.get("selector_scenarios") != SCENARIOS:
        failures.append("same_close_contract_scenarios")
    if not producer_path.is_file():
        return blocked_payload(
            output_dir=output_dir,
            valuation_date=valuation_date,
            failures=["producer_status_missing"],
            inputs=inputs,
        )
    producer = read_json(producer_path)
    if producer.get("exact_packet_ready") is not True:
        failures.append("exact_packet_not_ready")
    if iso_date(producer.get("valuation_price_cutoff_date")) != valuation_date:
        failures.append("producer_date_mismatch")
    try:
        selector_path, inputs["selector_manifest"] = verified_record(
            producer_path, producer.get("selector_manifest") or {}, "selector_manifest"
        )
        risk_path, inputs["candidate_risk_summary"] = verified_record(
            producer_path,
            producer.get("candidate_risk_summary") or {},
            "candidate_risk_summary",
        )
        selector = read_json(selector_path)
        risk_summary = read_json(risk_path)
        projection_path, inputs["selector_projection"] = verified_output(
            selector_path, selector, "advisory_policy_projection"
        )
        comparison_path, inputs["selector_comparison"] = verified_output(
            selector_path, selector, "marked_official_advisory_comparison"
        )
        risk_rows_path, inputs["candidate_risk_rows"] = verified_output(
            risk_path, risk_summary, "candidate_risk_watch"
        )
        score_path, inputs["score_manifest"] = verified_record(
            selector_path,
            (selector.get("source_inputs") or {}).get("score_stack_manifest") or {},
            "score_stack_manifest",
        )
        decision_path, inputs["decision_manifest"] = verified_record(
            selector_path,
            (selector.get("source_inputs") or {}).get("decision_manifest") or {},
            "decision_manifest",
        )
        score = read_json(score_path)
        decision = read_json(decision_path)
        crisis_path, inputs["crisis_manifest"] = verified_record(
            producer_path,
            (producer.get("source_inputs") or {}).get("crisis_manifest") or {},
            "crisis_manifest",
        )
        crisis = read_json(crisis_path)
        crisis_row_path, inputs["current_crisis_state"] = verified_output(
            crisis_path, crisis, "current_crisis_state"
        )
        selection_context_path, inputs["selection_context"] = verified_output(
            decision_path, decision, "selection_context"
        )
    except Exception as exc:
        failures.append(f"input_contract:{type(exc).__name__}:{exc}")
        return blocked_payload(
            output_dir=output_dir,
            valuation_date=valuation_date,
            failures=failures,
            inputs=inputs,
        )
    if selector.get("status") != SELECTOR_STATUS or selector.get("selector_no_write_passed") is not True:
        failures.append("selector_not_ready")
    if risk_summary.get("candidate_risk_watch_passed") is not True:
        failures.append("candidate_risk_not_ready")
    if score.get("status") != SCORE_STATUS:
        failures.append("score_stack_not_ready")
    if crisis.get("status") != "READY_CURRENT_CRISIS_STATE_NONSELECTING":
        failures.append("crisis_state_not_ready")
    if iso_date(crisis.get("valuation_price_cutoff_date")) != valuation_date:
        failures.append("crisis_state_date_mismatch")
    if ((crisis.get("feature_contract") or {}).get("future_labels_used_for_state")) is not False:
        failures.append("crisis_future_label_contract")
    contract, contract_failures = validate_timestamp_contract(
        selector=selector,
        score=score,
        decision=decision,
        candidate_risk=risk_summary,
        valuation_date=valuation_date,
    )
    failures.extend(contract_failures)
    activity, activity_audit, activity_failures = activity_gate(score_path, score)
    if activity_audit:
        inputs["prediction_activity_audit"] = activity_audit
    failures.extend(activity_failures)
    projection = pd.read_csv(projection_path, low_memory=False)
    comparison = pd.read_csv(comparison_path, low_memory=False)
    risk_rows = pd.read_csv(risk_rows_path, low_memory=False)
    crisis_rows = pd.read_csv(crisis_row_path, low_memory=False)
    selection_context = pd.read_parquet(selection_context_path)
    required_projection = {"portfolio_kind", "scenario", "ticker", "advisory_weight"}
    required_comparison = {"portfolio_kind", "scenario", "ticker", "marked_weight"}
    if not required_projection.issubset(projection.columns):
        failures.append("projection_columns")
    if not required_comparison.issubset(comparison.columns):
        failures.append("comparison_columns")
    if failures:
        return blocked_payload(
            output_dir=output_dir,
            valuation_date=valuation_date,
            failures=sorted(set(failures)),
            inputs=inputs,
        )

    if len(crisis_rows) != 1:
        return blocked_payload(
            output_dir=output_dir,
            valuation_date=valuation_date,
            failures=["current_crisis_state_row_count"],
            inputs=inputs,
        )
    crisis_context = canonical_crisis_context(
        crisis_row=crisis_rows.iloc[0].to_dict(),
        selection_context=selection_context,
        decision_time=contract["selector_decision_time_utc"],
        available_from=decision.get("feature_available_from"),
    )

    targets: dict[str, pd.DataFrame] = {}
    crisis_shadow_targets: dict[str, pd.DataFrame] = {}
    risk_actions: dict[str, list[dict[str, Any]]] = {}
    crisis_actions: dict[str, list[dict[str, Any]]] = {}
    crisis_policy: dict[str, dict[str, Any]] = {}
    reserve_reconciliations: dict[str, dict[str, Any]] = {}
    reserve_policy = resolve_reserve_asset_policy(
        DEFAULT_CURRENT_PAPER_MODE,
        context="current_paper",
    )
    turnover: dict[str, dict[str, Any]] = {}
    for portfolio, scenario in SCENARIOS.items():
        selected = projection.loc[
            projection["portfolio_kind"].eq(portfolio)
            & projection["scenario"].eq(scenario)
        ].copy()
        detail = comparison.loc[
            comparison["portfolio_kind"].eq(portfolio)
            & comparison["scenario"].eq(scenario)
        ].copy()
        if selected.empty or detail.empty:
            failures.append(f"missing_scenario:{portfolio}:{scenario}")
            continue
        try:
            target, actions = apply_risk_intersection(selected, detail, risk_rows)
            evidence_columns = [
                column
                for column in (
                    "ticker",
                    "holding_state",
                    "leader_tier",
                    "alphaops_vnext_score",
                )
                if column in selected.columns
            ]
            evidence = detail.merge(
                selected[evidence_columns].drop_duplicates("ticker", keep="last"),
                on="ticker",
                how="outer",
            )
            crisis_shadow, selective_actions, policy_summary = apply_selective_defense(
                target,
                state=crisis_context["state"],
                portfolio_kind=portfolio,
                evidence=evidence,
            )
        except Exception as exc:
            failures.append(f"risk_or_crisis_policy:{portfolio}:{type(exc).__name__}:{exc}")
            continue
        for field, value in contract.items():
            target[field] = value
            crisis_shadow[field] = value
        target["canonical_crisis_state"] = crisis_context["state"]
        crisis_shadow["canonical_crisis_state"] = crisis_context["state"]
        for reason in RESERVE_REASONS:
            target[reason] = 0.0
            crisis_shadow[reason] = 0.0
            crisis_shadow.loc[crisis_shadow["ticker"].eq("CASH"), reason] = float(
                (policy_summary.get("reserve_reasons") or {}).get(reason, 0.0)
            )
        target.loc[target["ticker"].eq("CASH"), "capacity_unallocated"] = float(
            target.loc[target["ticker"].eq("CASH"), "weight"].sum()
        )
        target_reconciliation = reserve_reason_reconciliation(
            target,
            policy=reserve_policy,
            weight_col="weight",
        )
        shadow_reconciliation = reserve_reason_reconciliation(
            crisis_shadow,
            policy=reserve_policy,
            weight_col="weight",
        )
        target[RESERVE_REASON_SOURCE_HASH_FIELD] = target_reconciliation[
            RESERVE_REASON_SOURCE_HASH_FIELD
        ]
        crisis_shadow[RESERVE_REASON_SOURCE_HASH_FIELD] = shadow_reconciliation[
            RESERVE_REASON_SOURCE_HASH_FIELD
        ]
        target["reserve_asset_policy_schema"] = target_reconciliation["schema_version"]
        target["reserve_asset_mode"] = reserve_policy.mode
        target["reserve_reason_reconciled"] = True
        crisis_shadow["reserve_asset_policy_schema"] = shadow_reconciliation["schema_version"]
        crisis_shadow["reserve_asset_mode"] = reserve_policy.mode
        crisis_shadow["reserve_reason_reconciled"] = True
        reserve_reconciliations[portfolio] = {
            "operating_target": target_reconciliation,
            "crisis_shadow_target": shadow_reconciliation,
        }
        target["portfolio_kind"] = portfolio
        crisis_shadow["portfolio_kind"] = portfolio
        target["selector_scenario"] = scenario
        crisis_shadow["selector_scenario"] = scenario
        target["rebalance_date"] = valuation_date
        crisis_shadow["rebalance_date"] = valuation_date
        target["same_close_target_hash"] = target_hash(target[["ticker", "weight"]])
        crisis_shadow["same_close_target_hash"] = target_hash(
            crisis_shadow[["ticker", "weight"]]
        )
        targets[portfolio] = target
        crisis_shadow_targets[portfolio] = crisis_shadow
        risk_actions[portfolio] = actions
        crisis_actions[portfolio] = selective_actions
        crisis_policy[portfolio] = policy_summary
        turnover[portfolio] = turnover_summary(target, detail, portfolio)
    if failures or set(targets) != set(SCENARIOS):
        return blocked_payload(
            output_dir=output_dir,
            valuation_date=valuation_date,
            failures=sorted(set(failures or ["target_set_incomplete"])),
            inputs=inputs,
        )

    output_records: dict[str, Any] = {}
    target_hashes: dict[str, str] = {}
    crisis_shadow_hashes: dict[str, str] = {}
    for portfolio, target in targets.items():
        path = output_dir / f"same_close_{portfolio}_target_book.csv"
        target.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")
        output_records[f"{portfolio}_target_book"] = fingerprint(path)
        target_hashes[portfolio] = str(target["same_close_target_hash"].iloc[0])
        shadow = crisis_shadow_targets[portfolio]
        shadow_path = output_dir / f"same_close_{portfolio}_crisis_shadow_target_book.csv"
        shadow.to_csv(
            shadow_path, index=False, lineterminator="\n", float_format="%.12g"
        )
        output_records[f"{portfolio}_crisis_shadow_target_book"] = fingerprint(
            shadow_path
        )
        crisis_shadow_hashes[portfolio] = str(
            shadow["same_close_target_hash"].iloc[0]
        )
    action_path = output_dir / "risk_intersection_audit.csv"
    pd.DataFrame(
        [dict(portfolio_kind=portfolio, **row) for portfolio, rows in risk_actions.items() for row in rows]
    ).to_csv(action_path, index=False, lineterminator="\n", float_format="%.12g")
    output_records["risk_intersection_audit"] = fingerprint(action_path)
    crisis_action_path = output_dir / "canonical_crisis_policy_audit.csv"
    pd.DataFrame(
        [
            dict(portfolio_kind=portfolio, **row)
            for portfolio, rows in crisis_actions.items()
            for row in rows
        ],
        columns=[
            "portfolio_kind",
            "ticker",
            "priority",
            "reason",
            "weight_before",
            "trim_weight",
            "weight_after",
        ],
    ).to_csv(crisis_action_path, index=False, lineterminator="\n", float_format="%.12g")
    output_records["canonical_crisis_policy_audit"] = fingerprint(crisis_action_path)
    decision_snapshot = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        **contract,
        "selector_scenarios": SCENARIOS,
        "active_prediction_heads": sorted(ACTIVE_HEADS),
        "prediction_head_activity_passed": True,
        "selector_input_hashes": {
            key: value.get("sha256", "") for key, value in sorted(inputs.items())
        },
        "target_hashes": target_hashes,
        "crisis_shadow_target_hashes": crisis_shadow_hashes,
        "turnover_and_cost": turnover,
        "risk_intersection": {
            portfolio: {
                "veto_or_cap_count": sum(row["action"] != "UNCHANGED" for row in rows),
                "actions": rows,
            }
            for portfolio, rows in risk_actions.items()
        },
        "canonical_crisis_state": crisis_context,
        "reserve_asset_policy": reserve_policy.audit(),
        "reserve_reason_reconciliation": reserve_reconciliations,
        "crisis_policy_promotion_status": "REJECTED_HISTORICAL_FIXED_BOOK",
        "crisis_policy_applied_to_operating_target": False,
        "crisis_policy_shadow_only": True,
        "canonical_crisis_policy": {
            portfolio: {
                **crisis_policy[portfolio],
                "selective_sell_actions": crisis_actions[portfolio],
            }
            for portfolio in sorted(crisis_policy)
        },
        "target_book_file_written": True,
        "orders_generated": False,
        "research_only": True,
        "paper_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
        "pit_universe_label_clean": False,
    }
    snapshot_path = output_dir / "decision_snapshot.json"
    write_json(snapshot_path, decision_snapshot)
    output_records["decision_snapshot"] = fingerprint(snapshot_path)
    status = {
        **decision_snapshot,
        "contract_failures": [],
        "source_inputs": inputs,
        "outputs": output_records,
    }
    write_json(output_dir / "status.json", status)
    return status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-status", required=True)
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument(
        "--contract", default="docs/run287_same_close_target_contract.json"
    )
    parser.add_argument("--output-dir", default="outputs/run287_same_close_decision")
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
