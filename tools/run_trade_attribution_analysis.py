#!/usr/bin/env python3
"""Trade attribution analysis from broker-ledger round trips.

Produces structured findings the autonomous agent loop can mine. Each
run emits per-portfolio:

    outputs/trade_attribution/<portfolio>/findings.json
    outputs/trade_attribution/<portfolio>/attribution_report.md

The findings JSON is the canonical machine-readable record. Each
``findings[*]`` entry has ``finding_id``, ``severity``, ``evidence``
(plain English with numbers) and ``candidate_fix`` (concrete code or
config change). Future commits that act on a finding must reference
the ``finding_id`` in their CHANGELOG entry, and a subsequent run
should either eliminate the finding or move its severity down.

Scope: read-only analysis. This tool never edits strategy code or
target books. It only describes what happened.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent


SCHEMA_VERSION = "trade-attribution-findings-v1"


TARGET_CONTEXT_COLUMNS = [
    "rebalance_date",
    "ticker",
    "weight",
    "target_weight",
    "sector",
    "industry_group",
    "primary_lane",
    "holding_state",
    "hold_replace_decision",
    "crisis_state",
    "market_style_regime_label",
    "regime_state",
    "regime_capacity_regime",
    "selection_confirmation_score",
    "breakout_setup_quality_score",
    "volatility_contraction_score",
    "rs_benchmark_1m",
    "ticker_ret_1m",
    "rs_benchmark_3m",
    "ticker_ret_3m",
    "atr14_pct",
    "price_above_ma50",
    "price_above_ma200",
    "spy_1m_return",
    "qqq_1m_return",
    "benchmark_risk_score",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pick_pnl_column(frame: pd.DataFrame) -> str | None:
    for cand in ("net_pnl_usd", "realized_pnl_usd", "pnl_usd"):
        if cand in frame.columns:
            return cand
    return None


def mdd_window(equity: pd.DataFrame) -> dict[str, Any]:
    if equity.empty or "equity_usd" not in equity.columns or "date" not in equity.columns:
        return {}
    eq = equity.copy()
    eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
    eq = eq.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if eq.empty:
        return {}
    eq["running_peak"] = eq["equity_usd"].cummax()
    eq["drawdown"] = eq["equity_usd"] / eq["running_peak"] - 1.0
    trough_idx = int(eq["drawdown"].idxmin())
    peak_idx = int(eq.iloc[: trough_idx + 1]["equity_usd"].idxmax())
    return {
        "peak_date": eq.loc[peak_idx, "date"].date().isoformat(),
        "trough_date": eq.loc[trough_idx, "date"].date().isoformat(),
        "peak_equity_usd": float(eq.loc[peak_idx, "equity_usd"]),
        "trough_equity_usd": float(eq.loc[trough_idx, "equity_usd"]),
        "drawdown_pct": float(eq["drawdown"].min() * 100.0),
        "duration_days": int((eq.loc[trough_idx, "date"] - eq.loc[peak_idx, "date"]).days),
    }


def trades_in_window(trade_journal: pd.DataFrame, peak_date: str, trough_date: str, pnl_col: str) -> dict[str, Any]:
    if trade_journal.empty or pnl_col not in trade_journal.columns:
        return {"exit_count": 0, "exit_pnl_usd": 0.0}
    tj = trade_journal.copy()
    tj["exit_date"] = pd.to_datetime(tj.get("exit_date"), errors="coerce")
    tj = tj.dropna(subset=["exit_date"])
    peak = pd.Timestamp(peak_date)
    trough = pd.Timestamp(trough_date)
    in_window = tj[(tj["exit_date"] >= peak) & (tj["exit_date"] <= trough)].copy()
    return {
        "exit_count": int(len(in_window)),
        "exit_pnl_usd": float(in_window[pnl_col].sum()),
        "worst_5_exits": worst_n(in_window, pnl_col, 5),
    }


def broker_trades_in_window(trades: pd.DataFrame, peak_date: str, trough_date: str) -> dict[str, Any]:
    if trades.empty or not peak_date or not trough_date or "date" not in trades.columns:
        return {"trade_count": 0, "gross_value_usd": 0.0, "buy_count": 0, "sell_count": 0, "net_cash_delta_usd": 0.0}
    t = trades.copy()
    t["date"] = pd.to_datetime(t["date"], errors="coerce")
    t = t.dropna(subset=["date"])
    peak = pd.Timestamp(peak_date)
    trough = pd.Timestamp(trough_date)
    window = t[(t["date"] >= peak) & (t["date"] <= trough)].copy()
    if window.empty:
        return {"trade_count": 0, "gross_value_usd": 0.0, "buy_count": 0, "sell_count": 0, "net_cash_delta_usd": 0.0}
    window["gross_value"] = pd.to_numeric(window.get("gross_value", 0.0), errors="coerce").fillna(0.0)
    window["cash_delta"] = pd.to_numeric(window.get("cash_delta", 0.0), errors="coerce").fillna(0.0)
    side = window.get("side", pd.Series(dtype=str)).astype(str).str.upper()
    top_gross = (
        window.groupby("ticker", dropna=False)["gross_value"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .reset_index()
        .rename(columns={"gross_value": "gross_value_usd"})
        .to_dict("records")
    )
    return {
        "trade_count": int(len(window)),
        "gross_value_usd": float(window["gross_value"].sum()),
        "buy_count": int(side.eq("BUY").sum()),
        "sell_count": int(side.eq("SELL").sum()),
        "net_cash_delta_usd": float(window["cash_delta"].sum()),
        "top_tickers_by_gross_value": top_gross,
    }


def target_metadata(latest_run: Path, portfolio_kind: str) -> dict[str, dict[str, str]]:
    name = "operating_main_target_book.csv" if portfolio_kind == "main" else "operating_concentrated_target_book.csv"
    target = read_csv(latest_run / "reports" / name)
    if target.empty or "ticker" not in target.columns:
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in target.to_dict("records"):
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker or ticker in {"CASH", "__CASH__"}:
            continue
        out[ticker] = {
            "sector": str(row.get("sector") or ""),
            "industry_group": str(row.get("industry_group") or ""),
            "primary_lane": str(row.get("primary_lane") or ""),
        }
    return out


def holdings_pnl_contributors(
    holdings: pd.DataFrame,
    peak_date: str,
    trough_date: str,
    metadata: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    if holdings.empty or not peak_date or not trough_date or "date" not in holdings.columns:
        return [], {}, {}
    h = holdings.copy()
    h["date"] = pd.to_datetime(h["date"], errors="coerce")
    h["ticker"] = h.get("ticker", "").astype(str).str.upper().str.strip()
    h["market_value_usd"] = pd.to_numeric(h.get("market_value_usd", 0.0), errors="coerce").fillna(0.0)
    h["weight"] = pd.to_numeric(h.get("weight", 0.0), errors="coerce").fillna(0.0)
    h = h.dropna(subset=["date"]).sort_values(["ticker", "date"])
    h["prev_value"] = h.groupby("ticker")["market_value_usd"].shift(1)
    h["position_pnl_usd"] = h["market_value_usd"] - h["prev_value"]
    peak = pd.Timestamp(peak_date)
    trough = pd.Timestamp(trough_date)
    window = h[(h["date"] > peak) & (h["date"] <= trough)].copy()
    if window.empty:
        return [], {}, {}
    by_ticker = (
        window.groupby("ticker")
        .agg(
            position_pnl_usd=("position_pnl_usd", "sum"),
            avg_weight=("weight", "mean"),
            max_weight=("weight", "max"),
            days_held=("date", "nunique"),
        )
        .reset_index()
    )
    for col in ("sector", "industry_group", "primary_lane"):
        by_ticker[col] = by_ticker["ticker"].map(lambda ticker: metadata.get(str(ticker), {}).get(col, ""))
    by_ticker = by_ticker.sort_values("position_pnl_usd")
    records = by_ticker.head(30).to_dict("records")
    sector_loss = loss_by_group(by_ticker[by_ticker["position_pnl_usd"] < 0], "sector", "position_pnl_usd")
    industry_loss = loss_by_group(by_ticker[by_ticker["position_pnl_usd"] < 0], "industry_group", "position_pnl_usd")
    return records, sector_loss, industry_loss


def target_book_file(latest_run: Path, portfolio_kind: str) -> Path:
    name = "operating_main_target_book.csv" if portfolio_kind == "main" else "operating_concentrated_target_book.csv"
    return latest_run / "reports" / name


def mdd_target_rows(
    latest_run: Path,
    portfolio_kind: str,
    mdd_info: dict[str, Any],
    contributors: list[dict[str, Any]],
    lookback_days: int = 45,
) -> pd.DataFrame:
    if not mdd_info or not contributors:
        return pd.DataFrame()
    target = read_csv(target_book_file(latest_run, portfolio_kind))
    if target.empty or "ticker" not in target.columns or "rebalance_date" not in target.columns:
        return pd.DataFrame()
    loss_map = {
        str(row.get("ticker") or "").upper().strip(): safe_float(row.get("position_pnl_usd"))
        for row in contributors
        if safe_float(row.get("position_pnl_usd")) < 0
    }
    loss_map = {ticker: pnl for ticker, pnl in loss_map.items() if ticker and ticker not in {"CASH", "__CASH__"}}
    if not loss_map:
        return pd.DataFrame()
    peak = pd.Timestamp(mdd_info.get("peak_date")) - pd.Timedelta(days=lookback_days)
    trough = pd.Timestamp(mdd_info.get("trough_date"))
    d = target.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d.dropna(subset=["rebalance_date"])
    d = d[d["ticker"].isin(loss_map)]
    d = d[(d["rebalance_date"] >= peak.normalize()) & (d["rebalance_date"] <= trough.normalize())].copy()
    if d.empty:
        return pd.DataFrame()
    for col in ["weight", "target_weight", "selection_confirmation_score", "breakout_setup_quality_score", "rs_benchmark_1m", "ticker_ret_1m"]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    d["linked_mdd_position_pnl_usd"] = d["ticker"].map(loss_map)
    keep = [col for col in TARGET_CONTEXT_COLUMNS if col in d.columns]
    keep.extend(["linked_mdd_position_pnl_usd"])
    return d[keep].sort_values(["rebalance_date", "linked_mdd_position_pnl_usd", "ticker"]).reset_index(drop=True)


def summarize_target_context(rows: pd.DataFrame) -> list[dict[str, Any]]:
    if rows.empty:
        return []
    d = rows.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    numeric_cols = [
        "weight",
        "target_weight",
        "selection_confirmation_score",
        "breakout_setup_quality_score",
        "rs_benchmark_1m",
        "ticker_ret_1m",
        "rs_benchmark_3m",
        "ticker_ret_3m",
        "atr14_pct",
        "price_above_ma50",
        "price_above_ma200",
        "spy_1m_return",
        "qqq_1m_return",
        "benchmark_risk_score",
        "linked_mdd_position_pnl_usd",
    ]
    for col in numeric_cols:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    out: list[dict[str, Any]] = []
    for ticker, group in d.groupby("ticker", sort=False):
        group = group.sort_values("rebalance_date")
        row: dict[str, Any] = {
            "ticker": ticker,
            "first_rebalance_date": group["rebalance_date"].min().date().isoformat(),
            "last_rebalance_date": group["rebalance_date"].max().date().isoformat(),
            "target_row_count": int(len(group)),
            "linked_mdd_position_pnl_usd": float(group["linked_mdd_position_pnl_usd"].dropna().iloc[0]),
        }
        for col in ["sector", "industry_group", "primary_lane", "crisis_state", "market_style_regime_label", "regime_state", "regime_capacity_regime"]:
            if col in group.columns:
                values = group[col].dropna().astype(str)
                row[col] = values.iloc[-1] if not values.empty else ""
        for col in ["weight", "target_weight", "selection_confirmation_score", "breakout_setup_quality_score", "rs_benchmark_1m", "ticker_ret_1m", "atr14_pct"]:
            if col in group.columns:
                values = pd.to_numeric(group[col], errors="coerce")
                row[f"avg_{col}"] = float(values.mean()) if values.notna().any() else None
                row[f"max_{col}"] = float(values.max()) if values.notna().any() else None
                row[f"min_{col}"] = float(values.min()) if values.notna().any() else None
        out.append(row)
    return sorted(out, key=lambda row: safe_float(row.get("linked_mdd_position_pnl_usd")))


def mdd_policy_bucket_summary(rows: pd.DataFrame) -> list[dict[str, Any]]:
    if rows.empty:
        return []
    d = rows.copy()
    for col in [
        "weight",
        "target_weight",
        "selection_confirmation_score",
        "breakout_setup_quality_score",
        "rs_benchmark_1m",
        "ticker_ret_1m",
        "atr14_pct",
        "spy_1m_return",
        "qqq_1m_return",
        "price_above_ma50",
        "price_above_ma200",
        "linked_mdd_position_pnl_usd",
    ]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
        else:
            d[col] = np.nan
    text = {
        col: d[col].astype(str).str.upper()
        for col in ["primary_lane", "crisis_state", "market_style_regime_label", "regime_state", "regime_capacity_regime", "sector"]
        if col in d.columns
    }
    buckets = [
        (
            "high_weight_market_leader",
            "MARKET_LEADER rows above 8% target weight",
            text.get("primary_lane", pd.Series("", index=d.index)).eq("MARKET_LEADER") & d["weight"].ge(0.08),
        ),
        (
            "negative_short_rs_weighted",
            "Rows above 4% where 1m absolute or benchmark-relative return is negative",
            d["weight"].ge(0.04) & (d["rs_benchmark_1m"].lt(0.0) | d["ticker_ret_1m"].lt(0.0)),
        ),
        (
            "high_vol_weighted",
            "Rows above 6% with ATR14 at or above 6%",
            d["weight"].ge(0.06) & d["atr14_pct"].ge(0.06),
        ),
        (
            "weak_confirmation_weighted",
            "Rows above 6% with confirmation below 0.50 or breakout quality below 0.60",
            d["weight"].ge(0.06) & (d["selection_confirmation_score"].lt(0.50) | d["breakout_setup_quality_score"].lt(0.60)),
        ),
        (
            "qqq_underperforms_spy_weighted",
            "Rows above 6% where QQQ one-month return is below SPY",
            d["weight"].ge(0.06) & d["qqq_1m_return"].lt(d["spy_1m_return"]),
        ),
        (
            "below_ma50_weighted",
            "Rows above 4% with price below the 50-day average flag",
            d["weight"].ge(0.04) & d["price_above_ma50"].le(0.0),
        ),
        (
            "information_technology_loss_cluster",
            "Information Technology MDD loss rows",
            text.get("sector", pd.Series("", index=d.index)).eq("INFORMATION TECHNOLOGY"),
        ),
    ]
    out: list[dict[str, Any]] = []
    for bucket_id, description, mask in buckets:
        selected = d[mask.fillna(False)].copy()
        if selected.empty:
            continue
        unique = selected.sort_values("linked_mdd_position_pnl_usd").drop_duplicates("ticker", keep="first")
        linked_loss = float(unique["linked_mdd_position_pnl_usd"].sum())
        tickers = unique["ticker"].astype(str).head(12).tolist() if "ticker" in unique.columns else []
        out.append(
            {
                "bucket_id": bucket_id,
                "description": description,
                "target_row_count": int(len(selected)),
                "ticker_count": int(unique["ticker"].nunique()) if "ticker" in unique.columns else 0,
                "linked_mdd_position_pnl_usd": linked_loss,
                "avg_weight": float(selected["weight"].mean()) if selected["weight"].notna().any() else None,
                "max_weight": float(selected["weight"].max()) if selected["weight"].notna().any() else None,
                "tickers": tickers,
                "research_note": "diagnostic bucket only; convert to policy only after broker replay validates a PIT-safe rule",
            }
        )
    return sorted(out, key=lambda row: safe_float(row.get("linked_mdd_position_pnl_usd")))


def target_bucket_findings(
    portfolio_kind: str,
    target_context: list[dict[str, Any]],
    policy_buckets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not policy_buckets or not target_context:
        return []
    total_context_loss = abs(
        sum(
            safe_float(row.get("linked_mdd_position_pnl_usd"))
            for row in target_context
            if safe_float(row.get("linked_mdd_position_pnl_usd")) < 0
        )
    )
    if total_context_loss <= 0:
        return []
    top_bucket = min(policy_buckets, key=lambda row: safe_float(row.get("linked_mdd_position_pnl_usd")))
    bucket_loss = abs(safe_float(top_bucket.get("linked_mdd_position_pnl_usd")))
    bucket_share = bucket_loss / max(total_context_loss, 1e-12)
    if bucket_share < 0.30:
        return []
    return [
        {
            "finding_id": f"F8_mdd_target_book_feature_bucket_{portfolio_kind}_{top_bucket.get('bucket_id')}",
            "severity": "medium",
            "evidence": (
                f"Operating target-book rows linked to MDD losers show bucket "
                f"`{top_bucket.get('bucket_id')}` with ${-bucket_loss:,.0f} linked position P&L "
                f"({bucket_share:.0%} of top context loss), "
                f"{top_bucket.get('ticker_count')} tickers, avg weight "
                f"{safe_float(top_bucket.get('avg_weight')):.1%}, max weight "
                f"{safe_float(top_bucket.get('max_weight')):.1%}. Top tickers: "
                f"{', '.join(top_bucket.get('tickers') or [])}."
            ),
            "candidate_fix": (
                "Use the emitted mdd_policy_bucket_summary.csv and mdd_target_rows.csv "
                "to design one narrow PIT-safe entry/hold sizing rule. Do not promote "
                "the bucket itself; validate any rule through broker-ledger fast replay."
            ),
        }
    ]


def worst_n(frame: pd.DataFrame, pnl_col: str, n: int) -> list[dict[str, Any]]:
    if frame.empty or pnl_col not in frame.columns:
        return []
    keep = ["ticker", "entry_date", "exit_date", "holding_days", "realized_return", pnl_col, "exit_reason", "entry_regime_state"]
    cols = [c for c in keep if c in frame.columns]
    rows = frame.sort_values(pnl_col).head(n)[cols].to_dict("records")
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else (None if pd.isna(v) else v)) for k, v in row.items()} for row in rows]


def best_n(frame: pd.DataFrame, pnl_col: str, n: int) -> list[dict[str, Any]]:
    if frame.empty or pnl_col not in frame.columns:
        return []
    keep = ["ticker", "entry_date", "exit_date", "holding_days", "realized_return", pnl_col, "exit_reason", "entry_regime_state"]
    cols = [c for c in keep if c in frame.columns]
    rows = frame.sort_values(pnl_col, ascending=False).head(n)[cols].to_dict("records")
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else (None if pd.isna(v) else v)) for k, v in row.items()} for row in rows]


def loss_by_group(losers: pd.DataFrame, group_col: str, pnl_col: str) -> dict[str, Any]:
    if losers.empty or group_col not in losers.columns:
        return {}
    g = losers.groupby(group_col)[pnl_col].agg(["sum", "count", "mean"]).sort_values("sum")
    return {
        str(k): {
            "sum_usd": float(row["sum"]),
            "count": int(row["count"]),
            "avg_usd": float(row["mean"]),
        }
        for k, row in g.iterrows()
    }


def build_findings(
    *,
    portfolio_kind: str,
    metrics: dict[str, Any],
    mdd_info: dict[str, Any],
    in_window: dict[str, Any],
    trade_journal: pd.DataFrame,
    pnl_col: str,
    losers: pd.DataFrame,
    winners: pd.DataFrame,
    loss_by_regime: dict[str, Any],
    loss_by_exit_reason: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    drawdown_pct = float(mdd_info.get("drawdown_pct") or 0.0)
    peak_eq = float(mdd_info.get("peak_equity_usd") or 0.0)
    trough_eq = float(mdd_info.get("trough_equity_usd") or 0.0)
    equity_loss_usd = peak_eq - trough_eq
    in_window_pnl = float(in_window.get("exit_pnl_usd") or 0.0)
    realized_share = (abs(in_window_pnl) / equity_loss_usd) if equity_loss_usd > 0 else 0.0

    # F1: MDD dominated by unrealized loss on held positions.
    if drawdown_pct <= -10.0 and realized_share < 0.20:
        findings.append({
            "finding_id": f"F1_mdd_dominated_by_unrealized_holdings_{portfolio_kind}",
            "severity": "high",
            "evidence": (
                f"MDD window {mdd_info.get('peak_date')} to {mdd_info.get('trough_date')} "
                f"({drawdown_pct:.2f}% drawdown, equity loss ${equity_loss_usd:,.0f}) had only "
                f"{in_window.get('exit_count', 0)} round-trip exits totaling "
                f"${in_window_pnl:,.0f} P&L. The drawdown is therefore dominated by "
                f"unrealized loss on still-held positions (realized share {realized_share:.1%})."
            ),
            "candidate_fix": (
                "Add a portfolio-level drawdown circuit breaker: when running DD exceeds "
                "10% within 5 trading days, force trim each position by 50% at next close. "
                "Re-entry permitted only after equity recovers to within 5% of prior peak. "
                "Implementation point: extend tools/run_broker_position_risk_replay.py "
                "or wire into operating_main/concentrated_target_book builder."
            ),
        })

    # F2: Loss concentration in a single regime.
    if loss_by_regime:
        total_loss = sum(v.get("sum_usd", 0.0) for v in loss_by_regime.values())
        for regime, payload in loss_by_regime.items():
            share = payload["sum_usd"] / total_loss if total_loss < 0 else 0.0
            if share > 0.55 and total_loss < 0:
                findings.append({
                    "finding_id": f"F2_loss_concentration_in_{regime}_regime_{portfolio_kind}",
                    "severity": "medium",
                    "evidence": (
                        f"{share:.0%} of total realized losses (${payload['sum_usd']:,.0f} of "
                        f"${total_loss:,.0f}) occurred in {regime} regime, "
                        f"across {payload['count']} trades (avg ${payload['avg_usd']:,.0f}). "
                        f"The engine over-allocates or over-trades in this regime."
                    ),
                    "candidate_fix": (
                        f"Reduce capacity_for_regime['{regime}'] in the operating book "
                        f"builder by 20-30%, or tighten entry quality threshold "
                        f"(e.g. raise min_score_quantile) for {regime} signal dates. "
                        f"Re-measure F2 share on next broker-ledger replay."
                    ),
                })
                break  # one regime is enough to flag

    # F3: Asymmetric exit reasons - target_exit losers vs target_rebalance losers.
    if "target_exit" in loss_by_exit_reason and "target_rebalance" in loss_by_exit_reason:
        te = loss_by_exit_reason["target_exit"]
        tr = loss_by_exit_reason["target_rebalance"]
        if te["count"] > 0 and te["avg_usd"] < tr.get("avg_usd", 0) - 200:
            findings.append({
                "finding_id": f"F3_target_exit_losers_deeper_than_rebalance_{portfolio_kind}",
                "severity": "medium",
                "evidence": (
                    f"target_exit losers average ${te['avg_usd']:,.0f} loss over {te['count']} trades, "
                    f"while target_rebalance losers average ${tr['avg_usd']:,.0f} over {tr['count']} trades. "
                    f"Explicit exits are firing too late."
                ),
                "candidate_fix": (
                    "Tighten the leader-rescue / stale-trim threshold so a position is "
                    "exit-flagged earlier in its decline. Inspect "
                    "tools/run_lifecycle_review_overlay.py and the stale_mega_leader_score "
                    "weighting in r1000_main_v2.py."
                ),
            })

    # F4: Single mega-loser. A single trade dominating losses signals concentration risk.
    if not trade_journal.empty and pnl_col in trade_journal.columns:
        all_losers = trade_journal[trade_journal[pnl_col] < 0]
        if len(all_losers) >= 5:
            worst = all_losers.sort_values(pnl_col).iloc[0]
            total_loss = float(all_losers[pnl_col].sum())
            if total_loss < 0:
                share = float(worst[pnl_col]) / total_loss
                if share > 0.10:
                    findings.append({
                        "finding_id": f"F4_single_trade_loss_concentration_{portfolio_kind}",
                        "severity": "medium",
                        "evidence": (
                            f"Worst single trade ({worst.get('ticker')}, "
                            f"{worst.get('entry_date')} -> {worst.get('exit_date')}, "
                            f"realized_return={safe_float(worst.get('realized_return')):.2%}, "
                            f"pnl ${safe_float(worst.get(pnl_col)):,.0f}) accounts for {share:.0%} of total losses. "
                            f"Position-level stop-loss or trailing-stop would have capped the bleed."
                        ),
                        "candidate_fix": (
                            "Add per-position hard stop and trailing stop in the broker-ledger "
                            "replay path (mirror legacy monthly engine's -8% hard / -15% trailing "
                            "as a starting point), then back the parameters out from a sweep."
                        ),
                    })

    # F5: Win rate sanity check - if win rate < 50%, picking model has issue.
    n_winners = len(winners)
    n_losers = len(losers)
    total = n_winners + n_losers
    if total > 30:
        win_rate = n_winners / total
        if win_rate < 0.50:
            findings.append({
                "finding_id": f"F5_low_win_rate_{portfolio_kind}",
                "severity": "high",
                "evidence": (
                    f"Win rate {win_rate:.1%} ({n_winners} winners / {n_losers} losers) is below 50%. "
                    f"Avg winner ${winners[pnl_col].mean():,.0f}, avg loser ${losers[pnl_col].mean():,.0f}."
                ),
                "candidate_fix": (
                    "Investigate selection model. Run tests/audit_features.py and "
                    "tools/regression_attribution.py to identify which signals have decayed. "
                    "Consider retraining or re-weighting the score stack."
                ),
            })

    return findings


def analyze_portfolio(
    *,
    latest_run: Path,
    portfolio_kind: str,
    output_dir: Path,
) -> dict[str, Any]:
    metrics = read_json(latest_run / "broker_replay" / portfolio_kind / "metrics.json")
    if metrics.get("status") != "completed":
        return {
            "portfolio_kind": portfolio_kind,
            "status": "blocked",
            "reason": f"broker_replay metrics for {portfolio_kind} not completed",
        }
    trade_journal = read_csv(latest_run / "broker_trade_journal" / portfolio_kind / "round_trips.csv")
    equity = read_csv(latest_run / "broker_replay" / portfolio_kind / "equity_curve.csv")
    broker_trades = read_csv(latest_run / "broker_replay" / portfolio_kind / "trades.csv")
    holdings = read_csv(latest_run / "broker_replay" / portfolio_kind / "holdings_daily.csv")
    pnl_col = pick_pnl_column(trade_journal)
    if pnl_col is None or trade_journal.empty:
        mdd_info = mdd_window(equity)
        metadata = target_metadata(latest_run, portfolio_kind)
        trade_window = broker_trades_in_window(broker_trades, mdd_info.get("peak_date", ""), mdd_info.get("trough_date", "")) if mdd_info else {}
        contributors, sector_loss, industry_loss = holdings_pnl_contributors(
            holdings,
            mdd_info.get("peak_date", ""),
            mdd_info.get("trough_date", ""),
            metadata,
        ) if mdd_info else ([], {}, {})
        if mdd_info and contributors:
            target_rows = mdd_target_rows(latest_run, portfolio_kind, mdd_info, contributors)
            target_context = summarize_target_context(target_rows)
            policy_buckets = mdd_policy_bucket_summary(target_rows)
            findings: list[dict[str, Any]] = []
            peak_eq = safe_float(mdd_info.get("peak_equity_usd"))
            trough_eq = safe_float(mdd_info.get("trough_equity_usd"))
            equity_loss_usd = max(0.0, peak_eq - trough_eq)
            drawdown_pct = safe_float(mdd_info.get("drawdown_pct"))
            worst = contributors[0]
            negative_pnl = sum(safe_float(row.get("position_pnl_usd")) for row in contributors if safe_float(row.get("position_pnl_usd")) < 0)
            worst_share = abs(safe_float(worst.get("position_pnl_usd"))) / max(abs(negative_pnl), 1e-12)
            if drawdown_pct <= -20.0 and worst_share >= 0.15:
                findings.append(
                    {
                        "finding_id": f"F6_mdd_ticker_loss_concentration_{portfolio_kind}",
                        "severity": "high" if worst_share >= 0.25 else "medium",
                        "evidence": (
                            f"During MDD {mdd_info.get('peak_date')} to {mdd_info.get('trough_date')}, "
                            f"{worst.get('ticker')} contributed ${safe_float(worst.get('position_pnl_usd')):,.0f} "
                            f"of top-30 negative position P&L ({worst_share:.0%} share). "
                            f"Max weight was {safe_float(worst.get('max_weight')):.1%}."
                        ),
                        "candidate_fix": (
                            "Add drawdown-aware single-name and industry caps to the event target book, "
                            "and require staged re-entry after DEFENSE_REVIEW/CRISIS_DEFENSE before the name "
                            "can be restored to full target weight."
                        ),
                    }
                )
            avg_cash = 0.0
            if not equity.empty and "cash_weight" in equity.columns and mdd_info:
                eq = equity.copy()
                eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
                window = eq[(eq["date"] >= pd.Timestamp(mdd_info["peak_date"])) & (eq["date"] <= pd.Timestamp(mdd_info["trough_date"]))]
                avg_cash = float(pd.to_numeric(window.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean()) if not window.empty else 0.0
            if drawdown_pct <= -25.0 and avg_cash < 0.20:
                findings.append(
                    {
                        "finding_id": f"F7_mdd_window_under_hedged_{portfolio_kind}",
                        "severity": "high",
                        "evidence": (
                            f"MDD was {drawdown_pct:.2f}% while average cash inside the peak-to-trough "
                            f"window was only {avg_cash:.1%}. Broker trade window had "
                            f"{trade_window.get('trade_count', 0)} executions and net cash delta "
                            f"${safe_float(trade_window.get('net_cash_delta_usd')):,.0f}."
                        ),
                        "candidate_fix": (
                            "Convert daily crisis states into broker-fillable target-book cash rows. "
                            "Use hysteresis and a re-entry delay so raised cash is not redeployed immediately."
                        ),
                    }
                )
            findings.extend(target_bucket_findings(portfolio_kind, target_context, policy_buckets))
            payload = {
                "schema_version": SCHEMA_VERSION,
                "portfolio_kind": portfolio_kind,
                "status": "completed",
                "analysis_mode": "broker_ledger_trades_holdings_fallback",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "broker_metrics_summary": {
                    "cagr": metrics.get("cagr"),
                    "sharpe": metrics.get("sharpe"),
                    "max_dd": metrics.get("max_dd"),
                    "trade_count": metrics.get("trade_count"),
                    "total_fees_usd": metrics.get("total_fees_usd"),
                },
                "trade_pnl_distribution": {
                    "round_trip_count": 0,
                    "winners_count": 0,
                    "losers_count": 0,
                    "win_rate": None,
                    "avg_winner_usd": None,
                    "avg_loser_usd": None,
                    "total_winner_usd": None,
                    "total_loser_usd": None,
                    "note": "round-trip journal missing; using broker execution and holdings_daily fallback",
                },
                "mdd_window": {
                    **mdd_info,
                    "broker_trades_in_window": trade_window,
                    "top_position_pnl_contributors": contributors[:15],
                },
                "mdd_target_context": {
                    "target_book": str(target_book_file(latest_run, portfolio_kind)),
                    "lookback_days_before_peak": 45,
                    "covered_ticker_count": len(target_context),
                    "target_row_count": int(len(target_rows)),
                    "top_context_by_ticker": target_context[:20],
                    "policy_buckets": policy_buckets[:12],
                },
                "loss_by_sector": sector_loss,
                "loss_by_industry_group": industry_loss,
                "top_10_losers": contributors[:10],
                "top_10_winners": [],
                "findings": findings,
                "research_only": True,
                "production_activation_allowed": False,
            }
            out_dir = output_dir / portfolio_kind
            write_json(out_dir / "findings.json", payload)
            pd.DataFrame(contributors).to_csv(out_dir / "mdd_position_pnl_by_ticker.csv", index=False)
            if not target_rows.empty:
                target_rows.to_csv(out_dir / "mdd_target_rows.csv", index=False)
            if target_context:
                pd.DataFrame(target_context).to_csv(out_dir / "mdd_target_context_by_ticker.csv", index=False)
            if policy_buckets:
                pd.DataFrame(policy_buckets).to_csv(out_dir / "mdd_policy_bucket_summary.csv", index=False)
            write_text(out_dir / "attribution_report.md", render_report(payload))
            return payload
        return {
            "portfolio_kind": portfolio_kind,
            "status": "blocked",
            "reason": "no usable P&L column in trade journal",
            "broker_metrics_summary": {
                "cagr": metrics.get("cagr"),
                "sharpe": metrics.get("sharpe"),
                "max_dd": metrics.get("max_dd"),
            },
        }
    trade_journal[pnl_col] = pd.to_numeric(trade_journal[pnl_col], errors="coerce").fillna(0.0)
    losers = trade_journal[trade_journal[pnl_col] < 0].copy()
    winners = trade_journal[trade_journal[pnl_col] > 0].copy()
    mdd_info = mdd_window(equity)
    in_window = trades_in_window(trade_journal, mdd_info.get("peak_date", ""), mdd_info.get("trough_date", ""), pnl_col) if mdd_info else {}
    metadata = target_metadata(latest_run, portfolio_kind)
    trade_window = broker_trades_in_window(broker_trades, mdd_info.get("peak_date", ""), mdd_info.get("trough_date", "")) if mdd_info else {}
    contributors, sector_loss, industry_loss = holdings_pnl_contributors(
        holdings,
        mdd_info.get("peak_date", ""),
        mdd_info.get("trough_date", ""),
        metadata,
    ) if mdd_info else ([], {}, {})
    target_rows = mdd_target_rows(latest_run, portfolio_kind, mdd_info, contributors)
    target_context = summarize_target_context(target_rows)
    policy_buckets = mdd_policy_bucket_summary(target_rows)
    loss_by_regime = loss_by_group(losers, "entry_regime_state", pnl_col)
    loss_by_exit_reason = loss_by_group(losers, "exit_reason", pnl_col)

    findings = build_findings(
        portfolio_kind=portfolio_kind,
        metrics=metrics,
        mdd_info=mdd_info,
        in_window=in_window,
        trade_journal=trade_journal,
        pnl_col=pnl_col,
        losers=losers,
        winners=winners,
        loss_by_regime=loss_by_regime,
        loss_by_exit_reason=loss_by_exit_reason,
    )
    findings.extend(target_bucket_findings(portfolio_kind, target_context, policy_buckets))

    win_rate = float(len(winners) / max(len(winners) + len(losers), 1))
    avg_winner = float(winners[pnl_col].mean()) if not winners.empty else 0.0
    avg_loser = float(losers[pnl_col].mean()) if not losers.empty else 0.0
    payload = {
        "schema_version": SCHEMA_VERSION,
        "portfolio_kind": portfolio_kind,
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "broker_metrics_summary": {
            "cagr": metrics.get("cagr"),
            "sharpe": metrics.get("sharpe"),
            "max_dd": metrics.get("max_dd"),
            "trade_count": metrics.get("trade_count"),
            "total_fees_usd": metrics.get("total_fees_usd"),
        },
        "trade_pnl_distribution": {
            "round_trip_count": int(len(trade_journal)),
            "winners_count": int(len(winners)),
            "losers_count": int(len(losers)),
            "win_rate": win_rate,
            "avg_winner_usd": avg_winner,
            "avg_loser_usd": avg_loser,
            "total_winner_usd": float(winners[pnl_col].sum()) if not winners.empty else 0.0,
            "total_loser_usd": float(losers[pnl_col].sum()) if not losers.empty else 0.0,
        },
        "mdd_window": {
            **mdd_info,
            "trades_exited_in_window": in_window.get("exit_count", 0),
            "trades_exited_pnl_usd": in_window.get("exit_pnl_usd", 0.0),
            "worst_5_exits_in_window": in_window.get("worst_5_exits", []),
            "broker_trades_in_window": trade_window,
            "top_position_pnl_contributors": contributors[:15],
        },
        "mdd_target_context": {
            "target_book": str(target_book_file(latest_run, portfolio_kind)),
            "lookback_days_before_peak": 45,
            "covered_ticker_count": len(target_context),
            "target_row_count": int(len(target_rows)),
            "top_context_by_ticker": target_context[:20],
            "policy_buckets": policy_buckets[:12],
        },
        "loss_by_regime": loss_by_regime,
        "loss_by_exit_reason": loss_by_exit_reason,
        "loss_by_sector": sector_loss,
        "loss_by_industry_group": industry_loss,
        "top_10_losers": worst_n(trade_journal, pnl_col, 10),
        "top_10_winners": best_n(trade_journal, pnl_col, 10),
        "findings": findings,
        "research_only": True,
        "production_activation_allowed": False,
    }
    out_dir = output_dir / portfolio_kind
    write_json(out_dir / "findings.json", payload)
    if contributors:
        pd.DataFrame(contributors).to_csv(out_dir / "mdd_position_pnl_by_ticker.csv", index=False)
    if not target_rows.empty:
        target_rows.to_csv(out_dir / "mdd_target_rows.csv", index=False)
    if target_context:
        pd.DataFrame(target_context).to_csv(out_dir / "mdd_target_context_by_ticker.csv", index=False)
    if policy_buckets:
        pd.DataFrame(policy_buckets).to_csv(out_dir / "mdd_policy_bucket_summary.csv", index=False)
    write_text(out_dir / "attribution_report.md", render_report(payload))
    return payload


def render_report(payload: dict[str, Any]) -> str:
    findings = payload.get("findings") or []
    mdd = payload.get("mdd_window") or {}
    pnl = payload.get("trade_pnl_distribution") or {}
    metrics = payload.get("broker_metrics_summary") or {}
    lines = [
        f"# Trade Attribution Report - {payload.get('portfolio_kind')}",
        "",
        f"- Generated: {payload.get('generated_at_utc')}",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Analysis mode: `{payload.get('analysis_mode', 'round_trip_journal')}`",
        "",
        "## Broker-Ledger Headline",
        "",
        f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
        f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
        f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
        f"- Trade count: {int(safe_float(metrics.get('trade_count')))}",
        "",
        "## Win/Loss Distribution",
        "",
        f"- Round trips: {pnl.get('round_trip_count', 0)}",
        f"- Win rate: {safe_float(pnl.get('win_rate')):.1%}",
        f"- Avg winner: ${safe_float(pnl.get('avg_winner_usd')):,.0f}",
        f"- Avg loser: ${safe_float(pnl.get('avg_loser_usd')):,.0f}",
        f"- Total winners P&L: ${safe_float(pnl.get('total_winner_usd')):,.0f}",
        f"- Total losers P&L: ${safe_float(pnl.get('total_loser_usd')):,.0f}",
        "",
        "## MDD Window",
        "",
        f"- Peak: {mdd.get('peak_date')}, ${safe_float(mdd.get('peak_equity_usd')):,.0f}",
        f"- Trough: {mdd.get('trough_date')}, ${safe_float(mdd.get('trough_equity_usd')):,.0f}",
        f"- Drawdown: {safe_float(mdd.get('drawdown_pct')):.2f}%",
        f"- Trades exited inside window: {mdd.get('trades_exited_in_window')} (total P&L ${safe_float(mdd.get('trades_exited_pnl_usd')):,.0f})",
        "",
    ]
    broker_window = mdd.get("broker_trades_in_window") if isinstance(mdd, dict) else None
    if isinstance(broker_window, dict) and broker_window:
        lines.extend(
            [
                "## Broker Trades In MDD Window",
                "",
                f"- Executions: {broker_window.get('trade_count', 0)}",
                f"- Buys / sells: {broker_window.get('buy_count', 0)} / {broker_window.get('sell_count', 0)}",
                f"- Gross traded: ${safe_float(broker_window.get('gross_value_usd')):,.0f}",
                f"- Net cash delta: ${safe_float(broker_window.get('net_cash_delta_usd')):,.0f}",
                "",
            ]
        )
    contributors = mdd.get("top_position_pnl_contributors") if isinstance(mdd, dict) else None
    if isinstance(contributors, list) and contributors:
        lines.extend(
            [
                "## Top Position P&L Contributors",
                "",
                "| Ticker | P&L | Avg weight | Max weight | Days held |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in contributors[:10]:
            lines.append(
                "| {ticker} | ${pnl:,.0f} | {avg:.1%} | {maxw:.1%} | {days} |".format(
                    ticker=row.get("ticker", ""),
                    pnl=safe_float(row.get("position_pnl_usd")),
                    avg=safe_float(row.get("avg_weight")),
                    maxw=safe_float(row.get("max_weight")),
                    days=int(safe_float(row.get("days_held"))),
                )
            )
        lines.append("")
    target_context = payload.get("mdd_target_context") or {}
    buckets = target_context.get("policy_buckets") or []
    if isinstance(buckets, list) and buckets:
        lines.extend(
            [
                "## MDD Target-Book Feature Buckets",
                "",
                "| Bucket | Linked P&L | Tickers | Avg weight | Max weight | Top tickers |",
                "| --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in buckets[:8]:
            lines.append(
                "| {bucket} | ${pnl:,.0f} | {count} | {avg:.1%} | {maxw:.1%} | {tickers} |".format(
                    bucket=row.get("bucket_id", ""),
                    pnl=safe_float(row.get("linked_mdd_position_pnl_usd")),
                    count=int(safe_float(row.get("ticker_count"))),
                    avg=safe_float(row.get("avg_weight")),
                    maxw=safe_float(row.get("max_weight")),
                    tickers=", ".join((row.get("tickers") or [])[:8]),
                )
            )
        lines.append("")
    context_rows = target_context.get("top_context_by_ticker") or []
    if isinstance(context_rows, list) and context_rows:
        lines.extend(
            [
                "## MDD Target-Book Context By Ticker",
                "",
                "| Ticker | Linked P&L | Date range | Rows | Max weight | Lane | Regime |",
                "| --- | ---: | --- | ---: | ---: | --- | --- |",
            ]
        )
        for row in context_rows[:10]:
            lines.append(
                "| {ticker} | ${pnl:,.0f} | {start} to {end} | {rows} | {maxw:.1%} | {lane} | {regime} |".format(
                    ticker=row.get("ticker", ""),
                    pnl=safe_float(row.get("linked_mdd_position_pnl_usd")),
                    start=row.get("first_rebalance_date", ""),
                    end=row.get("last_rebalance_date", ""),
                    rows=int(safe_float(row.get("target_row_count"))),
                    maxw=safe_float(row.get("max_weight")),
                    lane=row.get("primary_lane", ""),
                    regime=row.get("regime_capacity_regime") or row.get("regime_state") or "",
                )
            )
        lines.append("")
    if findings:
        lines.append("## Findings (machine-readable in findings.json)")
        lines.append("")
        for f in findings:
            lines.append(f"### [{f['severity'].upper()}] `{f['finding_id']}`")
            lines.append("")
            lines.append(f"**Evidence**: {f['evidence']}")
            lines.append("")
            lines.append(f"**Candidate fix**: {f['candidate_fix']}")
            lines.append("")
    else:
        lines.extend(["## Findings", "", "None at current severity thresholds.", ""])
    lines.append("Research-only analysis. Production decisions still require broker-ledger and human review.")
    lines.append("")
    return "\n".join(lines)


def run(
    *,
    latest_run: Path,
    output_dir: Path,
    portfolios: list[str],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    portfolio_reports = {}
    all_findings: list[dict[str, Any]] = []
    for kind in portfolios:
        report = analyze_portfolio(latest_run=latest_run, portfolio_kind=kind, output_dir=output_dir)
        portfolio_reports[kind] = report
        if report.get("status") == "completed":
            for finding in report.get("findings") or []:
                all_findings.append({"portfolio_kind": kind, **finding})
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "portfolios": portfolio_reports,
        "all_findings": all_findings,
        "high_severity_count": sum(1 for f in all_findings if f.get("severity") == "high"),
        "medium_severity_count": sum(1 for f in all_findings if f.get("severity") == "medium"),
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="cloud_results/full_rebuild/latest_global_alpha_universe")
    parser.add_argument("--output-dir", default="outputs/trade_attribution")
    parser.add_argument("--portfolios", nargs="+", default=["main", "concentrated"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(
        latest_run=repo_path(args.latest_run),
        output_dir=repo_path(args.output_dir),
        portfolios=args.portfolios,
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "portfolios"}, indent=2, default=str))
    completed = [p for p in summary["portfolios"].values() if p.get("status") == "completed"]
    return 0 if completed else 2


if __name__ == "__main__":
    raise SystemExit(main())
