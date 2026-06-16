#!/usr/bin/env python3
"""Separate useful crisis defense cash from cash traps and reentry lag.

Measurement-only sidecar. It reads target-book cash, broker cash/equity, and
crisis-state artifacts, then writes review flags. It does not change cash
policy, orders, target books, or production gates.
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_text


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/cash_reentry_quality"
CASH_TICKER = "CASH"
PORTFOLIOS = ("main", "concentrated")

COMMON_METADATA_COLUMNS = [
    "source_run_id",
    "source_commit_sha",
    "source_branch",
    "portfolio_policy",
    "metric_mode",
    "official_metric_source",
    "candidate_source",
    "target_book_source",
    "generated_at",
    "production_mutation_allowed",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_value(args: list[str], default: str = "unknown") -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_path("."), text=True, stderr=subprocess.DEVNULL).strip() or default
    except Exception:
        return default


def _metadata(latest_run: Path, generated_at: str) -> dict[str, Any]:
    return {
        "source_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "source_commit_sha": os.environ.get("GITHUB_SHA") or _git_value(["rev-parse", "--short", "HEAD"]),
        "source_branch": os.environ.get("GITHUB_REF_NAME") or _git_value(["branch", "--show-current"]),
        "portfolio_policy": os.environ.get("PORTFOLIO_POLICY", "alphaops_vnext_production"),
        "metric_mode": "broker_ledger_next_close",
        "official_metric_source": "outputs/account_evaluation/official_metrics.json",
        "candidate_source": str(latest_run / "reports" / "candidate_replay_book.csv"),
        "target_book_source": str(latest_run / "reports" / "operating_*_target_book.csv"),
        "generated_at": generated_at,
        "production_mutation_allowed": False,
    }


def _normalize_date(frame: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    if frame.empty or col not in frame.columns:
        return frame
    out = frame.copy()
    out[col] = pd.to_datetime(out[col], errors="coerce")
    out = out.dropna(subset=[col]).copy()
    return out


def _crisis_bucket(value: Any) -> str:
    text = str(value or "").upper()
    if "CRISIS" in text:
        return "CRISIS"
    if "DEFENSE" in text:
        return "DEFENSE"
    if "WATCH" in text:
        return "WATCH"
    return "GREEN"


def _read_crisis_state(latest_run: Path) -> pd.DataFrame:
    for path in [
        latest_run / "daily_crisis_monitor" / "daily_crisis_state.csv",
        latest_run / "alphaops_vnext" / "daily_crisis_state.csv",
        latest_run / "crisis_paper_order_bridge" / "crisis_actions.csv",
    ]:
        frame = read_table(path)
        if frame.empty:
            continue
        date_col = "date" if "date" in frame.columns else "rebalance_date" if "rebalance_date" in frame.columns else ""
        state_col = "crisis_state" if "crisis_state" in frame.columns else "state" if "state" in frame.columns else ""
        if not date_col or not state_col:
            continue
        d = frame[[date_col, state_col]].copy().rename(columns={date_col: "date", state_col: "crisis_state"})
        d = _normalize_date(d, "date")
        d["crisis_bucket"] = d["crisis_state"].map(_crisis_bucket)
        return d.sort_values("date")
    return pd.DataFrame(columns=["date", "crisis_state", "crisis_bucket"])


def _target_book_path(latest_run: Path, portfolio: str) -> Path:
    if portfolio == "main":
        return latest_run / "reports" / "operating_main_target_book.csv"
    return latest_run / "reports" / "operating_concentrated_target_book.csv"


def _fallback_book_path(latest_run: Path, portfolio: str) -> Path:
    if portfolio == "main":
        return latest_run / "reports" / "main_monthly_weights.csv"
    return latest_run / "reports" / "concentrated_strategy_holdings.csv"


def _load_cash_rows(latest_run: Path, portfolio: str, meta: dict[str, Any]) -> pd.DataFrame:
    path = _target_book_path(latest_run, portfolio)
    frame = read_table(path)
    source = str(path)
    if frame.empty:
        path = _fallback_book_path(latest_run, portfolio)
        frame = read_table(path)
        source = str(path)
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    if "rebalance_date" not in d.columns:
        d["rebalance_date"] = "latest"
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    if d["rebalance_date"].isna().all():
        d["rebalance_date"] = pd.Timestamp.utcnow().tz_localize(None).normalize()
    d = d.dropna(subset=["rebalance_date"]).copy()
    d["ticker"] = d.get("ticker", pd.Series([""] * len(d))).astype(str).str.upper().str.strip()
    weight_col = "weight" if "weight" in d.columns else "target_weight" if "target_weight" in d.columns else ""
    d["_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0) if weight_col else 0.0
    rows = []
    for date, group in d.groupby("rebalance_date", sort=True):
        stock_count = int(((group["ticker"] != CASH_TICKER) & (group["_weight"] > 1e-10)).sum())
        explicit_cash = float(group.loc[group["ticker"].eq(CASH_TICKER), "_weight"].sum())
        implicit_cash = max(0.0, 1.0 - float(group.loc[~group["ticker"].eq(CASH_TICKER), "_weight"].sum()) - explicit_cash)
        cash_weight = max(0.0, explicit_cash + implicit_cash)
        rows.append(
            {
                **meta,
                "portfolio": portfolio,
                "rebalance_date": date,
                "cash_weight": cash_weight,
                "explicit_cash_weight": explicit_cash,
                "implicit_cash_weight": implicit_cash,
                "stock_count": stock_count,
                "target_book_source": source,
            }
        )
    return pd.DataFrame(rows)


def _attach_crisis(cash_rows: pd.DataFrame, crisis: pd.DataFrame) -> pd.DataFrame:
    if cash_rows.empty:
        return cash_rows
    out = cash_rows.copy()
    if crisis.empty:
        out["crisis_state"] = "UNKNOWN"
        out["crisis_bucket"] = "GREEN"
        return out
    c = crisis.sort_values("date").copy()
    out = out.sort_values("rebalance_date").copy()
    merged = pd.merge_asof(out, c, left_on="rebalance_date", right_on="date", direction="backward")
    merged["crisis_state"] = merged["crisis_state"].fillna("UNKNOWN")
    merged["crisis_bucket"] = merged["crisis_bucket"].fillna("GREEN")
    return merged.drop(columns=["date"], errors="ignore")


def _cash_reason(row: pd.Series) -> str:
    bucket = str(row.get("crisis_bucket", "GREEN")).upper()
    cash = safe_float(row.get("cash_weight"), 0.0)
    stock_count = safe_float(row.get("stock_count"), 0.0)
    if bucket in {"CRISIS", "DEFENSE"} and cash >= 0.05:
        return "crisis_state"
    if cash <= 0.02:
        return "target_cash_policy"
    if stock_count <= 2 and cash >= 0.10:
        return "missing_candidate"
    if 0.02 < cash < 0.10:
        return "cap_residual"
    if bucket in {"GREEN", "WATCH"} and cash >= 0.10:
        return "reentry_delay"
    return "unknown"


def _cash_by_group(rows: pd.DataFrame, group_col: str, meta: dict[str, Any]) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    out_rows = []
    for (portfolio, value), group in rows.groupby(["portfolio", group_col], dropna=False):
        out_rows.append(
            {
                **meta,
                "portfolio": portfolio,
                group_col: value,
                "months": int(len(group)),
                "avg_cash": float(pd.to_numeric(group["cash_weight"], errors="coerce").mean()),
                "max_cash": float(pd.to_numeric(group["cash_weight"], errors="coerce").max()),
                "cash_trap_days": int(pd.Series(group.get("cash_trap_flag", False)).astype(bool).sum()),
            }
        )
    return pd.DataFrame(out_rows)


def _read_metrics(path: Path) -> dict[str, Any]:
    try:
        import json

        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _mdd_improvement(latest_run: Path, portfolio: str) -> float | None:
    cur = _read_metrics(latest_run / "broker_replay" / portfolio / "metrics.json")
    base = _read_metrics(latest_run / "legacy_monthly_broker_replay" / portfolio / "metrics.json")
    cur_dd = safe_float(cur.get("max_dd", cur.get("max_drawdown")), math.nan)
    base_dd = safe_float(base.get("max_dd", base.get("max_drawdown")), math.nan)
    if not math.isfinite(cur_dd) or not math.isfinite(base_dd):
        return None
    return float(cur_dd - base_dd)


def _reentry_normalization(rows: pd.DataFrame) -> pd.DataFrame:
    columns = ["portfolio", "crisis_end_date", "cash_normalized_date", "reentry_cash_normalization_days"]
    if rows.empty:
        return pd.DataFrame(columns=columns)
    out_rows = []
    for portfolio, group in rows.sort_values("rebalance_date").groupby("portfolio", dropna=False):
        in_crisis = False
        crisis_end = None
        for _, row in group.iterrows():
            bucket = str(row.get("crisis_bucket", "GREEN")).upper()
            if bucket in {"CRISIS", "DEFENSE"}:
                in_crisis = True
                crisis_end = None
                continue
            if in_crisis and crisis_end is None:
                crisis_end = row["rebalance_date"]
            if crisis_end is not None and safe_float(row.get("cash_weight"), 0.0) <= 0.10:
                out_rows.append(
                    {
                        "portfolio": portfolio,
                        "crisis_end_date": crisis_end.date().isoformat() if hasattr(crisis_end, "date") else str(crisis_end),
                        "cash_normalized_date": row["rebalance_date"].date().isoformat() if hasattr(row["rebalance_date"], "date") else str(row["rebalance_date"]),
                        "reentry_cash_normalization_days": int((row["rebalance_date"] - crisis_end).days),
                    }
                )
                in_crisis = False
                crisis_end = None
    return pd.DataFrame(out_rows, columns=columns)


def _rebound_capture(latest_run: Path, rows: pd.DataFrame, meta: dict[str, Any]) -> pd.DataFrame:
    curves = []
    for portfolio in PORTFOLIOS:
        curve = read_table(latest_run / "broker_replay" / portfolio / "equity_curve.csv")
        if curve.empty or "date" not in curve.columns:
            continue
        c = curve.copy()
        c["portfolio"] = portfolio
        c["date"] = pd.to_datetime(c["date"], errors="coerce")
        c = c.dropna(subset=["date"])
        equity_col = "equity" if "equity" in c.columns else "account_value" if "account_value" in c.columns else ""
        if not equity_col:
            continue
        c["equity"] = pd.to_numeric(c[equity_col], errors="coerce")
        curves.append(c[["portfolio", "date", "equity"]])
    if not curves or rows.empty:
        return pd.DataFrame(columns=[*COMMON_METADATA_COLUMNS, "portfolio", "rebalance_date", "cash_weight", "rebound_capture_20d", "rebound_capture_63d", "missed_rebound_pct"])
    curve_all = pd.concat(curves, ignore_index=True)
    out = []
    for _, row in rows.iterrows():
        if str(row.get("crisis_bucket", "")).upper() not in {"GREEN", "WATCH"}:
            continue
        if safe_float(row.get("cash_weight"), 0.0) <= 0.10:
            continue
        portfolio = str(row["portfolio"])
        date = row["rebalance_date"]
        c = curve_all[curve_all["portfolio"].eq(portfolio)].sort_values("date")
        current = c[c["date"] >= date].head(1)
        if current.empty:
            continue
        cur_eq = safe_float(current.iloc[0].get("equity"), math.nan)
        def ret_after(days: int) -> float | None:
            fut = c[c["date"] >= date + pd.Timedelta(days=days)].head(1)
            if fut.empty or not math.isfinite(cur_eq) or cur_eq <= 0:
                return None
            return safe_float(fut.iloc[0].get("equity"), math.nan) / cur_eq - 1.0
        r20 = ret_after(20)
        r63 = ret_after(63)
        out.append(
            {
                **meta,
                "portfolio": portfolio,
                "rebalance_date": date.date().isoformat() if hasattr(date, "date") else str(date),
                "cash_weight": row.get("cash_weight"),
                "rebound_capture_20d": r20 if r20 is not None else "",
                "rebound_capture_63d": r63 if r63 is not None else "",
                "missed_rebound_pct": (safe_float(row.get("cash_weight"), 0.0) * max(r63 or 0.0, 0.0)) if r63 is not None else "",
            }
        )
    return pd.DataFrame(out, columns=[*COMMON_METADATA_COLUMNS, "portfolio", "rebalance_date", "cash_weight", "rebound_capture_20d", "rebound_capture_63d", "missed_rebound_pct"])


def _apply_cash_trap_flags(rows: pd.DataFrame, latest_run: Path, normalization: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    out = rows.copy()
    norm_by_port = {
        str(port): float(pd.to_numeric(group["reentry_cash_normalization_days"], errors="coerce").max())
        for port, group in normalization.groupby("portfolio", dropna=False)
    } if not normalization.empty else {}
    for portfolio, group_idx in out.groupby("portfolio", dropna=False).groups.items():
        group = out.loc[group_idx]
        green_avg = float(group.loc[group["crisis_bucket"].eq("GREEN"), "cash_weight"].mean()) if bool(group["crisis_bucket"].eq("GREEN").any()) else 0.0
        latest = group.sort_values("rebalance_date").tail(1)
        latest_cash = safe_float(latest.iloc[0].get("cash_weight"), 0.0) if not latest.empty else 0.0
        latest_bucket = str(latest.iloc[0].get("crisis_bucket", "GREEN")).upper() if not latest.empty else "GREEN"
        mdd_improve = _mdd_improvement(latest_run, str(portfolio))
        norm_days = norm_by_port.get(str(portfolio), 0.0)
        port_flag = (
            green_avg > 0.10
            or (latest_cash > 0.50 and latest_bucket != "CRISIS")
            or (mdd_improve is not None and mdd_improve < 0.03 and float(group["cash_weight"].mean()) > 0.10)
            or norm_days > 20
        )
        out.loc[group_idx, "green_avg_cash"] = green_avg
        out.loc[group_idx, "latest_cash"] = latest_cash
        out.loc[group_idx, "latest_crisis_state"] = latest_bucket
        out.loc[group_idx, "mdd_improvement"] = mdd_improve if mdd_improve is not None else ""
        out.loc[group_idx, "reentry_cash_normalization_days"] = norm_days
        out.loc[group_idx, "cash_trap_flag"] = bool(port_flag)
    return out


def _summary(rows: pd.DataFrame, normalization: pd.DataFrame, rebound: pd.DataFrame, meta: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "status": "completed" if not rows.empty else "skipped",
        "schema_version": "cash_reentry_quality_audit_v1",
        **meta,
        "rows": int(len(rows)),
        "cash_trap_rows": int(pd.Series(rows.get("cash_trap_flag", [])).astype(bool).sum()) if not rows.empty else 0,
        "by_portfolio": {},
    }
    for portfolio, group in rows.groupby("portfolio", dropna=False) if not rows.empty else []:
        green = group[group["crisis_bucket"].eq("GREEN")]
        watch = group[group["crisis_bucket"].eq("WATCH")]
        defense = group[group["crisis_bucket"].eq("DEFENSE")]
        crisis = group[group["crisis_bucket"].eq("CRISIS")]
        payload["by_portfolio"][str(portfolio)] = {
            "green_avg_cash": float(green["cash_weight"].mean()) if not green.empty else 0.0,
            "watch_avg_cash": float(watch["cash_weight"].mean()) if not watch.empty else 0.0,
            "defense_avg_cash": float(defense["cash_weight"].mean()) if not defense.empty else 0.0,
            "crisis_avg_cash": float(crisis["cash_weight"].mean()) if not crisis.empty else 0.0,
            "latest_cash": safe_float(group.sort_values("rebalance_date").tail(1).iloc[0].get("cash_weight"), 0.0),
            "cash_trap_flag": bool(pd.Series(group["cash_trap_flag"]).astype(bool).any()),
            "unknown_cash_reason_share": float((group["cash_reason"].eq("unknown")).mean()) if "cash_reason" in group.columns else 0.0,
        }
    return payload


def run(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    generated_at = _now_iso()
    meta = _metadata(latest_run, generated_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    crisis = _read_crisis_state(latest_run)
    frames = []
    for portfolio in PORTFOLIOS:
        frame = _load_cash_rows(latest_run, portfolio, meta)
        if not frame.empty:
            frames.append(frame)
    rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    rows = _attach_crisis(rows, crisis)
    if not rows.empty:
        rows["cash_reason"] = rows.apply(_cash_reason, axis=1)
    normalization = _reentry_normalization(rows)
    rows = _apply_cash_trap_flags(rows, latest_run, normalization)
    rebound = _rebound_capture(latest_run, rows, meta)

    cash_by_regime = _cash_by_group(rows, "crisis_bucket", meta)
    cash_by_crisis = _cash_by_group(rows, "crisis_state", meta)
    cash_drag = rows.copy()
    if not cash_drag.empty:
        for col in ("rebalance_date",):
            cash_drag[col] = pd.to_datetime(cash_drag[col], errors="coerce").dt.strftime("%Y-%m-%d")
    cash_drag.to_csv(output_dir / "cash_drag_report.csv", index=False)
    cash_by_regime.to_csv(output_dir / "cash_by_regime.csv", index=False)
    cash_by_crisis.to_csv(output_dir / "cash_by_crisis_state.csv", index=False)
    normalization.to_csv(output_dir / "reentry_lag_report.csv", index=False)
    rebound.to_csv(output_dir / "missed_rebound_report.csv", index=False)

    payload = _summary(rows, normalization, rebound, meta)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", _render_report(payload))
    return payload


def _render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Cash/Reentry Quality Audit",
        "",
        "Measurement-only diagnostic. No cash-policy, target-book, or order mutation.",
        "",
        "## Summary",
        "",
        f"- status: `{payload.get('status')}`",
        f"- metric mode: `{payload.get('metric_mode')}`",
        f"- production mutation allowed: `{payload.get('production_mutation_allowed')}`",
        f"- rows: {payload.get('rows', 0)}",
        f"- cash trap rows: {payload.get('cash_trap_rows', 0)}",
        "",
        "## Portfolio Cash",
        "",
    ]
    for portfolio, block in sorted((payload.get("by_portfolio") or {}).items()):
        lines.append(
            f"- `{portfolio}`: GREEN {safe_float(block.get('green_avg_cash'), 0.0):.1%}, "
            f"WATCH {safe_float(block.get('watch_avg_cash'), 0.0):.1%}, "
            f"DEFENSE {safe_float(block.get('defense_avg_cash'), 0.0):.1%}, "
            f"CRISIS {safe_float(block.get('crisis_avg_cash'), 0.0):.1%}, "
            f"latest {safe_float(block.get('latest_cash'), 0.0):.1%}, "
            f"cash_trap={block.get('cash_trap_flag')}"
        )
    lines.extend(
        [
            "",
            "## Cash Trap Rules",
            "",
            "- GREEN avg cash > 10%.",
            "- latest cash > 50% outside CRISIS.",
            "- avg cash up but MDD improvement < 3pp.",
            "- reentry cash normalization > 20 trading days.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(repo_path(args.latest_run), repo_path(args.output_dir))
    print(f"[cash-reentry-quality] {payload.get('status')} -> {repo_path(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
