#!/usr/bin/env python3
"""Learn SEC Form 4 + 13F evidence weights before production use.

This is a research-only orchestration sidecar for the seven-step SEC evidence
plan:

1. Load historical Form 4 transactions and 13F holdings.
2. Enrich the historical candidate replay book by PIT `available_from`.
3. Evaluate Form 4 / 13F / combined SEC factors with forward-return diagnostics.
4. Learn small candidate weight blends through research-only top-k/IC tests.
5. Optionally run official broker-ledger alpha-selector challengers.
6. Compare candidates with locked main/concentrated baselines.
7. Emit a promotion-gate report. Production activation remains disabled.
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

from tools.run_alpha_selector_broker_grid import run as run_alpha_selector_grid  # noqa: E402
from tools.run_sec_enriched_candidate_replay import (  # noqa: E402
    enrich_candidate_book,
    read_table,
)
from tools.run_sec_evidence_signal_audit import run as run_signal_audit  # noqa: E402
from tools.run_selection_quality_report import run as run_selection_quality  # noqa: E402

DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"
DEFAULT_FORM4 = "data_pit/sec/form4_transactions.parquet"
DEFAULT_13F = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_OUTPUT_DIR = "outputs/sec_evidence_learning"

BASELINES = {
    "main": {"cagr": 0.2184, "max_dd": -0.2862, "label": "codex/broker-ledger-replay-foundation"},
    "concentrated": {"cagr": 0.3510, "max_dd": -0.2268, "label": "20260514_global_alpha_universe"},
}

COMPONENT_COLUMNS = {
    "future": "portfolio_future_winner_engine_score",
    "market": "selection_market_confirmation_score",
    "form4": "early_evidence_score",
    "institutional": "institutional_evidence_score",
    "combined_sec": "sec_combined_evidence_score",
    "support_sec": "sec_support_boost_score",
    "13f_breadth": "sec_13f_breadth_score",
    "leader_sec_v2": "leader_onset_sec_v2_score",
    "leader_sec_v3": "leader_onset_sec_v3_score",
    "leader_sec_v4": "leader_onset_sec_v4_support_score",
    "rs": "rs_acceleration_score",
    "industry": "industry_group_strength_score",
    "entry": "entry_quality_score",
}

POLICY_FEATURE_COMPONENT_MAP = {
    "sec_form4_open_market_buy_score": "form4",
    "sec_form4_cluster_buy_score": "form4",
    "sec_form4_ceo_cfo_buy_score": "form4",
    "sec_form4_ten_percent_owner_buy_score": "form4",
    "sec_form4_net_buy_score": "form4",
    "early_evidence_score": "form4",
    "sec_13f_consensus_buy_score": "institutional",
    "sec_13f_accumulation_score": "institutional",
    "sec_13f_new_position_score": "institutional",
    "sec_13f_smart_money_score": "institutional",
    "institutional_evidence_score": "institutional",
    "sec_13f_breadth_score": "13f_breadth",
    "sec_combined_evidence_score": "combined_sec",
    "sec_support_boost_score": "support_sec",
    "leader_onset_sec_v2_score": "leader_sec_v2",
    "leader_onset_sec_v3_score": "leader_sec_v3",
    "leader_onset_sec_v4_support_score": "leader_sec_v4",
}

POLICY_FEATURE_PENALTY_MAP = {
    "sec_13f_crowding_score": "crowding_penalty",
    "sec_13f_stale_penalty": "stale_penalty",
    "sec_form4_sale_risk_score": "form4_sale_risk_penalty",
    "sec_form4_sale_pressure_score": "form4_sale_risk_penalty",
}

WEIGHT_PRESETS: dict[str, dict[str, float]] = {
    "control_no_sec": {
        "future": 0.35,
        "market": 0.20,
        "rs": 0.15,
        "industry": 0.15,
        "entry": 0.05,
    },
    "form4_light": {
        "future": 0.32,
        "market": 0.20,
        "form4": 0.08,
        "rs": 0.13,
        "industry": 0.12,
        "entry": 0.05,
    },
    "13f_light": {
        "future": 0.32,
        "market": 0.20,
        "institutional": 0.08,
        "rs": 0.13,
        "industry": 0.12,
        "entry": 0.05,
        "13f_breadth": 0.05,
        "crowding_penalty": 0.02,
    },
    "sec_balanced": {
        "future": 0.30,
        "market": 0.18,
        "combined_sec": 0.17,
        "institutional": 0.10,
        "rs": 0.08,
        "industry": 0.12,
        "entry": 0.05,
        "crowding_penalty": 0.03,
    },
    "form4_fast": {
        "future": 0.30,
        "market": 0.20,
        "form4": 0.18,
        "institutional": 0.04,
        "rs": 0.10,
        "industry": 0.10,
        "entry": 0.05,
        "form4_sale_risk_penalty": 0.03,
    },
    "13f_validation": {
        "future": 0.30,
        "market": 0.20,
        "form4": 0.05,
        "institutional": 0.15,
        "combined_sec": 0.08,
        "13f_breadth": 0.05,
        "rs": 0.08,
        "industry": 0.10,
        "entry": 0.04,
        "crowding_penalty": 0.03,
        "stale_penalty": 0.06,
    },
    "sec_support_overlay": {
        "future": 0.36,
        "market": 0.22,
        "support_sec": 0.08,
        "institutional": 0.06,
        "form4": 0.04,
        "13f_breadth": 0.04,
        "rs": 0.10,
        "industry": 0.07,
        "entry": 0.03,
        "form4_sale_risk_penalty": 0.02,
        "stale_penalty": 0.04,
    },
    "form4_buy_trigger_light": {
        "future": 0.34,
        "market": 0.22,
        "form4": 0.10,
        "support_sec": 0.04,
        "institutional": 0.04,
        "rs": 0.10,
        "industry": 0.11,
        "entry": 0.05,
        "form4_sale_risk_penalty": 0.03,
    },
    "13f_breadth_support": {
        "future": 0.34,
        "market": 0.20,
        "institutional": 0.12,
        "support_sec": 0.06,
        "13f_breadth": 0.06,
        "form4": 0.03,
        "rs": 0.10,
        "industry": 0.05,
        "entry": 0.04,
        "crowding_penalty": 0.02,
        "stale_penalty": 0.04,
    },
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def forward_return_series(frame: pd.DataFrame) -> pd.Series:
    for col in ["period_forward_return", "forward_return", "next_return", "fwd_return"]:
        if col in frame.columns:
            return pd.to_numeric(frame[col], errors="coerce")
    return pd.Series(math.nan, index=frame.index, dtype=float)


def prepare_learning_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns or "rebalance_date" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    d["forward_return"] = forward_return_series(d)
    d = d[d["ticker"].ne("") & d["rebalance_date"].notna() & d["forward_return"].notna()].copy()
    return d


def rank_by_date(frame: pd.DataFrame, col: str, *, lower_is_better: bool = False) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(0.5, index=frame.index, dtype=float)
    return (
        pd.to_numeric(frame[col], errors="coerce")
        .groupby(frame["rebalance_date"])
        .rank(pct=True, ascending=not lower_is_better)
        .fillna(0.5)
        .clip(0.0, 1.0)
    )


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    positive = {k: max(float(v), 0.0) for k, v in weights.items() if not k.endswith("_penalty")}
    total = sum(positive.values())
    if total <= 0:
        return dict(weights)
    out = dict(weights)
    for key, value in positive.items():
        out[key] = value / total
    return out


def apply_weight_preset(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    norm = normalize_weights(weights)
    score = pd.Series(0.0, index=frame.index, dtype=float)
    for key, col in COMPONENT_COLUMNS.items():
        weight = float(norm.get(key, 0.0))
        if weight:
            score += weight * rank_by_date(frame, col)
    crowding_penalty = float(weights.get("crowding_penalty", 0.0))
    stale_penalty = float(weights.get("stale_penalty", 0.0))
    form4_sale_risk_penalty = float(weights.get("form4_sale_risk_penalty", 0.0))
    if crowding_penalty:
        score -= crowding_penalty * numeric(frame, "sec_13f_crowding_score", 0.0).clip(0.0, 1.0)
    if stale_penalty:
        score -= stale_penalty * numeric(frame, "sec_13f_stale_penalty", 0.0).clip(0.0, 1.0)
    if form4_sale_risk_penalty:
        score -= form4_sale_risk_penalty * numeric(frame, "sec_form4_sale_risk_score", 0.0).clip(0.0, 1.0)
    return score.fillna(0.0).clip(0.0, 1.0)


def build_price_follow_adaptive_preset(policy: dict[str, Any]) -> dict[str, float]:
    """Convert price-follow diagnostics into a research-only SEC overlay preset.

    This does not change production scoring. It only creates one additional
    learning-grid candidate so the historical data can challenge our hand-made
    Form 4 / 13F assumptions.
    """
    if not policy or policy.get("status") != "completed":
        return {}

    component_strength: dict[str, float] = {}
    for item in policy.get("support_features", []) or []:
        feature = str(item.get("feature", ""))
        component = POLICY_FEATURE_COMPONENT_MAP.get(feature)
        if not component:
            continue
        try:
            strength = float(item.get("suggested_support_weight", 0.0))
        except (TypeError, ValueError):
            strength = 0.0
        if strength <= 0.0:
            continue
        component_strength[component] = component_strength.get(component, 0.0) + strength

    if not component_strength:
        return {}

    weights: dict[str, float] = {
        "future": 0.34,
        "market": 0.21,
        "rs": 0.10,
        "industry": 0.08,
        "entry": 0.04,
    }
    total_strength = sum(component_strength.values())
    support_budget = min(0.24, max(0.08, total_strength))
    for component, strength in component_strength.items():
        weights[component] = weights.get(component, 0.0) + support_budget * (strength / total_strength)

    # If a composite leader SEC score wins the diagnostic, reduce raw SEC
    # evidence additions a little to avoid double-counting the same signal.
    if any(k in component_strength for k in ["leader_sec_v2", "leader_sec_v3", "leader_sec_v4"]):
        for component in ["form4", "institutional", "combined_sec", "support_sec", "13f_breadth"]:
            if component in weights:
                weights[component] *= 0.65

    for item in policy.get("risk_penalty_features", []) or []:
        feature = str(item.get("feature", ""))
        penalty = POLICY_FEATURE_PENALTY_MAP.get(feature)
        if not penalty:
            continue
        try:
            strength = float(item.get("suggested_support_weight", 0.0))
        except (TypeError, ValueError):
            strength = 0.0
        if strength > 0.0:
            weights[penalty] = min(0.06, weights.get(penalty, 0.0) + strength * 0.35)

    return weights


def weight_presets_for_policy(policy: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    presets = dict(WEIGHT_PRESETS)
    adaptive = build_price_follow_adaptive_preset(policy or {})
    if adaptive:
        presets["price_follow_adaptive_overlay"] = adaptive
    return presets


def evaluate_score(frame: pd.DataFrame, score: pd.Series, *, topks: list[int]) -> dict[str, Any]:
    d = frame[["rebalance_date", "ticker", "forward_return"]].copy()
    d["candidate_score"] = pd.to_numeric(score, errors="coerce")
    d = d.dropna(subset=["candidate_score", "forward_return"])
    if len(d) < 20:
        return {"status": "insufficient_rows", "rows": int(len(d))}

    by_month_ic: list[float] = []
    topk_payload: dict[str, Any] = {}
    for _, group in d.groupby("rebalance_date"):
        if len(group) >= 8 and group["candidate_score"].nunique(dropna=True) > 1:
            corr = group["candidate_score"].corr(group["forward_return"], method="spearman")
            if pd.notna(corr):
                by_month_ic.append(float(corr))
    for topk in topks:
        rows = []
        for _, group in d.groupby("rebalance_date"):
            if len(group) < max(3, min(int(topk), 5)):
                continue
            universe = float(group["forward_return"].mean())
            top = group.sort_values("candidate_score", ascending=False).head(int(topk))
            rows.append(float(top["forward_return"].mean() - universe))
        topk_payload[f"top{topk}_avg_excess_return"] = float(sum(rows) / len(rows)) if rows else math.nan
        topk_payload[f"top{topk}_months"] = int(len(rows))
    return {
        "status": "completed",
        "rows": int(len(d)),
        "months": int(d["rebalance_date"].nunique()),
        "avg_monthly_spearman_ic": float(sum(by_month_ic) / len(by_month_ic)) if by_month_ic else math.nan,
        "positive_ic_month_share": float(sum(1 for x in by_month_ic if x > 0) / len(by_month_ic)) if by_month_ic else math.nan,
        **topk_payload,
    }


def learn_score_weights(enriched: pd.DataFrame, out_dir: Path, *, price_follow_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    frame = prepare_learning_frame(enriched)
    if frame.empty:
        payload = {
            "status": "blocked",
            "reason": "missing candidate replay forward returns",
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(out_dir / "best_score_weights.json", payload)
        pd.DataFrame().to_csv(out_dir / "score_weight_grid.csv", index=False)
        return payload

    rows: list[dict[str, Any]] = []
    presets = weight_presets_for_policy(price_follow_policy)
    for name, weights in presets.items():
        score = apply_weight_preset(frame, weights)
        metrics = evaluate_score(frame, score, topks=[5, 10, 20])
        rows.append({"preset": name, "weights_json": json.dumps(weights, sort_keys=True), **metrics})
    grid = pd.DataFrame(rows)
    if not grid.empty:
        grid = grid.sort_values(
            ["top5_avg_excess_return", "avg_monthly_spearman_ic", "positive_ic_month_share"],
            ascending=[False, False, False],
            na_position="last",
        )
    grid.to_csv(out_dir / "score_weight_grid.csv", index=False)
    if grid.empty or str(grid.iloc[0].get("status")) != "completed":
        payload = {
            "status": "blocked",
            "reason": "no completed score-weight candidates",
            "research_only": True,
            "production_activation_allowed": False,
        }
    else:
        best = grid.iloc[0].to_dict()
        payload = {
            "status": "completed",
            "research_only": True,
            "production_activation_allowed": False,
            "selection_rule": "best_top5_excess_then_ic",
            "policy_adaptive_preset_included": "price_follow_adaptive_overlay" in presets,
            "best_preset": best.get("preset"),
            "best_weights": json.loads(str(best.get("weights_json") or "{}")),
            "best_metrics": {k: v for k, v in best.items() if k not in {"weights_json"}},
            "grid_csv": str(out_dir / "score_weight_grid.csv"),
        }
    write_json(out_dir / "best_score_weights.json", payload)
    return payload


def broker_gate(metrics: dict[str, Any], portfolio: str) -> dict[str, Any]:
    baseline = BASELINES[portfolio]
    cagr = float(metrics.get("cagr", math.nan)) if metrics else math.nan
    max_dd = float(metrics.get("max_dd", metrics.get("max_drawdown", math.nan))) if metrics else math.nan
    valid = bool(metrics.get("valid_for_production")) if metrics else False
    return {
        "portfolio": portfolio,
        "baseline": baseline,
        "candidate_cagr": cagr,
        "candidate_max_dd": max_dd,
        "valid_for_production_metric": valid,
        "beats_cagr": bool(math.isfinite(cagr) and cagr > baseline["cagr"]),
        "beats_or_matches_mdd": bool(math.isfinite(max_dd) and max_dd >= baseline["max_dd"]),
        "promotion_allowed": False,
        "reason": "research-only SEC evidence; human approval required even if metrics pass",
    }


def run_broker_grids(args: argparse.Namespace, enriched_csv: Path, output_dir: Path) -> dict[str, Any]:
    if not bool(args.run_broker_grid):
        return {"status": "skipped", "reason": "run_broker_grid is false"}
    results: dict[str, Any] = {"status": "completed", "portfolios": {}}
    for portfolio in ["main", "concentrated"]:
        target_ns = getattr(args, f"{portfolio}_target_ns", "") or args.target_ns
        caps = getattr(args, f"{portfolio}_single_name_caps", "") or args.single_name_caps
        out = output_dir / "alpha_selector_broker_grid" / portfolio
        payload = run_alpha_selector_grid(
            argparse.Namespace(
                candidate_book=str(enriched_csv),
                price_cache=str(args.price_cache),
                output_dir=str(out),
                portfolio_kind=portfolio,
                starting_capital=float(args.starting_capital),
                fill_mode=args.fill_mode,
                cost_bps=float(args.cost_bps),
                no_integer_shares=False,
                max_fill_lag_days=int(args.max_fill_lag_days),
                styles=args.styles,
                target_ns=target_ns,
                single_name_caps=caps,
                max_variants=int(args.max_variants),
                min_market_cap_usd=float(args.min_market_cap_usd),
                min_dollar_volume_usd=float(args.min_dollar_volume_usd),
                min_price=float(args.min_price),
                allow_unfillable_targets=bool(args.allow_unfillable_targets),
            )
        )
        results["portfolios"][portfolio] = {"metrics": payload, "gate": broker_gate(payload, portfolio)}
    return results


def render_report(summary: dict[str, Any]) -> str:
    learning = summary.get("score_learning", {})
    broker = summary.get("broker_grid", {})
    audit = summary.get("signal_audit", {})
    lines = [
        "# SEC Evidence Learning Pipeline",
        "",
        "Research-only Form 4 + 13F scoring and broker-ledger validation pipeline.",
        "",
        f"- status: `{summary.get('status')}`",
        f"- enriched rows: {summary.get('enriched_rows', 0)}",
        f"- rows with Form 4 evidence: {summary.get('rows_with_form4_evidence', 0)}",
        f"- rows with 13F evidence: {summary.get('rows_with_13f_evidence', 0)}",
        f"- best learned preset: `{learning.get('best_preset', '')}`",
        f"- signal audit: `{audit.get('status', 'skipped')}`",
        "",
        "## Promotion",
        "",
        "Production activation is disabled. Promotion requires official broker-ledger improvement and human approval.",
        "",
    ]
    if broker.get("portfolios"):
        lines.extend(["| portfolio | CAGR | MaxDD | beats CAGR | beats MDD |", "| --- | ---: | ---: | --- | --- |"])
        for portfolio, item in broker["portfolios"].items():
            gate = item.get("gate", {})
            lines.append(
                "| {p} | {cagr:.2%} | {mdd:.2%} | {bc} | {bm} |".format(
                    p=portfolio,
                    cagr=float(gate.get("candidate_cagr", math.nan)),
                    mdd=float(gate.get("candidate_max_dd", math.nan)),
                    bc=gate.get("beats_cagr"),
                    bm=gate.get("beats_or_matches_mdd"),
                )
            )
    else:
        lines.append(f"- broker grid: `{broker.get('status', 'skipped')}`")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate_path = repo_path(args.candidate_book)
    form4_path = repo_path(args.form4)
    holdings_13f_path = repo_path(args.institutional_13f)
    candidates = read_table(candidate_path)
    form4 = read_table(form4_path)
    holdings_13f = read_table(holdings_13f_path)

    enriched = enrich_candidate_book(
        candidates,
        form4,
        holdings_13f,
        lookback_days=int(args.form4_lookback_days),
        institutional_lookback_days=int(args.institutional_lookback_days),
    )
    enriched_csv = output_dir / "candidate_replay_book_sec_enriched.csv"
    enriched.to_csv(enriched_csv, index=False)

    latest_dir = output_dir / "enriched_latest"
    reports_dir = latest_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(reports_dir / "candidate_replay_book.csv", index=False)

    selection_quality = run_selection_quality(latest_dir, output_dir / "selection_quality", top_n=int(args.top_n))
    signal_audit = run_signal_audit(
        argparse.Namespace(
            candidate_book=str(enriched_csv),
            form4=str(form4_path),
            institutional_13f=str(holdings_13f_path),
            output_dir=str(output_dir / "signal_audit"),
            form4_lookback_days=int(args.form4_lookback_days),
            institutional_lookback_days=int(args.institutional_lookback_days),
            already_enriched=True,
            min_manager_observations=int(args.min_manager_observations),
            min_feature_nonzero_rows=int(args.min_feature_nonzero_rows),
        )
    )
    score_learning = learn_score_weights(
        enriched,
        output_dir,
        price_follow_policy=(signal_audit or {}).get("price_follow_policy", {}),
    )
    broker_grid = run_broker_grids(args, enriched_csv, output_dir)

    summary = {
        "status": "completed",
        "schema_version": "sec-evidence-learning-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "candidate_book": str(candidate_path),
        "form4_transactions": str(form4_path),
        "institutional_13f_holdings": str(holdings_13f_path),
        "enriched_candidate_book": str(enriched_csv),
        "candidate_rows": int(len(candidates)),
        "form4_rows": int(len(form4)),
        "institutional_13f_rows": int(len(holdings_13f)),
        "enriched_rows": int(len(enriched)),
        "rows_with_form4_evidence": int((pd.to_numeric(enriched.get("evidence_confidence_score", 0.0), errors="coerce").fillna(0.0) > 0).sum())
        if not enriched.empty
        else 0,
        "rows_with_13f_evidence": int(
            (pd.to_numeric(enriched.get("institutional_evidence_confidence_score", 0.0), errors="coerce").fillna(0.0) > 0).sum()
        )
        if not enriched.empty
        else 0,
        "selection_quality": selection_quality,
        "score_learning": score_learning,
        "signal_audit": signal_audit,
        "broker_grid": broker_grid,
        "promotion_allowed": False,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--institutional-13f", default=DEFAULT_13F)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--form4-lookback-days", type=int, default=90)
    parser.add_argument("--institutional-lookback-days", type=int, default=210)
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--run-broker-grid", action="store_true")
    parser.add_argument("--portfolio-kind", default="both")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--styles", default="sec_support_overlay,sec_evidence_shadow,leader_onset_shadow")
    parser.add_argument("--target-ns", default="3,5,7")
    parser.add_argument("--single-name-caps", default="0.25,0.33,0.50")
    parser.add_argument("--main-target-ns", default="")
    parser.add_argument("--main-single-name-caps", default="")
    parser.add_argument("--concentrated-target-ns", default="")
    parser.add_argument("--concentrated-single-name-caps", default="")
    parser.add_argument("--max-variants", type=int, default=18)
    parser.add_argument("--min-market-cap-usd", type=float, default=1_000_000_000.0)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=20_000_000.0)
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-manager-observations", type=int, default=3)
    parser.add_argument("--min-feature-nonzero-rows", type=int, default=30)
    parser.add_argument("--allow-unfillable-targets", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "enriched_rows": payload.get("enriched_rows"),
                "best_preset": (payload.get("score_learning") or {}).get("best_preset"),
            },
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
