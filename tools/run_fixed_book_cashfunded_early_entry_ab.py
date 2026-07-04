#!/usr/bin/env python3
"""Research-only fixed-book A/B for Concentrated cash-funded early entry.

This replays a fixed target book after adding at most one non-sticky unheld
candidate per rebalance date, funded only by explicit or implicit cash. Candidate
ranking uses PIT score columns only; forward-return columns are never used for
selection and are copied only to audit output when present.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import CASH_TICKERS, safe_float  # noqa: E402

SCHEMA_VERSION = "fixed-book-cashfunded-early-entry-ab-v1"
DEFAULT_OUTPUT_DIR = "outputs/fixed_book_cashfunded_early_entry_ab"
DEFAULT_ARMS = "baseline,entry_w3p0,entry_w5p8,entry_w3p0_breakout70,entry_w5p8_breakout70"
FORWARD_AUDIT_COLUMNS = ("period_forward_return", "forward_21d_excess", "forward_63d_excess", "forward_126d_excess")
CANDIDATE_COLUMNS = (
    "rebalance_date",
    "ticker",
    "Name",
    "sector",
    "industry_group",
    "source_universe",
    "variant_id",
    "future_winner_scout_score",
    "breakout_setup_quality_score",
    "crisis_state",
    "primary_lane",
    "portfolio_candidate_gate_label",
    "alphaops_vnext_score",
    "rs_benchmark_3m",
    "rs_spy_3m",
    "leader_tier",
    "actual_results_score",
    *FORWARD_AUDIT_COLUMNS,
)


ARM_CONFIGS: dict[str, dict[str, Any]] = {
    "baseline": {"add_weight": 0.0, "min_breakout": 0.50},
    "entry_w3p0": {"add_weight": 0.030, "min_breakout": 0.50},
    "entry_w5p8": {"add_weight": 0.058, "min_breakout": 0.50},
    "entry_w3p0_breakout70": {"add_weight": 0.030, "min_breakout": 0.70},
    "entry_w5p8_breakout70": {"add_weight": 0.058, "min_breakout": 0.70},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_arms(text: str) -> list[str]:
    arms: list[str] = []
    for token in str(text or "").split(","):
        arm = token.strip()
        if arm:
            if arm not in ARM_CONFIGS:
                raise ValueError(f"unknown arm: {arm}")
            if arm not in arms:
                arms.append(arm)
    return arms or ["baseline"]


def read_target_book(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    if "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        raise ValueError("target book must include rebalance_date and ticker")
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    out["ticker"] = out["ticker"].map(clean_ticker)
    for col in ("weight", "target_weight"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
        elif col == "target_weight" and "weight" in out.columns:
            out[col] = out["weight"]
    return out.dropna(subset=["rebalance_date"]).copy()


def read_candidates(path: Path, *, variant_id: str) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0)
    usecols = [col for col in CANDIDATE_COLUMNS if col in header.columns]
    if "rebalance_date" not in usecols or "ticker" not in usecols:
        raise ValueError("candidate source must include rebalance_date and ticker")
    frame = pd.read_csv(path, usecols=usecols, low_memory=False)
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    out["ticker"] = out["ticker"].map(clean_ticker)
    if variant_id and "variant_id" in out.columns:
        out = out[out["variant_id"].astype(str).eq(variant_id)].copy()
    for col in (
        "future_winner_scout_score",
        "breakout_setup_quality_score",
        "alphaops_vnext_score",
        "rs_benchmark_3m",
        "rs_spy_3m",
        "actual_results_score",
        *FORWARD_AUDIT_COLUMNS,
    ):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[out["ticker"].ne("")].copy()


def is_cash_ticker(value: Any) -> bool:
    return clean_ticker(value) in CASH_TICKERS


def stock_mask(frame: pd.DataFrame) -> pd.Series:
    return ~frame["ticker"].map(is_cash_ticker)


def cash_weight(day: pd.DataFrame) -> float:
    explicit = float(pd.to_numeric(day.loc[~stock_mask(day), "weight"], errors="coerce").fillna(0.0).sum())
    if explicit > 0:
        return explicit
    stock = float(pd.to_numeric(day.loc[stock_mask(day), "weight"], errors="coerce").fillna(0.0).sum())
    return max(0.0, 1.0 - stock)


def numeric_series(frame: pd.DataFrame, column: str, default: float = float("nan")) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def reduce_cash(day: pd.DataFrame, amount: float) -> pd.DataFrame:
    out = day.copy()
    cash_rows = out.index[~stock_mask(out)].tolist()
    if amount <= 1e-12:
        return out
    if cash_rows:
        idx = cash_rows[0]
        before = safe_float(out.at[idx, "weight"])
        after = max(0.0, before - amount)
        out.at[idx, "weight"] = after
        out.at[idx, "target_weight"] = after
        return out
    return out


def sort_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    out = candidates.copy()
    out["_signal_sort"] = numeric_series(out, "future_winner_scout_score").fillna(-999999.0)
    out["_breakout_sort"] = numeric_series(out, "breakout_setup_quality_score").fillna(-999999.0)
    out["_alphaops_sort"] = numeric_series(out, "alphaops_vnext_score").fillna(-999999.0)
    return out.sort_values(
        ["_signal_sort", "_breakout_sort", "_alphaops_sort", "ticker"],
        ascending=[False, False, False, True],
    )


def select_candidate(
    candidates: pd.DataFrame,
    *,
    held: set[str],
    allow_crisis: bool,
) -> tuple[pd.Series | None, str, int]:
    if candidates.empty:
        return None, "no_candidate_rows_for_date", 0
    frame = candidates.copy()
    frame = frame[~frame["ticker"].isin(held)]
    frame = frame[~frame["ticker"].map(is_cash_ticker)]
    frame = frame[numeric_series(frame, "future_winner_scout_score").notna()]
    if not allow_crisis and "crisis_state" in frame.columns:
        state = frame["crisis_state"].astype(str).str.upper()
        frame = frame[~state.str.contains("CRISIS|DEFENSE", regex=True, na=False)]
    if frame.empty:
        return None, "no_unheld_signal_candidate", 0
    sorted_frame = sort_candidates(frame)
    return sorted_frame.iloc[0], "candidate_selected", int(len(sorted_frame))


def candidate_row_for_book(day: pd.DataFrame, candidate: pd.Series, *, inject: float, arm: str) -> dict[str, Any]:
    template = {col: "" for col in day.columns}
    for col in day.columns:
        if col in candidate.index and pd.notna(candidate.get(col)):
            template[col] = candidate.get(col)
    template["rebalance_date"] = str(candidate.get("rebalance_date"))
    template["ticker"] = clean_ticker(candidate.get("ticker"))
    template["weight"] = float(inject)
    template["target_weight"] = float(inject)
    template["holding_state"] = "NEW"
    template["holding_state_reason"] = "fixed_book_cashfunded_early_entry_candidate"
    template["hold_replace_decision"] = "cashfunded_early_entry"
    template["prior_weight"] = 0.0
    template["concentrated_cashfunded_early_entry_applied"] = True
    template["concentrated_cashfunded_early_entry_non_sticky"] = True
    template["concentrated_cashfunded_early_entry_added_weight"] = float(inject)
    template["concentrated_cashfunded_early_entry_signal"] = "future_winner_scout_score"
    template["concentrated_cashfunded_early_entry_signal_value"] = safe_float(candidate.get("future_winner_scout_score"))
    template["fixed_book_cashfunded_early_entry_arm"] = arm
    template["selection_reason"] = (
        str(candidate.get("primary_lane") or template.get("selection_reason") or "alphaops_vnext_score")
        + f"|fixed_book_cashfunded_early_entry:{arm}:{inject:.4f}"
    )
    return template


def build_arm_book(
    book: pd.DataFrame,
    candidates: pd.DataFrame,
    *,
    arm: str,
    allow_crisis: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    cfg = ARM_CONFIGS[arm]
    if arm == "baseline":
        out = book.copy()
        out["fixed_book_cashfunded_early_entry_arm"] = arm
        return out, pd.DataFrame(), {"arm": arm, "applied_count": 0, "status": "baseline"}

    add_weight = float(cfg["add_weight"])
    min_breakout = float(cfg["min_breakout"])
    by_date = {date: group.copy() for date, group in candidates.groupby("rebalance_date", sort=False)}
    groups: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    for date, day in book.groupby("rebalance_date", sort=True):
        day = day.copy()
        day["fixed_book_cashfunded_early_entry_arm"] = arm
        held = {clean_ticker(t) for t in day.loc[stock_mask(day), "ticker"]}
        cash_before = cash_weight(day)
        candidate, status, eligible_count = select_candidate(by_date.get(date, pd.DataFrame()), held=held, allow_crisis=allow_crisis)
        applied = False
        inject = 0.0
        chosen_ticker = ""
        chosen_breakout = None
        chosen_signal = None
        if candidate is not None:
            chosen_ticker = clean_ticker(candidate.get("ticker"))
            chosen_breakout = safe_float(candidate.get("breakout_setup_quality_score"), float("nan"))
            chosen_signal = safe_float(candidate.get("future_winner_scout_score"), float("nan"))
            if chosen_breakout < min_breakout:
                status = "blocked_top_candidate_low_breakout_quality"
            elif cash_before <= 1e-12:
                status = "blocked_no_cash"
            else:
                inject = min(add_weight, cash_before)
                day = reduce_cash(day, inject)
                entry = candidate_row_for_book(day, candidate, inject=inject, arm=arm)
                day = pd.concat([day, pd.DataFrame([entry])], ignore_index=True)
                status = "applied"
                applied = True
        audit = {
            "rebalance_date": date,
            "arm": arm,
            "status": status,
            "applied": applied,
            "eligible_candidate_count": eligible_count,
            "chosen_ticker": chosen_ticker,
            "chosen_signal": chosen_signal,
            "chosen_breakout": chosen_breakout,
            "cash_before": cash_before,
            "added_weight": inject,
            "cash_after": cash_before - inject,
            "forward_labels_used_for_ranking": False,
        }
        if candidate is not None:
            for col in FORWARD_AUDIT_COLUMNS:
                if col in candidate.index:
                    audit[f"audit_{col}"] = candidate.get(col)
        audit_rows.append(audit)
        groups.append(day)
    out = pd.concat(groups, ignore_index=True) if groups else book.copy()
    audit = pd.DataFrame(audit_rows)
    return out, audit, {
        "arm": arm,
        "status": "completed",
        "applied_count": int(audit["applied"].sum()) if not audit.empty else 0,
        "blocked_no_cash_count": int(audit["status"].eq("blocked_no_cash").sum()) if not audit.empty else 0,
        "blocked_low_breakout_count": int(audit["status"].eq("blocked_top_candidate_low_breakout_quality").sum()) if not audit.empty else 0,
    }


def run_broker_replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio_kind: str,
    starting_capital: float,
    cost_bps: float,
    max_fill_lag_days: int,
    cash_carry_mode: str,
    cash_rate_path: str,
    cash_rate_source: str,
    cash_rate_lag_days: int,
    cash_carry_haircut_bps: float,
    cash_carry_day_count: int,
    replay_end_date: str,
    official_baseline_end_date: str,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "run_broker_ledger_replay.py"),
        "--target-book",
        str(target_book),
        "--price-cache",
        str(price_cache),
        "--portfolio-kind",
        portfolio_kind,
        "--output-dir",
        str(output_dir),
        "--fill-mode",
        "next_close",
        "--cost-bps",
        str(cost_bps),
        "--max-fill-lag-days",
        str(max_fill_lag_days),
        "--starting-capital",
        str(starting_capital),
        "--disable-concentrated-champion-filter",
    ]
    if cash_carry_mode:
        cmd.extend(["--cash-carry-mode", cash_carry_mode])
    if cash_rate_path:
        cmd.extend(["--cash-rate-path", str(repo_path(cash_rate_path))])
    if cash_rate_source:
        cmd.extend(["--cash-rate-source", cash_rate_source])
    cmd.extend(["--cash-rate-lag-days", str(cash_rate_lag_days)])
    cmd.extend(["--cash-carry-haircut-bps", str(cash_carry_haircut_bps)])
    cmd.extend(["--cash-carry-day-count", str(cash_carry_day_count)])
    if replay_end_date:
        cmd.extend(["--replay-end-date", replay_end_date])
    if official_baseline_end_date:
        cmd.extend(["--official-baseline-end-date", official_baseline_end_date])
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    metrics_path = output_dir / "metrics.json"
    if not metrics_path.exists():
        return {"status": "missing_metrics", "broker_metrics_path": str(metrics_path)}
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["broker_metrics_path"] = str(metrics_path)
    return payload


def metric_row(arm: str, info: dict[str, Any], metrics: dict[str, Any], arm_book_path: Path) -> dict[str, Any]:
    windows = metrics.get("windows") if isinstance(metrics.get("windows"), dict) else {}
    is_window = windows.get("is") if isinstance(windows.get("is"), dict) else {}
    oos_window = windows.get("oos") if isinstance(windows.get("oos"), dict) else {}
    oos2_window = windows.get("oos2") if isinstance(windows.get("oos2"), dict) else {}
    return {
        "arm": arm,
        "status": metrics.get("status", ""),
        "metric_mode": metrics.get("metric_mode", ""),
        "cagr": safe_float(metrics.get("cagr")),
        "max_dd": safe_float(metrics.get("max_dd")),
        "sharpe": safe_float(metrics.get("sharpe")),
        "years": safe_float(metrics.get("years")),
        "start_date": metrics.get("start_date", ""),
        "end_date": metrics.get("end_date", ""),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "min_cash_usd": safe_float(metrics.get("min_cash_usd")),
        "trade_count": int(safe_float(metrics.get("trade_count"))),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd")),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
        "is_cagr": safe_float(is_window.get("cagr")),
        "is_max_dd": safe_float(is_window.get("max_dd")),
        "oos_cagr": safe_float(oos_window.get("cagr")),
        "oos_max_dd": safe_float(oos_window.get("max_dd")),
        "oos2_cagr": safe_float(oos2_window.get("cagr")),
        "oos2_max_dd": safe_float(oos2_window.get("max_dd")),
        "applied_count": int(info.get("applied_count", 0)),
        "blocked_no_cash_count": int(info.get("blocked_no_cash_count", 0)),
        "blocked_low_breakout_count": int(info.get("blocked_low_breakout_count", 0)),
        "target_book_path": str(arm_book_path),
        "broker_metrics_path": str(metrics.get("broker_metrics_path", "")),
        "end_date_matches_official": bool(metrics.get("end_date_matches_official", False)),
    }


def add_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = next((row for row in rows if row["arm"] == "baseline"), None)
    if not baseline:
        return rows
    for row in rows:
        row["delta_cagr_pp"] = (safe_float(row.get("cagr")) - safe_float(baseline.get("cagr"))) * 100.0
        row["delta_max_dd_pp"] = (safe_float(row.get("max_dd")) - safe_float(baseline.get("max_dd"))) * 100.0
        row["delta_sharpe"] = safe_float(row.get("sharpe")) - safe_float(baseline.get("sharpe"))
        row["delta_is_cagr_pp"] = (safe_float(row.get("is_cagr")) - safe_float(baseline.get("is_cagr"))) * 100.0
        row["delta_oos_cagr_pp"] = (safe_float(row.get("oos_cagr")) - safe_float(baseline.get("oos_cagr"))) * 100.0
    return rows


def classify(row: dict[str, Any]) -> str:
    if row["arm"] == "baseline":
        return "baseline"
    if row.get("metric_mode") not in {"broker_ledger_next_close", "broker_ledger_next_close_cash_carry"}:
        return "blocked_invalid_metric_mode"
    if not bool(row.get("end_date_matches_official")):
        return "blocked_window_mismatch"
    if int(row.get("applied_count", 0)) <= 0:
        return "blocked_no_signal"
    if safe_float(row.get("cagr")) >= 0.50 and safe_float(row.get("max_dd")) >= -0.25:
        return "research_pass_policy_candidate"
    if safe_float(row.get("delta_cagr_pp")) <= 0:
        return "reject_no_cagr_edge"
    if safe_float(row.get("max_dd")) < -0.25:
        return "reject_mdd_still_below_target"
    return "partial"


def render_report(rows: list[dict[str, Any]], *, target_book: Path, candidate_source: Path) -> str:
    lines = [
        "# Fixed-Book Cash-Funded Early-Entry A/B",
        "",
        f"- target book: `{target_book}`",
        f"- candidate source: `{candidate_source}`",
        "- research only: true",
        "- production activation: false",
        "- forward labels used for ranking: false",
        "",
        "| arm | verdict | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | applied |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {arm} | `{verdict}` | {cagr:.2%} | {mdd:.2%} | {sharpe:.3f} | {dc:+.2f} | {dm:+.2f} | {applied} |".format(
                arm=row["arm"],
                verdict=row["verdict"],
                cagr=safe_float(row.get("cagr")),
                mdd=safe_float(row.get("max_dd")),
                sharpe=safe_float(row.get("sharpe")),
                dc=safe_float(row.get("delta_cagr_pp")),
                dm=safe_float(row.get("delta_max_dd_pp")),
                applied=int(row.get("applied_count", 0)),
            )
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    candidate_source = repo_path(args.candidate_source)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    arms = parse_arms(args.arms)
    book = read_target_book(target_book)
    candidates = read_candidates(candidate_source, variant_id=args.variant_id)

    rows: list[dict[str, Any]] = []
    for arm in arms:
        arm_dir = output_dir / arm
        arm_book, audit, info = build_arm_book(book, candidates, arm=arm, allow_crisis=bool(args.allow_crisis))
        arm_book_path = arm_dir / "target_book.csv"
        write_csv(arm_book_path, arm_book)
        write_csv(arm_dir / "early_entry_audit.csv", audit)
        metrics = run_broker_replay(
            target_book=arm_book_path,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            portfolio_kind=args.portfolio_kind,
            starting_capital=float(args.starting_capital),
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
            cash_carry_mode=str(args.cash_carry_mode),
            cash_rate_path=str(args.cash_rate_path),
            cash_rate_source=str(args.cash_rate_source),
            cash_rate_lag_days=int(args.cash_rate_lag_days),
            cash_carry_haircut_bps=float(args.cash_carry_haircut_bps),
            cash_carry_day_count=int(args.cash_carry_day_count),
            replay_end_date=str(args.replay_end_date),
            official_baseline_end_date=str(args.official_baseline_end_date),
        )
        rows.append(metric_row(arm, info, metrics, arm_book_path))

    rows = add_deltas(rows)
    for row in rows:
        row["verdict"] = classify(row)
    table = pd.DataFrame(rows)
    write_csv(output_dir / "arm_metrics.csv", table)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "research_only": True,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "forward_labels_used_for_ranking": False,
        "forward_return_is_audit_label_only": True,
        "target_book": str(target_book),
        "candidate_source": str(candidate_source),
        "variant_id": args.variant_id,
        "price_cache": str(price_cache),
        "cash_carry_mode": args.cash_carry_mode,
        "replay_end_date": args.replay_end_date,
        "arms": rows,
        "policy_candidates": [row for row in rows if row.get("verdict") == "research_pass_policy_candidate"],
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(rows, target_book=target_book, candidate_source=candidate_source))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--candidate-source", required=True)
    parser.add_argument("--variant-id", default="concentrated_N5")
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio-kind", default="concentrated", choices=["concentrated"])
    parser.add_argument("--arms", default=DEFAULT_ARMS)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--cash-carry-mode", choices=["none", "risk_free_rate"], default="risk_free_rate")
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-path", default="")
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    parser.add_argument("--replay-end-date", default="")
    parser.add_argument("--official-baseline-end-date", default="")
    parser.add_argument("--allow-crisis", action="store_true")
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
