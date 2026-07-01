#!/usr/bin/env python3
"""Research-only bull-floor A/B on an already-built official target book.

This tool exists for official-window replay work where the accepted baseline is
the target book emitted by a completed fullrun. Re-running vNext policy replay
can drift from that artifact when code, env flags, candidate filtering, or data
freshness changed. Here we keep the existing official book fixed and test only
one replay-stage intervention: lift stock exposure up to a bull-regime floor.
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

from tools.run_alphaops_vnext_policy_replay import (  # noqa: E402
    BULL_REGIME_STATES,
    CASH_TICKERS,
    DEFAULT_BULL_FLOOR_SINGLE_CAP,
    capacity_cash_row,
    capped_proportional_fill,
    dominant_text,
    safe_float,
)
from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    CASH_CARRY_MODE_RISK_FREE,
    CashCarryConfig,
    replay,
)


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_floors(text: str) -> list[float]:
    out: list[float] = []
    for token in str(text or "").split(","):
        token = token.strip()
        if not token:
            continue
        value = float(token)
        if value not in out:
            out.append(value)
    return out


def apply_bull_floor_lift_only(book: pd.DataFrame, *, portfolio_kind: str, floor: float) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Lift an already-capacity-adjusted book in bull regimes only.

    Unlike ``apply_regime_capacity_overlay``, this does not apply bear/neutral
    dampening. Fullrun official books already carry that policy; applying it
    again would double-dampen the control arm and invalidate the A/B.
    """
    if book.empty or "rebalance_date" not in book.columns or "weight" not in book.columns:
        summary = {
            "portfolio": portfolio_kind,
            "status": "blocked",
            "reason": "empty_or_missing_required_columns",
            "rebalance_dates_total": 0,
            "rebalance_dates_bull_floor_lifted": 0,
            "bull_floor": float(floor),
        }
        return book.copy(), summary, pd.DataFrame()

    out = book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in out.columns:
        out["target_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(out["weight"])
    else:
        out["target_weight"] = out["weight"]

    single_cap = float(DEFAULT_BULL_FLOOR_SINGLE_CAP.get(portfolio_kind, 0.20))
    audit_rows: list[dict[str, Any]] = []
    rebuilt: list[pd.DataFrame] = []
    lifted_dates = 0
    for raw_dt in sorted(out["rebalance_date"].dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        day = out[out["rebalance_date"].eq(raw_dt)].copy()
        regime = dominant_text(day["regime_state"]) if "regime_state" in day.columns else "unknown"
        stock_mask = ~day["ticker"].isin(CASH_TICKERS)
        pre_stock = float(day.loc[stock_mask, "weight"].sum())
        applied = False
        if floor > 1e-12 and regime in BULL_REGIME_STATES and pre_stock > 1e-9 and pre_stock < floor - 1e-9:
            idx = list(day.index[stock_mask])
            weights = [float(day.at[i, "weight"]) for i in idx]
            if "effective_single_weight_cap" in day.columns:
                ceilings = [
                    float(safe_float(day.at[i, "effective_single_weight_cap"], single_cap) or single_cap)
                    for i in idx
                ]
            else:
                ceilings = [single_cap] * len(idx)
            lifted = capped_proportional_fill(weights, floor, ceilings)
            for i, new_weight in zip(idx, lifted):
                day.at[i, "weight"] = new_weight
                day.at[i, "target_weight"] = new_weight
            if "selection_reason" in day.columns:
                day.loc[stock_mask, "selection_reason"] = (
                    day.loc[stock_mask, "selection_reason"].astype(str) + "|official_book_bull_floor_lifted"
                )
            applied = True
            lifted_dates += 1

        post_stock = float(day.loc[stock_mask, "weight"].sum())
        cash_weight = max(0.0, 1.0 - post_stock)
        cash_mask = day["ticker"].isin(CASH_TICKERS)
        if cash_mask.any():
            first_cash_idx = day.index[cash_mask][0]
            day.loc[cash_mask, ["weight", "target_weight"]] = 0.0
            day.loc[first_cash_idx, "weight"] = cash_weight
            day.loc[first_cash_idx, "target_weight"] = cash_weight
        elif cash_weight > 1e-10:
            template = day.iloc[0] if not day.empty else None
            day = pd.concat([day, pd.DataFrame([capacity_cash_row(dt, portfolio_kind, cash_weight, template)])], ignore_index=True)

        day["official_book_bull_floor_lift_applied"] = bool(applied)
        rebuilt.append(day)
        audit_rows.append(
            {
                "rebalance_date": dt.date().isoformat(),
                "portfolio_kind": portfolio_kind,
                "regime": regime,
                "pre_stock_weight": pre_stock,
                "post_stock_weight": post_stock,
                "cash_weight": cash_weight,
                "bull_floor_applied": bool(applied),
                "rows_affected": int(stock_mask.sum() if applied else 0),
            }
        )

    result = pd.concat(rebuilt, ignore_index=True) if rebuilt else out
    result["rebalance_date"] = pd.to_datetime(result["rebalance_date"], errors="coerce").dt.date.astype(str)
    result = result.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    audit = pd.DataFrame(audit_rows)
    summary = {
        "portfolio": portfolio_kind,
        "status": "completed",
        "bull_floor": float(floor),
        "rebalance_dates_total": int(len(audit)),
        "rebalance_dates_bull_floor_lifted": int(lifted_dates),
        "avg_cash_weight": float(pd.to_numeric(audit.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean()) if not audit.empty else 0.0,
        "max_cash_weight": float(pd.to_numeric(audit.get("cash_weight", pd.Series(dtype=float)), errors="coerce").max()) if not audit.empty else 0.0,
        "research_only": True,
        "production_activation_allowed": False,
    }
    return result, summary, audit


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


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_book = pd.read_csv(target_book)
    rows: list[dict[str, Any]] = []
    for floor in parse_floors(args.floors):
        tag = str(floor).replace("-", "m").replace(".", "p")
        arm_dir = output_dir / f"floor_{tag}"
        arm_dir.mkdir(parents=True, exist_ok=True)
        adjusted, overlay_summary, audit = apply_bull_floor_lift_only(base_book, portfolio_kind=args.portfolio_kind, floor=floor)
        arm_book = arm_dir / "target_book.csv"
        adjusted.to_csv(arm_book, index=False)
        audit.to_csv(arm_dir / "bull_floor_lift_audit.csv", index=False)
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
        row = {
            "floor": float(floor),
            **{f"overlay_{k}": v for k, v in overlay_summary.items()},
            **{
                f"broker_{k}": metrics.get(k)
                for k in [
                    "status",
                    "reason",
                    "metric_mode",
                    "cagr",
                    "max_dd",
                    "sharpe",
                    "years",
                    "avg_cash_weight",
                    "cash_interest_accrued_usd",
                    "actual_equity_curve_end_date",
                    "end_date_matches_official",
                    "replay_end_filtered_target_date_count",
                    "replay_end_skipped_rebalance_count",
                ]
            },
        }
        rows.append(row)

    pd.DataFrame(rows).to_csv(output_dir / "arm_metrics.csv", index=False)
    payload = {
        "status": "completed",
        "schema_version": "official-book-bull-floor-broker-ab-v1",
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "portfolio_kind": args.portfolio_kind,
        "floors": parse_floors(args.floors),
        "replay_end_date": args.replay_end_date,
        "cash_carry_mode": args.cash_carry_mode or CASH_CARRY_MODE_NONE,
        "research_only": True,
        "production_activation_allowed": False,
        "arms": rows,
    }
    write_json(output_dir / "summary.json", payload)
    lines = ["# Official Book Bull-Floor Broker A/B", ""]
    lines.append("| floor | lifted_dates | CAGR | MaxDD | Sharpe | avg_cash | status |")
    lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in rows:
        lines.append(
            f"| {row.get('floor')} | {row.get('overlay_rebalance_dates_bull_floor_lifted')} | "
            f"{row.get('broker_cagr')} | {row.get('broker_max_dd')} | {row.get('broker_sharpe')} | "
            f"{row.get('broker_avg_cash_weight')} | {row.get('broker_status')} |"
        )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default="outputs/official_book_bull_floor_broker_ab")
    parser.add_argument("--portfolio-kind", default="concentrated", choices=["main", "concentrated"])
    parser.add_argument("--floors", default="0.0,0.85,0.90,0.95")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--replay-end-date", default="")
    parser.add_argument("--official-baseline-end-date", default="")
    parser.add_argument("--cash-carry-mode", default="", choices=["", CASH_CARRY_MODE_NONE, CASH_CARRY_MODE_RISK_FREE])
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-path", default="")
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
