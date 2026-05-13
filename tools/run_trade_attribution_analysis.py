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


def yearly_cagr_from_equity(equity_df: pd.DataFrame) -> dict[str, Any]:
    """Decompose CAGR by calendar year. Partial years are annualized.

    Answers the question: did the headline CAGR come from a few outlier
    years or is it broadly distributed? A point estimate of ``28.91%``
    over 7 years means different things if the per-year split is
    `{2020:45, 2021:35, 2022:-5, 2023:40, 2024:28, 2025:42}` vs
    `{2020:100, 2021:5, 2022:5, ...}`.
    """
    if equity_df.empty or "date" not in equity_df.columns or "equity_usd" not in equity_df.columns:
        return {}
    eq = equity_df.copy()
    eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
    eq = eq.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    eq["year"] = eq["date"].dt.year
    out: dict[str, Any] = {}
    for year, sub in eq.groupby("year"):
        if len(sub) < 5:
            continue
        start_eq = float(sub["equity_usd"].iloc[0])
        end_eq = float(sub["equity_usd"].iloc[-1])
        if start_eq <= 0:
            continue
        n_days = int(len(sub))
        ret = end_eq / start_eq - 1.0
        if n_days >= 252:
            cagr = ret
        elif n_days > 1:
            cagr = (1.0 + ret) ** (252.0 / n_days) - 1.0
        else:
            cagr = ret
        out[str(int(year))] = {
            "yearly_return": float(ret),
            "annualized_cagr": float(cagr),
            "days_observed": n_days,
            "start_equity_usd": start_eq,
            "end_equity_usd": end_eq,
        }
    return out


def build_regime_calendar(latest_run: Path, portfolio_kind: str) -> dict[pd.Timestamp, str]:
    """Build {rebalance_date -> dominant regime} map from the operating
    book. Concentrated books usually have null regime_state; fall back
    to the main book in that case so the calendar still resolves.
    """
    # Concentrated books often have regime_state null on ~all rows
    # (the source `concentrated_strategy_holdings.csv` does not carry
    # the engine's regime label). Try the portfolio's own book first,
    # but fall through to the main book when the own book yields a
    # near-empty calendar so concentrated analyses inherit main's
    # market-wide regime signal.
    candidates = [
        latest_run / "reports" / f"operating_{portfolio_kind}_target_book.csv",
        latest_run / "reports" / "operating_main_target_book.csv",
    ]
    best: dict[pd.Timestamp, str] = {}
    for path in candidates:
        if not path.exists():
            continue
        try:
            book = pd.read_csv(path, low_memory=False, usecols=["rebalance_date", "regime_state"])
        except Exception:
            continue
        if "regime_state" not in book.columns or "rebalance_date" not in book.columns:
            continue
        book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce")
        book = book.dropna(subset=["rebalance_date"])
        out: dict[pd.Timestamp, str] = {}
        for date, sub in book.groupby("rebalance_date"):
            labels = sub["regime_state"].dropna().astype(str).str.strip().str.lower()
            labels = labels[labels != ""]
            if labels.empty:
                continue
            mode = labels.mode()
            if mode.empty:
                continue
            out[pd.Timestamp(date)] = str(mode.iloc[0])
        if len(out) > len(best):
            best = out
        # Heuristic: a usable calendar needs more than ~10 dates. Some
        # books carry a stray non-null regime row from the latest target
        # snapshot which alone is not enough.
        if len(best) >= 10:
            return best
    return best


def regime_for_date(date: pd.Timestamp, regime_calendar: dict[pd.Timestamp, str]) -> str:
    """Return the regime label active on ``date`` (most recent
    rebalance_date on or before). Returns 'unknown' before the calendar
    starts.
    """
    if not regime_calendar:
        return "unknown"
    keys = sorted(regime_calendar.keys())
    target = pd.Timestamp(date)
    pos = -1
    for i, k in enumerate(keys):
        if k <= target:
            pos = i
        else:
            break
    if pos < 0:
        return "unknown"
    return regime_calendar.get(keys[pos], "unknown")


def cagr_by_regime_from_equity(
    equity_df: pd.DataFrame,
    regime_calendar: dict[pd.Timestamp, str],
) -> dict[str, Any]:
    """Decompose CAGR by regime label. Days where the engine labeled the
    market `bull` vs `bear` etc. are pooled separately; geometric mean
    daily return per regime is annualized.

    Answers the question: in which regime does this portfolio earn its
    return? If `cagr_by_regime["bull"]` is the only positive bucket,
    the strategy is a bull-market beta player. If `bear` is also
    positive, real defensive alpha exists.
    """
    if equity_df.empty or not regime_calendar or "date" not in equity_df.columns:
        return {}
    eq = equity_df.copy()
    eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
    eq = eq.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    if len(eq) < 5:
        return {}
    eq["regime"] = eq["date"].apply(lambda d: regime_for_date(d, regime_calendar))
    eq["daily_return"] = eq["equity_usd"].pct_change().fillna(0.0)
    out: dict[str, Any] = {}
    for regime, sub in eq.groupby("regime"):
        if regime == "unknown" or len(sub) < 5:
            continue
        cumret = float((1.0 + sub["daily_return"]).prod())
        n_days = int(len(sub))
        if cumret <= 0:
            annualized = -1.0
        else:
            annualized = float(cumret ** (252.0 / max(n_days, 1)) - 1.0)
        out[str(regime)] = {
            "annualized_cagr": annualized,
            "total_return_in_regime": float(cumret - 1.0),
            "days_in_regime": n_days,
            "share_of_period": float(n_days / len(eq)),
        }
    return out


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
    pnl_col = pick_pnl_column(trade_journal)
    if pnl_col is None or trade_journal.empty:
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

    win_rate = float(len(winners) / max(len(winners) + len(losers), 1))
    avg_winner = float(winners[pnl_col].mean()) if not winners.empty else 0.0
    avg_loser = float(losers[pnl_col].mean()) if not losers.empty else 0.0
    yearly_cagr = yearly_cagr_from_equity(equity)
    regime_calendar = build_regime_calendar(latest_run, portfolio_kind)
    cagr_by_regime = cagr_by_regime_from_equity(equity, regime_calendar)
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
        "yearly_cagr": yearly_cagr,
        "cagr_by_regime": cagr_by_regime,
        "regime_calendar_size": int(len(regime_calendar)),
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
        },
        "loss_by_regime": loss_by_regime,
        "loss_by_exit_reason": loss_by_exit_reason,
        "top_10_losers": worst_n(trade_journal, pnl_col, 10),
        "top_10_winners": best_n(trade_journal, pnl_col, 10),
        "findings": findings,
        "research_only": True,
        "production_activation_allowed": False,
    }
    out_dir = output_dir / portfolio_kind
    write_json(out_dir / "findings.json", payload)
    write_text(out_dir / "attribution_report.md", render_report(payload))
    return payload


def render_report(payload: dict[str, Any]) -> str:
    findings = payload.get("findings") or []
    mdd = payload.get("mdd_window") or {}
    pnl = payload.get("trade_pnl_distribution") or {}
    metrics = payload.get("broker_metrics_summary") or {}
    lines = [
        f"# Trade Attribution Report — {payload.get('portfolio_kind')}",
        "",
        f"- Generated: {payload.get('generated_at_utc')}",
        f"- Schema: `{payload.get('schema_version')}`",
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
