#!/usr/bin/env python3
"""Report-only shakeout vs breakdown study.

The study turns sharp drawdowns in liquid, investable stocks into labeled
training events:

* SHAKEOUT: a leader drops sharply, then recovers prior highs and generates
  positive forward return.
* BUYABLE_RESET: the prior high is not fully recovered yet, but the reset leads
  to strong forward return.
* DISTRIBUTION: the stock bounces partway, fails, and makes a lower low
  or slowly stair-steps lower with weak relative strength.
* TRUE_BREAKDOWN: the drawdown continues directly or forward return remains poor.
* DEAD_THEME: the stock fails to reclaim the prior high and trades below long
  trend while forward return is weak.

Outputs are research-only. They are meant to feed AutoLearning and future
portfolio-level challenger replay, not to change production behavior directly.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_winner_onset_study import (  # noqa: E402
    DEFAULT_CASH_TICKERS,
    fetch_history,
    finite_float,
    forward_return,
    load_tickers_from_scored,
    max_drawdown_between,
    max_forward_return,
    normalize_history,
    safe_return,
)

DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "shakeout_breakdown_study"


@dataclass
class DrawdownEvent:
    ticker: str
    event_date: str
    prior_peak_date: str
    event_price: float
    prior_peak_price: float
    drawdown_from_peak: float
    days_since_peak: int
    label: str
    label_reason: str
    recovery_3m: int
    recovery_6m: int
    half_recovery_3m: int
    half_recovery_6m: int
    lower_low_after_half_recovery_6m: int
    fast_drop_flag: int
    high_volume_panic_flag: int
    v_recovery_days: int
    forward_1m_return: float
    forward_3m_return: float
    forward_6m_return: float
    max_forward_3m_return: float
    max_forward_6m_return: float
    max_dd_next_3m: float
    max_dd_next_6m: float
    mom_1m: float
    mom_3m: float
    mom_6m: float
    rs_vs_spy_3m: float
    rs_vs_spy_6m: float
    price_vs_sma50: float
    price_vs_sma200: float
    volume_surge: float
    distribution_risk_score: float
    breakdown_risk_score: float
    shakeout_quality_score: float


def pct(value: Any) -> str:
    value = finite_float(value)
    if not math.isfinite(value):
        return "NA"
    return f"{value:.2%}"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def compute_event_features(hist: pd.DataFrame, idx: int, spy_hist: Optional[pd.DataFrame] = None) -> dict[str, float]:
    hist = normalize_history(hist)
    close = hist["close"].astype(float)
    volume = hist["volume"].astype(float) if "volume" in hist else pd.Series(np.nan, index=hist.index)
    price = finite_float(close.iloc[idx])
    sma50 = finite_float(close.iloc[max(0, idx - 49):idx + 1].mean())
    sma200 = finite_float(close.iloc[max(0, idx - 199):idx + 1].mean())
    vol20 = finite_float(volume.iloc[max(0, idx - 19):idx + 1].mean())
    vol120 = finite_float(volume.iloc[max(0, idx - 119):idx + 1].mean())
    rs3 = rs6 = float("nan")
    if spy_hist is not None and not spy_hist.empty:
        try:
            spy_close = spy_hist["close"].astype(float)
            spy_idx = spy_close.index.get_indexer([hist.index[idx]], method="pad")[0]
            if spy_idx >= 126:
                rs3 = safe_return(close, idx, 63) - safe_return(spy_close, spy_idx, 63)
                rs6 = safe_return(close, idx, 126) - safe_return(spy_close, spy_idx, 126)
        except Exception:
            pass
    return {
        "mom_1m": safe_return(close, idx, 21),
        "mom_3m": safe_return(close, idx, 63),
        "mom_6m": safe_return(close, idx, 126),
        "rs_vs_spy_3m": rs3,
        "rs_vs_spy_6m": rs6,
        "price_vs_sma50": price / sma50 - 1.0 if price > 0 and sma50 > 0 else float("nan"),
        "price_vs_sma200": price / sma200 - 1.0 if price > 0 and sma200 > 0 else float("nan"),
        "volume_surge": vol20 / vol120 if vol20 > 0 and vol120 > 0 else float("nan"),
    }


def _days_to_reclaim(future: pd.Series, event_date: pd.Timestamp, level: float) -> int:
    if future.empty or not np.isfinite(level):
        return -1
    hits = future[future >= level]
    if hits.empty:
        return -1
    return int((pd.Timestamp(hits.index[0]) - pd.Timestamp(event_date)).days)


def _half_recovery_flags(
    future3: pd.Series,
    future6: pd.Series,
    *,
    event_price: float,
    prior_peak_price: float,
) -> tuple[bool, bool, bool]:
    if event_price <= 0 or prior_peak_price <= event_price:
        return False, False, False
    half_level = event_price + 0.50 * (prior_peak_price - event_price)
    half3 = bool((future3 >= half_level).any()) if not future3.empty else False
    half6 = bool((future6 >= half_level).any()) if not future6.empty else False
    lower_low_after_half = False
    if half6 and not future6.empty:
        first_half_date = pd.Timestamp(future6[future6 >= half_level].index[0])
        after_half = future6[future6.index > first_half_date]
        lower_low_after_half = bool(not after_half.empty and float(after_half.min()) <= event_price * 0.98)
    return half3, half6, lower_low_after_half


def score_shakeout_quality(
    features: dict[str, float],
    drawdown: float,
    recovery_6m: bool,
    fwd6: float,
    *,
    days_since_peak: int,
    half_recovery_3m: bool,
    lower_low_after_half_recovery_6m: bool,
) -> float:
    vol = features.get("volume_surge", np.nan)
    high_volume_panic = 1.50 <= vol <= 5.00
    checks = [
        (drawdown >= -0.35, 0.08),
        (days_since_peak <= 35, 0.12),
        (features.get("rs_vs_spy_3m", np.nan) >= -0.08, 0.12),
        (features.get("rs_vs_spy_6m", np.nan) >= -0.10, 0.08),
        (features.get("price_vs_sma200", np.nan) >= -0.15, 0.10),
        (high_volume_panic, 0.10),
        (half_recovery_3m, 0.10),
        (not lower_low_after_half_recovery_6m, 0.10),
        (recovery_6m, 0.20),
        (fwd6 >= 0.20, 0.10),
    ]
    weight = sum(w for _, w in checks)
    return sum(w for ok, w in checks if bool(ok)) / weight if weight else 0.0


def score_distribution_risk(
    features: dict[str, float],
    drawdown: float,
    recovery_6m: bool,
    fwd6: float,
    max_dd_6m: float,
    *,
    days_since_peak: int,
    half_recovery_6m: bool,
    lower_low_after_half_recovery_6m: bool,
) -> float:
    vol = features.get("volume_surge", np.nan)
    checks = [
        (drawdown <= -0.18, 0.08),
        (days_since_peak >= 45, 0.12),
        (half_recovery_6m, 0.13),
        (lower_low_after_half_recovery_6m, 0.22),
        (features.get("rs_vs_spy_3m", np.nan) < -0.08, 0.12),
        (features.get("rs_vs_spy_6m", np.nan) < -0.12, 0.10),
        (features.get("price_vs_sma200", np.nan) < -0.08, 0.10),
        (vol <= 2.0, 0.05),
        (not recovery_6m, 0.10),
        (fwd6 <= 0.10 or max_dd_6m <= -0.22, 0.08),
    ]
    weight = sum(w for _, w in checks)
    return sum(w for ok, w in checks if bool(ok)) / weight if weight else 0.0


def score_breakdown_risk(
    features: dict[str, float],
    drawdown: float,
    recovery_6m: bool,
    fwd6: float,
    max_dd_6m: float,
) -> float:
    checks = [
        (drawdown <= -0.30, 0.15),
        (features.get("rs_vs_spy_3m", np.nan) < -0.10, 0.15),
        (features.get("rs_vs_spy_6m", np.nan) < -0.15, 0.12),
        (features.get("price_vs_sma200", np.nan) < -0.10, 0.13),
        (features.get("volume_surge", np.nan) >= 2.0, 0.08),
        (not recovery_6m, 0.17),
        (fwd6 <= 0.00, 0.10),
        (max_dd_6m <= -0.25, 0.10),
    ]
    weight = sum(w for _, w in checks)
    return sum(w for ok, w in checks if bool(ok)) / weight if weight else 0.0


def classify_event(
    recovery_3m: bool,
    recovery_6m: bool,
    half_recovery_6m: bool,
    lower_low_after_half_recovery_6m: bool,
    fwd6: float,
    max_forward_6m: float,
    max_dd_6m: float,
    features: dict[str, float],
    days_since_peak: int,
) -> tuple[str, str]:
    under_200 = features.get("price_vs_sma200", np.nan) < -0.10
    weak_rs = features.get("rs_vs_spy_3m", np.nan) < -0.10
    failed_half_recovery = half_recovery_6m and lower_low_after_half_recovery_6m
    slow_stair_step = days_since_peak >= 45 and not recovery_6m
    if failed_half_recovery and (fwd6 < 0.15 or under_200 or weak_rs or max_dd_6m <= -0.22):
        return "DISTRIBUTION", "half_recovery_failed_then_lower_low"
    if slow_stair_step and (under_200 or weak_rs) and fwd6 < 0.10:
        return "DISTRIBUTION", "slow_stair_step_lower_with_weak_relative_strength"
    if recovery_6m and fwd6 >= 0.20:
        return "SHAKEOUT", "reclaimed_prior_high_with_positive_6m_return"
    if not recovery_6m and fwd6 >= 0.30 and max_forward_6m >= 0.50 and not failed_half_recovery:
        return "BUYABLE_RESET", "did_not_reclaim_high_but_generated_strong_forward_return"
    if (not recovery_6m) and under_200 and weak_rs and fwd6 < 0.10:
        return "DEAD_THEME", "failed_recovery_below_200dma_with_weak_relative_strength"
    if fwd6 <= -0.10 or ((not recovery_3m) and max_dd_6m <= -0.30):
        return "TRUE_BREAKDOWN", "continued_lower_or_forward_loss_after_drawdown"
    return "AMBIGUOUS", "mixed_forward_evidence"


def detect_drawdown_events(
    ticker: str,
    hist: pd.DataFrame,
    spy_hist: Optional[pd.DataFrame] = None,
    min_drop: float = 0.12,
    lookback_days: int = 126,
    min_gap_days: int = 42,
) -> list[DrawdownEvent]:
    hist = normalize_history(hist)
    if hist.empty or len(hist) < 252 * 2:
        return []
    close = hist["close"].astype(float)
    events: list[DrawdownEvent] = []
    last_event_idx = -10_000
    end = len(hist) - 126
    for idx in range(252, max(252, end)):
        if idx - last_event_idx < min_gap_days:
            continue
        start = max(0, idx - lookback_days)
        prior_window = close.iloc[start:idx + 1]
        if prior_window.empty:
            continue
        peak_rel_idx = int(np.nanargmax(prior_window.to_numpy(dtype=float)))
        peak_idx = start + peak_rel_idx
        peak_price = finite_float(close.iloc[peak_idx])
        event_price = finite_float(close.iloc[idx])
        if peak_idx >= idx or peak_price <= 0 or event_price <= 0:
            continue
        drawdown = event_price / peak_price - 1.0
        if drawdown > -abs(min_drop):
            continue
        prev_price = finite_float(close.iloc[idx - 1])
        prev_drawdown = prev_price / peak_price - 1.0 if peak_price > 0 and prev_price > 0 else 0.0
        if prev_drawdown <= -abs(min_drop):
            continue

        future3 = close.iloc[idx + 1:min(len(close), idx + 64)]
        future6 = close.iloc[idx + 1:min(len(close), idx + 127)]
        recovery_3m = bool((future3 >= peak_price * 0.98).any()) if not future3.empty else False
        recovery_6m = bool((future6 >= peak_price * 0.98).any()) if not future6.empty else False
        half_recovery_3m, half_recovery_6m, lower_low_after_half = _half_recovery_flags(
            future3,
            future6,
            event_price=event_price,
            prior_peak_price=peak_price,
        )
        days_since_peak = int((hist.index[idx] - hist.index[peak_idx]).days)
        fwd1 = forward_return(close, idx, 21)
        fwd3 = forward_return(close, idx, 63)
        fwd6 = forward_return(close, idx, 126)
        max3 = max_forward_return(close, idx, 63)[0]
        max6 = max_forward_return(close, idx, 126)[0]
        maxdd3 = max_drawdown_between(close, idx, min(len(close) - 1, idx + 63))
        maxdd6 = max_drawdown_between(close, idx, min(len(close) - 1, idx + 126))
        features = compute_event_features(hist, idx, spy_hist)
        vol = features.get("volume_surge", np.nan)
        high_volume_panic = bool(1.50 <= vol <= 5.00)
        label, reason = classify_event(
            recovery_3m,
            recovery_6m,
            half_recovery_6m,
            lower_low_after_half,
            fwd6,
            max6,
            maxdd6,
            features,
            days_since_peak,
        )
        shake_score = score_shakeout_quality(
            features,
            drawdown,
            recovery_6m,
            fwd6,
            days_since_peak=days_since_peak,
            half_recovery_3m=half_recovery_3m,
            lower_low_after_half_recovery_6m=lower_low_after_half,
        )
        distribution_score = score_distribution_risk(
            features,
            drawdown,
            recovery_6m,
            fwd6,
            maxdd6,
            days_since_peak=days_since_peak,
            half_recovery_6m=half_recovery_6m,
            lower_low_after_half_recovery_6m=lower_low_after_half,
        )
        breakdown_score = score_breakdown_risk(features, drawdown, recovery_6m, fwd6, maxdd6)
        events.append(
            DrawdownEvent(
                ticker=ticker.upper(),
                event_date=str(hist.index[idx].date()),
                prior_peak_date=str(hist.index[peak_idx].date()),
                event_price=event_price,
                prior_peak_price=peak_price,
                drawdown_from_peak=drawdown,
                days_since_peak=days_since_peak,
                label=label,
                label_reason=reason,
                recovery_3m=int(recovery_3m),
                recovery_6m=int(recovery_6m),
                half_recovery_3m=int(half_recovery_3m),
                half_recovery_6m=int(half_recovery_6m),
                lower_low_after_half_recovery_6m=int(lower_low_after_half),
                fast_drop_flag=int(days_since_peak <= 35),
                high_volume_panic_flag=int(high_volume_panic),
                v_recovery_days=_days_to_reclaim(future6, hist.index[idx], peak_price * 0.98),
                forward_1m_return=fwd1,
                forward_3m_return=fwd3,
                forward_6m_return=fwd6,
                max_forward_3m_return=max3,
                max_forward_6m_return=max6,
                max_dd_next_3m=maxdd3,
                max_dd_next_6m=maxdd6,
                mom_1m=features["mom_1m"],
                mom_3m=features["mom_3m"],
                mom_6m=features["mom_6m"],
                rs_vs_spy_3m=features["rs_vs_spy_3m"],
                rs_vs_spy_6m=features["rs_vs_spy_6m"],
                price_vs_sma50=features["price_vs_sma50"],
                price_vs_sma200=features["price_vs_sma200"],
                volume_surge=features["volume_surge"],
                distribution_risk_score=distribution_score,
                breakdown_risk_score=breakdown_score,
                shakeout_quality_score=shake_score,
            )
        )
        last_event_idx = idx
    return events


def action_return(row: dict[str, Any], action: str, horizon: str) -> float:
    fwd = finite_float(row.get(f"forward_{horizon}_return"))
    if action == "hold":
        return fwd
    if action == "exit_to_cash":
        return 0.0
    if action == "trim50":
        return 0.5 * fwd
    if action == "add25":
        return 1.25 * fwd
    if action == "label_oracle":
        label = row.get("label")
        if label in {"SHAKEOUT", "BUYABLE_RESET"}:
            return 1.25 * fwd
        if label in {"DISTRIBUTION", "TRUE_BREAKDOWN", "DEAD_THEME"}:
            return 0.0
        return 0.5 * fwd
    return float("nan")


def build_action_replay(events_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    actions = ["hold", "trim50", "add25", "exit_to_cash", "label_oracle"]
    horizons = ["1m", "3m", "6m"]
    for _, row in events_df.iterrows():
        payload = row.to_dict()
        for horizon in horizons:
            for action in actions:
                rows.append({
                    "ticker": row.get("ticker"),
                    "event_date": row.get("event_date"),
                    "label": row.get("label"),
                    "horizon": horizon,
                    "action": action,
                    "action_return": action_return(payload, action, horizon),
                    "drawdown_from_peak": row.get("drawdown_from_peak"),
                    "shakeout_quality_score": row.get("shakeout_quality_score"),
                    "breakdown_risk_score": row.get("breakdown_risk_score"),
                    "production_activation_allowed": False,
                })
    return pd.DataFrame(rows)


def summarize_action_replay(action_df: pd.DataFrame) -> list[dict[str, Any]]:
    if action_df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for (label, horizon, action), group in action_df.groupby(["label", "horizon", "action"], dropna=False):
        vals = pd.to_numeric(group["action_return"], errors="coerce").dropna()
        if vals.empty:
            continue
        rows.append({
            "label": label,
            "horizon": horizon,
            "action": action,
            "n": int(len(vals)),
            "avg_return": float(vals.mean()),
            "median_return": float(vals.median()),
            "hit_rate": float((vals > 0).mean()),
            "worst_return": float(vals.min()),
            "best_return": float(vals.max()),
        })
    return sorted(rows, key=lambda r: (str(r["label"]), str(r["horizon"]), str(r["action"])))


def summarize(events_df: pd.DataFrame, action_df: pd.DataFrame, args: argparse.Namespace) -> dict[str, Any]:
    label_counts = Counter(events_df["label"].astype(str)) if not events_df.empty else Counter()
    by_label: dict[str, dict[str, Any]] = {}
    if not events_df.empty:
        for label, group in events_df.groupby("label"):
            by_label[str(label)] = {
                "n": int(len(group)),
                "median_drawdown_from_peak": finite_float(group["drawdown_from_peak"].median()),
                "median_forward_6m_return": finite_float(group["forward_6m_return"].median()),
                "median_shakeout_quality_score": finite_float(group["shakeout_quality_score"].median()),
                "median_distribution_risk_score": finite_float(group["distribution_risk_score"].median()),
                "median_breakdown_risk_score": finite_float(group["breakdown_risk_score"].median()),
                "recovery_6m_rate": finite_float(pd.to_numeric(group["recovery_6m"], errors="coerce").mean()),
                "half_recovery_6m_rate": finite_float(pd.to_numeric(group["half_recovery_6m"], errors="coerce").mean()),
                "lower_low_after_half_recovery_6m_rate": finite_float(
                    pd.to_numeric(group["lower_low_after_half_recovery_6m"], errors="coerce").mean()
                ),
            }
    action_summary = summarize_action_replay(action_df)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "research_only",
        "production_activation_allowed": False,
        "event_count": int(len(events_df)),
        "label_counts": dict(label_counts),
        "by_label": by_label,
        "action_summary": action_summary,
        "filters": {
            "min_drop": args.min_drop,
            "lookback_days": args.lookback_days,
            "min_gap_days": args.min_gap_days,
            "min_current_mcap_usd": args.min_current_mcap_usd,
            "min_dollar_vol_20d": args.min_dollar_vol_20d,
            "note": "scored-universe filters use current market cap/liquidity; PIT validation requires monthly feature-store replay",
        },
    }


def render_report(summary: dict[str, Any], events_df: pd.DataFrame) -> str:
    lines = [
        "# Shakeout vs Distribution/Breakdown Study",
        "",
        "Report-only event study. No production behavior is changed.",
        "",
        f"- events: {summary.get('event_count', 0)}",
        f"- production_activation_allowed: `{summary.get('production_activation_allowed')}`",
        "",
        "## Label Counts",
        "",
    ]
    for label, count in (summary.get("label_counts") or {}).items():
        lines.append(f"- `{label}`: {count}")
    lines.extend(["", "## Label Medians", ""])
    lines.append("| Label | N | Median DD | Median 6m Return | Recovery 6m | Half Recovery 6m | Lower Low After Half | Shakeout Quality | Distribution Risk | Breakdown Risk |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for label, payload in (summary.get("by_label") or {}).items():
        lines.append(
            f"| {label} | {payload.get('n')} | {pct(payload.get('median_drawdown_from_peak'))} | "
            f"{pct(payload.get('median_forward_6m_return'))} | {pct(payload.get('recovery_6m_rate'))} | "
            f"{pct(payload.get('half_recovery_6m_rate'))} | "
            f"{pct(payload.get('lower_low_after_half_recovery_6m_rate'))} | "
            f"{finite_float(payload.get('median_shakeout_quality_score')):.3f} | "
            f"{finite_float(payload.get('median_distribution_risk_score')):.3f} | "
            f"{finite_float(payload.get('median_breakdown_risk_score')):.3f} |"
        )
    lines.extend(["", "## Best Event-Level Actions By Label/Horizon", ""])
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for row in summary.get("action_summary") or []:
        key = (str(row.get("label")), str(row.get("horizon")))
        if key not in best or finite_float(row.get("median_return"), -999.0) > finite_float(best[key].get("median_return"), -999.0):
            best[key] = row
    lines.append("| Label | Horizon | Best Action | N | Median Return | Hit Rate |")
    lines.append("|---|---|---|---:|---:|---:|")
    for (label, horizon), row in sorted(best.items()):
        lines.append(
            f"| {label} | {horizon} | {row.get('action')} | {row.get('n')} | "
            f"{pct(row.get('median_return'))} | {pct(row.get('hit_rate'))} |"
        )
    if not events_df.empty:
        lines.extend(["", "## Recent / Largest Events", ""])
        show = events_df.sort_values(["event_date", "drawdown_from_peak"], ascending=[False, True]).head(15)
        lines.append("| Ticker | Event | Label | DD | Fwd 6m | Recovery 6m | Half Recovery 6m | Lower Low | Quality | Dist Risk | Breakdown Risk |")
        lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, row in show.iterrows():
            lines.append(
                f"| {row.get('ticker')} | {row.get('event_date')} | {row.get('label')} | "
                f"{pct(row.get('drawdown_from_peak'))} | {pct(row.get('forward_6m_return'))} | "
                f"{row.get('recovery_6m')} | {row.get('half_recovery_6m')} | "
                f"{row.get('lower_low_after_half_recovery_6m')} | "
                f"{finite_float(row.get('shakeout_quality_score')):.3f} | "
                f"{finite_float(row.get('distribution_risk_score')):.3f} | "
                f"{finite_float(row.get('breakdown_risk_score')):.3f} |"
            )
    lines.extend([
        "",
        "## Next Gate",
        "",
        "Use these event labels to train/validate a hold/add/trim/exit policy,",
        "then run a true portfolio-level challenger replay before production activation.",
        "",
    ])
    return "\n".join(lines)


def render_policy_yaml(summary: dict[str, Any]) -> str:
    lines = [
        "# Generated by tools/run_shakeout_breakdown_study.py",
        "mode: proposal_only",
        "production_activation_allowed: false",
        "requires_historical_replay: true",
        "requires_human_approval: true",
        "candidate_rules:",
        "  - id: shakeout_hold_add_candidate",
        "    status: proposal_only",
        "    intent: hold or add to high-quality leaders when drawdown pattern resembles historical shakeout",
        "    suggested_conditions:",
        "      shakeout_quality_score_min: 0.60",
        "      breakdown_risk_score_max: 0.45",
        "      max_initial_add_weight: 0.05",
        "      require_regime_not_deep_bear: true",
        "  - id: distribution_exit_candidate",
        "    status: proposal_only",
        "    intent: trim or exit when a partial recovery fails into a lower low",
        "    suggested_conditions:",
        "      distribution_risk_score_min: 0.60",
        "      lower_low_after_half_recovery_6m: true",
        "      allow_swap_to_new_leader: true",
        "  - id: true_breakdown_exit_candidate",
        "    status: proposal_only",
        "    intent: exit or trim when drawdown pattern resembles failed recovery / dead theme",
        "    suggested_conditions:",
        "      breakdown_risk_score_min: 0.60",
        "      shakeout_quality_score_max: 0.45",
        "      allow_swap_to_new_leader: true",
        "sizing_experiments:",
        "  concentrated_single_name_cap_grid: [0.25, 0.33, 0.40, 0.50]",
        "  main_single_name_cap_grid: [0.15, 0.20, 0.25, 0.33]",
        "  activation: portfolio_challenger_only",
    ]
    return "\n".join(lines) + "\n"


def load_tickers(args: argparse.Namespace) -> list[str]:
    tickers: list[str] = []
    if args.tickers:
        tickers.extend(t.strip().upper() for t in args.tickers.split(",") if t.strip())
    if args.ticker_file:
        path = Path(args.ticker_file)
        if path.exists():
            if path.suffix.lower() == ".csv":
                rows = read_csv_rows(path)
                if rows:
                    col = "ticker" if "ticker" in rows[0] else next(iter(rows[0].keys()))
                    tickers.extend(str(row.get(col, "")).upper().strip() for row in rows)
            else:
                tickers.extend(t.strip().upper() for t in path.read_text(encoding="utf-8").splitlines() if t.strip())
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


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tickers = load_tickers(args)
    if args.limit:
        tickers = tickers[:args.limit]
    if not tickers:
        raise SystemExit("ERROR: no tickers supplied. Use --tickers, --ticker-file, or --scored.")

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=int(args.years * 365.25))
    spy_hist = fetch_history("SPY", str(start), str(end))
    events: list[DrawdownEvent] = []
    print(f"[shakeout] tickers={len(tickers)} years={args.years} output={output_dir}")
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
        events.extend(
            detect_drawdown_events(
                ticker,
                hist,
                spy_hist=spy_hist,
                min_drop=args.min_drop,
                lookback_days=args.lookback_days,
                min_gap_days=args.min_gap_days,
            )
        )
        if args.sleep:
            time.sleep(args.sleep)

    events_df = pd.DataFrame([asdict(e) for e in events])
    if not events_df.empty:
        events_df = events_df.sort_values(["event_date", "ticker"]).reset_index(drop=True)
    action_df = build_action_replay(events_df)
    summary = summarize(events_df, action_df, args)

    events_df.to_csv(output_dir / "events.csv", index=False)
    action_df.to_csv(output_dir / "action_replay.csv", index=False)
    write_csv(
        output_dir / "action_summary.csv",
        summary.get("action_summary", []),
        ["label", "horizon", "action", "n", "avg_return", "median_return", "hit_rate", "worst_return", "best_return"],
    )
    write_json(output_dir / "pattern_summary.json", summary)
    (output_dir / "shakeout_breakdown_report.md").write_text(render_report(summary, events_df), encoding="utf-8")
    (output_dir / "system_policy_candidates.yaml").write_text(render_policy_yaml(summary), encoding="utf-8")
    print(f"[shakeout] wrote {output_dir} events={len(events_df)}")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", default="", help="comma-separated explicit tickers")
    parser.add_argument("--ticker-file", default="", help="CSV/text ticker list")
    parser.add_argument("--scored", default="", help="scored_latest.csv to source a universe")
    parser.add_argument("--top-tickers", type=int, default=0, help="if --scored, optionally use top N by score")
    parser.add_argument("--limit", type=int, default=0, help="debug limit after loading tickers")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--min-current-mcap-usd", type=float, default=5_000_000_000.0)
    parser.add_argument("--min-dollar-vol-20d", type=float, default=20_000_000.0)
    parser.add_argument("--min-drop", type=float, default=0.12, help="minimum drawdown from 6m high to label an event")
    parser.add_argument("--lookback-days", type=int, default=126, help="prior peak lookback")
    parser.add_argument("--min-gap-days", type=int, default=42, help="minimum gap between events per ticker")
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps({
        "event_count": summary.get("event_count"),
        "label_counts": summary.get("label_counts"),
        "production_activation_allowed": summary.get("production_activation_allowed"),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
