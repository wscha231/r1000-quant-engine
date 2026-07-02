#!/usr/bin/env python3
"""Research-only cap-safe sizing A/B on a fixed Concentrated official book."""
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
    "vol_adjusted_weight",
    "max_drawdown_contribution_capped",
    "rs_plus_low_vol_blend",
    "winner_pyramiding_only_if_positive_rs",
    "equal_weight_with_cash_preserved",
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


def stock_mask(df: pd.DataFrame) -> pd.Series:
    return ~df["ticker"].astype(str).str.upper().isin(CASH_TICKERS)


def rs_score(row: pd.Series) -> float:
    vals = [
        safe_float(row.get("rs_benchmark_3m")),
        safe_float(row.get("rs_benchmark_6m")),
        safe_float(row.get("rs_spy_3m")),
        safe_float(row.get("rs_qqq_3m")),
        safe_float(row.get("rs_spy_6m")),
        safe_float(row.get("rs_qqq_6m")),
    ]
    return max(vals)


def vol_penalty(row: pd.Series) -> float:
    atr = safe_float(row.get("atr14_pct"), 0.0)
    vol = safe_float(row.get("realized_vol_63d"), 0.0)
    return max(atr, vol, 0.0)


def single_cap(row: pd.Series, default: float) -> float:
    cap = safe_float(row.get("effective_single_weight_cap"), default)
    if cap <= 0:
        cap = default
    return min(default, cap)


def normalize_positive(values: list[float]) -> list[float]:
    clean = [max(0.0, float(v)) for v in values]
    total = sum(clean)
    if total <= 1e-12:
        return [1.0 / len(clean)] * len(clean) if clean else []
    return [v / total for v in clean]


def cap_preserving_waterfill(weights: list[float], target_total: float, ceilings: list[float]) -> tuple[list[float], str]:
    """Return cap-respecting weights.

    Unlike the production bull-floor helper, this starts by clipping weights
    already above cap, then redistributes remaining feasible gross. If caps
    cannot hold the original stock gross, the residual is left for cash.
    """
    raw = [max(0.0, float(x)) for x in weights]
    caps = [max(0.0, float(c)) for c in ceilings]
    if not raw:
        return raw, "empty"
    feasible_total = min(float(target_total), sum(caps))
    out = [min(w, cap) for w, cap in zip(raw, caps)]
    for _ in range(len(out) + 2):
        deficit = feasible_total - sum(out)
        if deficit <= 1e-12:
            break
        eligible = [i for i, (w, cap) in enumerate(zip(out, caps)) if w < cap - 1e-12]
        if not eligible:
            break
        base = sum(max(raw[i], 1e-12) for i in eligible)
        if base <= 1e-12:
            add = deficit / len(eligible)
            for i in eligible:
                out[i] = min(caps[i], out[i] + add)
        else:
            for i in eligible:
                add = deficit * max(raw[i], 1e-12) / base
                out[i] = min(caps[i], out[i] + add)
    status = "gross_preserved"
    if sum(caps) + 1e-12 < float(target_total):
        status = "cap_infeasible_cash_residual"
    return out, status


def apply_sizing_arm(book: pd.DataFrame, *, arm: str, portfolio_kind: str, max_single_weight: float) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if arm == "baseline_cash_carry":
        out = finalize_book(book.copy())
        out["fixed_book_sizing_arm"] = arm
        return out, pd.DataFrame(), {"status": "completed", "arm": arm, "applied_count": 0, "cap_breach_count": 0}

    rebuilt: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    for raw_dt in sorted(book["rebalance_date"].dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        day = book[book["rebalance_date"].eq(raw_dt)].copy()
        mask = stock_mask(day)
        stock = day.loc[mask].copy()
        if stock.empty:
            rebuilt.append(day)
            continue
        original = pd.to_numeric(stock["weight"], errors="coerce").fillna(0.0).tolist()
        gross = float(sum(original))
        caps = [single_cap(row, max_single_weight) for _, row in stock.iterrows()]
        if gross <= 1e-12:
            rebuilt.append(day)
            continue

        if arm == "equal_weight_with_cash_preserved":
            prefs = [1.0] * len(stock)
        elif arm == "vol_adjusted_weight":
            prefs = [1.0 / max(0.02, vol_penalty(row)) for _, row in stock.iterrows()]
        elif arm == "rs_plus_low_vol_blend":
            prefs = [max(0.0, 1.0 + 3.0 * rs_score(row)) / max(0.05, 1.0 + vol_penalty(row)) for _, row in stock.iterrows()]
        elif arm == "winner_pyramiding_only_if_positive_rs":
            prefs = [max(0.05, 1.0 + 5.0 * max(0.0, rs_score(row))) for _, row in stock.iterrows()]
        elif arm == "max_drawdown_contribution_capped":
            prefs = [
                max(0.05, 1.0 - min(0.7, max(vol_penalty(row), safe_float(row.get("benchmark_risk_score"), 0.0) * 0.1)))
                for _, row in stock.iterrows()
            ]
        else:
            raise ValueError(f"Unknown arm: {arm}")

        shares = normalize_positive(prefs)
        raw_new = [gross * p for p in shares]
        new_weights, gross_status = cap_preserving_waterfill(raw_new, gross, caps)
        idxs = list(stock.index)
        for idx, old_w, new_w in zip(idxs, original, new_weights):
            day.at[idx, "weight"] = float(new_w)
            day.at[idx, "target_weight"] = float(new_w)
            day.at[idx, "fixed_book_sizing_arm"] = arm
            if abs(float(new_w) - float(old_w)) > 1e-8:
                audit_rows.append(
                    {
                        "rebalance_date": dt.date().isoformat(),
                        "ticker": str(day.at[idx, "ticker"]),
                        "arm": arm,
                        "old_weight": float(old_w),
                        "new_weight": float(new_w),
                        "delta_weight": float(new_w) - float(old_w),
                        "rs_score": rs_score(day.loc[idx]),
                        "vol_penalty": vol_penalty(day.loc[idx]),
                        "gross_preservation_status": gross_status,
                    }
                )
        day = rebuild_cash(day, portfolio_kind=portfolio_kind)
        rebuilt.append(day)

    out = finalize_book(pd.concat(rebuilt, ignore_index=True) if rebuilt else book.copy())
    stock = out.loc[stock_mask(out)].copy()
    cap_breach = int((pd.to_numeric(stock["weight"], errors="coerce").fillna(0.0) > max_single_weight + 1e-9).sum())
    audit = pd.DataFrame(audit_rows)
    statuses = sorted(set(audit["gross_preservation_status"].dropna().astype(str))) if "gross_preservation_status" in audit.columns else []
    return out, audit, {
        "status": "completed",
        "arm": arm,
        "applied_count": int(len(audit)),
        "cap_breach_count": cap_breach,
        "gross_preservation_statuses": statuses,
    }


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
        template["selection_reason"] = "cash_from_fixed_book_sizing_ab"
        out = pd.concat([out, pd.DataFrame([template])], ignore_index=True)
    return out


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
        "cap_breach_count": summary.get("cap_breach_count", 0),
        "gross_preservation_statuses": ";".join(summary.get("gross_preservation_statuses", [])),
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
        adjusted, audit, overlay_summary = apply_sizing_arm(
            base_book,
            arm=arm,
            portfolio_kind=args.portfolio_kind,
            max_single_weight=args.max_single_weight,
        )
        arm_book = arm_dir / "target_book.csv"
        adjusted.to_csv(arm_book, index=False)
        audit.to_csv(arm_dir / "sizing_audit.csv", index=False)
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
    baseline = metrics_df[metrics_df["arm"].eq("baseline_cash_carry")].iloc[0].to_dict() if "baseline_cash_carry" in set(metrics_df["arm"]) else {}
    for col in ["cagr", "max_dd", "sharpe"]:
        if baseline and col in metrics_df.columns:
            metrics_df[f"delta_{col}"] = pd.to_numeric(metrics_df[col], errors="coerce") - safe_float(baseline.get(col))
    metrics_df.to_csv(output_dir / "arm_metrics.csv", index=False)
    payload = {
        "status": "completed",
        "schema_version": "fixed-book-concentrated-sizing-ab-v1",
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "portfolio_kind": args.portfolio_kind,
        "arms": metrics_df.to_dict("records"),
        "cash_carry_mode": args.cash_carry_mode or CASH_CARRY_MODE_NONE,
        "max_single_weight": float(args.max_single_weight),
        "replay_end_date": args.replay_end_date,
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", payload)
    lines = ["# Fixed Official Book Concentrated Sizing A/B", ""]
    lines.append("| arm | applied | cap_breach | CAGR | MaxDD | Sharpe | delta_CAGR | delta_MaxDD | status |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for row in metrics_df.to_dict("records"):
        lines.append(
            f"| {row.get('arm')} | {row.get('applied_count')} | {row.get('cap_breach_count')} | "
            f"{row.get('cagr')} | {row.get('max_dd')} | {row.get('sharpe')} | "
            f"{row.get('delta_cagr', '')} | {row.get('delta_max_dd', '')} | {row.get('broker_status')} |"
        )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default="outputs/fixed_book_concentrated_sizing_ab")
    parser.add_argument("--portfolio-kind", default="concentrated", choices=["concentrated"])
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--max-single-weight", type=float, default=0.30)
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
