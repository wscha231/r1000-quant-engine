#!/usr/bin/env python3
"""Build a review-only durable-quality screen and trade checklist.

This sidecar separates four ideas that the legacy ``moat_proxy_score`` mixes:
balance-sheet resilience, economic durability, technology reinvestment, and
market confirmation.  It also grades decisions only after fixed forward
horizons mature.  It never changes a score, rank, selector, target, cash
policy, or order.

The current Run287 frame does not contain exact total debt for the full
universe.  ``liabilities / assets`` is therefore labelled as a balance-sheet
proxy, never as debt.  Missing evidence is neutral in the score and explicit
in coverage gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "run287-durable-quality-learning-v1"
PRIMARY_GRADE_HORIZON = 63
SECONDARY_GRADE_HORIZON = 21

BALANCE_COMPONENTS: tuple[tuple[str, int], ...] = (
    ("liabilities_to_assets", -1),
    ("debt_to_equity_delta_4q", -1),
    ("interest_coverage", 1),
    ("fcf_margin", 1),
    ("dilution_penalty", -1),
)
ECONOMIC_COMPONENTS: tuple[tuple[str, int], ...] = (
    ("roic_approx", 1),
    ("gross_margin_ttm", 1),
    ("op_margin_ttm", 1),
    ("margin_stability_8q", 1),
    ("capital_efficiency_score", 1),
    ("fcf_margin", 1),
    ("sales_cagr_3y", 1),
)
TECHNOLOGY_COMPONENTS: tuple[tuple[str, int], ...] = (
    ("rd_intensity", 1),
    ("rule_of_40", 1),
    ("gross_margin_ttm", 1),
    ("sales_cagr_3y", 1),
)
MARKET_COMPONENTS: tuple[tuple[str, int], ...] = (
    ("rs_sector_6m", 1),
    ("near_52w_high_pct", 1),
    ("price_above_ma200", 1),
    ("dynamic_leader_score", 1),
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def _bool(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[name]
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False).astype(bool)
    return values.astype(str).str.lower().isin({"1", "true", "yes", "y"})


def sector_percentile_score(frame: pd.DataFrame, name: str, direction: int) -> pd.Series:
    """Return a bounded past-snapshot cross-sectional score in [-1, 1]."""

    values = _numeric(frame, name).replace([np.inf, -np.inf], np.nan)
    global_score = values.rank(method="average", pct=True).mul(2.0).sub(1.0)
    sectors = frame.get("sector", pd.Series("Unknown", index=frame.index)).fillna("Unknown").astype(str)
    grouped = values.groupby(sectors)
    sector_rank = grouped.rank(method="average", pct=True).mul(2.0).sub(1.0)
    group_count = grouped.transform("count")
    score = sector_rank.where(group_count.ge(8), global_score)
    return score.mul(float(direction)).where(values.notna())


def pillar(
    frame: pd.DataFrame,
    components: Iterable[tuple[str, int]],
    prefix: str,
) -> tuple[pd.Series, pd.Series]:
    component_list = list(components)
    scores = pd.DataFrame(index=frame.index)
    for name, direction in component_list:
        scores[name] = sector_percentile_score(frame, name, direction)
        frame[f"{prefix}_component_{name}"] = scores[name]
    coverage = scores.notna().sum(axis=1).div(max(len(component_list), 1))
    # Missing evidence is neutral, while coverage prevents sparse rows from
    # being interpreted as complete high-quality firms.
    score = scores.fillna(0.0).sum(axis=1).div(max(len(component_list), 1))
    return score, coverage


def build_quality_universe(context: pd.DataFrame, decision_time: pd.Timestamp) -> pd.DataFrame:
    required = {"ticker", "sector"}
    missing = required - set(context.columns)
    if missing:
        raise ValueError(f"selection context missing columns: {sorted(missing)}")
    frame = context.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame = frame.loc[frame["ticker"].ne("") & frame["ticker"].ne("NAN")].copy()
    if frame["ticker"].duplicated().any():
        raise ValueError("selection context must contain one row per ticker")

    assets = _numeric(frame, "assets").replace(0.0, np.nan)
    liabilities = _numeric(frame, "liabilities")
    frame["liabilities_to_assets"] = liabilities.div(assets)
    frame["liabilities_to_assets"] = frame["liabilities_to_assets"].where(
        frame["liabilities_to_assets"].between(0.0, 2.0)
    )

    accepted = pd.to_datetime(frame.get("fund_effective_accepted"), errors="coerce", utc=True)
    available = pd.to_datetime(frame.get("feature_available_from"), errors="coerce", utc=True)
    frame["future_fundamental_row"] = accepted.gt(decision_time).fillna(False)
    frame["future_feature_row"] = available.gt(decision_time).fillna(False)
    frame["pit_future_row"] = frame["future_fundamental_row"] | frame["future_feature_row"]
    frame["fundamental_evidence_present"] = accepted.notna() & ~frame["future_fundamental_row"]

    frame["balance_resilience_score"], frame["balance_coverage"] = pillar(
        frame, BALANCE_COMPONENTS, "balance"
    )
    frame["balance_resilience_score_before_exact_debt"] = frame["balance_resilience_score"]
    frame["exact_net_debt_score"] = sector_percentile_score(
        frame, "exact_net_debt_to_assets", -1
    )
    exact_debt_score_present = frame["exact_net_debt_score"].notna()
    frame.loc[exact_debt_score_present, "balance_resilience_score"] = (
        0.60 * frame.loc[exact_debt_score_present, "balance_resilience_score_before_exact_debt"]
        + 0.40 * frame.loc[exact_debt_score_present, "exact_net_debt_score"]
    )
    frame.loc[exact_debt_score_present, "balance_coverage"] = (
        0.80 * frame.loc[exact_debt_score_present, "balance_coverage"] + 0.20
    ).clip(upper=1.0)
    frame["economic_durability_score"], frame["economic_coverage"] = pillar(
        frame, ECONOMIC_COMPONENTS, "economic"
    )
    frame["technology_reinvestment_score"], frame["technology_coverage"] = pillar(
        frame, TECHNOLOGY_COMPONENTS, "technology"
    )
    frame["market_confirmation_score_clean"], frame["market_coverage"] = pillar(
        frame, MARKET_COMPONENTS, "market"
    )
    frame["core_quality_coverage"] = (
        frame["balance_coverage"].mul(len(BALANCE_COMPONENTS))
        + frame["economic_coverage"].mul(len(ECONOMIC_COMPONENTS))
    ).div(len(BALANCE_COMPONENTS) + len(ECONOMIC_COMPONENTS))
    frame["business_quality_score"] = (
        0.45 * frame["balance_resilience_score"]
        + 0.55 * frame["economic_durability_score"]
    )

    sector_text = frame["sector"].fillna("").astype(str)
    industry_text = frame.get("industry", pd.Series("", index=frame.index)).fillna("").astype(str)
    frame["technology_business"] = (
        sector_text.str.contains("Information Technology", case=False, regex=False)
        | industry_text.str.contains(
            "semiconductor|software|electronic|computer|data|internet|communication equipment",
            case=False,
            regex=True,
        )
    )
    tech_weight = np.where(frame["technology_business"], 0.20, 0.0)
    frame["durable_quality_review_score"] = (
        (0.75 - tech_weight) * frame["business_quality_score"]
        + tech_weight * frame["technology_reinvestment_score"]
        + 0.25 * frame["market_confirmation_score_clean"]
    )

    exact_debt_columns = {"long_term_debt_exact", "current_debt_exact", "cash_exact"}
    exact_debt_present = exact_debt_columns.issubset(frame.columns)
    if exact_debt_present:
        if "exact_debt_component_coverage" in frame:
            exact_coverage = _numeric(frame, "exact_debt_component_coverage").fillna(0.0).clip(0.0, 1.0)
        else:
            exact_count = frame[list(exact_debt_columns)].notna().sum(axis=1)
            exact_coverage = exact_count.div(len(exact_debt_columns))
        frame["exact_debt_component_coverage"] = exact_coverage
        frame["debt_measurement_status"] = np.where(
            exact_coverage.eq(1.0),
            "EXACT_DEBT_AND_CASH_COMPLETE",
            np.where(exact_coverage.gt(0.0), "EXACT_DEBT_PARTIAL", "TOTAL_LIABILITIES_PROXY_ONLY"),
        )
    else:
        frame["exact_debt_component_coverage"] = 0.0
        frame["debt_measurement_status"] = "TOTAL_LIABILITIES_PROXY_ONLY"

    frame["economic_moat_evidence"] = np.select(
        [
            frame["economic_coverage"].ge(0.57)
            & frame["economic_durability_score"].ge(0.35)
            & frame["balance_resilience_score"].ge(0.0),
            frame["economic_coverage"].ge(0.43)
            & frame["economic_durability_score"].ge(0.20),
        ],
        ["STRONG_QUANTITATIVE_PROXY", "PROMISING_QUANTITATIVE_PROXY"],
        default="INSUFFICIENT_OR_WEAK_QUANTITATIVE_PROXY",
    )
    frame["technology_moat_evidence"] = np.select(
        [
            frame["technology_business"]
            & frame["technology_coverage"].ge(0.50)
            & frame["technology_reinvestment_score"].ge(0.20),
            frame["technology_business"],
        ],
        ["QUANT_REINVESTMENT_EVIDENCE_TEXT_REVIEW_REQUIRED", "TEXTUAL_MOAT_REVIEW_REQUIRED"],
        default="NOT_A_TECHNOLOGY_BUSINESS_OR_NOT_APPLICABLE",
    )

    complete = (
        ~frame["pit_future_row"]
        & frame["fundamental_evidence_present"]
        & frame["exact_debt_component_coverage"].eq(1.0)
        & frame["core_quality_coverage"].ge(0.55)
        & frame["economic_durability_score"].ge(0.20)
        & frame["balance_resilience_score"].ge(0.0)
        & frame["market_confirmation_score_clean"].ge(0.0)
    )
    partial = (
        ~frame["pit_future_row"]
        & frame["core_quality_coverage"].ge(0.35)
        & frame["economic_durability_score"].ge(0.20)
        & frame["balance_resilience_score"].ge(-0.10)
        & frame["market_confirmation_score_clean"].ge(0.0)
    )
    divergence = (
        ~frame["pit_future_row"]
        & frame["core_quality_coverage"].ge(0.35)
        & frame["economic_durability_score"].ge(0.20)
        & frame["market_confirmation_score_clean"].lt(0.0)
    )
    frame["candidate_status"] = np.select(
        [
            frame["pit_future_row"],
            frame["core_quality_coverage"].lt(0.35),
            complete,
            partial,
            divergence,
        ],
        [
            "BLOCKED_PIT_FUTURE_ROW",
            "INSUFFICIENT_CORE_DATA",
            "REVIEW_CANDIDATE_COMPLETE",
            "REVIEW_CANDIDATE_PARTIAL",
            "QUALITY_MARKET_DIVERGENCE",
        ],
        default="NOT_CURRENT_REVIEW_CANDIDATE",
    )
    company_id = frame.get("cik10", pd.Series("", index=frame.index)).astype(str).str.replace(r"\.0$", "", regex=True)
    company_id = company_id.where(company_id.ne("") & company_id.ne("nan"), frame["ticker"])
    frame["company_review_id"] = company_id
    frame["share_class_count"] = frame.groupby("company_review_id")["ticker"].transform("nunique")
    frame["company_review_primary"] = False
    primary_order = frame.sort_values(
        ["company_review_id", "durable_quality_review_score", "ticker"],
        ascending=[True, False, True],
    ).drop_duplicates("company_review_id", keep="first").index
    frame.loc[primary_order, "company_review_primary"] = True
    frame["textual_business_moat_review_required"] = True
    frame["selector_or_rank_changed"] = False
    return frame.sort_values(
        ["candidate_status", "durable_quality_review_score", "ticker"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def load_optional_risk(path: Path | None) -> pd.DataFrame:
    if path is None or not path.is_file():
        return pd.DataFrame(columns=["portfolio_kind", "ticker", "risk_state", "risk_advisory_action"])
    risk = pd.read_csv(path, low_memory=False)
    if "ticker" not in risk:
        return pd.DataFrame(columns=["portfolio_kind", "ticker", "risk_state", "risk_advisory_action"])
    risk["ticker"] = risk["ticker"].astype(str).str.upper().str.strip()
    if "portfolio_kind" not in risk:
        risk["portfolio_kind"] = ""
    risk = risk.rename(columns={"advisory_action": "risk_advisory_action"})
    keep = [c for c in ["portfolio_kind", "ticker", "risk_state", "risk_advisory_action", "reason_codes"] if c in risk]
    return risk[keep].drop_duplicates(["portfolio_kind", "ticker"], keep="last")


def build_trade_checklist(
    current_status: pd.DataFrame,
    quality: pd.DataFrame,
    risk: pd.DataFrame,
) -> pd.DataFrame:
    required = {"ticker", "portfolio_kind", "scenario"}
    missing = required - set(current_status.columns)
    if missing:
        raise ValueError(f"current status missing columns: {sorted(missing)}")
    status = current_status.copy()
    status["ticker"] = status["ticker"].astype(str).str.upper().str.strip()
    quality_keep = [
        "ticker", "candidate_status", "debt_measurement_status", "exact_debt_component_coverage",
        "balance_resilience_score", "balance_coverage", "economic_durability_score",
        "economic_coverage", "technology_reinvestment_score", "technology_coverage",
        "market_confirmation_score_clean", "market_coverage", "core_quality_coverage",
        "business_quality_score", "durable_quality_review_score", "economic_moat_evidence",
        "technology_moat_evidence", "pit_future_row",
    ]
    output = status.merge(quality[quality_keep], on="ticker", how="left", validate="many_to_one")
    if not risk.empty:
        output = output.merge(risk, on=["portfolio_kind", "ticker"], how="left", validate="many_to_one")
    else:
        output["risk_state"] = "NOT_AVAILABLE"
        output["risk_advisory_action"] = "NOT_AVAILABLE"
    output["risk_state"] = output["risk_state"].fillna("NOT_HELD_OR_NOT_AVAILABLE")
    output["risk_advisory_action"] = output["risk_advisory_action"].fillna("NOT_HELD_OR_NOT_AVAILABLE")

    prior = _numeric(output, "prior_weight").fillna(0.0)
    target = _numeric(output, "operating_target_weight").fillna(0.0)
    selected = _bool(output, "selector_selected")
    output["observed_decision_type"] = np.select(
        [
            target.gt(prior + 1e-9),
            target.gt(0.0) & prior.gt(0.0),
            target.le(0.0) & prior.gt(0.0),
            selected,
        ],
        ["BUY_OR_ADD", "HOLD_OR_RESIZE", "EXIT_OR_REPLACE", "SELECTOR_BUY_CANDIDATE"],
        default="REJECT_OR_NOT_HELD",
    )
    output["check_pit_no_future"] = ~output["pit_future_row"].fillna(False).astype(bool)
    output["check_core_quality_coverage"] = _numeric(output, "core_quality_coverage").ge(0.55)
    output["check_balance_not_red"] = (
        _numeric(output, "balance_coverage").ge(0.40)
        & _numeric(output, "balance_resilience_score").ge(0.0)
    )
    output["check_economic_durability"] = (
        _numeric(output, "economic_coverage").ge(0.43)
        & _numeric(output, "economic_durability_score").ge(0.20)
    )
    output["check_market_confirmation"] = _numeric(output, "market_confirmation_score_clean").ge(0.0)
    output["check_risk_clear"] = ~output["risk_state"].isin({"ALERT", "WATCH"})
    output["check_exact_debt_available"] = _numeric(output, "exact_debt_component_coverage").eq(1.0)

    active = output["observed_decision_type"].isin(
        {"BUY_OR_ADD", "HOLD_OR_RESIZE", "SELECTOR_BUY_CANDIDATE"}
    )
    output["buy_hold_checklist_status"] = "NOT_AN_ACTIVE_BUY_OR_HOLD_DECISION"
    output.loc[active, "buy_hold_checklist_status"] = "REVIEW_BUY_OR_HOLD"
    output.loc[active & ~output["check_core_quality_coverage"], "buy_hold_checklist_status"] = (
        "BLOCK_INCREMENTAL_BUY_DATA_INCOMPLETE"
    )
    output.loc[
        active & output["check_core_quality_coverage"] & ~output["check_balance_not_red"],
        "buy_hold_checklist_status",
    ] = "BLOCK_INCREMENTAL_BUY_BALANCE_RISK"
    output.loc[
        active
        & output["check_core_quality_coverage"]
        & output["check_balance_not_red"]
        & ~output["check_economic_durability"],
        "buy_hold_checklist_status",
    ] = "BLOCK_INCREMENTAL_BUY_DURABILITY_WEAK"
    output.loc[
        active & ~output["check_market_confirmation"], "buy_hold_checklist_status"
    ] = "FREEZE_INCREMENTAL_BUY_MARKET_DAMAGE"
    output.loc[
        active & ~output["check_risk_clear"], "buy_hold_checklist_status"
    ] = "FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW"

    owned = target.gt(0.0)
    output["sell_replace_checklist_status"] = np.where(
        owned
        & ~output["check_market_confirmation"]
        & ~output["check_economic_durability"],
        "MANUAL_REVIEW_NEEDS_EXACT_FUNDAMENTAL_BREAK",
        np.where(owned, "NO_AUTOMATIC_SELL_HOLD_REVIEW", "NOT_OWNED"),
    )
    output["portfolio_action_authorized"] = False
    output["automatic_model_update_allowed"] = False
    return output


def build_mistake_notebook(checklist: pd.DataFrame) -> pd.DataFrame:
    output = checklist.copy()
    output["grade_horizon"] = 0
    output["grade_excess_return"] = np.nan
    output["grade_status"] = "WAITING_21D_OR_63D"
    for horizon in (PRIMARY_GRADE_HORIZON, SECONDARY_GRADE_HORIZON):
        status_col = f"outcome_{horizon}d_status"
        excess_col = f"outcome_{horizon}d_spy_excess_total_return"
        if status_col not in output or excess_col not in output:
            continue
        completed = output[status_col].astype(str).eq("completed") & output["grade_horizon"].eq(0)
        output.loc[completed, "grade_horizon"] = horizon
        output.loc[completed, "grade_excess_return"] = _numeric(output, excess_col)[completed]
        output.loc[completed, "grade_status"] = "GRADE_READY"

    own = output["observed_decision_type"].isin(
        {"BUY_OR_ADD", "HOLD_OR_RESIZE", "SELECTOR_BUY_CANDIDATE"}
    )
    ready = output["grade_status"].eq("GRADE_READY")
    positive = _numeric(output, "grade_excess_return").gt(0.0)
    output["answer_label"] = "PENDING_FIXED_HORIZON"
    output.loc[ready & own & positive, "answer_label"] = "CORRECT_OWN"
    output.loc[ready & own & ~positive, "answer_label"] = "WRONG_OWN"
    output.loc[ready & ~own & positive, "answer_label"] = "MISSED_WINNER"
    output.loc[ready & ~own & ~positive, "answer_label"] = "CORRECT_AVOID"
    output["answer_note"] = np.select(
        [
            output["answer_label"].eq("WRONG_OWN") & ~output["check_balance_not_red"],
            output["answer_label"].eq("WRONG_OWN") & ~output["check_economic_durability"],
            output["answer_label"].eq("WRONG_OWN") & ~output["check_market_confirmation"],
            output["answer_label"].eq("MISSED_WINNER") & output["check_economic_durability"],
        ],
        [
            "owned_despite_balance_warning",
            "owned_without_durability_confirmation",
            "owned_without_market_confirmation",
            "rejected_despite_durable_quality_evidence",
        ],
        default="wait_or_multi_factor_review",
    )
    output["checklist_change_proposed"] = False
    output["automatic_checklist_change_allowed"] = False
    return output


def write_report(output_dir: Path, summary: dict[str, Any], queue: pd.DataFrame) -> None:
    lines = [
        "# Run287 Durable Quality Learning",
        "",
        f"Status: `{summary['status']}`",
        "",
        "This is a review-only sidecar. Quantitative moat evidence is not proof of a brand, network, patent, switching-cost, or cost-curve moat.",
        "",
        "## Coverage",
        "",
        f"- universe: {summary['universe_count']}",
        f"- complete review candidates: {summary['candidate_counts'].get('REVIEW_CANDIDATE_COMPLETE', 0)}",
        f"- partial review candidates: {summary['candidate_counts'].get('REVIEW_CANDIDATE_PARTIAL', 0)}",
        f"- insufficient core data: {summary['candidate_counts'].get('INSUFFICIENT_CORE_DATA', 0)}",
        f"- exact debt and cash complete: {summary['exact_debt_complete_count']}",
        f"- fixed-horizon answer rows ready: {summary['answer_ready_count']}",
        "",
        "## Review Queue",
        "",
        "| ticker | status | quality | balance | economic | technology | market | core coverage | debt evidence |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in queue.head(30).itertuples(index=False):
        lines.append(
            "| {ticker} | {status} | {quality:.3f} | {balance:.3f} | {economic:.3f} | "
            "{technology:.3f} | {market:.3f} | {coverage:.1%} | {debt} |".format(
                ticker=row.ticker,
                status=row.candidate_status,
                quality=float(row.durable_quality_review_score),
                balance=float(row.balance_resilience_score),
                economic=float(row.economic_durability_score),
                technology=float(row.technology_reinvestment_score),
                market=float(row.market_confirmation_score_clean),
                coverage=float(row.core_quality_coverage),
                debt=row.debt_measurement_status,
            )
        )
    lines.extend(
        [
            "",
            "## Fixed Checklist",
            "",
            "1. PIT and exact-close inputs must be available before the decision.",
            "2. Core quality coverage must be at least 55%; missing is neutral, not a pass.",
            "3. Balance resilience and economic durability must both pass before an incremental buy.",
            "4. Market damage or a holding-risk WATCH/ALERT freezes an incremental buy.",
            "5. A price alert alone never authorizes a sale. Replacement requires a selector-approved challenger and exact fundamental-break evidence.",
            "6. Decisions are graded at 63 sessions, with 21 sessions secondary. One-day outcomes never rewrite the checklist.",
            "7. Checklist changes require 26 decision weeks, 200 resolved 63D outcomes, block-bootstrap support, and human approval.",
            "",
            "No rank, selector, target, cash policy, order, historical backtest, fullrun, production, or live state changed.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def existing_columns(frame: pd.DataFrame, names: Iterable[str]) -> list[str]:
    return [name for name in names if name in frame.columns]


def slim_quality_output(frame: pd.DataFrame) -> pd.DataFrame:
    raw_components = [name for name, _ in (
        BALANCE_COMPONENTS + ECONOMIC_COMPONENTS + TECHNOLOGY_COMPONENTS + MARKET_COMPONENTS
    )]
    component_scores = [
        column for column in frame.columns
        if column.startswith(("balance_component_", "economic_component_", "technology_component_", "market_component_"))
    ]
    columns = [
        "ticker", "Name", "sector", "industry", "cik10", "fund_effective_accepted",
        "feature_available_from", "fund_effective_age_days", "fund_join_status",
        "ranking_eligible", "score_total", "free_data_selection_rank", "assets", "liabilities",
        *raw_components,
        "fundamental_evidence_present", "pit_future_row", "future_fundamental_row", "future_feature_row",
        "liabilities_to_assets", "assets_exact", "cash_exact", "long_term_debt_exact",
        "current_debt_exact", "total_debt_exact", "net_debt_exact", "exact_debt_to_assets",
        "exact_net_debt_to_assets", "debt_scope_status", "unit_consistent", "debt_measurement_status",
        "exact_debt_component_coverage", "balance_resilience_score_before_exact_debt",
        "exact_net_debt_score", "balance_resilience_score", "balance_coverage",
        "economic_durability_score", "economic_coverage",
        "technology_business", "technology_reinvestment_score", "technology_coverage",
        "market_confirmation_score_clean", "market_coverage", "core_quality_coverage",
        "business_quality_score", "durable_quality_review_score", "economic_moat_evidence",
        "technology_moat_evidence", "textual_business_moat_review_required", "candidate_status",
        "company_review_id", "share_class_count", "company_review_primary",
        "selector_or_rank_changed", *component_scores,
    ]
    return frame[existing_columns(frame, dict.fromkeys(columns))].copy()


def slim_checklist_output(frame: pd.DataFrame, *, include_grade: bool) -> pd.DataFrame:
    columns = [
        "decision_date", "decision_time_utc", "portfolio_kind", "scenario", "ticker",
        "prior_holding", "prior_weight", "selector_selected", "selector_reason_code",
        "published_rank", "final_rank", "advisory_weight", "operating_target_weight",
        "simulated_fill_weight", "observed_decision_type", "candidate_status",
        "debt_measurement_status", "exact_debt_component_coverage", "core_quality_coverage",
        "balance_resilience_score", "balance_coverage", "economic_durability_score",
        "economic_coverage", "technology_reinvestment_score", "technology_coverage",
        "market_confirmation_score_clean", "market_coverage", "economic_moat_evidence",
        "technology_moat_evidence", "risk_state", "risk_advisory_action", "reason_codes",
        "check_pit_no_future", "check_core_quality_coverage", "check_balance_not_red",
        "check_economic_durability", "check_market_confirmation", "check_risk_clear",
        "check_exact_debt_available", "buy_hold_checklist_status", "sell_replace_checklist_status",
        "portfolio_action_authorized", "automatic_model_update_allowed",
        "outcome_21d_status", "outcome_21d_spy_excess_total_return",
        "outcome_63d_status", "outcome_63d_spy_excess_total_return",
    ]
    if include_grade:
        columns.extend(
            [
                "grade_horizon", "grade_excess_return", "grade_status", "answer_label",
                "answer_note", "checklist_change_proposed", "automatic_checklist_change_allowed",
            ]
        )
    return frame[existing_columns(frame, columns)].copy()


def build(args: argparse.Namespace) -> dict[str, Any]:
    context_path = repo_path(args.selection_context)
    status_path = repo_path(args.current_status)
    output_dir = repo_path(args.output_dir)
    risk_path = repo_path(args.risk_watch) if str(args.risk_watch or "").strip() else None
    debt_path = (
        repo_path(args.exact_debt_snapshot)
        if str(getattr(args, "exact_debt_snapshot", "") or "").strip()
        else None
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_time = pd.to_datetime(args.decision_time_utc, errors="raise", utc=True)
    context = pd.read_parquet(context_path)
    if debt_path is not None and debt_path.is_file():
        debt = pd.read_csv(debt_path, low_memory=False)
        if "ticker" not in debt:
            raise ValueError("exact debt snapshot missing ticker")
        debt["ticker"] = debt["ticker"].astype(str).str.upper().str.strip()
        debt = debt.drop_duplicates("ticker", keep="last")
        overlap = sorted((set(context.columns) & set(debt.columns)) - {"ticker"})
        context = context.drop(columns=overlap, errors="ignore").merge(
            debt, on="ticker", how="left", validate="one_to_one"
        )
    current_status = pd.read_parquet(status_path)
    quality = build_quality_universe(context, pd.Timestamp(decision_time))
    risk = load_optional_risk(risk_path)
    checklist = build_trade_checklist(current_status, quality, risk)
    notebook = build_mistake_notebook(checklist)
    candidate_statuses = {"REVIEW_CANDIDATE_COMPLETE", "REVIEW_CANDIDATE_PARTIAL", "QUALITY_MARKET_DIVERGENCE"}
    queue = quality[
        quality["candidate_status"].isin(candidate_statuses)
        & quality["company_review_primary"].astype(bool)
    ].sort_values(
        ["candidate_status", "durable_quality_review_score", "ticker"],
        ascending=[True, False, True],
    )

    quality_export = slim_quality_output(quality)
    queue_export = slim_quality_output(queue)
    checklist_export = slim_checklist_output(checklist, include_grade=False)
    notebook_export = slim_checklist_output(notebook, include_grade=True)
    quality_export.to_csv(output_dir / "durable_quality_universe.csv", index=False, lineterminator="\n")
    queue_export.to_csv(output_dir / "durable_quality_review_queue.csv", index=False, lineterminator="\n")
    checklist_export.to_csv(output_dir / "buy_hold_sell_checklist.csv", index=False, lineterminator="\n")
    notebook_export.to_csv(output_dir / "trade_answer_notebook.csv", index=False, lineterminator="\n")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_RUN287_DURABLE_QUALITY_LEARNING_REVIEW_ONLY",
        "decision_time_utc": pd.Timestamp(decision_time).isoformat(),
        "universe_count": int(quality["ticker"].nunique()),
        "candidate_counts": {str(k): int(v) for k, v in quality["candidate_status"].value_counts().items()},
        "candidate_company_count": int(queue["company_review_id"].nunique()),
        "exact_debt_complete_count": int(quality["exact_debt_component_coverage"].eq(1.0).sum()),
        "total_liabilities_proxy_only_count": int(
            quality["debt_measurement_status"].eq("TOTAL_LIABILITIES_PROXY_ONLY").sum()
        ),
        "future_row_count": int(quality["pit_future_row"].sum()),
        "trade_checklist_row_count": int(len(checklist)),
        "answer_ready_count": int(notebook["grade_status"].eq("GRADE_READY").sum()),
        "primary_grade_horizon_sessions": PRIMARY_GRADE_HORIZON,
        "secondary_grade_horizon_sessions": SECONDARY_GRADE_HORIZON,
        "source_inputs": {
            "selection_context": fingerprint(context_path),
            "current_status": fingerprint(status_path),
            "risk_watch": fingerprint(risk_path) if risk_path else {"exists": False, "path": ""},
            "exact_debt_snapshot": fingerprint(debt_path) if debt_path else {"exists": False, "path": ""},
        },
        "outputs": {
            name: fingerprint(output_dir / name)
            for name in (
                "durable_quality_universe.csv",
                "durable_quality_review_queue.csv",
                "buy_hold_sell_checklist.csv",
                "trade_answer_notebook.csv",
            )
        },
        "quantitative_moat_is_proof": False,
        "exact_debt_required_for_promotion": True,
        "textual_moat_review_required": True,
        "model_mutated": False,
        "score_mutated": False,
        "rank_mutated": False,
        "selector_mutated": False,
        "target_books_mutated": False,
        "cash_policy_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "automatic_checklist_change_allowed": False,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(output_dir, summary, queue)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-context", required=True)
    parser.add_argument("--current-status", required=True)
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--risk-watch", default="")
    parser.add_argument("--exact-debt-snapshot", default="")
    parser.add_argument("--output-dir", default="outputs/run287_durable_quality_learning")
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
