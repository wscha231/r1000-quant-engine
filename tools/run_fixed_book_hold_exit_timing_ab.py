#!/usr/bin/env python3
"""Research-only hold/exit timing A/B on a fixed official target book.

This harness intentionally does not regenerate AlphaOps vNext selections. It
starts from a completed fullrun's official target book and applies narrow,
mechanical timing transformations before replaying the result through the
broker ledger. It is for replay-stage evidence only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import CASH_TICKERS, safe_float  # noqa: E402
from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    CASH_CARRY_MODE_RISK_FREE,
    CashCarryConfig,
    replay,
)


ARMS = [
    "baseline_cash_carry",
    "delay_target_exit_one_cycle",
    "delay_target_exit_only_if_leader",
    "partial_replace_50",
    "accelerate_exit_if_deteriorating",
    "keep_winner_if_rs_positive",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_book(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce")
    df = df.dropna(subset=["rebalance_date"]).copy()
    df["rebalance_date"] = df["rebalance_date"].dt.normalize()
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["weight"] = pd.to_numeric(df.get("weight", 0.0), errors="coerce").fillna(0.0)
    if "target_weight" in df.columns:
        df["target_weight"] = pd.to_numeric(df["target_weight"], errors="coerce").fillna(df["weight"])
    else:
        df["target_weight"] = df["weight"]
    return df


def is_cash(ticker: str) -> bool:
    return str(ticker).upper().strip() in CASH_TICKERS


def stock_mask(df: pd.DataFrame) -> pd.Series:
    return ~df["ticker"].astype(str).str.upper().isin(CASH_TICKERS)


def date_text(dt: Any) -> str:
    parsed = pd.to_datetime(dt, errors="coerce")
    return "" if pd.isna(parsed) else pd.Timestamp(parsed).date().isoformat()


def rs_positive(row: pd.Series) -> bool:
    values = [
        safe_float(row.get("rs_benchmark_3m")),
        safe_float(row.get("rs_benchmark_6m")),
        safe_float(row.get("rs_spy_3m")),
        safe_float(row.get("rs_qqq_3m")),
        safe_float(row.get("rs_spy_6m")),
        safe_float(row.get("rs_qqq_6m")),
    ]
    return any(v > 0 for v in values)


def thesis_intact(row: pd.Series) -> bool:
    ma200 = safe_float(row.get("price_above_ma200"), 1.0)
    hard = str(row.get("holding_state_reason") or row.get("selection_reason") or "").lower()
    crisis = str(row.get("crisis_state") or "").upper()
    severe = "hard_reject" in hard or "ma200" in hard and ma200 < 0.5
    return bool(ma200 >= 0.5 and not severe and crisis not in {"CRISIS_DEFENSE", "CRISIS"})


def deteriorating(row: pd.Series) -> bool:
    ma50 = safe_float(row.get("price_above_ma50"), 1.0)
    ma200 = safe_float(row.get("price_above_ma200"), 1.0)
    rs3 = max(
        safe_float(row.get("rs_benchmark_3m")),
        safe_float(row.get("rs_spy_3m")),
        safe_float(row.get("rs_qqq_3m")),
    )
    return bool(ma50 < 0.5 and ma200 < 0.5 and rs3 < 0)


def rebuild_cash(day: pd.DataFrame, *, portfolio_kind: str) -> pd.DataFrame:
    out = day.copy()
    mask = stock_mask(out)
    stock_weight = float(out.loc[mask, "weight"].sum())
    cash_weight = max(0.0, 1.0 - stock_weight)
    cash_mask = ~mask
    if cash_mask.any():
        first = out.index[cash_mask][0]
        out.loc[cash_mask, ["weight", "target_weight"]] = 0.0
        out.loc[first, "weight"] = cash_weight
        out.loc[first, "target_weight"] = cash_weight
    elif cash_weight > 1e-10 and not out.empty:
        template = out.iloc[0].copy()
        template["ticker"] = "CASH"
        template["Name"] = "Cash"
        template["sector"] = "Cash"
        template["weight"] = cash_weight
        template["target_weight"] = cash_weight
        template["portfolio_kind"] = portfolio_kind
        template["primary_lane"] = "CASH"
        template["selection_reason"] = "cash_from_fixed_book_hold_exit_timing_ab"
        out = pd.concat([out, pd.DataFrame([template])], ignore_index=True)
    return out


def fund_added_weight(day: pd.DataFrame, add_weight: float, *, protected_tickers: set[str]) -> pd.DataFrame:
    if add_weight <= 1e-12 or day.empty:
        return day
    out = day.copy()
    cash = out["ticker"].isin(CASH_TICKERS)
    cash_available = float(out.loc[cash, "weight"].sum()) if cash.any() else 0.0
    take_cash = min(cash_available, add_weight)
    if take_cash > 0 and cash.any():
        first_cash = out.index[cash][0]
        out.loc[first_cash, "weight"] = max(0.0, float(out.at[first_cash, "weight"]) - take_cash)
        out.loc[first_cash, "target_weight"] = out.at[first_cash, "weight"]
    remaining = add_weight - take_cash
    if remaining > 1e-12:
        eligible = stock_mask(out) & ~out["ticker"].isin(protected_tickers)
        total = float(out.loc[eligible, "weight"].sum())
        if total > 1e-12:
            for idx in out.index[eligible]:
                cut = remaining * float(out.at[idx, "weight"]) / total
                out.at[idx, "weight"] = max(0.0, float(out.at[idx, "weight"]) - cut)
                out.at[idx, "target_weight"] = out.at[idx, "weight"]
    return out


def apply_hold_exit_arm(book: pd.DataFrame, *, arm: str, portfolio_kind: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if arm == "baseline_cash_carry":
        out = book.copy()
        out["fixed_book_hold_exit_arm"] = arm
        audit = pd.DataFrame()
        return finalize_book(out), audit, {"status": "completed", "applied_count": 0, "arm": arm}

    rebuilt: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    prev_stocks: dict[str, pd.Series] = {}
    for raw_dt in sorted(book["rebalance_date"].dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        # Use the official book as the prior state. Extended rows are research
        # overlays and must not become eligible for another "one cycle" delay.
        official_day = book[book["rebalance_date"].eq(raw_dt)].copy()
        day = official_day.copy()
        current_tickers = set(day.loc[stock_mask(day), "ticker"].astype(str))

        if arm in {"delay_target_exit_one_cycle", "delay_target_exit_only_if_leader", "partial_replace_50", "keep_winner_if_rs_positive"}:
            for ticker, prev_row in list(prev_stocks.items()):
                if ticker in current_tickers:
                    continue
                weight = float(prev_row.get("weight", 0.0))
                if arm == "partial_replace_50":
                    weight *= 0.5
                if weight <= 1e-8:
                    continue
                leader_required = arm in {"delay_target_exit_only_if_leader", "keep_winner_if_rs_positive"}
                if leader_required and not (rs_positive(prev_row) and thesis_intact(prev_row)):
                    continue
                add = prev_row.copy()
                add["rebalance_date"] = dt
                add["weight"] = weight
                add["target_weight"] = weight
                add["fixed_book_hold_exit_arm"] = arm
                add["selection_reason"] = str(add.get("selection_reason") or "") + f"|{arm}:one_cycle_hold"
                day = fund_added_weight(day, weight, protected_tickers={ticker})
                day = pd.concat([day, pd.DataFrame([add])], ignore_index=True)
                current_tickers.add(ticker)
                audit_rows.append(
                    {
                        "rebalance_date": dt.date().isoformat(),
                        "ticker": ticker,
                        "action": "hold_extension",
                        "arm": arm,
                        "added_weight": weight,
                        "rs_positive": rs_positive(prev_row),
                        "thesis_intact": thesis_intact(prev_row),
                    }
                )

        if arm == "accelerate_exit_if_deteriorating":
            for idx in list(day.index[stock_mask(day)]):
                row = day.loc[idx]
                if not deteriorating(row):
                    continue
                dropped = float(row.get("weight", 0.0))
                day.at[idx, "weight"] = 0.0
                day.at[idx, "target_weight"] = 0.0
                day.at[idx, "fixed_book_exit_accelerated"] = True
                audit_rows.append(
                    {
                        "rebalance_date": dt.date().isoformat(),
                        "ticker": str(row.get("ticker")),
                        "action": "exit_accelerated",
                        "arm": arm,
                        "dropped_weight": dropped,
                    }
                )

        day["fixed_book_hold_exit_arm"] = arm
        day = rebuild_cash(day, portfolio_kind=portfolio_kind)
        rebuilt.append(day)
        prev_stocks = {
            str(row["ticker"]): row
            for _, row in official_day.loc[
                stock_mask(official_day) & (pd.to_numeric(official_day["weight"], errors="coerce").fillna(0.0) > 1e-8)
            ].iterrows()
        }
    out = finalize_book(pd.concat(rebuilt, ignore_index=True) if rebuilt else book.copy())
    audit = pd.DataFrame(audit_rows)
    return out, audit, {"status": "completed", "applied_count": int(len(audit)), "arm": arm}


def finalize_book(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
    out["target_weight"] = pd.to_numeric(out.get("target_weight", out["weight"]), errors="coerce").fillna(out["weight"])
    out = out[out["weight"] > 1e-10].copy()
    out = out.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    return out


def cash_carry_config_from_args(args: argparse.Namespace) -> CashCarryConfig:
    if args.cash_carry_mode in {"", CASH_CARRY_MODE_NONE}:
        return CashCarryConfig(mode=CASH_CARRY_MODE_NONE)
    return CashCarryConfig(
        mode=CASH_CARRY_MODE_RISK_FREE,
        rate_source=args.cash_rate_source,
        rate_lag_days=args.cash_rate_lag_days,
        haircut_bps=args.cash_carry_haircut_bps,
        day_count=args.cash_carry_day_count,
        rate_path=repo_path(args.cash_rate_path) if args.cash_rate_path else None,
    )


def metric_row(arm: str, summary: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "arm": arm,
        "applied_count": summary.get("applied_count", 0),
        "broker_status": metrics.get("status"),
        "broker_reason": metrics.get("reason", ""),
        "metric_mode": metrics.get("metric_mode"),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "years": metrics.get("years"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "trade_count": metrics.get("trade_count"),
        "gross_traded": metrics.get("gross_traded"),
        "fees_paid": metrics.get("fees_paid"),
        "cash_interest_accrued_usd": metrics.get("cash_interest_accrued_usd"),
        "actual_equity_curve_end_date": metrics.get("actual_equity_curve_end_date"),
        "end_date_matches_official": metrics.get("end_date_matches_official"),
        "replay_end_skipped_rebalance_count": metrics.get("replay_end_skipped_rebalance_count"),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_book = read_book(target_book)
    rows: list[dict[str, Any]] = []
    arms = [a.strip() for a in str(args.arms).split(",") if a.strip()]
    for arm in arms:
        if arm not in ARMS:
            raise ValueError(f"Unknown arm: {arm}")
        arm_dir = output_dir / arm
        arm_dir.mkdir(parents=True, exist_ok=True)
        adjusted, audit, overlay_summary = apply_hold_exit_arm(base_book, arm=arm, portfolio_kind=args.portfolio_kind)
        arm_book = arm_dir / "target_book.csv"
        adjusted.to_csv(arm_book, index=False)
        audit.to_csv(arm_dir / "actions.csv", index=False)
        write_json(arm_dir / "overlay_summary.json", overlay_summary)
        metrics = replay(
            target_book=arm_book,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            portfolio_kind=args.portfolio_kind,
            fill_mode="next_close",
            cost_bps=args.cost_bps,
            max_fill_lag_days=args.max_fill_lag_days,
            replay_end_date=args.replay_end_date or None,
            official_baseline_end_date=args.official_baseline_end_date or args.replay_end_date or None,
            cash_carry_config=cash_carry_config_from_args(args),
        )
        rows.append(metric_row(arm, overlay_summary, metrics))

    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(output_dir / "arm_metrics.csv", index=False)
    baseline = metrics_df[metrics_df["arm"].eq("baseline_cash_carry")].iloc[0].to_dict() if "baseline_cash_carry" in set(metrics_df["arm"]) else {}
    for col in ["cagr", "max_dd", "sharpe"]:
        if baseline and col in metrics_df.columns:
            metrics_df[f"delta_{col}"] = pd.to_numeric(metrics_df[col], errors="coerce") - safe_float(baseline.get(col))
    metrics_df.to_csv(output_dir / "arm_metrics.csv", index=False)
    payload = {
        "status": "completed",
        "schema_version": "fixed-book-hold-exit-timing-ab-v1",
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "portfolio_kind": args.portfolio_kind,
        "arms": metrics_df.to_dict("records"),
        "cash_carry_mode": args.cash_carry_mode or CASH_CARRY_MODE_NONE,
        "replay_end_date": args.replay_end_date,
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", payload)
    lines = ["# Fixed Official Book Hold / Exit Timing A/B", ""]
    lines.append("| arm | applied | CAGR | MaxDD | Sharpe | delta_CAGR | delta_MaxDD | status |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in metrics_df.to_dict("records"):
        lines.append(
            f"| {row.get('arm')} | {row.get('applied_count')} | {row.get('cagr')} | {row.get('max_dd')} | "
            f"{row.get('sharpe')} | {row.get('delta_cagr', '')} | {row.get('delta_max_dd', '')} | {row.get('broker_status')} |"
        )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default="outputs/fixed_book_hold_exit_timing_ab")
    parser.add_argument("--portfolio-kind", default="concentrated", choices=["main", "concentrated"])
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--replay-end-date", default="")
    parser.add_argument("--official-baseline-end-date", default="")
    parser.add_argument("--cash-carry-mode", default=CASH_CARRY_MODE_RISK_FREE, choices=["", CASH_CARRY_MODE_NONE, CASH_CARRY_MODE_RISK_FREE])
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-path", default="")
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
