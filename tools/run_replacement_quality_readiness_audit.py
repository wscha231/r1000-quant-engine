#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def metric_payload(path: Path, portfolio: str = "concentrated") -> dict[str, Any]:
    data = read_json(path)
    if isinstance(data.get("portfolios"), dict):
        return dict(data["portfolios"].get(portfolio) or {})
    return dict(data)


def num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def first_metric(payload: dict[str, Any], names: list[str], default: float = 0.0) -> float:
    for name in names:
        if name in payload:
            return num(payload.get(name), default)
    return default


def cagr_from_values(start: float, end: float, years: float) -> float:
    if start <= 0 or end <= 0 or years <= 0:
        return 0.0
    return (end / start) ** (1.0 / years) - 1.0


def control_reproduction(
    *,
    official: dict[str, Any],
    baseline: dict[str, Any],
    cagr_tolerance: float,
    ending_capital_tolerance_pct: float,
) -> dict[str, Any]:
    official_start = first_metric(official, ["starting_capital_usd", "starting_capital"], 100000.0)
    official_end = first_metric(official, ["ending_capital_usd", "ending_capital", "final_value"], 0.0)
    official_years = first_metric(official, ["years"], 0.0)
    official_cagr = first_metric(official, ["cagr"], 0.0)
    official_max_dd = first_metric(official, ["max_dd", "max_drawdown"], 0.0)

    baseline_start = first_metric(baseline, ["starting_capital_usd", "starting_capital"], official_start)
    baseline_end = first_metric(baseline, ["ending_capital_usd", "ending_capital", "final_value"], 0.0)
    baseline_years = first_metric(baseline, ["years"], official_years)
    baseline_cagr = first_metric(baseline, ["cagr"], 0.0)
    baseline_max_dd = first_metric(baseline, ["max_dd", "max_drawdown"], 0.0)
    cash_interest = first_metric(baseline, ["cash_interest_accrued_usd"], 0.0)
    baseline_mode = str(baseline.get("metric_mode") or "")

    expected_cashcarry_end = official_end + cash_interest if cash_interest else official_end
    expected_cashcarry_cagr = cagr_from_values(baseline_start or official_start, expected_cashcarry_end, baseline_years)
    direct_cagr_delta = baseline_cagr - official_cagr
    cash_adjusted_cagr_delta = baseline_cagr - expected_cashcarry_cagr
    ending_capital_delta = baseline_end - official_end
    cash_adjusted_ending_delta = baseline_end - expected_cashcarry_end
    ending_ref = max(abs(expected_cashcarry_end), 1.0)
    cash_adjusted_ending_delta_pct = cash_adjusted_ending_delta / ending_ref
    cash_carry_expected = "cash_carry" in baseline_mode or bool(cash_interest)
    if cash_carry_expected:
        reproduced = (
            abs(cash_adjusted_cagr_delta) <= cagr_tolerance
            and abs(cash_adjusted_ending_delta_pct) <= ending_capital_tolerance_pct
        )
        comparison_mode = "official_plus_cash_interest"
    else:
        reproduced = abs(direct_cagr_delta) <= cagr_tolerance and abs(ending_capital_delta / max(abs(official_end), 1.0)) <= ending_capital_tolerance_pct
        comparison_mode = "direct_official"

    return {
        "comparison_mode": comparison_mode,
        "control_reproduced": bool(reproduced),
        "official_cagr": official_cagr,
        "official_max_dd": official_max_dd,
        "official_start_date": official.get("start_date"),
        "official_end_date": official.get("end_date"),
        "official_years": official_years,
        "official_ending_capital_usd": official_end,
        "baseline_metric_mode": baseline_mode,
        "baseline_cagr": baseline_cagr,
        "baseline_max_dd": baseline_max_dd,
        "baseline_start_date": baseline.get("start_date"),
        "baseline_end_date": baseline.get("end_date"),
        "baseline_years": baseline_years,
        "baseline_ending_capital_usd": baseline_end,
        "cash_interest_accrued_usd": cash_interest,
        "expected_cashcarry_ending_capital_usd": expected_cashcarry_end,
        "expected_cashcarry_cagr": expected_cashcarry_cagr,
        "direct_cagr_delta": direct_cagr_delta,
        "cash_adjusted_cagr_delta": cash_adjusted_cagr_delta,
        "ending_capital_delta_usd": ending_capital_delta,
        "cash_adjusted_ending_delta_usd": cash_adjusted_ending_delta,
        "cash_adjusted_ending_delta_pct": cash_adjusted_ending_delta_pct,
        "cagr_tolerance": cagr_tolerance,
        "ending_capital_tolerance_pct": ending_capital_tolerance_pct,
    }


def normalize_text(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def load_fixed_swaps(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    out = frame.copy()
    for col in ["rebalance_date", "added_ticker", "removed_ticker"]:
        if col not in out.columns:
            out[col] = ""
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    out["added_ticker"] = out["added_ticker"].map(normalize_text)
    out["removed_ticker"] = out["removed_ticker"].map(normalize_text)
    out["swap_key"] = out["rebalance_date"] + "|" + out["added_ticker"] + "|" + out["removed_ticker"]
    out["source_fixed_book"] = True
    return out


def bool_mask(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})


def load_hook_swaps(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "concentrated_replacement_quality_applied" not in frame.columns:
        return pd.DataFrame(columns=["rebalance_date", "added_ticker", "removed_ticker", "swap_key", "source_hook"])
    applied = bool_mask(frame["concentrated_replacement_quality_applied"])
    out = frame.loc[applied].copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    out["added_ticker"] = out.get("concentrated_replacement_quality_added_ticker", out.get("ticker", "")).map(normalize_text)
    out["removed_ticker"] = out.get("concentrated_replacement_quality_removed_ticker", "").map(normalize_text)
    out["swap_key"] = out["rebalance_date"] + "|" + out["added_ticker"] + "|" + out["removed_ticker"]
    out["source_hook"] = True
    return out


def swap_diff(fixed: pd.DataFrame, hook: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    fixed_cols = [
        "swap_key",
        "rebalance_date",
        "added_ticker",
        "removed_ticker",
        "replacement_weight",
        "leader_rank_ex_ante",
        "rs_spy_3m",
        "revenue_growth",
        "theme",
        "sector",
    ]
    hook_cols = [
        "swap_key",
        "rebalance_date",
        "added_ticker",
        "removed_ticker",
        "concentrated_replacement_quality_replacement_weight",
        "concentrated_replacement_quality_leader_rank_ex_ante",
        "concentrated_replacement_quality_rs_spy_3m",
        "concentrated_replacement_quality_revenue_growth",
        "concentrated_replacement_quality_source_rejection_reason",
        "sector",
        "industry_group",
    ]
    f = fixed[[c for c in fixed_cols if c in fixed.columns]].copy()
    h = hook[[c for c in hook_cols if c in hook.columns]].copy()
    merged = f.merge(h, on="swap_key", how="outer", suffixes=("_fixed", "_hook"), indicator=True)
    merged["diff_status"] = merged["_merge"].map(
        {"both": "both", "left_only": "fixed_only", "right_only": "hook_only"}
    )
    fixed_dates = set(fixed.get("rebalance_date", pd.Series(dtype=str)).astype(str))
    hook_dates = set(hook.get("rebalance_date", pd.Series(dtype=str)).astype(str))
    hook_only = int((merged["diff_status"] == "hook_only").sum())
    fixed_only = int((merged["diff_status"] == "fixed_only").sum())
    both = int((merged["diff_status"] == "both").sum())
    hook_count = int(len(hook))
    fixed_count = int(len(fixed))
    stats = {
        "fixed_swap_count": fixed_count,
        "hook_swap_count": hook_count,
        "overlap_count": both,
        "fixed_only_count": fixed_only,
        "hook_only_count": hook_only,
        "fixed_date_count": len(fixed_dates),
        "hook_date_count": len(hook_dates),
        "date_overlap_count": len(fixed_dates & hook_dates),
        "hook_is_subset_of_fixed": bool(hook_only == 0),
        "hook_overlap_share": float(both / hook_count) if hook_count else 0.0,
        "fixed_covered_share": float(both / fixed_count) if fixed_count else 0.0,
        "hook_broader_than_fixed": bool(hook_count > fixed_count or hook_only > 0),
    }
    return merged, stats


def render_report(summary: dict[str, Any]) -> str:
    control = summary["control_reproduction"]
    swaps = summary["swap_diff"]
    blockers = summary["blockers"]
    cf_inputs = summary.get("counterfactual_inputs") or {}
    lines = [
        "# Replacement-Quality Readiness Audit",
        "",
        f"- status: `{summary['status']}`",
        f"- run label: `{summary.get('run_label')}`",
        f"- official metrics: `{summary['official_metrics']}`",
        f"- counterfactual summary: `{summary['counterfactual_summary']}`",
        f"- hook target book: `{summary['hook_target_book']}`",
        f"- fixed swaps: `{summary['fixed_swaps']}`",
        "",
        "## Counterfactual Inputs",
        "",
        f"- target book: `{cf_inputs.get('target_book', '')}`",
        f"- price cache: `{cf_inputs.get('price_cache', '')}`",
        f"- baseline metrics: `{cf_inputs.get('baseline_metrics', '')}`",
        f"- replay end date: `{cf_inputs.get('replay_end_date', '')}`",
        "",
        "## Control Reproduction",
        "",
        f"- comparison mode: `{control['comparison_mode']}`",
        f"- control reproduced: `{control['control_reproduced']}`",
        f"- official CAGR / MDD: `{control['official_cagr']:.4%}` / `{control['official_max_dd']:.2%}`",
        f"- baseline CAGR / MDD: `{control['baseline_cagr']:.4%}` / `{control['baseline_max_dd']:.2%}`",
        f"- cash-adjusted CAGR delta: `{control['cash_adjusted_cagr_delta']:.4%}`",
        f"- cash-adjusted ending-capital delta: `{control['cash_adjusted_ending_delta_usd']:.2f}` (`{control['cash_adjusted_ending_delta_pct']:.2%}`)",
        "",
        "## Swap Diff",
        "",
        f"- fixed swaps: `{swaps['fixed_swap_count']}`",
        f"- hook swaps: `{swaps['hook_swap_count']}`",
        f"- overlap: `{swaps['overlap_count']}`",
        f"- fixed only: `{swaps['fixed_only_count']}`",
        f"- hook only: `{swaps['hook_only_count']}`",
        f"- hook subset of fixed: `{swaps['hook_is_subset_of_fixed']}`",
        f"- hook overlap share: `{swaps['hook_overlap_share']:.2%}`",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        lines.extend([f"- `{item}`" for item in blockers])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            summary["verdict"],
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    official_path = repo_path(args.official_metrics)
    summary_path = repo_path(args.counterfactual_summary)
    hook_path = repo_path(args.hook_target_book)
    fixed_swaps_path = repo_path(args.fixed_swaps)

    cf_summary = read_json(summary_path)
    baseline_path = repo_path(args.baseline_metrics or cf_summary.get("baseline_metrics") or "")
    cf_inputs = {
        "target_book": cf_summary.get("target_book"),
        "price_cache": cf_summary.get("price_cache"),
        "baseline_metrics": str(baseline_path),
        "replay_end_date": cf_summary.get("replay_end_date"),
        "baseline_metric_mode": cf_summary.get("baseline_metric_mode"),
        "cash_carry_mode": cf_summary.get("cash_carry_mode"),
        "cash_rate_path": cf_summary.get("cash_rate_path"),
    }
    official = metric_payload(official_path, args.portfolio)
    baseline = metric_payload(baseline_path, args.portfolio)
    control = control_reproduction(
        official=official,
        baseline=baseline,
        cagr_tolerance=float(args.cagr_tolerance),
        ending_capital_tolerance_pct=float(args.ending_capital_tolerance_pct),
    )

    fixed = load_fixed_swaps(fixed_swaps_path)
    hook = load_hook_swaps(hook_path)
    diff, diff_stats = swap_diff(fixed, hook)
    diff.to_csv(output_dir / "swap_diff.csv", index=False)
    fixed.to_csv(output_dir / "fixed_swaps_normalized.csv", index=False)
    hook.to_csv(output_dir / "hook_swaps_normalized.csv", index=False)
    pd.DataFrame([control]).to_csv(output_dir / "control_reproduction.csv", index=False)

    blockers: list[str] = []
    if not control["control_reproduced"]:
        blockers.append("control_not_reproduced")
    if diff_stats["hook_broader_than_fixed"]:
        blockers.append("hook_broader_than_fixed_counterfactual")
    if diff_stats["hook_swap_count"] <= 0:
        blockers.append("hook_no_applied_swaps")
    status = "blocked" if blockers else "ready_for_broker_ab"
    verdict = (
        "Do not run fullrun or acceptance broker A/B until blockers are resolved."
        if blockers
        else "Control and swap scope are aligned enough to proceed to cheap broker A/B."
    )
    payload = {
        "schema_version": "replacement-quality-readiness-audit-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "run_label": args.run_label,
        "portfolio": args.portfolio,
        "official_metrics": str(official_path),
        "counterfactual_summary": str(summary_path),
        "baseline_metrics": str(baseline_path),
        "counterfactual_inputs": cf_inputs,
        "hook_target_book": str(hook_path),
        "fixed_swaps": str(fixed_swaps_path),
        "control_reproduction": control,
        "swap_diff": diff_stats,
        "blockers": blockers,
        "verdict": verdict,
        "production_activation_allowed": False,
        "fullrun_allowed": False,
        "live_trading_enabled": False,
    }
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-metrics", required=True)
    parser.add_argument("--counterfactual-summary", required=True)
    parser.add_argument("--hook-target-book", required=True)
    parser.add_argument("--fixed-swaps", required=True)
    parser.add_argument("--baseline-metrics", default="")
    parser.add_argument("--output-dir", default="outputs/replacement_quality_readiness_audit")
    parser.add_argument("--run-label", default="")
    parser.add_argument("--portfolio", default="concentrated")
    parser.add_argument("--cagr-tolerance", type=float, default=0.0025)
    parser.add_argument("--ending-capital-tolerance-pct", type=float, default=0.01)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
