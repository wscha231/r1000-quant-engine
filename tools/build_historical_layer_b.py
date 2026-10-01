#!/usr/bin/env python3
"""Build historical Layer-B B1 from contemporaneous candidate-book fundamentals.

Research-only PIT proxy. Future return columns are retained only for later replay
evaluation and are never used by feature construction or ranking.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

FORBIDDEN_OUTCOME_COLUMNS = {"r_1m", "y_blend", "period_forward_return"}
FEATURE_INPUTS = {
    "leadership": ["mom_1m", "mom_3m", "mom_6m", "mom_12m", "industry_group_strength_score"],
    "growth": ["sales_growth_yoy", "eps_growth_yoy", "ocf_growth_yoy", "revenue_growth_final", "rev_growth_accel_4q"],
    "quality": ["operating_margins", "roe_proxy"],
    "valuation_raw": ["revenues_ttm", "net_income_ttm", "ocf_ttm", "capex_ttm", "mktcap"],
    "risk": ["atr14_pct", "dollar_vol_20d"],
}
assert not (set(sum(FEATURE_INPUTS.values(), [])) & FORBIDDEN_OUTCOME_COLUMNS)


def pct(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rank(pct=True, method="average") * 100.0


def sector_pct(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    out = pd.Series(index=frame.index, dtype=float)
    for _, index in frame.groupby(frame["sector"].fillna("UNKNOWN")).groups.items():
        out.loc[index] = values.loc[index].rank(pct=True, method="average") * 100.0
    return out


def observed_mean(frame: pd.DataFrame, columns: list[str]) -> tuple[pd.Series, pd.Series]:
    values = frame[columns]
    return values.mean(axis=1, skipna=True), values.notna().sum(axis=1)


def build(source: Path) -> pd.DataFrame:
    raw = pd.read_csv(source, low_memory=False)
    needed = {"rebalance_date", "ticker", "sector", "industry_group", *sum(FEATURE_INPUTS.values(), [])}
    missing = needed - set(raw.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    keep = needed | FORBIDDEN_OUTCOME_COLUMNS | {"regime_state"}
    frame = raw[[column for column in raw.columns if column in keep]].copy()
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce")
    for column in set(sum(FEATURE_INPUTS.values(), [])) | FORBIDDEN_OUTCOME_COLUMNS:
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["fcf_ttm_b1"] = frame["ocf_ttm"] - frame["capex_ttm"]
    positive_mcap = frame["mktcap"].where(frame["mktcap"] > 0)
    frame["earnings_yield_b1"] = frame["net_income_ttm"] / positive_mcap
    frame["fcf_yield_b1"] = frame["fcf_ttm_b1"] / positive_mcap
    frame["sales_yield_b1"] = frame["revenues_ttm"] / positive_mcap
    frame["fcf_margin_b1"] = frame["fcf_ttm_b1"] / frame["revenues_ttm"].where(frame["revenues_ttm"].abs() > 0)

    groups = []
    for _, group in frame.groupby("rebalance_date", sort=True):
        group = group.copy()
        for column in ["mom_1m", "mom_3m", "mom_6m", "mom_12m", "industry_group_strength_score"]:
            group[f"p_{column}"] = pct(group[column])
        group["leadership_score_b1"] = (
            0.20 * group["p_mom_1m"]
            + 0.30 * group["p_mom_3m"]
            + 0.30 * group["p_mom_6m"]
            + 0.20 * group["p_mom_12m"]
        )
        industry_ok = group["p_industry_group_strength_score"].isna() | (group["p_industry_group_strength_score"] >= 40)
        lead_cut = group["leadership_score_b1"].quantile(0.80)
        group["candidate_discovery_pass_b1"] = (group["leadership_score_b1"] >= lead_cut) & industry_ok

        growth_columns = []
        for column in FEATURE_INPUTS["growth"]:
            percentile = f"p_{column}"
            group[percentile] = pct(group[column])
            growth_columns.append(percentile)
        group["growth_score_b1"], group["growth_fields_b1"] = observed_mean(group, growth_columns)

        quality_columns = []
        for column in ["operating_margins", "roe_proxy", "fcf_margin_b1"]:
            percentile = f"p_{column}"
            group[percentile] = pct(group[column])
            quality_columns.append(percentile)
        group["quality_score_b1"], group["quality_fields_b1"] = observed_mean(group, quality_columns)

        valuation_columns = []
        for column in ["earnings_yield_b1", "fcf_yield_b1", "sales_yield_b1"]:
            percentile = f"sector_p_{column}"
            group[percentile] = sector_pct(group, column)
            valuation_columns.append(percentile)
        group["valuation_score_b1"], group["valuation_fields_b1"] = observed_mean(group, valuation_columns)

        group["p_low_atr_b1"] = 100.0 - pct(group["atr14_pct"])
        group["p_liquidity_b1"] = pct(np.log1p(group["dollar_vol_20d"].clip(lower=0)))
        group["risk_liquidity_score_b1"], group["risk_fields_b1"] = observed_mean(group, ["p_low_atr_b1", "p_liquidity_b1"])

        weights = {"growth_score_b1": 0.35, "quality_score_b1": 0.25, "valuation_score_b1": 0.25, "risk_liquidity_score_b1": 0.15}
        numerator = sum(group[column].fillna(0) * weight for column, weight in weights.items())
        denominator = sum(group[column].notna().astype(float) * weight for column, weight in weights.items())
        group["expected_return_proxy_b1"] = numerator / denominator.replace(0, np.nan)
        group["layer_b_coverage_b1"] = (
            group["growth_fields_b1"] + group["quality_fields_b1"] + group["valuation_fields_b1"] + group["risk_fields_b1"]
        ) / 13.0
        group["expected_return_confidence_adj_b1"] = group["expected_return_proxy_b1"] * (0.80 + 0.20 * group["layer_b_coverage_b1"].clip(0, 1))
        group["layer_b_status"] = "PIT_PROXY_RESEARCH_ONLY"
        groups.append(group)
    return pd.concat(groups, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()
    output = build(Path(args.source))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.out, index=False, compression="gzip")
    summary = {
        "schema_version": "historical-layer-b-b1-v1",
        "status": "completed",
        "authority": "RESEARCH_ONLY",
        "pit_status": "PIT_PROXY_NOT_INTRADAY_CERTIFIED",
        "rows": len(output),
        "tickers": int(output.ticker.nunique()),
        "decision_dates": int(output.rebalance_date.nunique()),
        "first_date": str(output.rebalance_date.min().date()),
        "last_date": str(output.rebalance_date.max().date()),
        "candidate_pass_rows": int(output.candidate_discovery_pass_b1.sum()),
        "mean_layer_b_coverage": float(output.layer_b_coverage_b1.mean()),
        "outcome_columns_excluded_from_features": sorted(FORBIDDEN_OUTCOME_COLUMNS),
        "weights": {
            "leadership": {"1m": 0.20, "3m": 0.30, "6m": 0.30, "12m": 0.20},
            "expected_return_proxy": {"growth": 0.35, "quality": 0.25, "valuation": 0.25, "risk_liquidity": 0.15},
        },
        "consensus_history_policy": "B2_ONLY_WHERE_REAL_ARCHIVED_FORWARD_SNAPSHOT_EXISTED_NO_BACKFILL",
    }
    Path(args.summary).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
