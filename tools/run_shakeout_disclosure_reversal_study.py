#!/usr/bin/env python3
"""Research-only shakeout plus disclosure reversal study.

This tool looks for the CRDO-style pattern:

* a strong/leader stock suffers a fast reset from a recent high,
* volume expands during the reset instead of simply drying up,
* a disclosure or fundamental catalyst appears near the reset
  (13F/Form 4/ETF/earnings event rows), and
* price reclaims/rebounds with confirmation after the catalyst.

Outputs are research-only. They are intended for post-disclosure learning and
challenger tests, not production score activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_EVENTS = "data_pit/sec/13f_position_events.parquet"
DEFAULT_PRICE_CACHE = "cache_prices"
DEFAULT_OUTPUT_DIR = "outputs/shakeout_disclosure_reversal_study"

OUTPUT_COLUMNS = [
    "event_id",
    "source_type",
    "manager_cik",
    "manager_name",
    "ticker",
    "event_type",
    "available_from",
    "event_seed_score",
    "manager_quality_score",
    "prior_peak_date",
    "prior_peak_close",
    "event_date",
    "event_close",
    "shakeout_low_date",
    "shakeout_low",
    "reset_window_days",
    "drawdown_from_prior_peak",
    "days_peak_to_low",
    "max_volume_ratio_reset_window",
    "max_volume_ratio_around_event",
    "volume_ratio_at_low",
    "sma50_at_event",
    "sma200_at_event",
    "price_vs_sma50_at_event",
    "price_vs_sma200_at_event",
    "ret_5d",
    "ret_21d",
    "ret_63d",
    "max_dd_21d",
    "max_dd_63d",
    "rebound_from_low_21d",
    "rebound_from_low_63d",
    "reclaim_prior_peak_21d",
    "reclaim_prior_peak_63d",
    "days_to_reclaim_prior_peak",
    "up_day_volume_confirmation",
    "shakeout_setup_score",
    "post_catalyst_confirmation_score",
    "shakeout_disclosure_reversal_score",
    "label_complete_21d",
    "label_complete_63d",
    "success_21d",
    "success_63d",
    "pattern_bucket",
    "research_only",
    "production_activation_allowed",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def px_cache_name(ticker: str) -> str:
    return f"{hashlib.sha1(str(ticker).upper().encode('utf-8')).hexdigest()[:16]}.parquet"


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat() if pd.notna(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def clip01(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def read_events(paths: list[Path]) -> pd.DataFrame:
    frames = [read_table(path) for path in paths if path.exists()]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True, sort=False)
    if "available_from" not in d.columns and "accepted_at" in d.columns:
        d["available_from"] = d["accepted_at"]
    if "event_seed_score" not in d.columns:
        for col in ("post_disclosure_event_seed_score", "etf_event_seed_score", "sec_13f_smart_money_score"):
            if col in d.columns:
                d["event_seed_score"] = d[col]
                break
    if "event_seed_score" not in d.columns:
        d["event_seed_score"] = 0.0
    d["ticker"] = d.get("ticker", "").fillna("").astype(str).str.upper().str.strip()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True).dt.tz_convert(None)
    d = d[d["ticker"].ne("") & d["available_from_ts"].notna()].copy()
    if "event_id" not in d.columns:
        d["event_id"] = [f"event:{i}" for i in range(len(d))]
    return d.sort_values(["available_from_ts", "ticker", "event_id"]).reset_index(drop=True)


def load_price_history(price_cache: Path, ticker: str) -> pd.DataFrame:
    path = price_cache / px_cache_name(ticker)
    if not path.exists():
        return pd.DataFrame()
    try:
        px = pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
    if px.empty:
        return pd.DataFrame()
    px = px.copy()
    px.index = pd.to_datetime(px.index, errors="coerce").tz_localize(None)
    px = px[px.index.notna()].sort_index()
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    close_col = "Adj Close" if "Adj Close" in px.columns else "Close"
    if close_col not in px.columns:
        return pd.DataFrame()
    out = pd.DataFrame(index=px.index)
    raw_close = pd.to_numeric(px.get("Close", px[close_col]), errors="coerce")
    adj_close = pd.to_numeric(px[close_col], errors="coerce")
    adjust = adj_close / raw_close.replace(0, np.nan)
    for source, target in [("Open", "open"), ("High", "high"), ("Low", "low")]:
        if source in px.columns:
            values = pd.to_numeric(px[source], errors="coerce")
            if close_col == "Adj Close" and "Close" in px.columns:
                values = values * adjust
            out[target] = values
    out["close"] = adj_close
    out["volume"] = pd.to_numeric(px.get("Volume", np.nan), errors="coerce")
    if "high" not in out.columns:
        out["high"] = out["close"]
    if "low" not in out.columns:
        out["low"] = out["close"]
    if "open" not in out.columns:
        out["open"] = out["close"]
    return out.dropna(subset=["close"]).sort_index()


def manager_quality_score(event: pd.Series) -> float:
    candidates = [
        safe_float(event.get("manager_disclosure_alpha_score"), math.nan),
        safe_float(event.get("manager_alpha_score"), math.nan),
        safe_float(event.get("manager_confidence"), math.nan),
    ]
    base = max([x for x in candidates if math.isfinite(x)] or [0.0])
    perf = max(
        safe_float(event.get("external_performance_2y"), math.nan),
        safe_float(event.get("performance_2y"), math.nan),
        safe_float(event.get("perf_3y"), math.nan),
    )
    if math.isfinite(perf):
        base = max(base, clip01(perf / 200.0))
    rank = min(
        safe_float(event.get("manager_rank"), math.inf),
        safe_float(event.get("rank"), math.inf),
        safe_float(event.get("user_priority"), math.inf),
    )
    if math.isfinite(rank) and rank <= 10:
        base = max(base, 1.0 - (rank - 1.0) / 12.0)
    return clip01(base)


def trading_offset(px: pd.DataFrame, date_like: Any, offset: int) -> tuple[pd.Timestamp | None, int]:
    idx = pd.DatetimeIndex(px.index)
    pos = int(idx.searchsorted(pd.Timestamp(date_like), side="left"))
    pos = min(max(pos + int(offset), 0), len(idx) - 1)
    if len(idx) == 0:
        return None, -1
    return pd.Timestamp(idx[pos]), pos


def window_slice(px: pd.DataFrame, center_pos: int, before: int, after: int) -> pd.DataFrame:
    start = max(0, center_pos - int(before))
    end = min(len(px), center_pos + int(after) + 1)
    return px.iloc[start:end].copy()


def ret_at(px: pd.DataFrame, pos: int, horizon: int, entry_price: float) -> float:
    target = pos + int(horizon)
    if target >= len(px) or not math.isfinite(entry_price) or entry_price <= 0:
        return math.nan
    return float(px["close"].iloc[target] / entry_price - 1.0)


def max_drawdown_after(px: pd.DataFrame, pos: int, horizon: int, entry_price: float) -> float:
    if not math.isfinite(entry_price) or entry_price <= 0:
        return math.nan
    end = min(len(px), pos + int(horizon) + 1)
    window = pd.to_numeric(px["low"].iloc[pos:end], errors="coerce").dropna()
    if window.empty:
        return math.nan
    return float((window / entry_price - 1.0).min())


def analyze_event(
    event: pd.Series,
    px: pd.DataFrame,
    *,
    peak_window: int,
    reset_window: int,
    event_window: int,
) -> dict[str, Any] | None:
    if px.empty:
        return None
    event_date, event_pos = trading_offset(px, event.get("available_from_ts"), 0)
    if event_date is None or event_pos < 5:
        return None
    prior = px.iloc[max(0, event_pos - peak_window): event_pos + 1].copy()
    if prior.empty:
        return None
    prior_peak_close = float(prior["close"].max())
    prior_peak_date = pd.Timestamp(prior["close"].idxmax())
    prior_peak_pos = int(pd.DatetimeIndex(px.index).get_loc(prior_peak_date))
    around = window_slice(px, event_pos, event_window, event_window)
    if around.empty or prior_peak_close <= 0:
        return None
    reset_start = max(0, min(prior_peak_pos, event_pos - int(reset_window)))
    reset_end = min(len(px), event_pos + int(event_window) + 1)
    reset = px.iloc[reset_start:reset_end].copy()
    reset_after_peak = reset.loc[reset.index >= prior_peak_date].copy()
    low_source = reset_after_peak if not reset_after_peak.empty else around
    low_date = pd.Timestamp(low_source["low"].idxmin())
    low_price = float(low_source.loc[low_date, "low"])
    low_pos = int(pd.DatetimeIndex(px.index).get_loc(low_date))
    event_close = float(px["close"].iloc[event_pos])
    close = pd.to_numeric(px["close"], errors="coerce")
    volume = pd.to_numeric(px["volume"], errors="coerce")
    vol20 = volume.rolling(20, min_periods=5).mean().shift(1)
    vol_ratio = volume / vol20.replace(0, np.nan)
    max_vol_ratio_reset = safe_float(vol_ratio.iloc[reset_start:reset_end].max(), math.nan)
    max_vol_ratio = safe_float(vol_ratio.iloc[max(0, event_pos - event_window): min(len(px), event_pos + event_window + 1)].max(), math.nan)
    low_vol_ratio = safe_float(vol_ratio.iloc[low_pos], math.nan)
    sma50 = safe_float(close.iloc[max(0, event_pos - 49): event_pos + 1].mean(), math.nan)
    sma200 = safe_float(close.iloc[max(0, event_pos - 199): event_pos + 1].mean(), math.nan)
    drawdown = low_price / prior_peak_close - 1.0
    days_peak_to_low = int((low_date - prior_peak_date).days)
    event_seed = safe_float(event.get("event_seed_score"), 0.0)
    m_quality = manager_quality_score(event)
    event_type = str(event.get("event_type", "")).lower()
    positive_disclosure = event_seed > 0.10 or "new" in event_type or "add" in event_type or "buy" in event_type

    ret5 = ret_at(px, event_pos, 5, event_close)
    ret21 = ret_at(px, event_pos, 21, event_close)
    ret63 = ret_at(px, event_pos, 63, event_close)
    max_dd21 = max_drawdown_after(px, event_pos, 21, event_close)
    max_dd63 = max_drawdown_after(px, event_pos, 63, event_close)

    forward21 = px.iloc[event_pos: min(len(px), event_pos + 22)].copy()
    reclaim_hits = forward21[forward21["close"] >= prior_peak_close] if not forward21.empty else pd.DataFrame()
    forward63 = px.iloc[event_pos: min(len(px), event_pos + 64)].copy()
    reclaim_hits_63 = forward63[forward63["close"] >= prior_peak_close] if not forward63.empty else pd.DataFrame()
    reclaimed = not reclaim_hits.empty
    reclaimed63 = not reclaim_hits_63.empty
    first_reclaim = reclaim_hits.index[0] if reclaimed else (reclaim_hits_63.index[0] if reclaimed63 else None)
    days_to_reclaim = int((pd.Timestamp(first_reclaim) - event_date).days) if first_reclaim is not None else -1
    rebound_from_low = float(forward21["close"].max() / low_price - 1.0) if not forward21.empty and low_price > 0 else math.nan
    rebound_from_low_63 = float(forward63["close"].max() / low_price - 1.0) if not forward63.empty and low_price > 0 else math.nan
    up_days = px.iloc[event_pos: min(len(px), event_pos + 6)].copy()
    up_day_vol_confirm = 0
    if len(up_days) >= 2:
        rets = up_days["close"].pct_change()
        ratios = vol_ratio.loc[up_days.index]
        up_day_vol_confirm = int(bool(((rets > 0.03) & (ratios >= 1.10)).any()))

    fast_reset = -0.45 <= drawdown <= -0.12 and 0 <= days_peak_to_low <= 21
    long_reset = -0.65 <= drawdown <= -0.20 and 22 <= days_peak_to_low <= 150
    max_vol_signal = max([x for x in [max_vol_ratio, max_vol_ratio_reset] if math.isfinite(x)] or [0.0])
    setup_checks = [
        (fast_reset or long_reset, 0.24),
        (0 <= days_peak_to_low <= 150, 0.12),
        (max_vol_signal >= 1.15, 0.14),
        (positive_disclosure, 0.20),
        (m_quality >= 0.40, 0.15),
        ((event_close / sma200 - 1.0) >= -0.20 if math.isfinite(sma200) and sma200 > 0 else True, 0.15),
    ]
    setup_score = sum(w for ok, w in setup_checks if bool(ok)) / sum(w for _, w in setup_checks)
    confirmation_checks = [
        (ret5 >= 0.05 if math.isfinite(ret5) else False, 0.16),
        (rebound_from_low >= 0.15 if math.isfinite(rebound_from_low) else False, 0.20),
        (reclaimed or reclaimed63, 0.25),
        (up_day_vol_confirm == 1, 0.16),
        (max_dd21 >= -0.12 if math.isfinite(max_dd21) else False, 0.10),
        (ret21 >= 0.10 if math.isfinite(ret21) else False, 0.13),
    ]
    confirmation_score = sum(w for ok, w in confirmation_checks if bool(ok)) / sum(w for _, w in confirmation_checks)
    total_score = 0.55 * setup_score + 0.45 * confirmation_score
    if setup_score >= 0.60 and confirmation_score >= 0.60:
        bucket = "long_base_shakeout_reversal_confirmed" if long_reset else "shakeout_reversal_confirmed"
    elif setup_score >= 0.60:
        bucket = "shakeout_watch_needs_confirmation"
    elif drawdown <= -0.45 or (math.isfinite(max_dd21) and max_dd21 <= -0.25):
        bucket = "possible_breakdown"
    else:
        bucket = "neutral"

    return {
        "event_id": str(event.get("event_id", "")),
        "source_type": str(event.get("source_type", "")),
        "manager_cik": str(event.get("manager_cik", "")),
        "manager_name": str(event.get("manager_name", "")),
        "ticker": str(event.get("ticker", "")).upper(),
        "event_type": str(event.get("event_type", "")),
        "available_from": str(event.get("available_from", "")),
        "event_seed_score": event_seed,
        "manager_quality_score": m_quality,
        "prior_peak_date": prior_peak_date.date().isoformat(),
        "prior_peak_close": prior_peak_close,
        "event_date": event_date.date().isoformat(),
        "event_close": event_close,
        "shakeout_low_date": low_date.date().isoformat(),
        "shakeout_low": low_price,
        "reset_window_days": int(reset_window),
        "drawdown_from_prior_peak": drawdown,
        "days_peak_to_low": days_peak_to_low,
        "max_volume_ratio_reset_window": max_vol_ratio_reset,
        "max_volume_ratio_around_event": max_vol_ratio,
        "volume_ratio_at_low": low_vol_ratio,
        "sma50_at_event": sma50,
        "sma200_at_event": sma200,
        "price_vs_sma50_at_event": event_close / sma50 - 1.0 if math.isfinite(sma50) and sma50 > 0 else math.nan,
        "price_vs_sma200_at_event": event_close / sma200 - 1.0 if math.isfinite(sma200) and sma200 > 0 else math.nan,
        "ret_5d": ret5,
        "ret_21d": ret21,
        "ret_63d": ret63,
        "max_dd_21d": max_dd21,
        "max_dd_63d": max_dd63,
        "rebound_from_low_21d": rebound_from_low,
        "rebound_from_low_63d": rebound_from_low_63,
        "reclaim_prior_peak_21d": int(reclaimed),
        "reclaim_prior_peak_63d": int(reclaimed63),
        "days_to_reclaim_prior_peak": days_to_reclaim,
        "up_day_volume_confirmation": up_day_vol_confirm,
        "shakeout_setup_score": setup_score,
        "post_catalyst_confirmation_score": confirmation_score,
        "shakeout_disclosure_reversal_score": total_score,
        "label_complete_21d": int(math.isfinite(ret21)),
        "label_complete_63d": int(math.isfinite(ret63)),
        "success_21d": (
            int(ret21 > 0.10 and (not math.isfinite(max_dd21) or max_dd21 > -0.18))
            if math.isfinite(ret21)
            else math.nan
        ),
        "success_63d": (
            int(ret63 > 0.20 and (not math.isfinite(max_dd63) or max_dd63 > -0.25))
            if math.isfinite(ret63)
            else math.nan
        ),
        "pattern_bucket": bucket,
        "research_only": True,
        "production_activation_allowed": False,
    }


def build_summary(events: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        return {
            "schema_version": "shakeout-disclosure-reversal-v2",
            "research_only": True,
            "production_activation_allowed": False,
            "event_count": 0,
        }
    bucket_counts = events["pattern_bucket"].value_counts(dropna=False).to_dict()
    score = pd.to_numeric(events["shakeout_disclosure_reversal_score"], errors="coerce")
    by_bucket: list[dict[str, Any]] = []
    for bucket, group in events.groupby("pattern_bucket", dropna=False):
        by_bucket.append(
            {
                "pattern_bucket": bucket,
                "rows": int(len(group)),
                "avg_score": safe_float(pd.to_numeric(group["shakeout_disclosure_reversal_score"], errors="coerce").mean(), 0.0),
                "success_21d_rate": safe_float(pd.to_numeric(group["success_21d"], errors="coerce").mean(), 0.0),
                "success_63d_rate": safe_float(pd.to_numeric(group["success_63d"], errors="coerce").mean(), 0.0),
                "avg_ret_21d": safe_float(pd.to_numeric(group["ret_21d"], errors="coerce").mean(), math.nan),
                "avg_ret_63d": safe_float(pd.to_numeric(group["ret_63d"], errors="coerce").mean(), math.nan),
            }
        )
    top = events.sort_values("shakeout_disclosure_reversal_score", ascending=False).head(20)
    return {
        "schema_version": "shakeout-disclosure-reversal-v2",
        "research_only": True,
        "production_activation_allowed": False,
        "event_count": int(len(events)),
        "mean_score": safe_float(score.mean(), 0.0),
        "confirmed_count": int(
            bucket_counts.get("shakeout_reversal_confirmed", 0)
            + bucket_counts.get("long_base_shakeout_reversal_confirmed", 0)
        ),
        "watch_count": int(bucket_counts.get("shakeout_watch_needs_confirmation", 0)),
        "label_complete_21d_count": int(pd.to_numeric(events["label_complete_21d"] if "label_complete_21d" in events.columns else pd.Series(dtype=float), errors="coerce").fillna(0).sum()),
        "label_complete_63d_count": int(pd.to_numeric(events["label_complete_63d"] if "label_complete_63d" in events.columns else pd.Series(dtype=float), errors="coerce").fillna(0).sum()),
        "bucket_counts": bucket_counts,
        "by_bucket": by_bucket,
        "top_candidates": top[["ticker", "available_from", "pattern_bucket", "shakeout_disclosure_reversal_score", "drawdown_from_prior_peak", "ret_21d", "ret_63d"]].to_dict(orient="records"),
        "notes": [
            "Research-only CRDO-style pattern: fast or 3-6 month reset, volume expansion, disclosure catalyst, and reclaim confirmation.",
            "Do not use this as production evidence until broker-ledger challenger improves CAGR/MDD.",
            "13F availability must use accepted_at/available_from, not report_period.",
        ],
    }


def render_report(summary: dict[str, Any], events: pd.DataFrame) -> str:
    lines = [
        "# Shakeout Disclosure Reversal Study",
        "",
        "Research-only study for CRDO-style reset plus disclosure-catalyst reversals.",
        "",
        f"- events: {summary.get('event_count', 0)}",
        f"- confirmed: {summary.get('confirmed_count', 0)}",
        f"- watch: {summary.get('watch_count', 0)}",
        f"- mean_score: {safe_float(summary.get('mean_score'), 0.0):.3f}",
        "",
        "## Rules",
        "",
        "- Production activation is not allowed.",
        "- The pattern can be used only as a challenger or watchlist signal.",
        "- Future returns are labels for learning, not live-score inputs.",
        "",
    ]
    if not events.empty:
        lines.extend(["## Top Events", "", "| ticker | date | bucket | score | drawdown | ret_21d | ret_63d |", "|---|---:|---|---:|---:|---:|---:|"])
        top = events.sort_values("shakeout_disclosure_reversal_score", ascending=False).head(15)
        for _, row in top.iterrows():
            lines.append(
                "| {ticker} | {date} | {bucket} | {score:.3f} | {dd:.1%} | {r21:.1%} | {r63:.1%} |".format(
                    ticker=row.get("ticker", ""),
                    date=row.get("event_date", ""),
                    bucket=row.get("pattern_bucket", ""),
                    score=safe_float(row.get("shakeout_disclosure_reversal_score"), 0.0),
                    dd=safe_float(row.get("drawdown_from_prior_peak"), math.nan),
                    r21=safe_float(row.get("ret_21d"), math.nan),
                    r63=safe_float(row.get("ret_63d"), math.nan),
                )
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    event_paths = [repo_path(part.strip()) for item in args.events for part in str(item).split(",") if part.strip()]
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    events = read_events(event_paths)
    rows: list[dict[str, Any]] = []
    for ticker, group in events.groupby("ticker", sort=True):
        px = load_price_history(price_cache, ticker)
        if px.empty:
            continue
        for _, event in group.iterrows():
            row = analyze_event(
                event,
                px,
                peak_window=int(args.peak_window),
                reset_window=int(args.reset_window),
                event_window=int(args.event_window),
            )
            if row is not None:
                rows.append(row)
    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_table(out, output_dir / "events.csv")
    write_table(out, output_dir / "events.parquet")
    summary = build_summary(out)
    write_json(output_dir / "pattern_summary.json", summary)
    (output_dir / "shakeout_disclosure_reversal_report.md").write_text(render_report(summary, out), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only CRDO-style shakeout plus disclosure reversal study")
    parser.add_argument("--events", action="append", default=[DEFAULT_EVENTS], help="CSV/parquet disclosure event file; repeat or comma-separate")
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--peak-window", type=int, default=126)
    parser.add_argument("--reset-window", type=int, default=126)
    parser.add_argument("--event-window", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(f"[shakeout-disclosure] events={summary.get('event_count', 0)} confirmed={summary.get('confirmed_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
