#!/usr/bin/env python3
"""Report-only historical winner onset study.

This tool mines historical price curves for "major winner onset" events:
dates where a stock was starting a move that later became a multi-month,
multi-bagger advance. It is intentionally ticker-agnostic. The CLI can take a
latest scored universe or an explicit ticker list, but no ticker is special.

Outputs
-------
    outputs/winner_onset_study/events.csv
    outputs/winner_onset_study/phase_snapshots.csv
    outputs/winner_onset_study/hold_diagnostics.csv
    outputs/winner_onset_study/pattern_summary.json
    outputs/winner_onset_study/winner_onset_report.md
    outputs/winner_onset_study/system_policy_candidates.yaml

The policy file is proposal-only and must never be wired into production
without a real historical challenger replay and explicit approval.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "winner_onset_study"

PHASE_OFFSETS_MONTHS = [-6, -3, -1, 0, 1, 3, 6]
TRADING_DAYS_PER_MONTH = 21
DEFAULT_CASH_TICKERS = {"CASH", "BIL", "SGOV", "SHV", "TBIL"}


@dataclass
class OnsetEvent:
    ticker: str
    onset_date: str
    peak_date: str
    onset_price: float
    peak_price: float
    peak_return_12m: float
    forward_3m_return: float
    forward_6m_return: float
    forward_12m_return: float
    max_drawdown_first_3m: float
    days_to_peak: int
    entry_readiness_score: float
    onset_mom_1m: float
    onset_mom_3m: float
    onset_mom_6m: float
    onset_rs_vs_spy_3m: float
    onset_rs_vs_spy_6m: float
    onset_volume_surge: float
    onset_price_vs_sma50: float
    onset_price_vs_sma200: float
    onset_dist_52w_high: float
    onset_breakout_63d: int


def finite_float(value, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def safe_return(close: pd.Series, idx: int, days: int) -> float:
    j = idx - days
    if j < 0 or idx < 0 or idx >= len(close):
        return float("nan")
    p0 = finite_float(close.iloc[j])
    p1 = finite_float(close.iloc[idx])
    if not (p0 > 0 and p1 > 0):
        return float("nan")
    return p1 / p0 - 1.0


def forward_return(close: pd.Series, idx: int, days: int) -> float:
    j = idx + days
    if idx < 0 or j >= len(close):
        return float("nan")
    p0 = finite_float(close.iloc[idx])
    p1 = finite_float(close.iloc[j])
    if not (p0 > 0 and p1 > 0):
        return float("nan")
    return p1 / p0 - 1.0


def max_forward_return(close: pd.Series, idx: int, days: int) -> tuple[float, int]:
    if idx < 0 or idx + 1 >= len(close):
        return float("nan"), -1
    end = min(len(close), idx + days + 1)
    future = close.iloc[idx + 1:end]
    if future.empty:
        return float("nan"), -1
    p0 = finite_float(close.iloc[idx])
    if p0 <= 0:
        return float("nan"), -1
    rel = future / p0 - 1.0
    peak_pos = int(np.nanargmax(rel.to_numpy(dtype=float)))
    return finite_float(rel.iloc[peak_pos]), idx + 1 + peak_pos


def max_drawdown_between(close: pd.Series, start_idx: int, end_idx: int) -> float:
    start_idx = max(0, start_idx)
    end_idx = min(len(close) - 1, end_idx)
    if end_idx <= start_idx:
        return float("nan")
    window = close.iloc[start_idx:end_idx + 1].astype(float)
    if window.empty:
        return float("nan")
    dd = window / window.cummax() - 1.0
    return finite_float(dd.min())


def normalize_history(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["close", "volume"])
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]) for c in df.columns]
    rename = {}
    for col in df.columns:
        low = str(col).lower().strip()
        if low in {"close", "adj close", "adj_close"}:
            rename[col] = "close"
        elif low == "volume":
            rename[col] = "volume"
    df = df.rename(columns=rename)
    if "close" not in df.columns and "Close" in raw.columns:
        df["close"] = raw["Close"]
    if "volume" not in df.columns:
        df["volume"] = np.nan
    out = df[["close", "volume"]].copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    out = out.dropna(subset=["close"]).sort_index()
    return out


def fetch_history(ticker: str, start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for CLI fetching") from exc
    hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
    return normalize_history(hist)


def compute_features(hist: pd.DataFrame, idx: int, spy_hist: Optional[pd.DataFrame] = None) -> dict:
    close = hist["close"].astype(float)
    volume = hist["volume"].astype(float) if "volume" in hist else pd.Series(np.nan, index=hist.index)
    price = finite_float(close.iloc[idx])
    sma50 = finite_float(close.iloc[max(0, idx - 49):idx + 1].mean())
    sma200 = finite_float(close.iloc[max(0, idx - 199):idx + 1].mean())
    high63 = finite_float(close.iloc[max(0, idx - 62):idx + 1].max())
    high252 = finite_float(close.iloc[max(0, idx - 251):idx + 1].max())
    vol20 = finite_float(volume.iloc[max(0, idx - 19):idx + 1].mean())
    vol120 = finite_float(volume.iloc[max(0, idx - 119):idx + 1].mean())
    rets30 = close.iloc[max(0, idx - 30):idx + 1].pct_change().dropna()
    rets90 = close.iloc[max(0, idx - 90):idx + 1].pct_change().dropna()

    rs3 = rs6 = float("nan")
    if spy_hist is not None and not spy_hist.empty:
        try:
            spy_close = spy_hist["close"].astype(float)
            sp_idx = spy_close.index.get_indexer([hist.index[idx]], method="pad")[0]
            if sp_idx >= 126:
                spy3 = safe_return(spy_close, sp_idx, 63)
                spy6 = safe_return(spy_close, sp_idx, 126)
                rs3 = safe_return(close, idx, 63) - spy3
                rs6 = safe_return(close, idx, 126) - spy6
        except Exception:
            pass

    return {
        "date": str(hist.index[idx].date()),
        "price": price,
        "mom_1m": safe_return(close, idx, 21),
        "mom_3m": safe_return(close, idx, 63),
        "mom_6m": safe_return(close, idx, 126),
        "mom_12m": safe_return(close, idx, 252),
        "rs_vs_spy_3m": rs3,
        "rs_vs_spy_6m": rs6,
        "price_vs_sma50": price / sma50 - 1.0 if price > 0 and sma50 > 0 else float("nan"),
        "price_vs_sma200": price / sma200 - 1.0 if price > 0 and sma200 > 0 else float("nan"),
        "sma50_vs_sma200": sma50 / sma200 - 1.0 if sma50 > 0 and sma200 > 0 else float("nan"),
        "dist_63d_high": price / high63 - 1.0 if price > 0 and high63 > 0 else float("nan"),
        "dist_52w_high": price / high252 - 1.0 if price > 0 and high252 > 0 else float("nan"),
        "breakout_63d": int(price >= high63 * 0.99) if price > 0 and high63 > 0 else 0,
        "volume_surge": vol20 / vol120 if vol20 > 0 and vol120 > 0 else float("nan"),
        "vol_30d": finite_float(rets30.std() * math.sqrt(252)) if len(rets30) >= 10 else float("nan"),
        "vol_90d": finite_float(rets90.std() * math.sqrt(252)) if len(rets90) >= 30 else float("nan"),
        "max_dd_90d": max_drawdown_between(close, max(0, idx - 90), idx),
    }


def entry_readiness_score(features: dict) -> float:
    """Score whether this date looks like the start of a durable advance."""
    score = 0.0
    weights = 0.0

    checks = [
        (features.get("mom_1m", np.nan) >= 0.04, 0.10),
        (features.get("mom_3m", np.nan) >= 0.10, 0.15),
        (features.get("mom_3m", np.nan) <= 0.90, 0.05),
        (features.get("mom_6m", np.nan) <= 1.50, 0.05),
        (features.get("rs_vs_spy_3m", np.nan) >= 0.06, 0.15),
        (features.get("rs_vs_spy_6m", np.nan) >= 0.08, 0.10),
        (features.get("price_vs_sma50", np.nan) >= -0.03, 0.10),
        (features.get("price_vs_sma200", np.nan) >= -0.08, 0.08),
        (features.get("sma50_vs_sma200", np.nan) >= -0.05, 0.07),
        (features.get("breakout_63d", 0) == 1, 0.10),
        (features.get("volume_surge", np.nan) >= 1.05, 0.10),
        (features.get("max_dd_90d", np.nan) >= -0.30, 0.05),
    ]
    for ok, weight in checks:
        weights += weight
        if bool(ok):
            score += weight
    return score / weights if weights else 0.0


def detect_onset_events(
    ticker: str,
    hist: pd.DataFrame,
    spy_hist: Optional[pd.DataFrame] = None,
    min_peak_return_12m: float = 1.50,
    min_forward_6m: float = 0.50,
    readiness_min: float = 0.55,
    min_gap_days: int = 126,
    max_events_per_ticker: int = 3,
) -> list[OnsetEvent]:
    hist = normalize_history(hist)
    if hist.empty or len(hist) < 252 * 2:
        return []

    close = hist["close"].astype(float)
    eligible = np.zeros(len(hist), dtype=bool)
    peak_idx_for = np.full(len(hist), -1, dtype=int)
    fwd6_for = np.full(len(hist), np.nan, dtype=float)
    fwd12_for = np.full(len(hist), np.nan, dtype=float)
    max12_for = np.full(len(hist), np.nan, dtype=float)

    start = 252
    end = len(hist) - 252
    for idx in range(start, max(start, end)):
        max12, peak_idx = max_forward_return(close, idx, 252)
        fwd6 = forward_return(close, idx, 126)
        fwd12 = forward_return(close, idx, 252)
        max12_for[idx] = max12
        fwd6_for[idx] = fwd6
        fwd12_for[idx] = fwd12
        peak_idx_for[idx] = peak_idx
        if max12 >= min_peak_return_12m and fwd6 >= min_forward_6m:
            eligible[idx] = True

    events: list[OnsetEvent] = []
    idx = start
    while idx < end and len(events) < max_events_per_ticker:
        if not eligible[idx]:
            idx += 1
            continue

        cluster_start = idx
        cluster_end = idx
        while cluster_end + 1 < end and eligible[cluster_end + 1]:
            cluster_end += 1

        onset_idx = -1
        onset_features: dict | None = None
        for j in range(cluster_start, cluster_end + 1):
            feats = compute_features(hist, j, spy_hist)
            readiness = entry_readiness_score(feats)
            if readiness >= readiness_min:
                onset_idx = j
                onset_features = feats
                break
        if onset_idx < 0:
            # No confirmation in this cluster; skip rather than over-label a
            # falling knife as an actionable onset.
            idx = cluster_end + 1
            continue

        peak_idx = int(peak_idx_for[onset_idx])
        if peak_idx <= onset_idx:
            idx = cluster_end + 1
            continue
        if onset_features is None:
            onset_features = compute_features(hist, onset_idx, spy_hist)
        readiness = entry_readiness_score(onset_features)
        event = OnsetEvent(
            ticker=ticker.upper(),
            onset_date=str(hist.index[onset_idx].date()),
            peak_date=str(hist.index[peak_idx].date()),
            onset_price=finite_float(close.iloc[onset_idx]),
            peak_price=finite_float(close.iloc[peak_idx]),
            peak_return_12m=finite_float(max12_for[onset_idx]),
            forward_3m_return=forward_return(close, onset_idx, 63),
            forward_6m_return=finite_float(fwd6_for[onset_idx]),
            forward_12m_return=finite_float(fwd12_for[onset_idx]),
            max_drawdown_first_3m=max_drawdown_between(close, onset_idx, min(len(close) - 1, onset_idx + 63)),
            days_to_peak=int((hist.index[peak_idx] - hist.index[onset_idx]).days),
            entry_readiness_score=readiness,
            onset_mom_1m=finite_float(onset_features.get("mom_1m")),
            onset_mom_3m=finite_float(onset_features.get("mom_3m")),
            onset_mom_6m=finite_float(onset_features.get("mom_6m")),
            onset_rs_vs_spy_3m=finite_float(onset_features.get("rs_vs_spy_3m")),
            onset_rs_vs_spy_6m=finite_float(onset_features.get("rs_vs_spy_6m")),
            onset_volume_surge=finite_float(onset_features.get("volume_surge")),
            onset_price_vs_sma50=finite_float(onset_features.get("price_vs_sma50")),
            onset_price_vs_sma200=finite_float(onset_features.get("price_vs_sma200")),
            onset_dist_52w_high=finite_float(onset_features.get("dist_52w_high")),
            onset_breakout_63d=int(onset_features.get("breakout_63d", 0) or 0),
        )
        events.append(event)
        idx = max(cluster_end + 1, peak_idx + min_gap_days)

    return events


def nearest_index(index: pd.DatetimeIndex, target: pd.Timestamp) -> int:
    loc = index.get_indexer([target], method="nearest")[0]
    return int(loc)


def build_phase_snapshots(
    events: list[OnsetEvent],
    histories: dict[str, pd.DataFrame],
    spy_hist: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    rows: list[dict] = []
    for event in events:
        hist = histories.get(event.ticker)
        if hist is None or hist.empty:
            continue
        hist = normalize_history(hist)
        onset_dt = pd.Timestamp(event.onset_date)
        for offset_m in PHASE_OFFSETS_MONTHS:
            target = onset_dt + pd.Timedelta(days=offset_m * TRADING_DAYS_PER_MONTH)
            try:
                idx = nearest_index(pd.DatetimeIndex(hist.index), target)
            except Exception:
                continue
            if idx < 252 or idx >= len(hist):
                continue
            feats = compute_features(hist, idx, spy_hist)
            row = {
                "ticker": event.ticker,
                "onset_date": event.onset_date,
                "offset_months": offset_m,
                "snapshot_date": feats.pop("date"),
                **feats,
                "forward_3m_return": forward_return(hist["close"], idx, 63),
                "forward_6m_return": forward_return(hist["close"], idx, 126),
                "forward_12m_return": forward_return(hist["close"], idx, 252),
                "entry_readiness_score": entry_readiness_score(feats),
            }
            rows.append(row)
    return pd.DataFrame(rows)


def first_exit_return(close: pd.Series, onset_idx: int, kind: str) -> tuple[float, Optional[str], Optional[int]]:
    price0 = finite_float(close.iloc[onset_idx])
    if price0 <= 0:
        return float("nan"), None, None
    running_high = price0
    below_ma50_days = 0
    for idx in range(onset_idx + 1, len(close)):
        price = finite_float(close.iloc[idx])
        if price <= 0:
            continue
        running_high = max(running_high, price)
        gain = running_high / price0 - 1.0
        if kind == "trail20_after_50pct" and gain >= 0.50 and price / running_high - 1.0 <= -0.20:
            return price / price0 - 1.0, str(close.index[idx].date()), idx - onset_idx
        if kind == "ma50_5d_after_50pct" and gain >= 0.50:
            ma50 = finite_float(close.iloc[max(0, idx - 49):idx + 1].mean())
            below_ma50_days = below_ma50_days + 1 if ma50 > 0 and price < ma50 else 0
            if below_ma50_days >= 5:
                return price / price0 - 1.0, str(close.index[idx].date()), idx - onset_idx
        if kind == "ma200_after_50pct" and gain >= 0.50:
            ma200 = finite_float(close.iloc[max(0, idx - 199):idx + 1].mean())
            if ma200 > 0 and price < ma200:
                return price / price0 - 1.0, str(close.index[idx].date()), idx - onset_idx
    return float("nan"), None, None


def build_hold_diagnostics(events: list[OnsetEvent], histories: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict] = []
    for event in events:
        hist = normalize_history(histories.get(event.ticker, pd.DataFrame()))
        if hist.empty:
            continue
        close = hist["close"].astype(float)
        try:
            onset_idx = nearest_index(pd.DatetimeIndex(hist.index), pd.Timestamp(event.onset_date))
        except Exception:
            continue
        row = {
            "ticker": event.ticker,
            "onset_date": event.onset_date,
            "peak_date": event.peak_date,
            "hold_3m_return": forward_return(close, onset_idx, 63),
            "hold_6m_return": forward_return(close, onset_idx, 126),
            "hold_12m_return": forward_return(close, onset_idx, 252),
            "hold_18m_return": forward_return(close, onset_idx, 378),
            "max_return_6m": max_forward_return(close, onset_idx, 126)[0],
            "max_return_12m": max_forward_return(close, onset_idx, 252)[0],
            "max_return_18m": max_forward_return(close, onset_idx, 378)[0],
            "max_dd_3m": max_drawdown_between(close, onset_idx, onset_idx + 63),
            "max_dd_6m": max_drawdown_between(close, onset_idx, onset_idx + 126),
            "max_dd_12m": max_drawdown_between(close, onset_idx, onset_idx + 252),
        }
        for multiple in (2.0, 3.0, 5.0):
            target_ret = multiple - 1.0
            first = None
            for idx in range(onset_idx + 1, min(len(close), onset_idx + 504)):
                if finite_float(close.iloc[idx]) / finite_float(close.iloc[onset_idx]) - 1.0 >= target_ret:
                    first = idx
                    break
            label = f"first_{int(multiple)}x"
            row[f"{label}_date"] = str(close.index[first].date()) if first is not None else ""
            row[f"{label}_days"] = int(first - onset_idx) if first is not None else None
        for kind in ("trail20_after_50pct", "ma50_5d_after_50pct", "ma200_after_50pct"):
            ret, dt, days = first_exit_return(close, onset_idx, kind)
            row[f"{kind}_return"] = ret
            row[f"{kind}_date"] = dt or ""
            row[f"{kind}_days"] = days
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_patterns(events_df: pd.DataFrame, snapshots_df: pd.DataFrame, hold_df: pd.DataFrame) -> dict:
    summary = {
        "event_count": int(len(events_df)),
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "production_activation_allowed": False,
    }
    if not events_df.empty:
        onset_cols = [
            "entry_readiness_score",
            "onset_mom_1m",
            "onset_mom_3m",
            "onset_mom_6m",
            "onset_rs_vs_spy_3m",
            "onset_rs_vs_spy_6m",
            "onset_volume_surge",
            "onset_price_vs_sma50",
            "onset_price_vs_sma200",
            "onset_dist_52w_high",
            "forward_6m_return",
            "forward_12m_return",
            "max_drawdown_first_3m",
            "days_to_peak",
        ]
        summary["onset_medians"] = {
            c: finite_float(events_df[c].median()) for c in onset_cols if c in events_df.columns
        }
        summary["top_events"] = (
            events_df.sort_values("peak_return_12m", ascending=False)
            .head(20)[["ticker", "onset_date", "peak_date", "peak_return_12m", "forward_6m_return"]]
            .to_dict("records")
        )
    if not hold_df.empty:
        hold_cols = [
            "hold_6m_return",
            "hold_12m_return",
            "max_return_12m",
            "max_dd_6m",
            "trail20_after_50pct_return",
            "ma50_5d_after_50pct_return",
        ]
        summary["hold_medians"] = {
            c: finite_float(hold_df[c].median()) for c in hold_cols if c in hold_df.columns
        }
    if not snapshots_df.empty:
        by_offset = {}
        for offset, sub in snapshots_df.groupby("offset_months"):
            by_offset[str(int(offset))] = {
                "n": int(len(sub)),
                "median_mom_3m": finite_float(sub["mom_3m"].median()) if "mom_3m" in sub else float("nan"),
                "median_rs_vs_spy_3m": finite_float(sub["rs_vs_spy_3m"].median()) if "rs_vs_spy_3m" in sub else float("nan"),
                "median_entry_readiness_score": finite_float(sub["entry_readiness_score"].median())
                if "entry_readiness_score" in sub else float("nan"),
                "median_forward_6m_return": finite_float(sub["forward_6m_return"].median())
                if "forward_6m_return" in sub else float("nan"),
            }
        summary["phase_medians_by_offset_months"] = by_offset
    return summary


def pct(value: float) -> str:
    if value is None or not math.isfinite(float(value)):
        return "NA"
    return f"{float(value) * 100:.1f}%"


def render_report(summary: dict, events_df: pd.DataFrame, output_dir: Path) -> str:
    lines = [
        "# Winner Onset Study",
        "",
        "Report-only historical study. No production behavior is changed.",
        "",
        f"- events: {summary.get('event_count', 0)}",
        f"- production_activation_allowed: {summary.get('production_activation_allowed', False)}",
        "",
    ]
    med = summary.get("onset_medians", {})
    if med:
        lines.extend([
            "## Median Onset Pattern",
            "",
            f"- readiness score: {med.get('entry_readiness_score', float('nan')):.3f}",
            f"- 1m momentum: {pct(med.get('onset_mom_1m', float('nan')))}",
            f"- 3m momentum: {pct(med.get('onset_mom_3m', float('nan')))}",
            f"- 6m momentum: {pct(med.get('onset_mom_6m', float('nan')))}",
            f"- RS vs SPY 3m: {pct(med.get('onset_rs_vs_spy_3m', float('nan')))}",
            f"- volume surge: {med.get('onset_volume_surge', float('nan')):.2f}x",
            f"- distance to 52w high: {pct(med.get('onset_dist_52w_high', float('nan')))}",
            f"- first 3m max drawdown: {pct(med.get('max_drawdown_first_3m', float('nan')))}",
            "",
        ])
    if not events_df.empty:
        lines.extend(["## Top Events", ""])
        top = events_df.sort_values("peak_return_12m", ascending=False).head(15)
        lines.append("| ticker | onset | peak | 12m peak return | fwd 6m | readiness |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for _, row in top.iterrows():
            lines.append(
                f"| {row['ticker']} | {row['onset_date']} | {row['peak_date']} | "
                f"{pct(row['peak_return_12m'])} | {pct(row['forward_6m_return'])} | "
                f"{finite_float(row['entry_readiness_score']):.3f} |"
            )
        lines.append("")
    lines.extend([
        "## Files",
        "",
        f"- `{(output_dir / 'events.csv').as_posix()}`",
        f"- `{(output_dir / 'phase_snapshots.csv').as_posix()}`",
        f"- `{(output_dir / 'hold_diagnostics.csv').as_posix()}`",
        f"- `{(output_dir / 'pattern_summary.json').as_posix()}`",
        f"- `{(output_dir / 'system_policy_candidates.yaml').as_posix()}`",
        "",
        "## Next Gate",
        "",
        "Use this report to propose counterfactual rules, then test those rules",
        "through a true historical challenger replay before any production wiring.",
        "",
    ])
    return "\n".join(lines)


def render_policy_yaml(summary: dict) -> str:
    med = summary.get("onset_medians", {})
    lines = [
        "# Generated by tools/run_winner_onset_study.py",
        "# Proposal-only. Do not apply directly to production selection.",
        "production_activation_allowed: false",
        "requires:",
        "  - true_historical_challenger_replay",
        "  - cost_sensitivity_check",
        "  - drawdown_stress_check",
        "  - human_approval",
        "candidate_rules:",
        "  - id: winner_onset_hold_candidate",
        "    status: proposal_only",
        "    intent: detect early major-winner onset and hold while trend remains intact",
        "    suggested_thresholds:",
        f"      entry_readiness_score_min: {finite_float(med.get('entry_readiness_score', 0.55), 0.55):.3f}",
        f"      mom_3m_min: {finite_float(med.get('onset_mom_3m', 0.10), 0.10):.4f}",
        f"      rs_vs_spy_3m_min: {finite_float(med.get('onset_rs_vs_spy_3m', 0.06), 0.06):.4f}",
        "      max_initial_position_weight: 0.05",
        "      staged_add_after_profit_cushion: true",
        "      avoid_if_first_3m_drawdown_exceeds: -0.25",
        "    candidate_exits:",
        "      - trail20_after_50pct_gain",
        "      - ma50_5d_after_50pct_gain",
        "      - ma200_after_50pct_gain",
    ]
    return "\n".join(lines) + "\n"


def load_tickers_from_scored(
    path: Path,
    top_n: int = 0,
    min_current_mcap_usd: float = 5_000_000_000.0,
    min_dollar_vol_20d: float = 20_000_000.0,
) -> list[str]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if "ticker" not in df.columns:
        return []
    cap_col = None
    for c in ("market_cap_live", "mktcap", "market_cap", "mcap"):
        if c in df.columns:
            cap_col = c
            break
    if cap_col and min_current_mcap_usd > 0:
        cap = pd.to_numeric(df[cap_col], errors="coerce")
        df = df[cap.isna() | (cap >= min_current_mcap_usd)].copy()
    if "dollar_vol_20d" in df.columns and min_dollar_vol_20d > 0:
        dv = pd.to_numeric(df["dollar_vol_20d"], errors="coerce")
        df = df[dv.isna() | (dv >= min_dollar_vol_20d)].copy()
    score_col = None
    for c in ("score", "raw_score", "combined_score", "portfolio_future_winner_engine_score"):
        if c in df.columns:
            score_col = c
            break
    if top_n and score_col:
        df = df.sort_values(score_col, ascending=False).head(top_n)
    tickers = [str(t).upper().strip() for t in df["ticker"].dropna()]
    return [t for t in tickers if t and t not in DEFAULT_CASH_TICKERS]


def load_tickers(args) -> list[str]:
    tickers: list[str] = []
    if args.tickers:
        tickers.extend(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    if args.ticker_file:
        path = Path(args.ticker_file)
        if path.exists():
            if path.suffix.lower() == ".csv":
                with path.open(newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    col = "ticker" if "ticker" in (reader.fieldnames or []) else (reader.fieldnames or [""])[0]
                    tickers.extend(str(row.get(col, "")).upper().strip() for row in reader)
            else:
                tickers.extend(t.strip().upper() for t in path.read_text(encoding="utf-8").splitlines())
    if args.scored:
        tickers.extend(
            load_tickers_from_scored(
                Path(args.scored),
                top_n=args.top_tickers,
                min_current_mcap_usd=args.min_current_mcap_usd,
                min_dollar_vol_20d=args.min_dollar_vol_20d,
            )
        )
    seen: set[str] = set()
    out: list[str] = []
    for ticker in tickers:
        if not ticker or ticker in DEFAULT_CASH_TICKERS or ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out


def run(args) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tickers = load_tickers(args)
    if not tickers:
        print("ERROR: no tickers supplied. Use --tickers, --ticker-file, or --scored.", file=sys.stderr)
        return 2
    if args.limit:
        tickers = tickers[:args.limit]

    end = datetime.utcnow().date()
    start = end - timedelta(days=int(args.years * 365.25))
    print(f"[winner_onset] tickers={len(tickers)} years={args.years} output={output_dir}")

    histories: dict[str, pd.DataFrame] = {}
    spy_hist = fetch_history("SPY", str(start), str(end))
    events: list[OnsetEvent] = []
    for i, ticker in enumerate(tickers, 1):
        if i == 1 or i % 25 == 0:
            print(f"  [{i}/{len(tickers)}] events={len(events)}")
        try:
            hist = fetch_history(ticker, str(start), str(end))
        except Exception as exc:
            print(f"  WARN {ticker}: {exc}", file=sys.stderr)
            continue
        if hist.empty:
            continue
        histories[ticker] = hist
        events.extend(
            detect_onset_events(
                ticker=ticker,
                hist=hist,
                spy_hist=spy_hist,
                min_peak_return_12m=args.min_peak_return,
                min_forward_6m=args.min_6m_return,
                readiness_min=args.readiness_min,
                max_events_per_ticker=args.max_events_per_ticker,
            )
        )
        if args.sleep:
            time.sleep(args.sleep)

    events_df = pd.DataFrame([asdict(e) for e in events])
    if not events_df.empty:
        events_df = events_df.sort_values(["peak_return_12m", "forward_6m_return"], ascending=False)
    snapshots_df = build_phase_snapshots(events, histories, spy_hist=spy_hist)
    hold_df = build_hold_diagnostics(events, histories)
    summary = summarize_patterns(events_df, snapshots_df, hold_df)
    summary["filters"] = {
        "min_current_mcap_usd": args.min_current_mcap_usd,
        "min_dollar_vol_20d": args.min_dollar_vol_20d,
        "note": "current scored-universe filter; point-in-time market cap requires monthly feature-store replay",
    }

    events_df.to_csv(output_dir / "events.csv", index=False)
    snapshots_df.to_csv(output_dir / "phase_snapshots.csv", index=False)
    hold_df.to_csv(output_dir / "hold_diagnostics.csv", index=False)
    (output_dir / "pattern_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "winner_onset_report.md").write_text(render_report(summary, events_df, output_dir), encoding="utf-8")
    (output_dir / "system_policy_candidates.yaml").write_text(render_policy_yaml(summary), encoding="utf-8")

    print(f"[winner_onset] wrote {output_dir} events={len(events_df)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tickers", default="", help="comma-separated explicit tickers")
    p.add_argument("--ticker-file", default="", help="CSV/text ticker list")
    p.add_argument("--scored", default="", help="scored_latest.csv to source a universe")
    p.add_argument("--top-tickers", type=int, default=0, help="if --scored, optionally use top N by score")
    p.add_argument("--limit", type=int, default=0, help="debug limit after loading tickers")
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--min-current-mcap-usd", type=float, default=5_000_000_000.0,
                   help="when --scored is used, exclude current micro/small caps below this market cap")
    p.add_argument("--min-dollar-vol-20d", type=float, default=20_000_000.0,
                   help="when --scored is used, exclude thin liquidity below this 20d dollar volume")
    p.add_argument("--min-peak-return", type=float, default=1.50, help="future max 12m return threshold")
    p.add_argument("--min-6m-return", type=float, default=0.50, help="future 6m return threshold")
    p.add_argument("--readiness-min", type=float, default=0.55, help="entry readiness score threshold")
    p.add_argument("--max-events-per-ticker", type=int, default=3)
    p.add_argument("--sleep", type=float, default=0.05, help="seconds between yfinance ticker calls")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
