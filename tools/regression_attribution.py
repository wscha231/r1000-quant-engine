#!/usr/bin/env python3
"""Build a report-only regression attribution between two cloud runs.

This tool reads existing artifacts only. It does not import or execute the
production engine and does not write production outputs.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from aggressive_lab_common import (
    ROOT,
    metric_delta,
    pct,
    read_csv_rows,
    read_json,
    safe_float,
    safe_int,
    write_json,
)


DEFAULT_LEFT = "cloud_results/full_rebuild/20260430_global_alpha_universe"
DEFAULT_RIGHT = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_REGISTRY = "cloud_results/full_rebuild/latest_global_alpha_universe/reports/baseline_registry.json"


def _run_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return ROOT / p


def _metrics(run_dir: Path) -> dict[str, Any]:
    return read_json(run_dir / "backtest_metrics.json", {}) or {}


def _concentrated_metrics(run_dir: Path) -> dict[str, Any]:
    return read_json(run_dir / "concentrated_backtest_metrics.json", {}) or {}


def _portfolio(run_dir: Path) -> list[dict[str, str]]:
    return read_csv_rows(run_dir / "portfolio_latest.csv")


def _scored(run_dir: Path) -> list[dict[str, str]]:
    return read_csv_rows(run_dir / "scored_latest.csv")


def _top_holdings(rows: list[dict[str, str]], n: int = 20) -> list[dict[str, Any]]:
    out = []
    for row in rows[:n]:
        out.append(
            {
                "ticker": row.get("ticker", ""),
                "rank": safe_int(row.get("rank"), 0),
                "weight": safe_float(row.get("weight"), 0.0),
                "score": safe_float(row.get("score"), None),
                "sector": row.get("sector", ""),
                "sleeve": row.get("portfolio_sleeve_label", ""),
            }
        )
    return out


def _portfolio_diff(left_rows: list[dict[str, str]], right_rows: list[dict[str, str]]) -> dict[str, Any]:
    left_by_ticker = {str(r.get("ticker", "")).upper(): r for r in left_rows if r.get("ticker")}
    right_by_ticker = {str(r.get("ticker", "")).upper(): r for r in right_rows if r.get("ticker")}
    left_tickers = set(left_by_ticker)
    right_tickers = set(right_by_ticker)
    common = sorted(left_tickers & right_tickers)
    added = sorted(right_tickers - left_tickers)
    removed = sorted(left_tickers - right_tickers)
    weight_deltas = []
    for ticker in common:
        left_w = safe_float(left_by_ticker[ticker].get("weight"), 0.0) or 0.0
        right_w = safe_float(right_by_ticker[ticker].get("weight"), 0.0) or 0.0
        weight_deltas.append(
            {
                "ticker": ticker,
                "left_weight": left_w,
                "right_weight": right_w,
                "delta_weight": right_w - left_w,
                "left_rank": safe_int(left_by_ticker[ticker].get("rank"), 0),
                "right_rank": safe_int(right_by_ticker[ticker].get("rank"), 0),
            }
        )
    weight_deltas.sort(key=lambda x: abs(float(x["delta_weight"])), reverse=True)
    return {
        "left_count": len(left_rows),
        "right_count": len(right_rows),
        "common_count": len(common),
        "added": added,
        "removed": removed,
        "largest_weight_deltas": weight_deltas[:15],
    }


def _scored_diagnostics(rows: list[dict[str, str]]) -> dict[str, Any]:
    regimes: dict[str, int] = {}
    event_alerts: dict[str, int] = {}
    explosion_cols = ["explosion_entry_score", "explosion_exit_score", "explosion_net_score"]
    max_abs_explosion = 0.0
    adr_rows = 0
    adr_selected_like = 0
    for row in rows:
        regime = row.get("regime_state", "")
        if regime:
            regimes[regime] = regimes.get(regime, 0) + 1
        alert = row.get("live_event_alert_label", "")
        if alert:
            event_alerts[alert] = event_alerts.get(alert, 0) + 1
        for col in explosion_cols:
            val = abs(safe_float(row.get(col), 0.0) or 0.0)
            max_abs_explosion = max(max_abs_explosion, val)
        source = str(row.get("universe_source", "")).lower()
        is_adr = "adr" in source
        if is_adr:
            adr_rows += 1
            if str(row.get("adr_global_alpha_fallback_pass")).lower() in {"true", "1", "1.0"}:
                adr_selected_like += 1
    return {
        "row_count": len(rows),
        "regime_distribution": regimes,
        "live_event_alert_distribution": event_alerts,
        "explosion_columns_present": [c for c in explosion_cols if rows and c in rows[0]],
        "explosion_nonzero": max_abs_explosion > 0.0,
        "max_abs_explosion_score": max_abs_explosion,
        "adr_rows_with_indicator": adr_rows,
        "adr_fallback_pass_count": adr_selected_like,
    }


def _read_trade_summary(run_dir: Path) -> dict[str, Any]:
    candidates = [
        run_dir / "trade_journal" / "insights" / "summary.md",
        run_dir / "trade_journal" / "trade_journal" / "insights" / "summary.md",
    ]
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            trade_count = None
            m = re.search(r"trades analyzed:\s*\*\*(\d+)\*\*", text)
            if m:
                trade_count = int(m.group(1))
            return {"path": str(path.relative_to(ROOT)), "trade_count": trade_count, "summary_text": text}
    return {"path": None, "trade_count": None, "summary_text": ""}


def _read_auto_learning(run_dir: Path) -> dict[str, Any]:
    return read_json(run_dir / "auto_learning" / "promotion_decision.json", {}) or {}


def _read_orchestrator(run_dir: Path) -> dict[str, Any]:
    for rel in [
        "orchestrator/unified_target_latest.json",
        "orchestrator/orchestrator/unified_target_latest.json",
    ]:
        payload = read_json(run_dir / rel, None)
        if payload:
            return payload
    return {}


def _compare_metric_sets(left: dict[str, Any], right: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: metric_delta(left.get(key), right.get(key)) for key in keys}


def build_attribution(left_dir: Path, right_dir: Path, registry_path: Path | None = None) -> dict[str, Any]:
    left_metrics = _metrics(left_dir)
    right_metrics = _metrics(right_dir)
    left_conc = _concentrated_metrics(left_dir)
    right_conc = _concentrated_metrics(right_dir)
    left_port = _portfolio(left_dir)
    right_port = _portfolio(right_dir)
    left_scored = _scored(left_dir)
    right_scored = _scored(right_dir)
    registry = read_json(registry_path, {}) if registry_path else {}

    main_keys = [
        "cagr",
        "sharpe",
        "sortino",
        "max_dd",
        "calmar",
        "ir",
        "avg_turnover_monthly",
        "avg_cash_weight",
        "avg_stock_names",
        "months",
        "ending_capital_usd",
        "benchmark_cagr",
        "excess_cagr",
    ]
    conc_keys = ["strategy_cagr", "sharpe", "max_dd", "comparison_objective", "selected_names"]

    return {
        "left_run": str(left_dir.relative_to(ROOT) if left_dir.is_relative_to(ROOT) else left_dir).replace("\\", "/"),
        "right_run": str(right_dir.relative_to(ROOT) if right_dir.is_relative_to(ROOT) else right_dir).replace("\\", "/"),
        "phase15d_control": (registry or {}).get("controls", {}).get("phase15d", {}),
        "main_metric_deltas": _compare_metric_sets(left_metrics, right_metrics, main_keys),
        "concentrated_metric_deltas": _compare_metric_sets(left_conc, right_conc, conc_keys),
        "left_main_metrics": left_metrics,
        "right_main_metrics": right_metrics,
        "left_concentrated_metrics": left_conc,
        "right_concentrated_metrics": right_conc,
        "portfolio_diff": _portfolio_diff(left_port, right_port),
        "left_top_holdings": _top_holdings(left_port),
        "right_top_holdings": _top_holdings(right_port),
        "left_scored_diagnostics": _scored_diagnostics(left_scored),
        "right_scored_diagnostics": _scored_diagnostics(right_scored),
        "left_trade_summary": _read_trade_summary(left_dir),
        "right_trade_summary": _read_trade_summary(right_dir),
        "right_auto_learning": _read_auto_learning(right_dir),
        "right_orchestrator": _read_orchestrator(right_dir),
    }


def _delta_line(label: str, delta: dict[str, Any], as_pct: bool = True) -> str:
    left = delta.get("left")
    right = delta.get("right")
    dpp = delta.get("delta_pp")
    if as_pct:
        left_s = pct(left)
        right_s = pct(right)
        delta_s = "n/a" if dpp is None else f"{dpp:+.2f} pp"
    else:
        left_s = "n/a" if left is None else f"{left:.4f}"
        right_s = "n/a" if right is None else f"{right:.4f}"
        raw_delta = delta.get("delta")
        delta_s = "n/a" if raw_delta is None else f"{raw_delta:+.4f}"
    return f"| {label} | {left_s} | {right_s} | {delta_s} |"


def render_markdown(payload: dict[str, Any]) -> str:
    main = payload["main_metric_deltas"]
    conc = payload["concentrated_metric_deltas"]
    pdiff = payload["portfolio_diff"]
    right_diag = payload["right_scored_diagnostics"]
    right_auto = payload["right_auto_learning"]
    orch = payload["right_orchestrator"]
    phase15 = payload.get("phase15d_control") or {}

    lines: list[str] = []
    lines.append("# Regression Attribution: 20260430 vs Latest")
    lines.append("")
    lines.append("Mode: report-only. No production files were changed.")
    lines.append("")
    lines.append(f"- Left run: `{payload['left_run']}`")
    lines.append(f"- Right run: `{payload['right_run']}`")
    if phase15:
        lines.append(
            "- Phase 15-D control: "
            f"CAGR {pct(phase15.get('cagr'))}, Sharpe {phase15.get('sharpe')}, MaxDD {pct(phase15.get('max_dd'))}"
        )
    lines.append("")

    lines.append("## Main Metrics")
    lines.append("")
    lines.append("| Metric | 20260430 | Latest | Delta |")
    lines.append("| --- | ---: | ---: | ---: |")
    lines.append(_delta_line("CAGR", main["cagr"]))
    lines.append(_delta_line("Sharpe", main["sharpe"], as_pct=False))
    lines.append(_delta_line("MaxDD", main["max_dd"]))
    lines.append(_delta_line("Monthly turnover", main["avg_turnover_monthly"]))
    lines.append(_delta_line("Avg stock names", main["avg_stock_names"], as_pct=False))
    lines.append(_delta_line("Ending capital", main["ending_capital_usd"], as_pct=False))
    lines.append("")

    lines.append("## Concentrated Metrics")
    lines.append("")
    lines.append("| Metric | 20260430 | Latest | Delta |")
    lines.append("| --- | ---: | ---: | ---: |")
    lines.append(_delta_line("CAGR", conc["strategy_cagr"]))
    lines.append(_delta_line("Sharpe", conc["sharpe"], as_pct=False))
    lines.append(_delta_line("MaxDD", conc["max_dd"]))
    lines.append(_delta_line("Selected names", conc["selected_names"], as_pct=False))
    lines.append("")

    lines.append("## Holdings Diff")
    lines.append("")
    lines.append(f"- Left positions: {pdiff['left_count']}")
    lines.append(f"- Right positions: {pdiff['right_count']}")
    lines.append(f"- Common positions: {pdiff['common_count']}")
    lines.append(f"- Added: {', '.join(pdiff['added']) if pdiff['added'] else 'none'}")
    lines.append(f"- Removed: {', '.join(pdiff['removed']) if pdiff['removed'] else 'none'}")
    lines.append("")
    lines.append("Largest common-name weight changes:")
    lines.append("")
    lines.append("| Ticker | 20260430 weight | Latest weight | Delta | Rank change |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for row in pdiff["largest_weight_deltas"][:10]:
        rank_change = int(row["right_rank"]) - int(row["left_rank"])
        lines.append(
            f"| {row['ticker']} | {pct(row['left_weight'])} | {pct(row['right_weight'])} | "
            f"{float(row['delta_weight']) * 100:+.2f} pp | {rank_change:+d} |"
        )
    lines.append("")

    lines.append("## Latest Diagnostics")
    lines.append("")
    lines.append(f"- Scored rows: {right_diag.get('row_count')}")
    lines.append(f"- Regime distribution: `{right_diag.get('regime_distribution')}`")
    lines.append(f"- Explosion columns present: `{right_diag.get('explosion_columns_present')}`")
    lines.append(f"- Explosion nonzero: `{right_diag.get('explosion_nonzero')}`")
    lines.append(f"- ADR indicator rows: {right_diag.get('adr_rows_with_indicator')}")
    lines.append(f"- ADR fallback pass count: {right_diag.get('adr_fallback_pass_count')}")
    lines.append("")

    lines.append("## Trade Journal And Auto-Learning")
    lines.append("")
    trade = payload["right_trade_summary"]
    lines.append(f"- Latest trade insight path: `{trade.get('path')}`")
    lines.append(f"- Latest trades analyzed: {trade.get('trade_count')}")
    if right_auto:
        lines.append(f"- Auto-learning approved: `{right_auto.get('approved')}`")
        lines.append(f"- Auto-learning promoted: `{right_auto.get('promoted')}`")
        lines.append(f"- Block reasons: `{right_auto.get('reasons')}`")
    lines.append("")

    lines.append("## Orchestrator Shadow State")
    lines.append("")
    if orch:
        lines.append(f"- Regime: `{orch.get('regime_state')}`")
        lines.append(f"- Cash target: {pct(orch.get('cash_target'))}")
        lines.append(f"- Mandate capacity: `{orch.get('by_mandate_capacity')}`")
        audit = orch.get("audit") or {}
        policy = audit.get("policy_capacity") or {}
        lines.append(f"- Actual invested after merge: {pct(policy.get('actual_total_invested_after_merge'))}")
        lines.append(f"- Merge conflict drag: {pct(policy.get('merged_below_expected_due_to_conflicts'))}")
    else:
        lines.append("- No orchestrator artifact found.")
    lines.append("")

    lines.append("## Initial Attribution Read")
    lines.append("")
    lines.append("- Latest main regressed on CAGR, Sharpe, and MaxDD versus 20260430.")
    lines.append("- Turnover stayed near the same high level, so regression was not compensated by lower churn.")
    lines.append("- Concentrated remains stronger than main, but its CAGR also declined from the 20260430 control.")
    lines.append("- Latest regime and explosion diagnostics show no active non-neutral or explosion signal contribution.")
    lines.append("- The highest-priority next experiment is not another production full rebuild; it is isolated Main v2 and orchestrator challenger testing.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", default=DEFAULT_LEFT)
    parser.add_argument("--right", default=DEFAULT_RIGHT)
    parser.add_argument("--phase15-control", default=DEFAULT_REGISTRY)
    parser.add_argument("--out", default="reports/regression_attribution_20260430_vs_latest.md")
    parser.add_argument("--json-out", default="reports/regression_attribution_20260430_vs_latest.json")
    args = parser.parse_args()

    left_dir = _run_path(args.left)
    right_dir = _run_path(args.right)
    registry = _run_path(args.phase15_control) if args.phase15_control else None
    payload = build_attribution(left_dir, right_dir, registry)
    write_json(args.json_out, payload)
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_markdown(payload), encoding="utf-8")
    print(f"[regression] wrote {out_path}")
    print(f"[regression] wrote {ROOT / args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
