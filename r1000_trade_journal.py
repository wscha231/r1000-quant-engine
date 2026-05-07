"""r1000_trade_journal - Phase 18a AlphaTrade journal foundation.

Persists per-trade entry/exit records and auto-grades them so later insight
and feature-gate tooling has a queryable training substrate. The production
backtest hook is sidecar-only: it writes outputs/trade_journal artifacts from
already-computed holdings and returns without changing portfolio metrics.

Artifacts
---------
    outputs/trade_journal/holdings_history.parquet
    outputs/trade_journal/trades.parquet
    outputs/trade_journal/grades.parquet
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd


# Phase 14 + 17 signals captured in entry_signal_breakdown JSON.
# Order matters for downstream JSON-key sorting. Keep in sync with
# r1000_config.PHASE14_HYBRID_ALPHA_COLUMNS + PHASE17_EXPLOSION_COLUMNS.
SIGNAL_BREAKDOWN_COLUMNS: tuple[str, ...] = (
    "rs_acceleration_score",
    "h1_oversold_value_score",
    "h6_dynamic_leader_score",
    "stage2_overext_penalty",
    "theme_phase_multiplier_primary",
    "theme_phase_multiplier_max",
    "explosion_entry_score",
    "explosion_exit_score",
    "explosion_net_score",
)

# Grade rule thresholds (18a defaults; tuned in 18b)
GRADE_WIN_RETURN = 0.05
GRADE_WIN_ALPHA = 0.02
GRADE_LOSS_RETURN = -0.10
GRADE_TRAP_RETURN = -0.20
GRADE_TRAP_HOLD_DAYS = 60
GRADE_GOOD_EXIT_ALPHA_QUANTILE = 0.75


# =====================================================================
# Hook A - capture entry signal breakdown when holdings_rows.append
# =====================================================================

def attach_signal_breakdown(
    month_df: pd.DataFrame,
    ticker: str,
    extra_cols: Optional[Iterable[str]] = None,
) -> dict:
    """Build the JSON-friendly dict of Phase 14/17 signal contributions
    for a single ticker at one rebalance date.

    Returns
    -------
    dict with float values keyed by signal name. Missing columns -> 0.0.
    """
    cols = list(SIGNAL_BREAKDOWN_COLUMNS) + list(extra_cols or [])
    if month_df is None or month_df.empty or "ticker" not in month_df.columns:
        return {c: 0.0 for c in cols}
    row = month_df.loc[month_df["ticker"].astype(str) == str(ticker)]
    if row.empty:
        return {c: 0.0 for c in cols}
    out: dict[str, float] = {}
    for c in cols:
        if c in row.columns:
            v = pd.to_numeric(row[c].iloc[0], errors="coerce")
            out[c] = float(v) if pd.notna(v) else 0.0
        else:
            out[c] = 0.0
    return out


def regime_at_row(month_df: pd.DataFrame, ticker: str) -> tuple[str, int]:
    """Return (regime_state, regime_state_score) for a single ticker
    row in month_df. Defaults to ('neutral', 0) if columns are missing."""
    if month_df is None or month_df.empty or "ticker" not in month_df.columns:
        return ("neutral", 0)
    row = month_df.loc[month_df["ticker"].astype(str) == str(ticker)]
    if row.empty:
        return ("neutral", 0)
    state = row["regime_state"].iloc[0] if "regime_state" in row.columns else "neutral"
    score = row["regime_state_score"].iloc[0] if "regime_state_score" in row.columns else 0
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0
    return (str(state) if pd.notna(state) else "neutral", score)


# =====================================================================
# Persistence - holdings_history.parquet
# =====================================================================

def persist_holdings_history(
    holdings_df: pd.DataFrame,
    paths: dict,
    engine_version: str,
) -> Optional[Path]:
    """Write the per-month holdings frame to outputs/trade_journal/.

    Parameters
    ----------
    holdings_df : DataFrame produced by backtest_portfolio (must contain
                  rebalance_date, ticker, weight, raw_score, sleeve cols,
                  period_forward_return). Optional cols populated by
                  attach_signal_breakdown: entry_signal_breakdown,
                  regime_state, regime_state_score.
    paths       : run-paths dict from prepare_run_paths (must have 'outputs').
    engine_version : ENGINE_REUSE_VERSION at time of run; tagged on every row.
    """
    if holdings_df is None or holdings_df.empty:
        return None
    out_dir = Path(paths.get("outputs", "outputs")) / "trade_journal"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = holdings_df.copy()
    df["engine_version"] = str(engine_version)

    # Normalize: ensure entry_signal_breakdown is JSON string, not dict
    if "entry_signal_breakdown" in df.columns:
        df["entry_signal_breakdown"] = df["entry_signal_breakdown"].apply(
            lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list)) else (v if isinstance(v, str) else "{}")
        )
    else:
        df["entry_signal_breakdown"] = "{}"

    if "regime_state" not in df.columns:
        df["regime_state"] = "neutral"
    if "regime_state_score" not in df.columns:
        df["regime_state_score"] = 0

    # Stable column order - required cols first, then any extras
    required = [
        "rebalance_date", "ticker", "weight", "raw_score",
        "portfolio_sleeve_label", "portfolio_sleeve_role",
        "portfolio_selection_path",
        "period_forward_return", "weighted_forward_return",
        "target_n",
        "entry_signal_breakdown",
        "regime_state", "regime_state_score",
        "engine_version",
    ]
    missing = [c for c in required if c not in df.columns]
    for c in missing:
        df[c] = np.nan
    extras = [c for c in df.columns if c not in required]
    df = df[required + extras]

    parquet_path = out_dir / "holdings_history.parquet"
    df.to_parquet(parquet_path, index=False)
    df.to_csv(out_dir / "holdings_history.csv", index=False)
    return parquet_path


# =====================================================================
# Pairing - entry/exit round-trip detection
# =====================================================================

def pair_entries_with_exits(
    holdings_df: pd.DataFrame,
    paths: dict,
    engine_version: str,
    benchmark_returns: Optional[pd.DataFrame] = None,
) -> Optional[pd.DataFrame]:
    """Walk monthly holdings to pair each entry with the rebalance at
    which the position is exited (no longer in current_w).

    A trade is opened when ticker first appears in a contiguous block
    of months and closed when the block ends. Each round-trip becomes
    one row in trades.parquet.

    Stop-loss / trailing exits aren't surfaced in 18a (they're consumed
    inside backtest_portfolio without writing back to holdings_rows);
    18a tags those exits as `exit_reason='dropped_from_topk'` since the
    visible signature is identical from the holdings_df viewpoint.

    Benchmark return per trade is computed from `benchmark_returns`
    DataFrame if supplied (must have rebalance_date + bench_return).
    """
    if holdings_df is None or holdings_df.empty:
        return None

    df = holdings_df.copy()
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce")
    df = df.dropna(subset=["rebalance_date", "ticker"]).sort_values(["ticker", "rebalance_date"])

    # Detect contiguous holding blocks per ticker. Use the rebalance
    # cadence (≈ monthly) to define adjacency: gap > 45 days -> new block.
    trades: list[dict] = []
    for ticker, grp in df.groupby("ticker", sort=False):
        grp = grp.sort_values("rebalance_date").reset_index(drop=True)
        if grp.empty:
            continue
        block_start_idx = 0
        for i in range(1, len(grp)):
            gap = (grp["rebalance_date"].iloc[i] - grp["rebalance_date"].iloc[i - 1]).days
            if gap > 45:
                trades.append(_build_trade_row(ticker, grp.iloc[block_start_idx:i], engine_version))
                block_start_idx = i
        trades.append(_build_trade_row(ticker, grp.iloc[block_start_idx:], engine_version))

    if not trades:
        return None

    trades_df = pd.DataFrame([t for t in trades if t is not None])
    if trades_df.empty:
        return None

    # Compute benchmark return per trade window
    if benchmark_returns is not None and not benchmark_returns.empty:
        trades_df["benchmark_return_same_period"] = trades_df.apply(
            lambda r: _bench_window_return(benchmark_returns, r["entry_date"], r["exit_date"]),
            axis=1,
        )
    else:
        trades_df["benchmark_return_same_period"] = np.nan
    trades_df["alpha_vs_benchmark"] = (
        pd.to_numeric(trades_df["realized_return"], errors="coerce")
        - pd.to_numeric(trades_df["benchmark_return_same_period"], errors="coerce")
    )

    out_dir = Path(paths.get("outputs", "outputs")) / "trade_journal"
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "trades.parquet"
    trades_df.to_parquet(parquet_path, index=False)
    trades_df.to_csv(out_dir / "trades.csv", index=False)
    return trades_df


def _build_trade_row(ticker: str, block: pd.DataFrame, engine_version: str) -> Optional[dict]:
    """Build a single trade row from a contiguous holding block.

    realized_return is the compound product of monthly period_forward_return
    over the block (excluding the final exit month, which has 0 by
    construction since the position was already closed by then).
    """
    if block is None or block.empty:
        return None
    rets = pd.to_numeric(block["period_forward_return"], errors="coerce").fillna(0.0).to_numpy()
    realized = float(np.prod(1.0 + rets) - 1.0) if len(rets) else 0.0
    holding_days = int((block["rebalance_date"].iloc[-1] - block["rebalance_date"].iloc[0]).days)
    # entry_signal_breakdown taken from the FIRST holding row in block
    breakdown = block["entry_signal_breakdown"].iloc[0] if "entry_signal_breakdown" in block.columns else "{}"
    if isinstance(breakdown, dict):
        breakdown = json.dumps(breakdown, default=str)
    elif not isinstance(breakdown, str):
        breakdown = "{}"
    return {
        "trade_id": str(uuid.uuid4()),
        "ticker": str(ticker),
        "entry_date": block["rebalance_date"].iloc[0],
        "exit_date": block["rebalance_date"].iloc[-1],
        "entry_score": float(block["raw_score"].iloc[0]) if "raw_score" in block.columns else np.nan,
        "entry_sleeve": str(block["portfolio_sleeve_label"].iloc[0]) if "portfolio_sleeve_label" in block.columns else "",
        "entry_regime_state": str(block["regime_state"].iloc[0]) if "regime_state" in block.columns else "neutral",
        "entry_signal_breakdown": breakdown,
        "exit_reason": "scheduled_rebalance" if len(block) > 1 else "single_period_hold",
        "holding_days": holding_days,
        "n_periods": int(len(block)),
        "realized_return": realized,
        "engine_version": str(engine_version),
    }


def _bench_window_return(
    benchmark_returns: pd.DataFrame,
    entry_date: pd.Timestamp,
    exit_date: pd.Timestamp,
) -> float:
    if benchmark_returns is None or benchmark_returns.empty:
        return float("nan")
    df = benchmark_returns.copy()
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce")
    mask = (df["rebalance_date"] >= entry_date) & (df["rebalance_date"] <= exit_date)
    rets = pd.to_numeric(df.loc[mask, "bench_return"], errors="coerce").fillna(0.0).to_numpy()
    if len(rets) == 0:
        return float("nan")
    return float(np.prod(1.0 + rets) - 1.0)


# =====================================================================
# Grading - auto-label each trade
# =====================================================================

def grade_trades(
    trades_df: pd.DataFrame,
    paths: dict,
) -> Optional[pd.DataFrame]:
    """Apply 18a grade rules to each trade row.

    Returns a small DataFrame keyed by trade_id with grade_label +
    grade_reason. Persists to outputs/trade_journal/grades.parquet.
    """
    if trades_df is None or trades_df.empty:
        return None
    df = trades_df.copy()
    realized = pd.to_numeric(df["realized_return"], errors="coerce").fillna(0.0)
    alpha = pd.to_numeric(df.get("alpha_vs_benchmark"), errors="coerce")
    holding = pd.to_numeric(df.get("holding_days", 0), errors="coerce").fillna(0)

    # Quantile threshold for GOOD_EXIT - top 25% alpha among winners
    good_alpha_cut = float(alpha[realized > 0].quantile(GRADE_GOOD_EXIT_ALPHA_QUANTILE)) if alpha.notna().any() else float("inf")

    labels: list[str] = []
    reasons: list[str] = []
    for r, a, h in zip(realized, alpha, holding):
        if pd.notna(r) and r <= GRADE_TRAP_RETURN and h >= GRADE_TRAP_HOLD_DAYS:
            labels.append("TRAP")
            reasons.append(f"realized={r:+.2%} held {int(h)}d")
        elif pd.notna(r) and r <= GRADE_LOSS_RETURN:
            labels.append("LOSS")
            reasons.append(f"realized={r:+.2%}")
        elif pd.notna(r) and r >= GRADE_WIN_RETURN and pd.notna(a) and a >= GRADE_WIN_ALPHA:
            if pd.notna(a) and a >= good_alpha_cut:
                labels.append("GOOD_EXIT")
                reasons.append(f"realized={r:+.2%} alpha={a:+.2%} (top quartile)")
            else:
                labels.append("WIN")
                reasons.append(f"realized={r:+.2%} alpha={a:+.2%}")
        else:
            labels.append("NEUTRAL")
            reasons.append(f"realized={r:+.2%}")

    grades = pd.DataFrame({
        "trade_id": df["trade_id"],
        "ticker": df["ticker"],
        "grade_label": labels,
        "grade_reason": reasons,
        "realized_return": realized,
        "alpha_vs_benchmark": alpha,
        "holding_days": holding.astype(int),
        "regime_at_entry": df.get("entry_regime_state", "neutral"),
        "entry_sleeve": df.get("entry_sleeve", ""),
    })

    out_dir = Path(paths.get("outputs", "outputs")) / "trade_journal"
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / "grades.parquet"
    grades.to_parquet(parquet_path, index=False)
    grades.to_csv(out_dir / "grades.csv", index=False)
    return grades


def summary_digest(grades_df: pd.DataFrame) -> dict:
    """Compact dict of grade counts + notable wins/losses for logging
    or Telegram digest."""
    if grades_df is None or grades_df.empty:
        return {"n_trades": 0}
    counts = grades_df["grade_label"].value_counts().to_dict()
    by_regime = (
        grades_df.groupby(["regime_at_entry", "grade_label"]).size().unstack(fill_value=0).to_dict(orient="index")
        if "regime_at_entry" in grades_df.columns else {}
    )
    realized = pd.to_numeric(grades_df["realized_return"], errors="coerce")
    return {
        "n_trades": int(len(grades_df)),
        "label_counts": {str(k): int(v) for k, v in counts.items()},
        "by_regime": by_regime,
        "win_rate": float((grades_df["grade_label"].isin({"WIN", "GOOD_EXIT"})).mean()),
        "loss_rate": float((grades_df["grade_label"].isin({"LOSS", "TRAP"})).mean()),
        "mean_realized": float(realized.mean()) if realized.notna().any() else None,
        "median_realized": float(realized.median()) if realized.notna().any() else None,
        "top_wins": grades_df.nlargest(5, "realized_return")[["ticker", "realized_return", "grade_label"]].to_dict(orient="records"),
        "top_losses": grades_df.nsmallest(5, "realized_return")[["ticker", "realized_return", "grade_label"]].to_dict(orient="records"),
    }
