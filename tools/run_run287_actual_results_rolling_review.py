#!/usr/bin/env python3
"""Rolling robustness review for run287 actual-results tilts.

This is a cheap, fixed-book broker-ledger review. It reruns only the unchanged
baseline and one default-off `actual_results_score` top-quintile tilt, then
computes rolling and calendar-window deltas from the resulting equity curves. It
does not dispatch a fullrun, add a hook, tune thresholds, or mutate production
state.
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

from tools.run_run287_profitability_broker_ab import (  # noqa: E402
    DEFAULT_LATEST_RUN,
    DEFAULT_REPLAY_END_DATE,
    build_arms,
    generate_arm_book,
    repo_path,
    resolve_target_book,
    run_broker_replay,
    safe_float,
    write_csv,
    write_json,
    write_text,
)
from tools.alphaops_governance import (  # noqa: E402
    measurement_contract_acceptance_blockers,
    measurement_contract_caveat_fields,
)

SCHEMA_VERSION = "run287-actual-results-rolling-review-v1"
DEFAULT_OUTPUT_DIR = "outputs/run287_actual_results_rolling_review"
DEFAULT_PARITY_SUMMARY = "outputs/run287_parity/summary.json"
DEFAULT_SURVIVORSHIP_SUMMARY = "outputs/run287_survivorship/summary.json"
SIGNAL = "actual_results_score"
DEFAULT_PORTFOLIO_KIND = "main"
DEFAULT_TARGET_ARM = "actual_results_top_quintile_tilt10"
DEFAULT_ROLLING_MONTHS = (12, 24, 36)


def target_cagr_for_portfolio(portfolio_kind: str) -> float:
    return 0.50 if str(portfolio_kind).lower() == "concentrated" else 0.35


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_equity(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["equity_usd"] = pd.to_numeric(frame["equity_usd"], errors="coerce")
    return frame.dropna(subset=["date", "equity_usd"]).sort_values("date").reset_index(drop=True)


def calc_window_metrics(equity: pd.DataFrame, *, label: str, start: pd.Timestamp | None, end: pd.Timestamp | None) -> dict[str, Any]:
    frame = equity.copy()
    if start is not None:
        frame = frame[frame["date"] >= start]
    if end is not None:
        frame = frame[frame["date"] <= end]
    frame = frame.dropna(subset=["date", "equity_usd"]).sort_values("date")
    if len(frame) < 2:
        return {
            "label": label,
            "status": "insufficient_points",
            "start_date": None,
            "end_date": None,
            "days": 0,
            "years": 0.0,
            "cagr": None,
            "max_dd": None,
        }
    start_date = pd.Timestamp(frame["date"].iloc[0]).normalize()
    end_date = pd.Timestamp(frame["date"].iloc[-1]).normalize()
    years = max((end_date - start_date).days / 365.25, 1e-9)
    start_eq = safe_float(frame["equity_usd"].iloc[0])
    end_eq = safe_float(frame["equity_usd"].iloc[-1])
    cagr = (end_eq / max(start_eq, 1e-12)) ** (1.0 / years) - 1.0
    rolling_peak = frame["equity_usd"].cummax()
    dd = frame["equity_usd"] / rolling_peak - 1.0
    return {
        "label": label,
        "status": "completed",
        "start_date": start_date.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "days": int((end_date - start_date).days),
        "years": float(years),
        "cagr": float(cagr),
        "max_dd": float(dd.min()),
        "start_equity_usd": float(start_eq),
        "end_equity_usd": float(end_eq),
    }


def month_end_dates(equity: pd.DataFrame) -> list[pd.Timestamp]:
    dates = pd.to_datetime(equity["date"], errors="coerce").dropna().sort_values()
    if dates.empty:
        return []
    month_ends = dates.groupby(dates.dt.to_period("M")).max().tolist()
    return [pd.Timestamp(value).normalize() for value in month_ends]


def metric_delta_row(
    base: dict[str, Any],
    arm: dict[str, Any],
    *,
    group: str,
    label: str,
    target_cagr: float,
) -> dict[str, Any]:
    row = {
        "window_group": group,
        "window": label,
        "start_date": arm.get("start_date"),
        "end_date": arm.get("end_date"),
        "years": arm.get("years"),
        "baseline_cagr": base.get("cagr"),
        "candidate_cagr": arm.get("cagr"),
        "baseline_max_dd": base.get("max_dd"),
        "candidate_max_dd": arm.get("max_dd"),
    }
    if base.get("cagr") is not None and arm.get("cagr") is not None:
        row["delta_cagr_pp"] = (safe_float(arm.get("cagr")) - safe_float(base.get("cagr"))) * 100.0
    else:
        row["delta_cagr_pp"] = None
    if base.get("max_dd") is not None and arm.get("max_dd") is not None:
        row["delta_max_dd_pp"] = (safe_float(arm.get("max_dd")) - safe_float(base.get("max_dd"))) * 100.0
    else:
        row["delta_max_dd_pp"] = None
    row["candidate_contract_pass"] = bool(
        arm.get("cagr") is not None
        and arm.get("max_dd") is not None
        and safe_float(arm.get("cagr")) >= target_cagr
        and safe_float(arm.get("max_dd")) >= -0.25
    )
    row["delta_positive"] = bool(row["delta_cagr_pp"] is not None and safe_float(row["delta_cagr_pp"]) > 0.0)
    return row


def broker_window_metric(metrics: dict[str, Any], *, label: str, key: str) -> dict[str, Any] | None:
    block = metrics if key == "full" else (metrics.get("windows") or {}).get(key)
    if not isinstance(block, dict) or block.get("cagr") is None or block.get("max_dd") is None:
        return None
    return {
        "label": label,
        "status": block.get("status", "completed"),
        "start_date": block.get("start_date"),
        "end_date": block.get("end_date"),
        "days": block.get("days"),
        "years": block.get("years"),
        "cagr": block.get("cagr"),
        "max_dd": block.get("max_dd"),
        "start_equity_usd": block.get("starting_capital_usd"),
        "end_equity_usd": block.get("ending_capital_usd"),
    }


def replace_fixed_rows_with_broker_metrics(
    rows: list[dict[str, Any]],
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    *,
    target_cagr: float,
) -> list[dict[str, Any]]:
    """Use broker metrics for fixed windows; keep equity-curve math for rolling windows."""
    old_fixed = {(row["window_group"], row["window"]): row for row in rows if row["window_group"] == "fixed"}
    out: list[dict[str, Any]] = []
    fixed_defs = [
        ("full", "full"),
        ("is_to_2024_06_30", "is"),
        ("oos_from_2024_07_01", "oos"),
        ("oos2_from_2023_01_01", "oos2"),
    ]
    for label, key in fixed_defs:
        base = broker_window_metric(baseline_metrics, label=label, key=key)
        arm = broker_window_metric(candidate_metrics, label=label, key=key)
        if base is None or arm is None:
            old = old_fixed.get(("fixed", label))
            if old is not None:
                out.append(old)
            continue
        out.append(metric_delta_row(base, arm, group="fixed", label=label, target_cagr=target_cagr))
    out.extend(row for row in rows if row["window_group"] != "fixed")
    return out


def build_window_rows(
    baseline_eq: pd.DataFrame,
    candidate_eq: pd.DataFrame,
    rolling_months: tuple[int, ...],
    *,
    target_cagr: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fixed_windows = [
        ("fixed", "full", None, None),
        ("fixed", "is_to_2024_06_30", None, pd.Timestamp("2024-06-30")),
        ("fixed", "oos_from_2024_07_01", pd.Timestamp("2024-07-01"), None),
        ("fixed", "oos2_from_2023_01_01", pd.Timestamp("2023-01-01"), None),
    ]
    for group, label, start, end in fixed_windows:
        base = calc_window_metrics(baseline_eq, label=label, start=start, end=end)
        arm = calc_window_metrics(candidate_eq, label=label, start=start, end=end)
        rows.append(metric_delta_row(base, arm, group=group, label=label, target_cagr=target_cagr))

    for year in range(2020, 2027):
        start = pd.Timestamp(f"{year}-01-01")
        end = pd.Timestamp(f"{year}-12-31")
        base = calc_window_metrics(baseline_eq, label=str(year), start=start, end=end)
        arm = calc_window_metrics(candidate_eq, label=str(year), start=start, end=end)
        if base.get("status") == "completed" and arm.get("status") == "completed":
            rows.append(metric_delta_row(base, arm, group="calendar_year", label=str(year), target_cagr=target_cagr))

    ends = month_end_dates(baseline_eq)
    candidate_end_set = set(month_end_dates(candidate_eq))
    for months in rolling_months:
        for end in ends:
            if end not in candidate_end_set:
                continue
            start = end - pd.DateOffset(months=months)
            base = calc_window_metrics(baseline_eq, label=f"{months}m_to_{end.date().isoformat()}", start=start, end=end)
            arm = calc_window_metrics(candidate_eq, label=f"{months}m_to_{end.date().isoformat()}", start=start, end=end)
            if base.get("years", 0.0) < (months / 12.0) * 0.75 or arm.get("years", 0.0) < (months / 12.0) * 0.75:
                continue
            rows.append(
                metric_delta_row(
                    base,
                    arm,
                    group=f"rolling_{months}m",
                    label=f"{months}m_to_{end.date().isoformat()}",
                    target_cagr=target_cagr,
                )
            )
    return rows


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(rows)
    out: dict[str, Any] = {}
    for group, subset in frame.groupby("window_group", sort=True):
        deltas = pd.to_numeric(subset["delta_cagr_pp"], errors="coerce").dropna()
        mdd_deltas = pd.to_numeric(subset["delta_max_dd_pp"], errors="coerce").dropna()
        out[str(group)] = {
            "window_count": int(len(subset)),
            "positive_cagr_delta_count": int((deltas > 0).sum()),
            "positive_cagr_delta_rate": float((deltas > 0).mean()) if len(deltas) else None,
            "median_delta_cagr_pp": float(deltas.median()) if len(deltas) else None,
            "min_delta_cagr_pp": float(deltas.min()) if len(deltas) else None,
            "max_delta_cagr_pp": float(deltas.max()) if len(deltas) else None,
            "median_delta_max_dd_pp": float(mdd_deltas.median()) if len(mdd_deltas) else None,
            "min_delta_max_dd_pp": float(mdd_deltas.min()) if len(mdd_deltas) else None,
            "contract_pass_count": int(subset["candidate_contract_pass"].astype(bool).sum()),
        }
    return out


def classify(summary: dict[str, Any], fixed_rows: list[dict[str, Any]]) -> str:
    full = next((row for row in fixed_rows if row["window_group"] == "fixed" and row["window"] == "full"), {})
    oos = next((row for row in fixed_rows if row["window_group"] == "fixed" and row["window"] == "oos_from_2024_07_01"), {})
    rolling_12 = summary.get("rolling_12m", {})
    rolling_24 = summary.get("rolling_24m", {})
    if not full.get("candidate_contract_pass"):
        return "reject_headline_contract_not_restored"
    if safe_float(oos.get("delta_cagr_pp")) < -0.25:
        return "mixed_headline_pass_oos_cagr_worse"
    if safe_float(rolling_12.get("positive_cagr_delta_rate"), 0.0) < 0.50:
        return "mixed_headline_pass_rolling_12m_not_robust"
    if safe_float(rolling_24.get("positive_cagr_delta_rate"), 0.0) < 0.50:
        return "mixed_headline_pass_rolling_24m_not_robust"
    return "robust_research_candidate_requires_review"


def render_report(payload: dict[str, Any]) -> str:
    full = next(row for row in payload["window_rows"] if row["window_group"] == "fixed" and row["window"] == "full")
    oos = next(row for row in payload["window_rows"] if row["window_group"] == "fixed" and row["window"] == "oos_from_2024_07_01")
    lines = [
        "# Run287 Actual Results Rolling Review",
        "",
        f"- Status: `{payload['status']}`",
        f"- Decision label: `{payload['decision_label']}`",
        f"- Candidate arm: `{payload['candidate_arm']}`",
        f"- Portfolio: `{payload['portfolio_kind']}`",
        f"- Target CAGR: `{safe_float(payload['target_cagr']):.0%}`",
        f"- Metric mode: `{payload['metric_mode']}`",
        f"- Replay end date: `{payload['replay_end_date']}`",
        f"- Runner parity status: `{payload['runner_parity_status']}`",
        f"- Survivorship label: `{payload['survivorship_inflation_label']}`",
        f"- Measurement acceptance allowed: `{payload['measurement_contract_acceptance_allowed']}`",
        "- No fullrun, hook, threshold tuning, production promotion, or live trading.",
        "",
        "## Fixed Windows",
        "",
        "| Window | Candidate CAGR | Candidate MaxDD | dCAGR pp | dMDD pp | Contract pass |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in [r for r in payload["window_rows"] if r["window_group"] == "fixed"]:
        lines.append(
            "| {window} | {cagr:.2%} | {mdd:.2%} | {dc:+.2f} | {dm:+.2f} | {passed} |".format(
                window=row["window"],
                cagr=safe_float(row.get("candidate_cagr")),
                mdd=safe_float(row.get("candidate_max_dd")),
                dc=safe_float(row.get("delta_cagr_pp")),
                dm=safe_float(row.get("delta_max_dd_pp")),
                passed=row.get("candidate_contract_pass"),
            )
        )
    lines.extend(
        [
            "",
            "## Rolling Summary",
            "",
            "| Group | Windows | Positive CAGR delta rate | Median dCAGR pp | Min dCAGR pp | Median dMDD pp |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for group, item in payload["window_group_summary"].items():
        if not str(group).startswith("rolling_"):
            continue
        lines.append(
            "| {group} | {count} | {rate:.2%} | {median:+.2f} | {minv:+.2f} | {mdd:+.2f} |".format(
                group=group,
                count=int(safe_float(item.get("window_count"))),
                rate=safe_float(item.get("positive_cagr_delta_rate")),
                median=safe_float(item.get("median_delta_cagr_pp")),
                minv=safe_float(item.get("min_delta_cagr_pp")),
                mdd=safe_float(item.get("median_delta_max_dd_pp")),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- Full-window contract pass: `{full.get('candidate_contract_pass')}` at {safe_float(full.get('candidate_cagr')):.2%} CAGR / {safe_float(full.get('candidate_max_dd')):.2%} MDD.",
            f"- OOS CAGR delta is {safe_float(oos.get('delta_cagr_pp')):+.2f} pp, so the result is not accepted as a hook/fullrun candidate.",
            f"- Measurement-contract blockers: `{', '.join(payload['measurement_contract_acceptance_blockers']) or 'none'}`.",
            "- This remains default-off research evidence only.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    portfolio_kind = str(args.portfolio_kind)
    target_arm = str(args.target_arm)
    target_cagr = target_cagr_for_portfolio(portfolio_kind)
    target_book = resolve_target_book(latest_run, portfolio_kind, args.target_book)
    price_cache = repo_path(args.price_cache)
    book = pd.read_csv(target_book, low_memory=False)
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce").dt.date.astype(str)
    allowed_arms = {arm["arm"] for arm in build_arms(SIGNAL)}
    if target_arm not in allowed_arms:
        raise ValueError(f"target_arm must be one of {sorted(allowed_arms - {'baseline'})}: {target_arm}")
    arms = [arm for arm in build_arms(SIGNAL) if arm["arm"] in {"baseline", target_arm}]

    arm_payloads: dict[str, dict[str, Any]] = {}
    for arm in arms:
        arm_dir = output_dir / "replay_artifacts" / arm["arm"]
        arm_book, date_telemetry, stock_telemetry = generate_arm_book(
            book,
            arm,
            signal=SIGNAL,
            default_single_cap=float(args.single_cap),
        )
        target_book_path = arm_dir / "target_book.csv"
        write_csv(target_book_path, arm_book)
        write_csv(arm_dir / "date_telemetry.csv", date_telemetry)
        write_csv(arm_dir / "stock_telemetry.csv", stock_telemetry)
        metrics = run_broker_replay(
            target_book=target_book_path,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            portfolio_kind=portfolio_kind,
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
            starting_capital=float(args.starting_capital),
            cash_carry_mode=str(args.cash_carry_mode),
            cash_rate_path=str(repo_path(args.cash_rate_path)) if args.cash_rate_path else "",
            cash_rate_source=str(args.cash_rate_source),
            cash_rate_lag_days=int(args.cash_rate_lag_days),
            cash_carry_haircut_bps=float(args.cash_carry_haircut_bps),
            cash_carry_day_count=int(args.cash_carry_day_count),
            replay_end_date=str(args.replay_end_date),
            official_baseline_end_date=str(args.official_baseline_end_date),
        )
        arm_payloads[arm["arm"]] = {
            "arm": arm["arm"],
            "target_book": str(target_book_path),
            "metrics": metrics,
            "equity_curve": str(arm_dir / "broker" / "equity_curve.csv"),
        }

    baseline_eq = load_equity(Path(arm_payloads["baseline"]["equity_curve"]))
    candidate_eq = load_equity(Path(arm_payloads[target_arm]["equity_curve"]))
    window_rows = build_window_rows(
        baseline_eq,
        candidate_eq,
        tuple(int(x) for x in args.rolling_months),
        target_cagr=target_cagr,
    )
    window_rows = replace_fixed_rows_with_broker_metrics(
        window_rows,
        arm_payloads["baseline"]["metrics"],
        arm_payloads[target_arm]["metrics"],
        target_cagr=target_cagr,
    )
    window_group_summary = summarize_rows(window_rows)
    decision_label = classify(window_group_summary, window_rows)
    contract_caveats = measurement_contract_caveat_fields(
        parity_summary_path=repo_path(args.parity_summary),
        survivorship_summary_path=repo_path(args.survivorship_summary),
    )
    contract_blockers = measurement_contract_acceptance_blockers(contract_caveats)
    measurement_contract_acceptance_allowed = not contract_blockers and decision_label == "robust_research_candidate_requires_review"
    if decision_label.startswith("mixed_"):
        next_action_allowed = "review_actual_results_tilt_only_no_hook_no_fullrun"
    elif decision_label.startswith("reject_"):
        next_action_allowed = "no_action"
    elif contract_blockers:
        next_action_allowed = "review_only_measurement_contract_blocks_acceptance"
    else:
        next_action_allowed = "human_review_required"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "decision_label": decision_label,
        "result_label": decision_label,
        "source_run_id": "28725350727",
        "portfolio_kind": portfolio_kind,
        "signal": SIGNAL,
        "candidate_arm": target_arm,
        "target_cagr": target_cagr,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "metric_mode": "broker_ledger_next_close_cash_carry",
        "cash_carry_mode": str(args.cash_carry_mode),
        "cash_rate_path": str(repo_path(args.cash_rate_path)) if args.cash_rate_path else "",
        "replay_end_date": str(args.replay_end_date),
        "official_baseline_end_date": str(args.official_baseline_end_date),
        "arms": arm_payloads,
        "window_rows": window_rows,
        "window_group_summary": window_group_summary,
        **contract_caveats,
        "measurement_contract_acceptance_blockers": contract_blockers,
        "measurement_contract_acceptance_allowed": measurement_contract_acceptance_allowed,
        "candidate_allowed": False,
        "next_action_allowed": next_action_allowed,
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
    write_csv(output_dir / "window_metrics.csv", pd.DataFrame(window_rows))
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--target-book", default="")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default=DEFAULT_PORTFOLIO_KIND)
    parser.add_argument("--target-arm", default=DEFAULT_TARGET_ARM)
    parser.add_argument("--price-cache", default="outputs/run287_price_cache_latest/cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--single-cap", type=float, default=0.30)
    parser.add_argument("--cash-carry-mode", choices=["none", "risk_free_rate"], default="risk_free_rate")
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-path", default="")
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    parser.add_argument("--replay-end-date", default=DEFAULT_REPLAY_END_DATE)
    parser.add_argument("--official-baseline-end-date", default=DEFAULT_REPLAY_END_DATE)
    parser.add_argument("--rolling-months", type=int, nargs="+", default=list(DEFAULT_ROLLING_MONTHS))
    parser.add_argument("--parity-summary", default=DEFAULT_PARITY_SUMMARY)
    parser.add_argument("--survivorship-summary", default=DEFAULT_SURVIVORSHIP_SUMMARY)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
