"""Research-only candidate lane scoring for AlphaOps vNext.

The lane router is intentionally sidecar-only. It does not write production
scores, feature-store schemas, or target defaults. Financial quality is strict
only for the quality-compounder lane; emerging tenbagger candidates can survive
weak current financials when theme, relative strength, liquidity, and evidence
are strong.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


LANES = (
    "QUALITY_COMPOUNDER",
    "MARKET_LEADER",
    "EMERGING_TENBAGGER",
    "TOP7_MANAGER_DISCOVERY",
    "CYCLICAL_RECOVERY",
    "CRISIS_BENEFICIARY",
)

LANE_FEATURE_MAPPING: dict[str, list[str]] = {
    "QUALITY_COMPOUNDER": [
        "sector_adjusted_quality_score",
        "capital_efficiency_score",
        "long_hold_compounder_score",
        "fundamental_reliability_score",
        "quality_growth_score",
        "fcf_margin",
        "rule_of_40",
    ],
    "MARKET_LEADER": [
        "rs_benchmark_1w",
        "rs_spy_1w",
        "rs_qqq_1w",
        "rs_benchmark_3m",
        "rs_benchmark_6m",
        "rs_semis_1m",
        "rs_semis_3m",
        "relative_strength_composite",
        "industry_group_strength_score",
        "oneil_leadership_score",
        "sub_industry_rs_score",
        "portfolio_future_winner_engine_score",
    ],
    "EMERGING_TENBAGGER": [
        "theme_phase_multiplier_primary",
        "theme_phase_multiplier_max",
        "portfolio_early_scout_engine_score",
        "portfolio_monster_early_score",
        "portfolio_future_winner_engine_score",
        "rs_benchmark_3m",
        "rs_acceleration_score",
        "dollar_vol_20d",
        "sec_form4_cluster_buy_score",
        "sec_13f_smart_money_score",
        "etf_theme_leadership_score",
    ],
    "TOP7_MANAGER_DISCOVERY": [
        "top7_discovery_score",
        "top_manager_discovery_score",
        "sec_13f_smart_money_score",
        "sec_13f_new_position_score",
        "post_disclosure_alpha_score",
        "issuer_float_impact_score",
    ],
    "CYCLICAL_RECOVERY": [
        "rs_sector_3m",
        "rs_industry_12m",
        "industry_group_strength_score",
        "earnings_inflection_score",
        "valuation_recovery_score",
        "inventory_cycle_recovery_score",
    ],
    "CRISIS_BENEFICIARY": [
        "defensive_rotation_score",
        "portfolio_defensive_rotation_action_score",
        "macro_regime_fit_score",
        "low_beta_score",
        "balance_sheet_score",
    ],
}

EMERGING_RISK_FIELDS = [
    "cash_runway_quarters",
    "dilution_4q",
    "shares_yoy",
    "sbc_to_revenue",
    "capex_to_revenue",
    "debt_refinancing_risk",
    "gross_margin_direction",
    "revenue_acceleration",
    "backlog_or_contract_signal",
]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def materialize_sector_relative_strength(
    frame: pd.DataFrame,
    *,
    periods: tuple[tuple[str, str], ...] = (
        ("mom_1m", "rs_sector_1m"),
        ("mom_3m", "rs_sector_3m"),
        ("mom_6m", "rs_sector_6m"),
        ("mom_12m", "rs_sector_12m"),
    ),
    fill_missing_only: bool = False,
) -> pd.DataFrame:
    """Materialize the canonical same-date, same-sector momentum residual.

    The calculation is entirely cross-sectional at the decision date.  It
    never uses a later return.  ``fill_missing_only`` supports append-only
    repair sidecars: existing finite evidence is preserved and only missing
    cells receive the canonical value.
    """

    out = frame.copy()
    required = {"rebalance_date", "sector"}
    if not required.issubset(out.columns):
        missing = ",".join(sorted(required - set(out.columns)))
        raise ValueError(f"sector relative strength requires:{missing}")
    dates = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    sectors = out["sector"].fillna("").astype(str).str.strip()
    if dates.isna().any() or sectors.eq("").any():
        raise ValueError("sector relative strength requires valid date and sector")
    group_keys = [dates, sectors]
    for momentum_column, output_column in periods:
        if momentum_column not in out.columns:
            raise ValueError(f"sector relative strength missing:{momentum_column}")
        momentum = pd.to_numeric(out[momentum_column], errors="coerce")
        group_mean = momentum.groupby(group_keys, sort=False).transform("mean")
        computed = momentum - group_mean
        if fill_missing_only and output_column in out.columns:
            existing = pd.to_numeric(out[output_column], errors="coerce")
            out[output_column] = existing.where(existing.notna(), computed)
        else:
            out[output_column] = computed
        out[output_column] = pd.to_numeric(
            out[output_column], errors="coerce"
        ).fillna(0.0)
    return out


def robust_z(values: pd.Series) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").fillna(0.0)
    med = float(x.median())
    mad = float((x - med).abs().median())
    if mad <= 1e-12:
        std = float(x.std(ddof=0))
        if std <= 1e-12:
            return pd.Series(0.0, index=x.index)
        return ((x - float(x.mean())) / std).clip(-3.0, 3.0)
    return ((x - med) / (1.4826 * mad)).clip(-3.0, 3.0)


def positive_z(frame: pd.DataFrame, col: str) -> pd.Series:
    return robust_z(numeric(frame, col, 0.0)).clip(lower=0.0)


def weighted_positive(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
    if not cols:
        return pd.Series(0.0, index=frame.index)
    parts = [positive_z(frame, col) for col in cols]
    return sum(parts) / max(len(parts), 1)


def valuation_support_score(frame: pd.DataFrame) -> pd.Series:
    """Positive-only valuation support used by vNext production selection.

    Missing valuation fields are neutral. Expensive valuations do not hard
    reject a candidate here; they simply fail to earn the support boost.
    """

    parts: list[pd.Series] = []
    inverse_cols = [
        "forward_pe",
        "pe_forward",
        "peg_ratio",
        "peg",
        "ev_ebitda",
        "ev_to_ebitda",
        "ev_sales",
        "ev_to_sales",
        "sector_relative_valuation",
        "valuation_percentile_sector",
    ]
    for col in inverse_cols:
        if col in frame.columns:
            raw = pd.to_numeric(frame[col], errors="coerce")
            fill = float(raw.median(skipna=True)) if raw.notna().any() else 0.0
            support = (-robust_z(raw.fillna(fill))).clip(lower=0.0)
            parts.append(support.where(raw.notna(), 0.0))
    for col in ["fcf_yield", "free_cash_flow_yield", "earnings_yield", "valuation_recovery_score"]:
        if col in frame.columns:
            raw = pd.to_numeric(frame[col], errors="coerce")
            support = positive_z(frame, col)
            parts.append(support.where(raw.notna(), 0.0))
    if not parts:
        return pd.Series(0.0, index=frame.index, dtype=float)
    return (sum(parts) / len(parts)).clip(lower=0.0)


def theme_state_strength(frame: pd.DataFrame) -> pd.Series:
    text = pd.Series("", index=frame.index, dtype=object)
    for col in ("theme_phase_primary", "theme_horizon_primary", "theme_holding_profile_primary"):
        if col in frame.columns:
            text = text.astype(str) + " " + frame[col].astype(str)
    low = text.str.lower()
    score = pd.Series(0.0, index=frame.index, dtype=float)
    score = score.mask(low.str.contains("leading|confirmed|structural", regex=True), 1.0)
    score = score.mask(low.str.contains("emerging|watch", regex=True), 0.6)
    score = score.mask(low.str.contains("fading|dead|ending", regex=True), -1.0)
    return score


def liquidity_score(frame: pd.DataFrame) -> pd.Series:
    dollar_vol = numeric(frame, "dollar_vol_20d", np.nan)
    if dollar_vol.isna().all():
        dollar_vol = numeric(frame, "avg_dollar_volume_20d", 0.0)
    return robust_z(np.log1p(dollar_vol.fillna(0.0))).clip(lower=-2.0, upper=3.0)


def emerging_hard_reject_reason(frame: pd.DataFrame) -> pd.Series:
    reasons: list[str] = []
    dollar_vol = numeric(frame, "dollar_vol_20d", np.nan)
    market_cap = numeric(frame, "market_cap_live", np.nan)
    data_conf = numeric(frame, "data_confidence", 1.0)
    runway = numeric(frame, "cash_runway_quarters", 99.0)
    dilution = numeric(frame, "dilution_4q", 0.0)
    price_alive = numeric(frame, "price_above_ma200", 1.0) + numeric(frame, "price_above_ma50", 1.0)
    for idx in frame.index:
        row_reasons: list[str] = []
        if pd.notna(dollar_vol.loc[idx]) and float(dollar_vol.loc[idx]) < 5_000_000:
            row_reasons.append("liquidity_too_low")
        if pd.notna(market_cap.loc[idx]) and float(market_cap.loc[idx]) < 250_000_000:
            row_reasons.append("market_cap_below_minimum")
        if float(data_conf.loc[idx]) < 0.35:
            row_reasons.append("data_confidence_too_low")
        if float(runway.loc[idx]) < 2.0 and float(dilution.loc[idx]) > 0.35:
            row_reasons.append("extreme_dilution_cash_runway_crisis")
        if float(price_alive.loc[idx]) <= 0.0:
            row_reasons.append("price_trend_not_alive")
        reasons.append(",".join(row_reasons))
    return pd.Series(reasons, index=frame.index, dtype=object)


def emerging_negative_fcf(frame: pd.DataFrame) -> pd.Series:
    fcf_ttm = numeric(frame, "fcf_ttm", 0.0)
    fcf_margin = numeric(frame, "fcf_margin", 0.0)
    return (fcf_ttm < 0.0) | (fcf_margin < 0.0)


def emerging_operating_loss(frame: pd.DataFrame) -> pd.Series:
    net_income = numeric(frame, "net_income_ttm", 0.0)
    op_income = numeric(frame, "op_income_ttm", 0.0)
    operating_margin = numeric(frame, "operating_margin", 0.0)
    return (net_income < 0.0) | (op_income < 0.0) | (operating_margin < 0.0)


def emerging_risk_cap(frame: pd.DataFrame) -> pd.Series:
    cap = pd.Series(1.0, index=frame.index, dtype=float)
    negative_fcf = emerging_negative_fcf(frame)
    operating_loss = emerging_operating_loss(frame)
    sbc = numeric(frame, "sbc_to_revenue", 0.0)
    dilution = numeric(frame, "dilution_4q", 0.0) + numeric(frame, "shares_yoy", 0.0).clip(lower=0.0)
    volatility = numeric(frame, "atr14_pct", 0.0)
    runway = numeric(frame, "cash_runway_quarters", 99.0)
    cap = cap.mask(negative_fcf, cap * 0.85)
    cap = cap.mask(operating_loss, cap * 0.90)
    cap = cap.mask(sbc > 0.25, cap * 0.80)
    cap = cap.mask(dilution > 0.20, cap * 0.70)
    cap = cap.mask(volatility > 0.08, cap * 0.80)
    cap = cap.mask(runway < 4.0, cap * 0.65)
    return cap.clip(lower=0.10, upper=1.0)


def score_candidate_lanes(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    if d.empty:
        return d
    quality = weighted_positive(d, LANE_FEATURE_MAPPING["QUALITY_COMPOUNDER"])
    valuation = valuation_support_score(d)
    market = (
        0.08 * positive_z(d, "rs_benchmark_1w")
        + 0.24 * positive_z(d, "rs_benchmark_3m")
        + 0.17 * positive_z(d, "rs_benchmark_6m")
        + 0.10 * positive_z(d, "rs_semis_1m")
        + 0.09 * positive_z(d, "rs_semis_3m")
        + 0.17 * positive_z(d, "relative_strength_composite")
        + 0.13 * positive_z(d, "industry_group_strength_score")
        + 0.08 * positive_z(d, "portfolio_future_winner_engine_score")
        + 0.04 * liquidity_score(d).clip(lower=0.0)
    )
    smart = (
        0.35 * positive_z(d, "sec_13f_smart_money_score")
        + 0.25 * positive_z(d, "sec_13f_new_position_score")
        + 0.20 * positive_z(d, "sec_form4_cluster_buy_score")
        + 0.20 * positive_z(d, "etf_theme_leadership_score")
    )
    emerging = (
        0.25 * (theme_state_strength(d).clip(lower=0.0) + positive_z(d, "theme_phase_multiplier_primary")) / 2.0
        + 0.25 * (positive_z(d, "rs_benchmark_3m") + positive_z(d, "rs_benchmark_1w") + positive_z(d, "rs_acceleration_score")) / 3.0
        + 0.15 * (positive_z(d, "revenue_acceleration") + positive_z(d, "backlog_or_contract_signal")) / 2.0
        + 0.15 * liquidity_score(d).clip(lower=0.0)
        + 0.10 * smart
        + 0.05 * positive_z(d, "portfolio_early_scout_engine_score")
        + 0.05 * positive_z(d, "portfolio_monster_early_score")
    )
    top7 = weighted_positive(d, LANE_FEATURE_MAPPING["TOP7_MANAGER_DISCOVERY"])
    cyclical = 0.80 * weighted_positive(d, LANE_FEATURE_MAPPING["CYCLICAL_RECOVERY"]) + 0.20 * valuation
    defensive_sector = d.get("sector", pd.Series("", index=d.index)).astype(str).str.lower().str.contains("utility|staple|health|defensive")
    crisis = weighted_positive(d, LANE_FEATURE_MAPPING["CRISIS_BENEFICIARY"]) + defensive_sector.astype(float) * 0.5

    hard_reject = emerging_hard_reject_reason(d)
    risk_cap = emerging_risk_cap(d)
    d["quality_compounder_lane_score"] = quality
    d["market_leader_lane_score"] = market
    d["valuation_support_score"] = valuation
    d["emerging_tenbagger_lane_score_raw"] = emerging
    d["emerging_tenbagger_risk_cap"] = risk_cap
    d["emerging_tenbagger_hard_reject_reason"] = hard_reject
    d["emerging_tenbagger_lane_score"] = emerging * risk_cap
    d.loc[hard_reject.astype(str).ne(""), "emerging_tenbagger_lane_score"] = -999.0
    d["top7_manager_discovery_lane_score"] = top7
    d["top7_manager_discovery_support_only"] = top7
    d["cyclical_recovery_lane_score"] = cyclical
    d["crisis_beneficiary_lane_score"] = crisis

    lane_cols = {
        "QUALITY_COMPOUNDER": "quality_compounder_lane_score",
        "MARKET_LEADER": "market_leader_lane_score",
        "EMERGING_TENBAGGER": "emerging_tenbagger_lane_score",
        "TOP7_MANAGER_DISCOVERY": "top7_manager_discovery_lane_score",
        "CYCLICAL_RECOVERY": "cyclical_recovery_lane_score",
        "CRISIS_BENEFICIARY": "crisis_beneficiary_lane_score",
    }
    scores = pd.DataFrame({lane: pd.to_numeric(d[col], errors="coerce").fillna(-999.0) for lane, col in lane_cols.items()}, index=d.index)
    confirming_lanes = scores[
        ["QUALITY_COMPOUNDER", "MARKET_LEADER", "EMERGING_TENBAGGER", "CYCLICAL_RECOVERY", "CRISIS_BENEFICIARY"]
    ].max(axis=1)
    top7_standalone = scores["TOP7_MANAGER_DISCOVERY"].gt(confirming_lanes) & confirming_lanes.lt(0.20)
    scores.loc[top7_standalone, "TOP7_MANAGER_DISCOVERY"] = -999.0
    d["top7_standalone_blocked"] = top7_standalone
    d["top7_support_boost"] = d["top7_manager_discovery_support_only"].clip(lower=0.0) * (~top7_standalone).astype(float)
    for lane in ["QUALITY_COMPOUNDER", "MARKET_LEADER", "EMERGING_TENBAGGER", "CYCLICAL_RECOVERY"]:
        scores[lane] = scores[lane] + 0.08 * d["top7_support_boost"]
    d["primary_lane"] = scores.idxmax(axis=1)
    d["lane_confidence"] = scores.max(axis=1).replace(-999.0, 0.0).clip(lower=0.0)
    secondaries = []
    for idx, row in scores.iterrows():
        secondaries.append(",".join([lane for lane, score in row.items() if score > 0.25 and lane != d.at[idx, "primary_lane"]]))
    d["secondary_lanes"] = secondaries
    d["lane_reason"] = d["primary_lane"].astype(str) + "_score_selected"
    d["theme_reason"] = np.where(theme_state_strength(d) > 0, "theme_active", "")
    d["evidence_reason"] = np.where(smart > 0, "positive_smart_money_or_etf_evidence", "")
    return d


def lane_feature_mapping_payload() -> dict[str, Any]:
    return {
        "schema_version": "lane-feature-mapping-v1",
        "lanes": LANE_FEATURE_MAPPING,
        "emerging_risk_fields": EMERGING_RISK_FIELDS,
        "rules": {
            "financial_quality_strict_only_for": "QUALITY_COMPOUNDER",
            "negative_fcf_for_emerging": "risk_cap_not_hard_reject",
            "top7_13f": "universe_expansion_and_confidence_only_not_standalone_buy",
            "valuation": "positive_support_only_missing_is_neutral",
        },
    }
