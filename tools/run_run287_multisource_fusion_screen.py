#!/usr/bin/env python3
"""Research-only run287 multi-source fusion screen.

Combines decision-time W4 SEC evidence, financial statement proxies,
technical/momentum features, macro/regime features, and risk-control fields
into fixed source-screen scores. `period_forward_return` is used only as an
audit label. This tool does not add alpha hooks, tune thresholds, dispatch a
fullrun, or mutate production state.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_run287_w4_form4_13f_source_screen import (  # noqa: E402
    DEFAULT_13F_PATH,
    DEFAULT_CANDIDATE_BOOK,
    DEFAULT_FORM4_PATH,
    DEFAULT_MANAGER_UNIVERSE,
    add_w4_scores,
    build_13f_source_events,
    build_form4_source_events,
    clean_ticker,
)

SCHEMA_VERSION = "run287-multisource-fusion-screen-v1"
DEFAULT_OUTPUT_DIR = "outputs/run287_multisource_fusion_screen"
DEFAULT_OOS_START = "2024-07-01"

BASE_COLUMNS = ["rebalance_date", "ticker", "Name", "sector", "industry_group", "period_forward_return"]
FINANCIAL_COLUMNS = [
    "actual_results_score",
    "selection_confirmation_score",
    "profitability_inflection_score",
    "capital_efficiency_score",
    "sector_adjusted_quality_score",
    "fundamental_reliability_score",
    "gross_margins",
    "operating_margins",
    "sales_growth_yoy",
    "eps_growth_yoy",
    "op_income_growth_yoy",
    "ocf_growth_yoy",
    "revenue_growth_final",
    "rev_growth_accel_4q",
]
TECHNICAL_POSITIVE_COLUMNS = [
    "relative_strength_composite",
    "rs_acceleration_score",
    "mom_3m",
    "mom_6m",
    "mom_12m",
    "ml_technical_agreement_score",
    "trend_template_full",
    "breakout_setup_quality_score",
    "volatility_contraction_score",
    "entry_quality_score",
    "post_breakout_hold_score",
    "price_above_ma50",
    "price_above_ma200",
    "near_52w_high_pct",
]
MACRO_POSITIVE_COLUMNS = [
    "style_row_breakout_fit",
    "style_row_turnaround_fit",
    "style_row_compounder_fit",
    "style_liquidity_tailwind_score",
    "regime_state_score",
]
MACRO_NEGATIVE_COLUMNS = [
    "style_rate_pressure_score",
    "style_inflation_pressure_score",
    "style_overheat_risk_score",
]
RISK_NEGATIVE_COLUMNS = [
    "risk_penalty",
    "stage2_overext_penalty",
    "overheat_penalty",
    "portfolio_risk_entry_block_score",
    "atr14_pct",
    "live_event_risk_score",
]
SLEEVE_COLUMNS = [
    "w4_sec_score",
    "financial_statement_proxy_score",
    "technical_momentum_score",
    "macro_regime_score",
    "risk_control_score",
]
FUSION_COLUMNS = [
    *SLEEVE_COLUMNS,
    "all_source_equal_score",
    "growth_confirmation_score",
    "drawdown_aware_fusion_score",
    "three_plus_sleeve_consensus_score",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def available_columns(path: Path) -> list[str]:
    if not path.exists():
        return []
    return list(pd.read_csv(path, nrows=0).columns)


def read_candidate_book(path: Path) -> pd.DataFrame:
    cols = available_columns(path)
    if not cols:
        return pd.DataFrame()
    wanted = list(dict.fromkeys(BASE_COLUMNS + FINANCIAL_COLUMNS + TECHNICAL_POSITIVE_COLUMNS + MACRO_POSITIVE_COLUMNS + MACRO_NEGATIVE_COLUMNS + RISK_NEGATIVE_COLUMNS))
    usecols = [col for col in wanted if col in cols]
    return pd.read_csv(path, usecols=usecols, low_memory=False)


def prepare_candidate_book(frame: pd.DataFrame, oos_start: str) -> pd.DataFrame:
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d.get("rebalance_date"), errors="coerce").dt.normalize()
    d["ticker"] = d.get("ticker", pd.Series(index=d.index, dtype=object)).map(clean_ticker)
    d["forward_return_audit_only"] = pd.to_numeric(d.get("period_forward_return"), errors="coerce")
    d = d[d["rebalance_date"].notna() & d["ticker"].ne("") & d["forward_return_audit_only"].notna()].copy()
    d["split"] = np.where(d["rebalance_date"].ge(pd.Timestamp(oos_start)), "oos", "is")
    return d.reset_index(drop=True)


def signed_cross_sectional_rank(frame: pd.DataFrame, column: str, *, invert: bool = False) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    values = pd.to_numeric(frame[column], errors="coerce")

    def rank_group(group: pd.Series) -> pd.Series:
        valid = group.dropna()
        if valid.nunique() < 2:
            return pd.Series(0.5, index=group.index, dtype=float)
        return group.rank(method="average", pct=True).fillna(0.5)

    ranks = values.groupby(frame["rebalance_date"], group_keys=False).apply(rank_group)
    signed = 2.0 * (ranks.astype(float) - 0.5)
    if invert:
        signed = -signed
    return signed.clip(-1.0, 1.0)


def mean_score(frame: pd.DataFrame, positive_columns: list[str], negative_columns: list[str] | None = None) -> tuple[pd.Series, list[str]]:
    pieces: list[pd.Series] = []
    used: list[str] = []
    for col in positive_columns:
        if col in frame.columns:
            pieces.append(signed_cross_sectional_rank(frame, col, invert=False))
            used.append(col)
    for col in negative_columns or []:
        if col in frame.columns:
            pieces.append(signed_cross_sectional_rank(frame, col, invert=True))
            used.append(f"-{col}")
    if not pieces:
        return pd.Series(0.0, index=frame.index, dtype=float), used
    scores = pd.concat(pieces, axis=1).mean(axis=1, skipna=True).fillna(0.0).clip(-1.0, 1.0)
    return scores, used


def add_source_scores(candidate: pd.DataFrame, form4_events: pd.DataFrame, sec13f_events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    d = add_w4_scores(candidate, form4_events, sec13f_events)
    d["w4_sec_score"] = pd.to_numeric(d.get("w4_combined_score"), errors="coerce").fillna(0.0).clip(-1.0, 1.0)
    financial, financial_used = mean_score(d, FINANCIAL_COLUMNS)
    technical, technical_used = mean_score(d, TECHNICAL_POSITIVE_COLUMNS)
    macro, macro_used = mean_score(d, MACRO_POSITIVE_COLUMNS, MACRO_NEGATIVE_COLUMNS)
    risk_control, risk_used = mean_score(d, [], RISK_NEGATIVE_COLUMNS)
    d["financial_statement_proxy_score"] = financial
    d["technical_momentum_score"] = technical
    d["macro_regime_score"] = macro
    d["risk_control_score"] = risk_control
    d["positive_sleeve_count"] = (d[SLEEVE_COLUMNS] > 0.0).sum(axis=1)
    d["negative_sleeve_count"] = (d[SLEEVE_COLUMNS] < 0.0).sum(axis=1)
    d["all_source_equal_score"] = d[SLEEVE_COLUMNS].mean(axis=1).clip(-1.0, 1.0)
    d["growth_confirmation_score"] = (
        0.25 * d["w4_sec_score"]
        + 0.25 * d["financial_statement_proxy_score"]
        + 0.30 * d["technical_momentum_score"]
        + 0.20 * d["macro_regime_score"]
    ).clip(-1.0, 1.0)
    d["drawdown_aware_fusion_score"] = (
        0.75 * d["growth_confirmation_score"] + 0.25 * d["risk_control_score"]
    ).clip(-1.0, 1.0)
    consensus_multiplier = (d["positive_sleeve_count"].clip(lower=0, upper=5) / 5.0).astype(float)
    d["three_plus_sleeve_consensus_score"] = np.where(
        d["positive_sleeve_count"].ge(3),
        d["all_source_equal_score"] * consensus_multiplier,
        np.where(d["negative_sleeve_count"].ge(3), d["all_source_equal_score"], 0.0),
    ).clip(-1.0, 1.0)
    used = {
        "financial_statement_proxy_score": financial_used,
        "technical_momentum_score": technical_used,
        "macro_regime_score": macro_used,
        "risk_control_score": risk_used,
        "w4_sec_score": ["w4_combined_score"],
    }
    return d, used


def quantile_stats(frame: pd.DataFrame, signal: str, min_rows: int) -> dict[str, Any]:
    d = frame[[signal, "forward_return_audit_only"]].dropna().copy()
    d = d[d[signal].astype(float).abs().gt(1.0e-12)].copy()
    if len(d) < min_rows or d[signal].nunique() < 2:
        return {"status": "insufficient_signal_coverage", "row_count": int(len(d))}
    try:
        d["quantile"] = pd.qcut(d[signal], q=min(5, d[signal].nunique()), labels=False, duplicates="drop")
    except ValueError:
        return {"status": "insufficient_unique_values", "row_count": int(len(d))}
    if d["quantile"].nunique() < 2:
        return {"status": "insufficient_quantiles", "row_count": int(len(d))}
    grouped = d.groupby("quantile")["forward_return_audit_only"].agg(["count", "mean"]).reset_index()
    low = grouped.sort_values("quantile").iloc[0]
    high = grouped.sort_values("quantile").iloc[-1]
    high_rows = d[d["quantile"].eq(high["quantile"])]
    spearman = float(d[signal].rank(method="average").corr(d["forward_return_audit_only"].rank(method="average")))
    return {
        "status": "ok",
        "row_count": int(len(d)),
        "spearman": spearman if math.isfinite(spearman) else 0.0,
        "low_quantile_count": int(low["count"]),
        "high_quantile_count": int(high["count"]),
        "low_quantile_mean": float(low["mean"]),
        "high_quantile_mean": float(high["mean"]),
        "high_minus_low": float(high["mean"] - low["mean"]),
        "high_quantile_positive_rate": float((high_rows["forward_return_audit_only"] > 0).mean()),
    }


def screen_signal(frame: pd.DataFrame, signal: str, min_rows: int, min_oos_high_count: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    split_stats: dict[str, dict[str, Any]] = {}
    for split, subset in [("full", frame), ("is", frame[frame["split"].eq("is")]), ("oos", frame[frame["split"].eq("oos")])]:
        stats = quantile_stats(subset, signal, min_rows)
        split_stats[split] = stats
        rows.append({"signal": signal, "split": split, **stats})
    full = split_stats.get("full", {})
    is_stats = split_stats.get("is", {})
    oos = split_stats.get("oos", {})
    source_positive = (
        full.get("status") == "ok"
        and is_stats.get("status") == "ok"
        and oos.get("status") == "ok"
        and safe_float(full.get("high_minus_low")) > 0.0
        and safe_float(is_stats.get("high_minus_low")) > 0.0
        and safe_float(oos.get("high_minus_low")) > 0.0
        and safe_float(oos.get("high_quantile_count")) >= min_oos_high_count
    )
    return (
        {
            "signal": signal,
            "source_positive": bool(source_positive),
            "full_high_minus_low": full.get("high_minus_low"),
            "is_high_minus_low": is_stats.get("high_minus_low"),
            "oos_high_minus_low": oos.get("high_minus_low"),
            "oos_high_quantile_count": oos.get("high_quantile_count"),
            "oos_high_quantile_positive_rate": oos.get("high_quantile_positive_rate"),
            "full_spearman": full.get("spearman"),
            "oos_spearman": oos.get("spearman"),
        },
        rows,
    )


def render_report(payload: dict[str, Any], signal_summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Run287 Multi-Source Fusion Screen",
        "",
        f"- Status: `{payload['status']}`",
        f"- Decision label: `{payload['decision_label']}`",
        f"- Candidate allowed: `{payload['candidate_allowed']}`",
        f"- Forward returns audit only: `{payload['forward_returns_audit_only']}`",
        "",
        "| Signal | Source positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in signal_summaries:
        lines.append(
            "| {signal} | {positive} | {full:.2%} | {is_:.2%} | {oos:.2%} | {count} | {hit:.2%} |".format(
                signal=item.get("signal"),
                positive=item.get("source_positive"),
                full=safe_float(item.get("full_high_minus_low")),
                is_=safe_float(item.get("is_high_minus_low")),
                oos=safe_float(item.get("oos_high_minus_low")),
                count=int(safe_float(item.get("oos_high_quantile_count"))),
                hit=safe_float(item.get("oos_high_quantile_positive_rate")),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This is a candidate-row source screen, not broker-ledger evidence.",
            "- The fusion scores use fixed source buckets: W4 SEC, financial proxy, technical/momentum, macro/regime, and risk control.",
            "- A positive screen only permits a default-off broker A/B review on official fixed books.",
            "- No fullrun, production promotion, live trading, or public performance claim is allowed from this artifact.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = repo_path(args.input)
    raw = read_candidate_book(candidate_path)
    if raw.empty:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "reason": "missing_or_empty_candidate_book",
            "input": str(candidate_path),
            "research_only": True,
            "production_promotion_allowed": False,
            "fullrun_dispatched": False,
        }
        write_json(output_dir / "summary.json", payload)
        return payload

    candidate = prepare_candidate_book(raw, args.oos_start)
    form4_events, form4_summary = build_form4_source_events(repo_path(args.form4_path), candidate)
    sec13f_events, sec13f_summary = build_13f_source_events(repo_path(args.sec13f_path), repo_path(args.manager_universe))
    enriched, source_columns_used = add_source_scores(candidate, form4_events, sec13f_events)

    signal_summaries: list[dict[str, Any]] = []
    stat_rows: list[dict[str, Any]] = []
    for signal in FUSION_COLUMNS:
        summary, rows = screen_signal(enriched, signal, args.min_rows, args.min_oos_high_count)
        signal_summaries.append(summary)
        stat_rows.extend(rows)
    positives = [item["signal"] for item in signal_summaries if item.get("source_positive")]
    preferred = [sig for sig in ["drawdown_aware_fusion_score", "all_source_equal_score", "growth_confirmation_score"] if sig in positives]
    decision_label = (
        "multisource_fusion_positive_requires_broker_ab_review"
        if preferred
        else "single_sleeve_positive_requires_review"
        if positives
        else "blocked_no_robust_multisource_fusion_signal"
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "input": str(candidate_path),
        "row_count": int(len(enriched)),
        "ticker_count": int(enriched["ticker"].nunique()),
        "oos_start": args.oos_start,
        "source_columns_used": source_columns_used,
        "form4": form4_summary,
        "sec13f": sec13f_summary,
        "signal_summaries": signal_summaries,
        "positive_signal_count": int(len(positives)),
        "positive_signals": positives,
        "preferred_positive_fusion_signals": preferred,
        "decision_label": decision_label,
        "next_action_allowed": "default_off_broker_ab_design_review_only" if positives else "do_not_design_hook_from_multisource_fusion",
        "candidate_allowed": False,
        "source_screen_only": True,
        "research_only": True,
        "forward_returns_audit_only": True,
        "used_forward_return_in_ranking": False,
        "same_day_disclosure_policy": "excluded_by_w4_source_screen_no_intraday_rebalance_contract",
        "score_formula": {
            "all_source_equal_score": "mean(w4_sec, financial_proxy, technical_momentum, macro_regime, risk_control)",
            "growth_confirmation_score": "0.25*w4 + 0.25*financial + 0.30*technical + 0.20*macro",
            "drawdown_aware_fusion_score": "0.75*growth_confirmation + 0.25*risk_control",
            "three_plus_sleeve_consensus_score": "positive only when at least three sleeves are positive; negative when at least three sleeves are negative",
        },
        "fullrun_dispatched": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "production_promotion_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
        "artifacts": {
            "summary": str(output_dir / "summary.json"),
            "signal_stats": str(output_dir / "signal_stats.csv"),
            "enriched_candidate_sample": str(output_dir / "enriched_candidate_sample.csv"),
            "report": str(output_dir / "report.md"),
        },
    }
    pd.DataFrame(stat_rows).to_csv(output_dir / "signal_stats.csv", index=False)
    sample_cols = [
        col
        for col in [
            "rebalance_date",
            "ticker",
            "Name",
            "sector",
            "industry_group",
            "forward_return_audit_only",
            *FUSION_COLUMNS,
            "positive_sleeve_count",
            "negative_sleeve_count",
        ]
        if col in enriched.columns
    ]
    sample = enriched.loc[enriched["drawdown_aware_fusion_score"].astype(float).abs().gt(1.0e-12), sample_cols].copy()
    sample = sample.reindex(sample["drawdown_aware_fusion_score"].abs().sort_values(ascending=False).index).head(int(args.sample_rows))
    sample.to_csv(output_dir / "enriched_candidate_sample.csv", index=False)
    (output_dir / "report.md").write_text(render_report(payload, signal_summaries), encoding="utf-8")
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--form4-path", default=DEFAULT_FORM4_PATH)
    parser.add_argument("--sec13f-path", default=DEFAULT_13F_PATH)
    parser.add_argument("--manager-universe", default=DEFAULT_MANAGER_UNIVERSE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START)
    parser.add_argument("--min-rows", type=int, default=50)
    parser.add_argument("--min-oos-high-count", type=int, default=20)
    parser.add_argument("--sample-rows", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
