#!/usr/bin/env python3
"""Attribute main-book cash to risk defense, idle cash, and artifact gaps.

This sidecar is diagnostic only. It does not change portfolio weights. Its
purpose is to answer the first cash-policy question after each full rebuild:

    Was cash intentional defense, or did selected capital sit idle?

It also compares the backtest source of truth (`regime_by_month.cash_weight`)
with explicit CASH rows in `main_monthly_weights.csv`. A large gap means
downstream replays that read only `main_monthly_weights.csv` may be overstating
deployment unless they reintroduce reported cash from `regime_by_month.csv`.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_rows, write_text


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/cash_policy"
CASH_TICKER = "CASH"
RISK_LABEL_TOKENS = ("risk", "systemic", "crisis", "shock", "stagflation", "carry_unwind", "war")


def _pct(value: Any) -> str:
    value = safe_float(value, 0.0)
    return f"{value:.2%}"


def _is_risk_label(label: str) -> bool:
    text = str(label or "").lower()
    return any(token in text for token in RISK_LABEL_TOKENS)


def _is_partial_action(action: str) -> bool:
    text = str(action or "").lower()
    return text.startswith("partial_rebalance") or text in {"scheduled_hold", "hold_after_empty_rebalance"}


def _primary_reason(row: dict[str, Any]) -> str:
    reported = safe_float(row.get("reported_cash_weight"), 0.0)
    if reported <= 0.005:
        return "no_cash"
    gap = safe_float(row.get("reported_vs_book_cash_gap"), 0.0)
    if gap > 0.02 and safe_float(row.get("book_explicit_cash_weight"), 0.0) < reported * 0.50:
        return "cash_export_mismatch"
    target = safe_float(row.get("cash_target_used"), 0.0)
    target_share = min(reported, max(target, 0.0)) / max(reported, 1e-12)
    if bool(row.get("drawdown_or_risk_defense")) and target_share >= 0.70:
        return "risk_defense_cash"
    if bool(row.get("drawdown_or_risk_defense")) and target_share > 0.05:
        return "mixed_risk_and_idle_cash"
    if safe_float(row.get("stock_count"), 0.0) < max(3.0, 0.80 * safe_float(row.get("target_n"), 0.0)):
        return "candidate_scarcity_cash"
    if bool(row.get("partial_rebalance")):
        return "partial_rebalance_leftover"
    if bool(row.get("possible_idle_cash")):
        return "idle_cash_candidate"
    return "cap_limited_leftover"


def _rows_by_month(holdings: pd.DataFrame, regime: pd.DataFrame) -> list[dict[str, Any]]:
    if holdings.empty and regime.empty:
        return []

    h = holdings.copy()
    if not h.empty:
        h["rebalance_date"] = pd.to_datetime(h["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        h["ticker"] = h["ticker"].astype(str).str.upper().str.strip()
        h["weight"] = pd.to_numeric(h.get("weight", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)

    r = regime.copy()
    if not r.empty:
        r["rebalance_date"] = pd.to_datetime(r["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")

    dates = sorted(set(h.get("rebalance_date", pd.Series(dtype=str)).dropna().astype(str)) | set(r.get("rebalance_date", pd.Series(dtype=str)).dropna().astype(str)))
    h_groups = {str(dt): group.copy() for dt, group in h.groupby("rebalance_date", sort=False)} if not h.empty else {}
    r_index = {str(row["rebalance_date"]): row for _, row in r.iterrows()} if not r.empty else {}

    rows: list[dict[str, Any]] = []
    for dt in dates:
        group = h_groups.get(dt, pd.DataFrame())
        rrow = r_index.get(dt, {})
        tickers = group.get("ticker", pd.Series(dtype=str)).astype(str).str.upper() if not group.empty else pd.Series(dtype=str)
        weights = pd.to_numeric(group.get("weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0) if not group.empty else pd.Series(dtype=float)
        cash_mask = tickers.eq(CASH_TICKER)
        explicit_cash = float(weights.loc[cash_mask].sum()) if len(weights) else 0.0
        stock_sum = float(weights.loc[~cash_mask].sum()) if len(weights) else 0.0
        stock_count = int((~cash_mask & (weights > 1e-10)).sum()) if len(weights) else 0

        reported_cash = safe_float(rrow.get("cash_weight"), explicit_cash)
        cash_target = safe_float(rrow.get("cash_target_used"), safe_float(group.get("cash_target", pd.Series([0.0])).iloc[0] if not group.empty and "cash_target" in group.columns else 0.0, 0.0))
        drawdown_before = safe_float(rrow.get("drawdown_before_month"), 0.0)
        drawdown_after = safe_float(rrow.get("drawdown_after_month"), 0.0)
        regime_label = str(rrow.get("regime_label", "") or "")
        action = str(rrow.get("rebalance_action", "") or "")
        target_n = safe_float(rrow.get("target_n"), safe_float(group.get("target_n", pd.Series([0.0])).iloc[0] if not group.empty and "target_n" in group.columns else 0.0, 0.0))
        risk_like = _is_risk_label(regime_label) or drawdown_before <= -0.08 or drawdown_after <= -0.08 or cash_target >= 0.10
        target_defense_cash = min(max(reported_cash, 0.0), max(cash_target, 0.0))
        excess_over_target = max(0.0, reported_cash - target_defense_cash)
        possible_idle = (
            reported_cash > 0.02
            and cash_target <= 0.01
            and not _is_risk_label(regime_label)
            and drawdown_before > -0.05
            and drawdown_after > -0.05
        )

        row = {
            "rebalance_date": dt,
            "regime_label": regime_label,
            "rebalance_action": action,
            "reported_cash_weight": reported_cash,
            "book_explicit_cash_weight": explicit_cash,
            "book_stock_weight_sum": stock_sum,
            "book_total_weight_sum": stock_sum + explicit_cash,
            "reported_vs_book_cash_gap": reported_cash - explicit_cash,
            "cash_target_used": cash_target,
            "target_defense_cash": target_defense_cash,
            "excess_cash_over_target": excess_over_target,
            "possible_idle_cash": possible_idle,
            "drawdown_or_risk_defense": risk_like,
            "partial_rebalance": _is_partial_action(action),
            "stock_count": stock_count,
            "target_n": target_n,
            "drawdown_before_month": drawdown_before,
            "drawdown_after_month": drawdown_after,
            "next_rebalance_date": rrow.get("next_rebalance_date", ""),
        }
        row["primary_cash_reason"] = _primary_reason(row)
        rows.append(row)
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    months = len(rows)
    reason_counts = Counter(str(row.get("primary_cash_reason")) for row in rows)
    cash_by_reason: dict[str, float] = defaultdict(float)
    for row in rows:
        cash_by_reason[str(row.get("primary_cash_reason"))] += safe_float(row.get("reported_cash_weight"), 0.0)

    def avg(key: str) -> float:
        return sum(safe_float(row.get(key), 0.0) for row in rows) / months if months else 0.0

    top_cash = sorted(rows, key=lambda row: safe_float(row.get("reported_cash_weight"), 0.0), reverse=True)[:12]
    high_idle = [
        row for row in rows
        if bool(row.get("possible_idle_cash"))
        and safe_float(row.get("reported_cash_weight"), 0.0) >= 0.10
    ]
    high_idle = sorted(high_idle, key=lambda row: safe_float(row.get("reported_cash_weight"), 0.0), reverse=True)[:12]

    mismatches = [
        row for row in rows
        if abs(safe_float(row.get("reported_vs_book_cash_gap"), 0.0)) > 0.02
    ]
    return {
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "months": months,
        "avg_reported_cash_weight": avg("reported_cash_weight"),
        "avg_book_explicit_cash_weight": avg("book_explicit_cash_weight"),
        "avg_reported_vs_book_cash_gap": avg("reported_vs_book_cash_gap"),
        "avg_target_defense_cash": avg("target_defense_cash"),
        "avg_excess_cash_over_target": avg("excess_cash_over_target"),
        "months_reported_cash_gt_20pct": sum(1 for row in rows if safe_float(row.get("reported_cash_weight"), 0.0) > 0.20),
        "months_reported_cash_gt_50pct": sum(1 for row in rows if safe_float(row.get("reported_cash_weight"), 0.0) > 0.50),
        "months_possible_idle_cash": sum(1 for row in rows if bool(row.get("possible_idle_cash"))),
        "months_cash_export_mismatch_gt_2pct": len(mismatches),
        "reason_counts": dict(reason_counts),
        "cash_weight_sum_by_reason": {key: value for key, value in sorted(cash_by_reason.items())},
        "top_cash_months": [
            {
                "rebalance_date": row.get("rebalance_date"),
                "reported_cash_weight": row.get("reported_cash_weight"),
                "book_explicit_cash_weight": row.get("book_explicit_cash_weight"),
                "reported_vs_book_cash_gap": row.get("reported_vs_book_cash_gap"),
                "cash_target_used": row.get("cash_target_used"),
                "regime_label": row.get("regime_label"),
                "rebalance_action": row.get("rebalance_action"),
                "primary_cash_reason": row.get("primary_cash_reason"),
                "possible_idle_cash": row.get("possible_idle_cash"),
                "stock_count": row.get("stock_count"),
                "target_n": row.get("target_n"),
            }
            for row in top_cash
        ],
        "top_possible_idle_months": [
            {
                "rebalance_date": row.get("rebalance_date"),
                "reported_cash_weight": row.get("reported_cash_weight"),
                "book_explicit_cash_weight": row.get("book_explicit_cash_weight"),
                "reported_vs_book_cash_gap": row.get("reported_vs_book_cash_gap"),
                "cash_target_used": row.get("cash_target_used"),
                "regime_label": row.get("regime_label"),
                "rebalance_action": row.get("rebalance_action"),
                "primary_cash_reason": row.get("primary_cash_reason"),
                "stock_count": row.get("stock_count"),
                "target_n": row.get("target_n"),
            }
            for row in high_idle
        ],
        "notes": [
            "Use reported_cash_weight from regime_by_month as the source of truth for backtest avg_cash_weight.",
            "A large reported_vs_book_cash_gap means main_monthly_weights does not explicitly carry the cash that influenced backtest_metrics.",
            "The existing main cash-drag replay must be repaired or it can understate cash by relying on explicit CASH rows only.",
            "Idle-cash redeploy A/B should preserve target_defense_cash and only test excess cash in non-risk regimes.",
        ],
    }


def _render_report(payload: dict[str, Any]) -> str:
    reason_counts = payload.get("reason_counts") or {}
    cash_by_reason = payload.get("cash_weight_sum_by_reason") or {}
    lines = [
        "# Cash Policy Attribution",
        "",
        "Research-only diagnostic. No production weights are changed.",
        "",
        "## Summary",
        "",
        f"- months: {payload.get('months', 0)}",
        f"- avg reported cash: {_pct(payload.get('avg_reported_cash_weight'))}",
        f"- avg explicit CASH in monthly book: {_pct(payload.get('avg_book_explicit_cash_weight'))}",
        f"- avg reported-vs-book cash gap: {_pct(payload.get('avg_reported_vs_book_cash_gap'))}",
        f"- avg target defense cash: {_pct(payload.get('avg_target_defense_cash'))}",
        f"- avg excess cash over target: {_pct(payload.get('avg_excess_cash_over_target'))}",
        f"- months reported cash >20%: {payload.get('months_reported_cash_gt_20pct')}",
        f"- months reported cash >50%: {payload.get('months_reported_cash_gt_50pct')}",
        f"- months possible idle cash: {payload.get('months_possible_idle_cash')}",
        f"- months with cash export mismatch >2pp: {payload.get('months_cash_export_mismatch_gt_2pct')}",
        "",
        "## Primary Reason Counts",
        "",
        "| reason | months | cash-weight sum |",
        "|---|---:|---:|",
    ]
    for reason, count in sorted(reason_counts.items()):
        lines.append(f"| `{reason}` | {count} | {_pct(cash_by_reason.get(reason, 0.0))} |")
    lines.extend([
        "",
        "## Largest Cash Months",
        "",
        "| date | reported cash | book cash | gap | target | regime | action | reason | idle? | stocks / target |",
        "|---|---:|---:|---:|---:|---|---|---|---:|---:|",
    ])
    for row in payload.get("top_cash_months", []):
        lines.append(
            f"| {row.get('rebalance_date')} | {_pct(row.get('reported_cash_weight'))} | "
            f"{_pct(row.get('book_explicit_cash_weight'))} | {_pct(row.get('reported_vs_book_cash_gap'))} | "
            f"{_pct(row.get('cash_target_used'))} | {row.get('regime_label')} | "
            f"{row.get('rebalance_action')} | `{row.get('primary_cash_reason')}` | "
            f"{str(row.get('possible_idle_cash')).lower()} | {row.get('stock_count')} / {row.get('target_n')} |"
        )
    lines.extend([
        "",
        "## Largest Possible Idle-Cash Months",
        "",
        "| date | reported cash | book cash | gap | target | regime | action | reason | stocks / target |",
        "|---|---:|---:|---:|---:|---|---|---|---:|",
    ])
    for row in payload.get("top_possible_idle_months", []):
        lines.append(
            f"| {row.get('rebalance_date')} | {_pct(row.get('reported_cash_weight'))} | "
            f"{_pct(row.get('book_explicit_cash_weight'))} | {_pct(row.get('reported_vs_book_cash_gap'))} | "
            f"{_pct(row.get('cash_target_used'))} | {row.get('regime_label')} | "
            f"{row.get('rebalance_action')} | `{row.get('primary_cash_reason')}` | "
            f"{row.get('stock_count')} / {row.get('target_n')} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- Defense cash should be preserved in crisis/red regimes.",
        "- Non-risk excess cash is the candidate pool for the next idle-cash redeploy A/B.",
        "- If reported cash and explicit monthly-book cash diverge, downstream replays must use the reported cash source or the monthly book should be repaired.",
        "",
    ])
    return "\n".join(lines)


def run(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    holdings_path = latest_run / "reports" / "main_monthly_weights.csv"
    regime_path = latest_run / "reports" / "regime_by_month.csv"
    holdings = read_table(holdings_path)
    regime = read_table(regime_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    if holdings.empty and regime.empty:
        payload = {
            "status": "blocked",
            "reason": "missing reports/main_monthly_weights.csv and reports/regime_by_month.csv",
            "required_paths": [str(holdings_path), str(regime_path)],
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "cash_drag_summary.json", payload)
        write_text(output_dir / "cash_drag_report.md", "# Cash Policy Attribution\n\nBlocked: missing required monthly artifacts.\n")
        return payload

    rows = _rows_by_month(holdings, regime)
    payload = _summary(rows)
    write_rows(output_dir / "cash_drag_attribution.csv", rows)
    write_json(output_dir / "cash_drag_summary.json", payload)
    write_text(output_dir / "cash_drag_report.md", _render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(repo_path(args.latest_run), repo_path(args.output_dir))
    print(
        {
            "status": payload.get("status"),
            "avg_reported_cash_weight": payload.get("avg_reported_cash_weight"),
            "avg_excess_cash_over_target": payload.get("avg_excess_cash_over_target"),
            "months_possible_idle_cash": payload.get("months_possible_idle_cash"),
            "months_cash_export_mismatch_gt_2pct": payload.get("months_cash_export_mismatch_gt_2pct"),
        }
    )
    return 0 if payload.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
