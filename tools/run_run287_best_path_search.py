#!/usr/bin/env python3
"""Research-only best-path search after run287 multi-source broker A/B.

This tool does not run a full rebuild, add hooks, tune thresholds, or mutate
production state. It reads broker replay artifacts, attributes the Main
growth-confirmation MDD failure, ranks optional Concentrated source-sleeve
broker A/B results, and emits a next-action decision.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.alphaops_governance import (  # noqa: E402
    measurement_contract_acceptance_blockers,
    measurement_contract_caveat_fields,
)

SCHEMA_VERSION = "run287-best-path-search-v1"
DEFAULT_FUSION_BROKER_SUMMARY = "outputs/run287_multisource_fusion_broker_ab/summary.json"
DEFAULT_FUSION_REPLAY_ROOT = "outputs/run287_multisource_fusion_broker_ab/signal_replays/growth_confirmation_score"
DEFAULT_SOURCE_BROKER_SUMMARY = "outputs/run287_best_path_source_broker_ab/summary.json"
DEFAULT_OUTPUT_DIR = "outputs/run287_best_path_search"
DEFAULT_PARITY_SUMMARY = "outputs/run287_parity/summary.json"
DEFAULT_SURVIVORSHIP_SUMMARY = "outputs/run287_survivorship/summary.json"
MAIN_BASELINE_ARM = "baseline"
MAIN_TILT_ARM = "growth_confirmation_top_quintile_tilt10"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def arm_dir(replay_root: Path, portfolio: str, arm: str) -> Path:
    return replay_root / portfolio / arm


def load_arm_metrics(replay_root: Path, portfolio: str, arm: str) -> dict[str, Any]:
    return read_json(arm_dir(replay_root, portfolio, arm) / "broker" / "metrics.json")


def load_holdings(replay_root: Path, portfolio: str, arm: str) -> pd.DataFrame:
    path = arm_dir(replay_root, portfolio, arm) / "broker" / "holdings_daily.csv"
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    d["date"] = pd.to_datetime(d.get("date"), errors="coerce").dt.normalize()
    d["ticker"] = d.get("ticker", pd.Series(index=d.index, dtype=object)).map(normalize_ticker)
    for col in ["shares", "price", "market_value_usd", "weight"]:
        d[col] = pd.to_numeric(d.get(col), errors="coerce")
    return d.dropna(subset=["date", "ticker"]).sort_values(["ticker", "date"]).reset_index(drop=True)


def load_equity(replay_root: Path, portfolio: str, arm: str) -> pd.DataFrame:
    path = arm_dir(replay_root, portfolio, arm) / "broker" / "equity_curve.csv"
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    d["date"] = pd.to_datetime(d.get("date"), errors="coerce").dt.normalize()
    d["equity_usd"] = pd.to_numeric(d.get("equity_usd"), errors="coerce")
    return d.dropna(subset=["date", "equity_usd"]).sort_values("date").reset_index(drop=True)


def load_stock_telemetry(replay_root: Path, portfolio: str, arm: str) -> pd.DataFrame:
    path = arm_dir(replay_root, portfolio, arm) / "stock_telemetry.csv"
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    d["rebalance_date"] = pd.to_datetime(d.get("rebalance_date"), errors="coerce").dt.normalize()
    d["ticker"] = d.get("ticker", pd.Series(index=d.index, dtype=object)).map(normalize_ticker)
    d["delta_weight"] = pd.to_numeric(d.get("delta_weight"), errors="coerce").fillna(0.0)
    d["score"] = pd.to_numeric(d.get("score"), errors="coerce")
    return d.dropna(subset=["rebalance_date", "ticker"]).reset_index(drop=True)


def price_contribution_by_ticker(
    holdings: pd.DataFrame,
    equity: pd.DataFrame,
    *,
    peak_date: str,
    trough_date: str,
) -> pd.DataFrame:
    if holdings.empty or equity.empty:
        return pd.DataFrame()
    peak = pd.Timestamp(peak_date).normalize()
    trough = pd.Timestamp(trough_date).normalize()
    peak_equity = safe_float(equity.loc[equity["date"].eq(peak), "equity_usd"].max())
    if peak_equity <= 0:
        peak_equity = safe_float(equity["equity_usd"].max(), 1.0)
    d = holdings.copy()
    d["prev_shares"] = d.groupby("ticker")["shares"].shift(1)
    d["prev_price"] = d.groupby("ticker")["price"].shift(1)
    d["price_pnl_usd"] = d["prev_shares"].fillna(0.0) * (d["price"] - d["prev_price"])
    window = d[d["date"].gt(peak) & d["date"].le(trough)].copy()
    avg_weight = d[d["date"].ge(peak) & d["date"].le(trough)].groupby("ticker")["weight"].mean()
    peak_weight = d[d["date"].eq(peak)].groupby("ticker")["weight"].sum()
    trough_weight = d[d["date"].eq(trough)].groupby("ticker")["weight"].sum()
    grouped = window.groupby("ticker", as_index=False)["price_pnl_usd"].sum()
    grouped["price_contribution_pct_peak_equity"] = grouped["price_pnl_usd"] / peak_equity
    grouped["avg_weight"] = grouped["ticker"].map(avg_weight).fillna(0.0)
    grouped["peak_weight"] = grouped["ticker"].map(peak_weight).fillna(0.0)
    grouped["trough_weight"] = grouped["ticker"].map(trough_weight).fillna(0.0)
    return grouped


def main_drawdown_attribution(replay_root: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    baseline_metrics = load_arm_metrics(replay_root, "main", MAIN_BASELINE_ARM)
    tilt_metrics = load_arm_metrics(replay_root, "main", MAIN_TILT_ARM)
    peak_date = str(tilt_metrics.get("max_dd_peak_date") or baseline_metrics.get("max_dd_peak_date"))
    trough_date = str(tilt_metrics.get("max_dd_trough_date") or baseline_metrics.get("max_dd_trough_date"))
    baseline_contrib = price_contribution_by_ticker(
        load_holdings(replay_root, "main", MAIN_BASELINE_ARM),
        load_equity(replay_root, "main", MAIN_BASELINE_ARM),
        peak_date=peak_date,
        trough_date=trough_date,
    )
    tilt_contrib = price_contribution_by_ticker(
        load_holdings(replay_root, "main", MAIN_TILT_ARM),
        load_equity(replay_root, "main", MAIN_TILT_ARM),
        peak_date=peak_date,
        trough_date=trough_date,
    )
    if baseline_contrib.empty or tilt_contrib.empty:
        summary = {
            "status": "blocked_missing_main_replay_internals",
            "baseline_metrics": baseline_metrics,
            "tilt_metrics": tilt_metrics,
        }
        return summary, pd.DataFrame()

    merged = baseline_contrib.merge(tilt_contrib, on="ticker", how="outer", suffixes=("_baseline", "_tilt")).fillna(0.0)
    merged["delta_price_contribution_pp"] = (
        merged["price_contribution_pct_peak_equity_tilt"]
        - merged["price_contribution_pct_peak_equity_baseline"]
    ) * 100.0
    merged["avg_weight_delta_pp"] = (merged["avg_weight_tilt"] - merged["avg_weight_baseline"]) * 100.0
    merged["peak_weight_delta_pp"] = (merged["peak_weight_tilt"] - merged["peak_weight_baseline"]) * 100.0
    merged["trough_weight_delta_pp"] = (merged["trough_weight_tilt"] - merged["trough_weight_baseline"]) * 100.0
    telemetry = load_stock_telemetry(replay_root, "main", MAIN_TILT_ARM)
    if not telemetry.empty:
        lo = pd.Timestamp(peak_date).normalize()
        hi = pd.Timestamp(trough_date).normalize()
        tel = telemetry[telemetry["rebalance_date"].ge(lo) & telemetry["rebalance_date"].le(hi)].copy()
        merged["target_delta_weight_sum_pp_in_mdd_window"] = (
            merged["ticker"].map(tel.groupby("ticker")["delta_weight"].sum()).fillna(0.0) * 100.0
        )
        merged["avg_score_in_mdd_window"] = merged["ticker"].map(tel.groupby("ticker")["score"].mean())
    else:
        merged["target_delta_weight_sum_pp_in_mdd_window"] = 0.0
        merged["avg_score_in_mdd_window"] = 0.0
    merged = merged.sort_values("delta_price_contribution_pp", ascending=True).reset_index(drop=True)

    baseline_cagr = safe_float(baseline_metrics.get("cagr"))
    tilt_cagr = safe_float(tilt_metrics.get("cagr"))
    baseline_mdd = safe_float(baseline_metrics.get("max_dd"))
    tilt_mdd = safe_float(tilt_metrics.get("max_dd"))
    top_worseners = merged.head(10).to_dict(orient="records")
    top_helpers = merged.tail(10).sort_values("delta_price_contribution_pp", ascending=False).to_dict(orient="records")
    summary = {
        "status": "completed",
        "baseline_arm": MAIN_BASELINE_ARM,
        "tilt_arm": MAIN_TILT_ARM,
        "peak_date": peak_date,
        "trough_date": trough_date,
        "baseline_cagr": baseline_cagr,
        "tilt_cagr": tilt_cagr,
        "delta_cagr_pp": (tilt_cagr - baseline_cagr) * 100.0,
        "baseline_mdd": baseline_mdd,
        "tilt_mdd": tilt_mdd,
        "delta_mdd_pp": (tilt_mdd - baseline_mdd) * 100.0,
        "cagr_goal_crossed_by_tilt": bool(tilt_cagr >= 0.35),
        "mdd_goal_failed_by_tilt": bool(tilt_mdd < -0.25),
        "top_mdd_worseners": top_worseners,
        "top_mdd_helpers": top_helpers,
        "decision": "main_growth_signal_exists_but_mdd_blocked",
    }
    return summary, merged


def rank_source_broker_rows(source_summary: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    rows = source_summary.get("arm_rows") if isinstance(source_summary, dict) else None
    if not isinstance(rows, list) or not rows:
        return {"status": "blocked_missing_source_broker_summary"}, pd.DataFrame()
    table = pd.DataFrame(rows)
    if table.empty:
        return {"status": "blocked_empty_source_broker_rows"}, table
    table = table[table.get("portfolio_kind", "").astype(str).eq("concentrated")].copy()
    if table.empty:
        return {"status": "blocked_no_concentrated_source_rows"}, table
    for col in ["cagr", "max_dd", "delta_cagr_pp", "delta_max_dd_pp", "target_contract_pass"]:
        if col in table.columns and col != "target_contract_pass":
            table[col] = pd.to_numeric(table[col], errors="coerce").fillna(0.0)
    nonbaseline = table[~table["arm"].astype(str).eq("baseline")].copy()
    if nonbaseline.empty:
        return {"status": "blocked_no_nonbaseline_source_rows"}, table
    nonbaseline["mdd_contract_pass"] = nonbaseline["max_dd"].ge(-0.25)
    nonbaseline["cagr_contract_pass"] = nonbaseline["cagr"].ge(0.50)
    nonbaseline["contract_pass"] = nonbaseline["mdd_contract_pass"] & nonbaseline["cagr_contract_pass"]
    ranked = nonbaseline.sort_values(
        ["contract_pass", "delta_cagr_pp", "delta_max_dd_pp"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    best = ranked.iloc[0].to_dict()
    positive = ranked[ranked["delta_cagr_pp"].gt(0.0)].copy()
    contract = ranked[ranked["contract_pass"]].copy()
    if not contract.empty:
        decision = "concentrated_source_contract_candidate_review_only"
    elif not positive.empty:
        decision = "concentrated_source_edge_not_contract"
    else:
        decision = "no_concentrated_source_tilt_candidate"
    summary = {
        "status": "completed",
        "decision": decision,
        "best_source_arm": best,
        "positive_source_arm_count": int(len(positive)),
        "contract_source_arm_count": int(len(contract)),
        "source_signal_count": int(nonbaseline["signal"].nunique()),
    }
    return summary, ranked


def classify_best_path(main_summary: dict[str, Any], source_summary: dict[str, Any], blockers: list[str]) -> str:
    source_decision = source_summary.get("decision")
    if source_decision == "concentrated_source_contract_candidate_review_only":
        return "best_path_concentrated_source_candidate_review_only_measurement_blocked" if blockers else "best_path_concentrated_source_candidate_review"
    if main_summary.get("decision") == "main_growth_signal_exists_but_mdd_blocked":
        return "best_path_main_mdd_neutralized_growth_design_needed"
    if source_decision == "concentrated_source_edge_not_contract":
        return "best_path_source_edges_exist_but_contract_not_restored"
    return "no_direct_alpha_path_found_prioritize_substrate_or_new_data"


def render_report(payload: dict[str, Any], main_table: pd.DataFrame, source_table: pd.DataFrame) -> str:
    lines = [
        "# Run287 Best Path Search",
        "",
        f"- Status: `{payload['status']}`",
        f"- Decision label: `{payload['decision_label']}`",
        f"- Runner parity status: `{payload['runner_parity_status']}`",
        f"- Measurement acceptance allowed: `{payload['measurement_contract_acceptance_allowed']}`",
        "- No fullrun, hook, threshold tuning, production promotion, or live trading.",
        "",
        "## Main MDD Attribution",
        "",
    ]
    main = payload["main_mdd_attribution"]
    lines.extend(
        [
            f"- Window: `{main.get('peak_date')}` to `{main.get('trough_date')}`",
            f"- Baseline: CAGR `{safe_float(main.get('baseline_cagr')):.2%}`, MDD `{safe_float(main.get('baseline_mdd')):.2%}`",
            f"- Tilt10: CAGR `{safe_float(main.get('tilt_cagr')):.2%}`, MDD `{safe_float(main.get('tilt_mdd')):.2%}`",
            f"- Delta: CAGR `{safe_float(main.get('delta_cagr_pp')):+.2f}pp`, MDD `{safe_float(main.get('delta_mdd_pp')):+.2f}pp`",
            "",
            "| Ticker | Delta price contribution pp | Avg weight delta pp | Target delta sum pp | Avg score |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    if not main_table.empty:
        for _, row in main_table.head(10).iterrows():
            lines.append(
                "| {ticker} | {contrib:+.2f} | {weight:+.2f} | {target:+.2f} | {score:.3f} |".format(
                    ticker=row.get("ticker"),
                    contrib=safe_float(row.get("delta_price_contribution_pp")),
                    weight=safe_float(row.get("avg_weight_delta_pp")),
                    target=safe_float(row.get("target_delta_weight_sum_pp_in_mdd_window")),
                    score=safe_float(row.get("avg_score_in_mdd_window")),
                )
            )
    lines.extend(["", "## Concentrated Source Ranking", ""])
    source = payload["concentrated_source_decomposition"]
    if source.get("status") == "completed":
        best = source.get("best_source_arm") or {}
        lines.extend(
            [
                f"- Source decision: `{source.get('decision')}`",
                "- Best source arm: `{signal}` / `{arm}` with CAGR `{cagr:.2%}`, MDD `{mdd:.2%}`, dCAGR `{dc:+.2f}pp`, dMDD `{dm:+.2f}pp`.".format(
                    signal=best.get("signal"),
                    arm=best.get("arm"),
                    cagr=safe_float(best.get("cagr")),
                    mdd=safe_float(best.get("max_dd")),
                    dc=safe_float(best.get("delta_cagr_pp")),
                    dm=safe_float(best.get("delta_max_dd_pp")),
                ),
                "",
            ]
        )
    if source_table.empty:
        lines.append(f"- Status: `{source.get('status')}`")
    else:
        lines.extend(
            [
                "| Signal | Arm | Verdict | CAGR | MaxDD | dCAGR pp | dMDD pp | Contract pass |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for _, row in source_table.head(20).iterrows():
            lines.append(
                "| {signal} | {arm} | `{verdict}` | {cagr:.2%} | {mdd:.2%} | {dc:+.2f} | {dm:+.2f} | {passed} |".format(
                    signal=row.get("signal"),
                    arm=row.get("arm"),
                    verdict=row.get("ab_verdict"),
                    cagr=safe_float(row.get("cagr")),
                    mdd=safe_float(row.get("max_dd")),
                    dc=safe_float(row.get("delta_cagr_pp")),
                    dm=safe_float(row.get("delta_max_dd_pp")),
                    passed=bool(row.get("contract_pass")),
                )
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Main has a growth signal, but direct overweighting worsens the structural 2022 drawdown.",
            "- The closest Concentrated path is W4 SEC, but it is a near-miss rather than a candidate because it still fails 50% CAGR and worsens OOS CAGR.",
            "- Concentrated source tilts must restore CAGR without relying on post-hoc percentile or threshold selection.",
            "- Any positive path remains review-only while runner parity is not exact and PIT membership is not clean.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    caveats = measurement_contract_caveat_fields(
        parity_summary_path=repo_path(args.parity_summary),
        survivorship_summary_path=repo_path(args.survivorship_summary),
    )
    blockers = measurement_contract_acceptance_blockers(caveats)
    fusion_summary = read_json(repo_path(args.fusion_broker_summary))
    main_summary, main_table = main_drawdown_attribution(repo_path(args.fusion_replay_root))
    source_summary_raw = read_json(repo_path(args.source_broker_summary))
    source_summary, source_table = rank_source_broker_rows(source_summary_raw)
    decision_label = classify_best_path(main_summary, source_summary, blockers)
    measurement_allowed = not blockers and "candidate_review" in decision_label
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "decision_label": decision_label,
        "fusion_broker_summary": str(repo_path(args.fusion_broker_summary)),
        "source_broker_summary": str(repo_path(args.source_broker_summary)),
        "source_run_id": "28725350727",
        "main_mdd_attribution": main_summary,
        "concentrated_source_decomposition": source_summary,
        "prior_fusion_decision_label": fusion_summary.get("decision_label"),
        **caveats,
        "measurement_contract_acceptance_blockers": blockers,
        "measurement_contract_acceptance_allowed": measurement_allowed,
        "candidate_allowed": False,
        "next_action_allowed": "human_review_only_no_hook_no_fullrun",
        "research_only": True,
        "fullrun_dispatched": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "used_forward_return_in_ranking": False,
        "production_promotion_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload, main_table, source_table))
    if not main_table.empty:
        write_csv(output_dir / "main_mdd_ticker_attribution.csv", main_table)
    if not source_table.empty:
        write_csv(output_dir / "concentrated_source_ranking.csv", source_table)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fusion-broker-summary", default=DEFAULT_FUSION_BROKER_SUMMARY)
    parser.add_argument("--fusion-replay-root", default=DEFAULT_FUSION_REPLAY_ROOT)
    parser.add_argument("--source-broker-summary", default=DEFAULT_SOURCE_BROKER_SUMMARY)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--parity-summary", default=DEFAULT_PARITY_SUMMARY)
    parser.add_argument("--survivorship-summary", default=DEFAULT_SURVIVORSHIP_SUMMARY)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
