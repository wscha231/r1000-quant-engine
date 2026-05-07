#!/usr/bin/env python3
"""Research-only macro policy engine and regime-speed audit.

The existing production engine already computes macro/regime features inside
the main pipeline. This sidecar does not change production weights. It reads a
completed full-rebuild artifact and emits a policy layer that can later be A/B
tested:

  macro risk state -> style state -> portfolio controls

The design goal is commercial-grade behavior for a high-CAGR equity engine:
fast defense when market plumbing breaks, slow re-entry after drawdowns, and
style routing between breakout growth, quality compounders, turnaround
accumulation, and cash defense.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_rows, write_text


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUT_DIR = "outputs/macro_policy_engine"


STYLE_COLS = [
    "style_breakout_preference",
    "style_turnaround_preference",
    "style_quality_compounder_preference",
    "style_cash_defense_preference",
    "style_liquidity_tailwind_score",
    "style_rate_pressure_score",
    "style_inflation_pressure_score",
    "style_overheat_risk_score",
]


CONTROL_MAP: dict[str, dict[str, Any]] = {
    "green": {
        "cash_floor": 0.03,
        "target_n": 12,
        "core_capacity": 0.30,
        "future_capacity": 0.45,
        "early_capacity": 0.25,
        "concentrated_capacity": 0.20,
        "tactical_capacity": 0.05,
        "new_buy_policy": "normal",
        "trim_policy": "winner_hold_stale_watch",
    },
    "yellow": {
        "cash_floor": 0.10,
        "target_n": 14,
        "core_capacity": 0.35,
        "future_capacity": 0.35,
        "early_capacity": 0.20,
        "concentrated_capacity": 0.10,
        "tactical_capacity": 0.00,
        "new_buy_policy": "scout_only",
        "trim_policy": "half_trim_stale_leaders",
    },
    "red": {
        "cash_floor": 0.28,
        "target_n": 16,
        "core_capacity": 0.35,
        "future_capacity": 0.25,
        "early_capacity": 0.12,
        "concentrated_capacity": 0.05,
        "tactical_capacity": 0.00,
        "new_buy_policy": "no_new_buy_except_top_quality_or_recovery",
        "trim_policy": "half_trim_then_exit_relative_losers",
    },
    "crisis": {
        "cash_floor": 0.45,
        "target_n": 18,
        "core_capacity": 0.30,
        "future_capacity": 0.15,
        "early_capacity": 0.05,
        "concentrated_capacity": 0.00,
        "tactical_capacity": 0.00,
        "new_buy_policy": "risk_reduction_only",
        "trim_policy": "exit_distribution_hold_only_true_winners",
    },
    "recovery": {
        "cash_floor": 0.10,
        "target_n": 14,
        "core_capacity": 0.25,
        "future_capacity": 0.40,
        "early_capacity": 0.30,
        "concentrated_capacity": 0.10,
        "tactical_capacity": 0.03,
        "new_buy_policy": "staged_scout_then_confirm",
        "trim_policy": "keep_cash_until_confirmation",
    },
}


NEXT_DATA_WATCHLIST = [
    {
        "group": "market_breadth",
        "series_or_source": "SPY/QQQ/RSP/IWM/SMH relative strength, % above MA50/MA200, new highs-lows",
        "why": "Fast warning when index leadership narrows or growth leaders break.",
        "priority": "high",
    },
    {
        "group": "credit_stress",
        "series_or_source": "FRED BAMLH0A0HYM2, BAMLC0A0CM, Chicago Fed NFCI/ANFCI, OFR FSI",
        "why": "Keep bear regimes active when financial conditions tighten slowly.",
        "priority": "high",
    },
    {
        "group": "volatility_structure",
        "series_or_source": "VIX level/change, VIX term structure, VVIX, MOVE",
        "why": "Distinguish temporary volatility shock from persistent risk-off plumbing stress.",
        "priority": "high",
    },
    {
        "group": "liquidity",
        "series_or_source": "WALCL, WTREGEN, RRPONTSYD, M2SL, DXY",
        "why": "Route between growth breakout and cash defense.",
        "priority": "high",
    },
    {
        "group": "labor_cycle",
        "series_or_source": "SAHMREALTIME, ICSA, CCSA, UNRATE",
        "why": "Separate slowdown/recession risk from pure equity-market pullbacks.",
        "priority": "medium",
    },
    {
        "group": "earnings_breadth",
        "series_or_source": "EPS revision breadth, surprise breadth by sector/theme",
        "why": "Confirm whether a style/sector rally is supported by fundamentals.",
        "priority": "medium",
    },
]


def _first_non_empty(values: list[Any], default: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return default


def _mean_group(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out = out.dropna(subset=["rebalance_date"])
    rows: list[dict[str, Any]] = []
    for dt, group in out.groupby("rebalance_date", sort=True):
        row: dict[str, Any] = {"rebalance_date": dt}
        for col in columns:
            if col in group.columns:
                row[col] = pd.to_numeric(group[col], errors="coerce").mean()
            else:
                row[col] = 0.0
        if "market_style_regime_label" in group.columns:
            modes = group["market_style_regime_label"].dropna().astype(str)
            row["market_style_regime_label"] = modes.mode().iloc[0] if not modes.empty else "unknown"
        if "regime_state" in group.columns:
            modes = group["regime_state"].dropna().astype(str)
            row["regime_state_from_candidates"] = modes.mode().iloc[0] if not modes.empty else ""
        rows.append(row)
    return pd.DataFrame(rows)


def _regime_state_by_month(latest_run: Path) -> pd.DataFrame:
    for rel in ("reports/main_monthly_weights.csv", "reports/candidate_replay_book.csv"):
        frame = read_table(latest_run / rel)
        if frame.empty or "rebalance_date" not in frame.columns or "regime_state" not in frame.columns:
            continue
        out = frame.copy()
        out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        rows = []
        for dt, group in out.groupby("rebalance_date", sort=True):
            modes = group["regime_state"].dropna().astype(str)
            rows.append({"rebalance_date": dt, "regime_state": modes.mode().iloc[0] if not modes.empty else ""})
        return pd.DataFrame(rows)
    return pd.DataFrame()


def _risk_score(row: dict[str, Any]) -> float:
    label = str(row.get("regime_label") or "").lower()
    state = str(row.get("regime_state") or "").lower()
    cash_target = safe_float(row.get("cash_target_used"), 0.0)
    cash_weight = safe_float(row.get("cash_weight"), 0.0)
    dd_before = safe_float(row.get("drawdown_before_month"), 0.0)
    dd_after = safe_float(row.get("drawdown_after_month"), 0.0)
    score = 0.0
    if "systemic" in label:
        score += 0.80
    elif "risk_off" in label:
        score += 0.62
    elif "growth_reentry" in label:
        score += 0.18
    else:
        score += 0.10

    if state == "deep_bear":
        score += 0.35
    elif state == "bear":
        score += 0.22
    elif state in {"bull", "strong_bull"}:
        score -= 0.10

    if cash_target >= 0.40 or cash_weight >= 0.50:
        score += 0.25
    elif cash_target >= 0.28 or cash_weight >= 0.25:
        score += 0.15
    if dd_before <= -0.15 or dd_after <= -0.15:
        score += 0.25
    elif dd_before <= -0.08 or dd_after <= -0.08:
        score += 0.15
    elif dd_before <= -0.04 or dd_after <= -0.04:
        score += 0.08
    return max(0.0, min(1.0, score))


def _risk_state(row: dict[str, Any], risk_score: float) -> str:
    label = str(row.get("regime_label") or "").lower()
    cash_target = safe_float(row.get("cash_target_used"), 0.0)
    dd_before = safe_float(row.get("drawdown_before_month"), 0.0)
    dd_after = safe_float(row.get("drawdown_after_month"), 0.0)
    if "systemic" in label or dd_before <= -0.15 or dd_after <= -0.15 or cash_target >= 0.40:
        return "crisis"
    if risk_score >= 0.65:
        return "red"
    if "growth_reentry" in label and dd_before > -0.08 and dd_after > -0.05:
        return "recovery"
    if risk_score >= 0.35:
        return "yellow"
    return "green"


def _style_state(row: dict[str, Any], risk_state: str) -> str:
    if risk_state in {"red", "crisis"}:
        return "cash_defense"
    scores = {
        "breakout_growth": safe_float(row.get("style_breakout_preference"), 0.0),
        "turnaround_accumulation": safe_float(row.get("style_turnaround_preference"), 0.0),
        "quality_compounder": safe_float(row.get("style_quality_compounder_preference"), 0.0),
        "cash_defense": safe_float(row.get("style_cash_defense_preference"), 0.0),
    }
    label = str(row.get("market_style_regime_label") or "").strip()
    if max(scores.values()) <= 0 and label:
        return label
    return max(scores.items(), key=lambda item: item[1])[0]


def _diagnostic_flags(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    prev_risk = False
    prev_label = ""
    for row in rows:
        label = str(row.get("regime_label") or "")
        risk_state = str(row.get("macro_risk_state") or "")
        is_risk = risk_state in {"red", "crisis"} or "risk_off" in label or "systemic" in label
        dd_before = safe_float(row.get("drawdown_before_month"), 0.0)
        dd_after = safe_float(row.get("drawdown_after_month"), 0.0)
        cash_weight = safe_float(row.get("cash_weight"), 0.0)
        flags: list[str] = []
        if dd_after <= -0.05 and not (is_risk or prev_risk):
            flags.append("late_risk_alert")
        if label == "balanced" and (dd_before <= -0.08 or dd_after <= -0.08):
            flags.append("balanced_under_drawdown")
        if label == "growth_reentry_alert" and (dd_before <= -0.08 or dd_after <= -0.05):
            flags.append("premature_growth_reentry")
        if cash_weight >= 0.25 and dd_before > -0.02 and dd_after > -0.02 and risk_state in {"green", "recovery"}:
            flags.append("possible_cash_drag")
        if flags:
            out.append(
                {
                    "rebalance_date": row.get("rebalance_date"),
                    "diagnostic_flags": ";".join(flags),
                    "regime_label": label,
                    "previous_regime_label": prev_label,
                    "macro_risk_state": risk_state,
                    "regime_state": row.get("regime_state", ""),
                    "cash_weight": row.get("cash_weight", ""),
                    "cash_target_used": row.get("cash_target_used", ""),
                    "drawdown_before_month": row.get("drawdown_before_month", ""),
                    "drawdown_after_month": row.get("drawdown_after_month", ""),
                    "recommended_action": row.get("recommended_action", ""),
                }
            )
        prev_risk = is_risk
        prev_label = label
    return out


def run(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    regime_path = latest_run / "reports" / "regime_by_month.csv"
    regime = read_table(regime_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    if regime.empty:
        payload = {
            "status": "blocked",
            "reason": "missing reports/regime_by_month.csv",
            "required_path": str(regime_path),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        write_text(output_dir / "report.md", "# Macro Policy Engine\n\nBlocked: missing regime_by_month.csv.\n")
        return payload

    regime = regime.copy()
    regime["rebalance_date"] = pd.to_datetime(regime["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    regime = regime.dropna(subset=["rebalance_date"])

    state = _regime_state_by_month(latest_run)
    if not state.empty:
        regime = regime.merge(state, on="rebalance_date", how="left")
    elif "regime_state" not in regime.columns:
        regime["regime_state"] = ""

    candidate = read_table(latest_run / "reports" / "candidate_replay_book.csv")
    style = _mean_group(candidate, STYLE_COLS)
    if not style.empty:
        regime = regime.merge(style, on="rebalance_date", how="left")

    rows: list[dict[str, Any]] = []
    for raw in regime.to_dict("records"):
        row = dict(raw)
        row["regime_state"] = _first_non_empty(
            [row.get("regime_state"), row.get("regime_state_from_candidates")],
            default="unknown",
        )
        risk_score = _risk_score(row)
        risk_state = _risk_state(row, risk_score)
        style_state = _style_state(row, risk_state)
        controls = CONTROL_MAP[risk_state]
        row.update(
            {
                "macro_risk_score": risk_score,
                "macro_risk_state": risk_state,
                "macro_style_state": style_state,
                "recommended_cash_floor": controls["cash_floor"],
                "recommended_target_n": controls["target_n"],
                "recommended_core_capacity": controls["core_capacity"],
                "recommended_future_capacity": controls["future_capacity"],
                "recommended_early_capacity": controls["early_capacity"],
                "recommended_concentrated_capacity": controls["concentrated_capacity"],
                "recommended_tactical_capacity": controls["tactical_capacity"],
                "recommended_new_buy_policy": controls["new_buy_policy"],
                "recommended_trim_policy": controls["trim_policy"],
                "recommended_action": _recommended_action(risk_state, style_state),
                "research_only": True,
                "production_activation_allowed": False,
            }
        )
        rows.append(row)

    diagnostics = _diagnostic_flags(rows)
    summary = _summary(rows, diagnostics, regime_path)

    write_json(output_dir / "summary.json", summary)
    write_rows(output_dir / "macro_policy_by_month.csv", rows)
    write_rows(output_dir / "regime_speed_audit.csv", diagnostics)
    write_rows(output_dir / "required_data_watchlist.csv", NEXT_DATA_WATCHLIST)
    write_text(output_dir / "report.md", render_report(summary, diagnostics))
    return summary


def _recommended_action(risk_state: str, style_state: str) -> str:
    if risk_state == "crisis":
        return "raise_cash_exit_distribution_only_hold_best_structural_winners"
    if risk_state == "red":
        return "defend_half_trim_stale_leaders_no_tactical_new_buys"
    if risk_state == "yellow":
        return "slow_new_buys_scout_only_require_confirmation"
    if risk_state == "recovery":
        return "staged_reentry_scout_then_scale_confirmed_new_leaders"
    if style_state == "breakout_growth":
        return "favor_future_winners_and_monster_breakouts"
    if style_state == "turnaround_accumulation":
        return "favor_early_scout_turnaround_accumulation"
    if style_state == "quality_compounder":
        return "favor_core_compounders_long_hold"
    return "balanced_growth_with_stale_leader_watch"


def _summary(rows: list[dict[str, Any]], diagnostics: list[dict[str, Any]], regime_path: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    style_counts: dict[str, int] = {}
    for row in rows:
        counts[str(row.get("macro_risk_state"))] = counts.get(str(row.get("macro_risk_state")), 0) + 1
        style_counts[str(row.get("macro_style_state"))] = style_counts.get(str(row.get("macro_style_state")), 0) + 1
    diag_counts: dict[str, int] = {}
    for row in diagnostics:
        for flag in str(row.get("diagnostic_flags") or "").split(";"):
            if flag:
                diag_counts[flag] = diag_counts.get(flag, 0) + 1
    latest = rows[-1] if rows else {}
    return {
        "status": "completed",
        "experiment_id": "macro_policy_engine",
        "source_regime_by_month": str(regime_path),
        "months": len(rows),
        "risk_state_counts": counts,
        "style_state_counts": style_counts,
        "diagnostic_counts": diag_counts,
        "latest": {
            "rebalance_date": latest.get("rebalance_date", ""),
            "macro_risk_state": latest.get("macro_risk_state", ""),
            "macro_style_state": latest.get("macro_style_state", ""),
            "recommended_cash_floor": latest.get("recommended_cash_floor", ""),
            "recommended_target_n": latest.get("recommended_target_n", ""),
            "recommended_new_buy_policy": latest.get("recommended_new_buy_policy", ""),
            "recommended_trim_policy": latest.get("recommended_trim_policy", ""),
            "recommended_action": latest.get("recommended_action", ""),
        },
        "research_only": True,
        "production_activation_allowed": False,
    }


def render_report(summary: dict[str, Any], diagnostics: list[dict[str, Any]]) -> str:
    latest = summary.get("latest") or {}
    diag_counts = summary.get("diagnostic_counts") or {}
    lines = [
        "# Macro Policy Engine",
        "",
        "Research-only sidecar. It does not change production weights.",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Months: {summary.get('months')}",
        f"- Latest risk state: `{latest.get('macro_risk_state', 'unknown')}`",
        f"- Latest style state: `{latest.get('macro_style_state', 'unknown')}`",
        f"- Recommended cash floor: {safe_float(latest.get('recommended_cash_floor')):.1%}",
        f"- Recommended target N: {latest.get('recommended_target_n', '')}",
        f"- New-buy policy: `{latest.get('recommended_new_buy_policy', '')}`",
        f"- Trim policy: `{latest.get('recommended_trim_policy', '')}`",
        f"- Action: `{latest.get('recommended_action', '')}`",
        "",
        "## Risk State Counts",
        "",
    ]
    for key, value in sorted((summary.get("risk_state_counts") or {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Regime Speed Diagnostics", ""])
    if diag_counts:
        for key, value in sorted(diag_counts.items()):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Use `macro_policy_by_month.csv` to A/B a slower re-entry / faster",
            "defense policy in Main v2. Use `regime_speed_audit.csv` to find",
            "months where the current regime label returned to balanced too early",
            "or kept excessive cash after risk had already normalized.",
            "",
            "Production promotion requires a separate historical challenger replay.",
        ]
    )
    if diagnostics:
        lines.extend(["", "## First Diagnostics", ""])
        for row in diagnostics[:10]:
            lines.append(
                f"- {row.get('rebalance_date')}: {row.get('diagnostic_flags')} "
                f"({row.get('regime_label')} -> {row.get('macro_risk_state')})"
            )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out = run(repo_path(args.latest_run), repo_path(args.output_dir))
    print(f"[macro-policy] {out.get('status')} -> {repo_path(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
