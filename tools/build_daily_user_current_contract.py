#!/usr/bin/env python3
"""Write the daily user-facing operating contract files.

This tool is a presentation bridge for daily review artifacts. It does not
change target books, scores, sizing, cash policy, universes, or production
gates. It collects already-built recommendation and freshness outputs into the
stable filenames the operating workflow promises to users.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PORTFOLIOS = ("main", "concentrated")
SNAPSHOT_TOLERANCE = 1e-8


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN", "NONE"} else ticker


def clean_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def first_value(row: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return value
    return default


def load_current_holdings(output_dir: Path) -> pd.DataFrame:
    frame = read_csv(output_dir / "01_current_holdings.csv")
    columns = ["portfolio", "ticker", "current_weight", "current_shares", "current_price", "row_type"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    out = frame.copy()
    if "portfolio" not in out.columns:
        if "portfolio_kind" in out.columns:
            out["portfolio"] = out["portfolio_kind"]
        else:
            out["portfolio"] = ""
    if "ticker" not in out.columns:
        out["ticker"] = ""
    if "current_weight" not in out.columns:
        out["current_weight"] = 0.0
    if "current_shares" not in out.columns:
        out["current_shares"] = 0.0
    if "current_price" not in out.columns:
        out["current_price"] = 0.0
    if "row_type" not in out.columns:
        out["row_type"] = ""
    out["portfolio"] = out["portfolio"].astype(str).str.lower().str.strip()
    out["ticker"] = out["ticker"].map(clean_ticker)
    out["current_weight"] = pd.to_numeric(out["current_weight"], errors="coerce").fillna(0.0)
    out["current_shares"] = pd.to_numeric(out["current_shares"], errors="coerce").fillna(0.0)
    out["current_price"] = pd.to_numeric(out["current_price"], errors="coerce").fillna(0.0)
    out["row_type"] = out["row_type"].astype(str)
    out = out[(out["portfolio"] != "") & (out["ticker"] != "")].copy()
    if out.empty:
        return pd.DataFrame(columns=columns)
    return (
        out.groupby(["portfolio", "ticker"], as_index=False)
        .agg(
            {
                "current_weight": "sum",
                "current_shares": "sum",
                "current_price": "last",
                "row_type": "last",
            }
        )
        .reindex(columns=columns)
    )


def current_weight_map(current_holdings: pd.DataFrame) -> dict[tuple[str, str], float]:
    if current_holdings.empty:
        return {}
    return {
        (str(row.portfolio).lower(), clean_ticker(row.ticker)): clean_float(row.current_weight)
        for row in current_holdings.itertuples(index=False)
    }


def freshness_state(latest_run: Path) -> dict[str, Any]:
    status = read_json(latest_run / "data_freshness_contract" / "status.json")
    summary = read_json(latest_run / "daily_operating_selection_refresh" / "summary.json")
    selection_allowed = bool(status.get("selection_allowed", summary.get("selection_allowed", False)))
    promotion_allowed = bool(status.get("promotion_allowed", summary.get("promotion_allowed", False)))
    recommendation_status = str(
        status.get("recommendation_status")
        or summary.get("recommendation_status")
        or "DO_NOT_USE_REVIEW_REQUIRED"
    )
    blockers = list(status.get("blockers") or [])
    return {
        "status": status.get("status") or ("pass" if selection_allowed else "blocked"),
        "selection_allowed": selection_allowed,
        "promotion_allowed": promotion_allowed,
        "recommendation_status": recommendation_status,
        "blockers": blockers,
        "warnings": list(status.get("warnings") or []),
        "source_status": status,
        "daily_summary": summary,
    }


def target_rows_from_portfolio_reports(latest_run: Path, review_required: bool, review_reason: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    reports_dir = latest_run / "user_portfolio_reports"
    for portfolio in PORTFOLIOS:
        frame = read_csv(reports_dir / f"{portfolio}_recommendation_latest.csv")
        if frame.empty:
            frame = read_csv(reports_dir / portfolio / "recommendation_latest.csv")
        if frame.empty:
            continue
        for source_row in frame.to_dict("records"):
            ticker = clean_ticker(source_row.get("ticker"))
            if not ticker:
                continue
            rows.append(
                {
                    "portfolio": portfolio,
                    "ticker": ticker,
                    "target_weight": clean_float(first_value(source_row, ["recommended_weight", "target_weight", "weight"])),
                    "current_weight": clean_float(first_value(source_row, ["current_account_weight", "current_weight"], 0.0)),
                    "delta_weight": clean_float(first_value(source_row, ["recommended_weight", "target_weight", "weight"]))
                    - clean_float(first_value(source_row, ["current_account_weight", "current_weight"], 0.0)),
                    "rank": int(clean_float(source_row.get("rank"), 0.0)),
                    "company_name": first_value(source_row, ["company_name", "name"], ""),
                    "sector": first_value(source_row, ["sector"], ""),
                    "lane": first_value(source_row, ["portfolio_sleeve_label", "lane"], ""),
                    "theme": first_value(source_row, ["theme", "theme_label", "subindustry"], ""),
                    "selection_score": clean_float(first_value(source_row, ["score", "selection_score", "score_total"], 0.0)),
                    "reference_price": clean_float(first_value(source_row, ["reference_price"], 0.0)),
                    "reference_price_date": first_value(source_row, ["reference_price_date"], ""),
                    "suggested_action": first_value(source_row, ["suggested_action", "trade_action_from_current"], "REVIEW_REQUIRED"),
                    "selection_reason": first_value(source_row, ["buy_logic", "selection_reason"], ""),
                    "review_required": review_required,
                    "review_reason": review_reason,
                    "production_mutation_allowed": False,
                    "live_trading_enabled": False,
                    "human_approval_required": True,
                }
            )
    return pd.DataFrame(rows)


def target_rows_from_operating_books(latest_run: Path, review_required: bool, review_reason: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for portfolio, name in {
        "main": "operating_main_target_book.csv",
        "concentrated": "operating_concentrated_target_book.csv",
    }.items():
        frame = read_csv(latest_run / "reports" / name)
        if frame.empty or "ticker" not in frame.columns:
            continue
        date_col = "rebalance_date" if "rebalance_date" in frame.columns else ""
        if date_col:
            dates = pd.to_datetime(frame[date_col], errors="coerce")
            if dates.notna().any():
                frame = frame.loc[dates.eq(dates.max())].copy()
        for source_row in frame.to_dict("records"):
            ticker = clean_ticker(source_row.get("ticker"))
            if not ticker:
                continue
            rows.append(
                {
                    "portfolio": portfolio,
                    "ticker": ticker,
                    "target_weight": clean_float(first_value(source_row, ["weight", "target_weight"], 0.0)),
                    "current_weight": 0.0,
                    "delta_weight": clean_float(first_value(source_row, ["weight", "target_weight"], 0.0)),
                    "rank": int(clean_float(source_row.get("rank"), 0.0)),
                    "company_name": first_value(source_row, ["company_name", "name"], ""),
                    "sector": first_value(source_row, ["sector"], ""),
                    "lane": first_value(source_row, ["portfolio_sleeve_label", "lane"], ""),
                    "theme": first_value(source_row, ["theme", "theme_label", "subindustry"], ""),
                    "selection_score": clean_float(first_value(source_row, ["score", "score_total", "selection_score"], 0.0)),
                    "reference_price": 0.0,
                    "reference_price_date": "",
                    "suggested_action": "REVIEW_REQUIRED",
                    "selection_reason": first_value(source_row, ["selection_reason", "buy_logic"], ""),
                    "review_required": review_required,
                    "review_reason": review_reason,
                    "production_mutation_allowed": False,
                    "live_trading_enabled": False,
                    "human_approval_required": True,
                }
            )
    return pd.DataFrame(rows)


def load_target_weights(
    latest_run: Path,
    review_required: bool,
    review_reason: str,
    current_holdings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    frame = target_rows_from_portfolio_reports(latest_run, review_required, review_reason)
    if frame.empty:
        frame = target_rows_from_operating_books(latest_run, review_required, review_reason)
    columns = [
        "portfolio",
        "ticker",
        "target_weight",
        "current_weight",
        "delta_weight",
        "rank",
        "company_name",
        "sector",
        "lane",
        "theme",
        "selection_score",
        "reference_price",
        "reference_price_date",
        "suggested_action",
        "selection_reason",
        "review_required",
        "review_reason",
        "production_mutation_allowed",
        "live_trading_enabled",
        "human_approval_required",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    out = frame.reindex(columns=columns).copy()
    current_map = current_weight_map(current_holdings if current_holdings is not None else pd.DataFrame())
    if current_map:
        out["current_weight"] = [
            current_map.get((str(row.get("portfolio") or "").lower(), clean_ticker(row.get("ticker"))), 0.0)
            for row in out.to_dict("records")
        ]
        out["delta_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(0.0) - pd.to_numeric(
            out["current_weight"], errors="coerce"
        ).fillna(0.0)
    return out.sort_values(["portfolio", "rank", "ticker"]).reset_index(drop=True)


def order_preview_from_current_snapshot(
    target_weights: pd.DataFrame,
    current_holdings: pd.DataFrame,
    review_required: bool,
    review_reason: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    target_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if not target_weights.empty:
        for row in target_weights.to_dict("records"):
            portfolio = str(row.get("portfolio") or "").lower()
            ticker = clean_ticker(row.get("ticker"))
            if portfolio and ticker:
                target_by_key[(portfolio, ticker)] = row
    current_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    if not current_holdings.empty:
        for row in current_holdings.to_dict("records"):
            portfolio = str(row.get("portfolio") or "").lower()
            ticker = clean_ticker(row.get("ticker"))
            if portfolio and ticker:
                current_by_key[(portfolio, ticker)] = row

    priority = 0
    for key in sorted(set(target_by_key) | set(current_by_key)):
        portfolio, ticker = key
        target_row = target_by_key.get(key, {})
        current_row = current_by_key.get(key, {})
        target_weight = clean_float(target_row.get("target_weight"), 0.0)
        current_weight = clean_float(current_row.get("current_weight"), clean_float(target_row.get("current_weight"), 0.0))
        delta_weight = target_weight - current_weight
        priority += 1
        if abs(delta_weight) < 1e-8 and ticker != "CASH":
            action = "HOLD"
        elif ticker == "CASH":
            action = "REVIEW_REQUIRED"
        elif target_weight <= 1e-8 and current_weight > 1e-8:
            action = "REVIEW_EXIT"
        elif delta_weight > 0:
            action = "REVIEW_ADD"
        else:
            action = "REVIEW_TRIM"
        rows.append(
            {
                "portfolio": portfolio,
                "ticker": ticker,
                "action": "REVIEW_REQUIRED" if review_required else action,
                "current_weight": current_weight,
                "target_weight": target_weight,
                "delta_weight": delta_weight,
                "estimated_shares": 0.0,
                "estimated_value": 0.0,
                "priority": int(clean_float(target_row.get("rank"), priority)),
                "review_required": True,
                "reason": review_reason,
                "order_source": "current_snapshot_vs_target_review_only",
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
                "human_approval_required": True,
            }
        )
    return pd.DataFrame(rows)


def key_weight_map(frame: pd.DataFrame, weight_col: str) -> dict[tuple[str, str], float]:
    if frame.empty or weight_col not in frame.columns:
        return {}
    out: dict[tuple[str, str], float] = {}
    for row in frame.to_dict("records"):
        portfolio = str(row.get("portfolio") or "").lower().strip()
        ticker = clean_ticker(row.get("ticker"))
        if not portfolio or not ticker:
            continue
        out[(portfolio, ticker)] = out.get((portfolio, ticker), 0.0) + clean_float(row.get(weight_col), 0.0)
    return out


def max_abs_drift(left: dict[tuple[str, str], float], right: dict[tuple[str, str], float]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    return max(abs(float(left.get(key, 0.0)) - float(right.get(key, 0.0))) for key in keys)


def max_abs_drift_for_keys(
    left: dict[tuple[str, str], float],
    right: dict[tuple[str, str], float],
    keys: set[tuple[str, str]],
) -> float:
    if not keys:
        return 0.0
    return max(abs(float(left.get(key, 0.0)) - float(right.get(key, 0.0))) for key in keys)


def validate_snapshot_contract(
    current_holdings: pd.DataFrame,
    target_weights: pd.DataFrame,
    order_preview: pd.DataFrame,
) -> dict[str, Any]:
    current = key_weight_map(current_holdings, "current_weight")
    target_current = key_weight_map(target_weights, "current_weight")
    target = key_weight_map(target_weights, "target_weight")
    order_current = key_weight_map(order_preview, "current_weight")
    order_target = key_weight_map(order_preview, "target_weight")
    order_delta = key_weight_map(order_preview, "delta_weight")
    expected_order_keys = set(current) | set(target)
    order_keys = set(order_current) | set(order_target) | set(order_delta)
    expected_delta = {key: float(target.get(key, 0.0)) - float(current.get(key, 0.0)) for key in expected_order_keys}

    current_target_drift = max_abs_drift_for_keys(current, target_current, set(target))
    order_current_drift = max_abs_drift(current, order_current)
    order_target_drift = max_abs_drift(target, order_target)
    order_delta_drift = max_abs_drift(expected_delta, order_delta)
    missing_order_keys = sorted(f"{portfolio}:{ticker}" for portfolio, ticker in expected_order_keys - order_keys)
    extra_order_keys = sorted(f"{portfolio}:{ticker}" for portfolio, ticker in order_keys - expected_order_keys)

    blockers: list[str] = []
    if current_holdings.empty:
        blockers.append("current holdings snapshot missing or empty")
    if target_weights.empty:
        blockers.append("target weights missing or empty")
    if order_preview.empty:
        blockers.append("order preview missing or empty")
    if current_target_drift > SNAPSHOT_TOLERANCE:
        blockers.append(f"target current_weight does not match current holdings snapshot: max_abs_drift={current_target_drift:.12g}")
    if order_current_drift > SNAPSHOT_TOLERANCE:
        blockers.append(f"order current_weight does not match current holdings snapshot: max_abs_drift={order_current_drift:.12g}")
    if order_target_drift > SNAPSHOT_TOLERANCE:
        blockers.append(f"order target_weight does not match target weights: max_abs_drift={order_target_drift:.12g}")
    if order_delta_drift > SNAPSHOT_TOLERANCE:
        blockers.append(f"order delta_weight is not target-current: max_abs_drift={order_delta_drift:.12g}")
    if missing_order_keys:
        blockers.append(f"order preview missing {len(missing_order_keys)} current/target rows")
    if extra_order_keys:
        blockers.append(f"order preview has {len(extra_order_keys)} rows outside current/target snapshot")

    return {
        "schema_version": "daily-snapshot-contract-v1",
        "snapshot_contract_pass": not blockers,
        "blockers": blockers,
        "current_target_weight_max_abs_drift": current_target_drift,
        "order_current_weight_max_abs_drift": order_current_drift,
        "order_target_weight_max_abs_drift": order_target_drift,
        "order_delta_weight_max_abs_drift": order_delta_drift,
        "expected_order_key_count": len(expected_order_keys),
        "order_key_count": len(order_keys),
        "missing_order_keys": missing_order_keys[:25],
        "extra_order_keys": extra_order_keys[:25],
        "tolerance": SNAPSHOT_TOLERANCE,
        "current_snapshot_used_for_order_preview": bool(not current_holdings.empty and not order_preview.empty),
    }


def load_order_preview(
    latest_run: Path,
    target_weights: pd.DataFrame,
    review_required: bool,
    review_reason: str,
    current_holdings: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if current_holdings is not None and not current_holdings.empty:
        snapshot_orders = order_preview_from_current_snapshot(target_weights, current_holdings, review_required, review_reason)
        if not snapshot_orders.empty:
            rows = snapshot_orders.to_dict("records")
    for portfolio in PORTFOLIOS:
        if rows:
            break
        preview = read_csv(latest_run / "account_ledger_preview" / portfolio / "orders_preview.csv")
        if not preview.empty and "ticker" in preview.columns:
            for source_row in preview.to_dict("records"):
                ticker = clean_ticker(source_row.get("ticker"))
                if not ticker:
                    continue
                target_weight = clean_float(source_row.get("target_weight"))
                current_weight = clean_float(source_row.get("current_weight"))
                rows.append(
                    {
                        "portfolio": portfolio,
                        "ticker": ticker,
                        "action": first_value(source_row, ["action", "order_action"], "REVIEW_REQUIRED"),
                        "current_weight": current_weight,
                        "target_weight": target_weight,
                        "delta_weight": target_weight - current_weight,
                        "estimated_shares": clean_float(first_value(source_row, ["quantity", "estimated_shares"], 0.0)),
                        "estimated_value": clean_float(first_value(source_row, ["trade_value_delta_usd", "target_value_usd"], 0.0)),
                        "priority": 0,
                        "review_required": True,
                        "reason": review_reason,
                        "order_source": "account_ledger_preview",
                        "production_mutation_allowed": False,
                        "live_trading_enabled": False,
                        "human_approval_required": True,
                    }
                )
    if not rows and not target_weights.empty:
        for source_row in target_weights.to_dict("records"):
            ticker = clean_ticker(source_row.get("ticker"))
            if not ticker:
                continue
            target_weight = clean_float(source_row.get("target_weight"))
            current_weight = clean_float(source_row.get("current_weight"))
            rows.append(
                {
                    "portfolio": source_row.get("portfolio", ""),
                    "ticker": ticker,
                    "action": "REVIEW_REQUIRED" if review_required else str(source_row.get("suggested_action") or "HOLD"),
                    "current_weight": current_weight,
                    "target_weight": target_weight,
                    "delta_weight": target_weight - current_weight,
                    "estimated_shares": 0.0,
                    "estimated_value": clean_float(source_row.get("reference_price"), 0.0) * 0.0,
                    "priority": int(clean_float(source_row.get("rank"), 0.0)),
                    "review_required": True,
                    "reason": review_reason,
                    "order_source": "target_recommendation_review_only",
                    "production_mutation_allowed": False,
                    "live_trading_enabled": False,
                    "human_approval_required": True,
                }
            )
    columns = [
        "portfolio",
        "ticker",
        "action",
        "current_weight",
        "target_weight",
        "delta_weight",
        "estimated_shares",
        "estimated_value",
        "priority",
        "review_required",
        "reason",
        "order_source",
        "production_mutation_allowed",
        "live_trading_enabled",
        "human_approval_required",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).reindex(columns=columns).sort_values(["portfolio", "priority", "ticker"]).reset_index(drop=True)


def build_decision(
    *,
    state: dict[str, Any],
    target_weights: pd.DataFrame,
    order_preview: pd.DataFrame,
    source_run_id: str,
    source_commit_sha: str,
    source_branch: str,
    source_artifact_name: str,
    snapshot_contract: dict[str, Any],
) -> dict[str, Any]:
    selection_allowed = bool(state["selection_allowed"])
    blockers = list(state["blockers"])
    contract_blockers = [f"snapshot_contract: {item}" for item in snapshot_contract.get("blockers", [])]
    blockers.extend(contract_blockers)
    if not selection_allowed:
        decision = "REVIEW_REQUIRED"
        reason = "; ".join(blockers) if blockers else state["recommendation_status"]
    elif not snapshot_contract.get("snapshot_contract_pass"):
        decision = "REVIEW_REQUIRED"
        reason = "; ".join(contract_blockers) or "daily snapshot contract failed"
    elif order_preview.empty:
        decision = "NO_ACTION"
        reason = "selection allowed but no order preview rows were generated"
    else:
        decision = "REVIEW_REQUIRED"
        reason = "review-only daily operating output; human approval required before any action"
    estimated_turnover = float(order_preview["delta_weight"].abs().sum()) if "delta_weight" in order_preview.columns else 0.0
    return {
        "schema_version": "daily-rebalance-decision-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "reason": reason,
        "data_freshness_status": state["status"],
        "recommendation_status": state["recommendation_status"],
        "selection_allowed": selection_allowed,
        "promotion_allowed": bool(state["promotion_allowed"]),
        "blockers": blockers,
        "warnings": list(state["warnings"]),
        "target_weight_rows": int(len(target_weights)),
        "order_preview_rows": int(len(order_preview)),
        "snapshot_contract_pass": bool(snapshot_contract.get("snapshot_contract_pass")),
        "snapshot_contract_blockers": snapshot_contract.get("blockers", []),
        "cash_trap_flag": None,
        "max_turnover_allowed": 0.2,
        "estimated_turnover": estimated_turnover,
        "daily_operating_refresh": True,
        "review_only": True,
        "canonical_production_sync": False,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "human_approval_required": True,
        "source_of_truth_level": "GITHUB_ARTIFACT",
        "source_run_id": source_run_id,
        "source_commit_sha": source_commit_sha,
        "source_branch": source_branch,
        "source_artifact_name": source_artifact_name,
    }


def update_json_file(path: Path, updates: dict[str, Any]) -> None:
    payload = read_json(path)
    payload.update(updates)
    write_json(path, payload)


def append_review_only_notice(path: Path) -> None:
    notice = (
        "\n"
        "- production_mutation_allowed: `false`\n"
        "- human_approval_required: `true`\n"
        "\n"
        "Daily target weights and order preview files are review-only. Rows marked "
        "`REVIEW_REQUIRED` or produced while `selection_allowed=false` must not be traded.\n"
    )
    if not path.exists():
        path.write_text("# Daily Review-Only Current Output\n" + notice, encoding="utf-8")
        return
    text = path.read_text(encoding="utf-8")
    if "human_approval_required" not in text:
        path.write_text(text.rstrip() + "\n" + notice, encoding="utf-8")


def build_contract(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    state = freshness_state(latest_run)
    review_required = True
    if not state["selection_allowed"]:
        review_reason = "; ".join(state["blockers"]) or state["recommendation_status"]
    else:
        review_reason = "daily output is review-only; human approval required"

    current_holdings = load_current_holdings(output_dir)
    target_weights = load_target_weights(latest_run, review_required, review_reason, current_holdings)
    order_preview = load_order_preview(latest_run, target_weights, review_required, review_reason, current_holdings)
    snapshot_contract = validate_snapshot_contract(current_holdings, target_weights, order_preview)
    decision = build_decision(
        state=state,
        target_weights=target_weights,
        order_preview=order_preview,
        source_run_id=args.source_run_id,
        source_commit_sha=args.source_commit_sha,
        source_branch=args.source_branch,
        source_artifact_name=args.source_artifact_name,
        snapshot_contract=snapshot_contract,
    )

    target_path = output_dir / "02_target_weights.csv"
    order_path = output_dir / "03_order_preview.csv"
    decision_path = output_dir / "08_rebalance_decision.json"
    target_weights.to_csv(target_path, index=False)
    order_preview.to_csv(order_path, index=False)
    write_json(decision_path, decision)

    metadata_updates = {
        "daily_operating_refresh": True,
        "review_only": True,
        "canonical_production_sync": False,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
        "human_approval_required": True,
        "source_of_truth_level": "GITHUB_ARTIFACT",
        "source_run_id": args.source_run_id,
        "source_commit_sha": args.source_commit_sha,
        "source_branch": args.source_branch,
        "source_artifact_name": args.source_artifact_name,
        "daily_contract_files": {
            "target_weights": str(target_path),
            "order_preview": str(order_path),
            "rebalance_decision": str(decision_path),
        },
        "current_snapshot_rows": int(len(current_holdings)),
        "current_snapshot_used_for_order_preview": not current_holdings.empty,
        "snapshot_contract_pass": bool(snapshot_contract.get("snapshot_contract_pass")),
        "snapshot_contract_blockers": snapshot_contract.get("blockers", []),
        "snapshot_contract": snapshot_contract,
    }
    update_json_file(latest_run / "daily_operating_selection_refresh" / "summary.json", metadata_updates)
    update_json_file(output_dir / "summary.json", metadata_updates)
    append_review_only_notice(output_dir / "DAILY_REVIEW_ONLY.md")

    summary = {
        "schema_version": "daily-user-current-contract-v1",
        "status": "completed",
        "target_weight_rows": int(len(target_weights)),
        "order_preview_rows": int(len(order_preview)),
        "current_snapshot_rows": int(len(current_holdings)),
        "current_snapshot_used_for_order_preview": not current_holdings.empty,
        "snapshot_contract_pass": bool(snapshot_contract.get("snapshot_contract_pass")),
        "snapshot_contract_blockers": snapshot_contract.get("blockers", []),
        "snapshot_contract": snapshot_contract,
        "decision": decision["decision"],
        "selection_allowed": state["selection_allowed"],
        "promotion_allowed": state["promotion_allowed"],
        "recommendation_status": state["recommendation_status"],
        "outputs": {
            "target_weights": str(target_path),
            "order_preview": str(order_path),
            "rebalance_decision": str(decision_path),
        },
        **metadata_updates,
    }
    write_json(output_dir / "09_daily_output_contract_summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/user_current")
    parser.add_argument("--source-run-id", default="")
    parser.add_argument("--source-commit-sha", default="")
    parser.add_argument("--source-branch", default="")
    parser.add_argument("--source-artifact-name", default="")
    return parser.parse_args()


def main() -> int:
    build_contract(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
