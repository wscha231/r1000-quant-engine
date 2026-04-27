#!/usr/bin/env python3
"""Daily tactical alpha monitor for the r1000 engine.

This is intentionally separate from the main/core portfolio engine:

* core/concentrated remain monthly research engines.
* tactical_alpha runs after the US close, checks the latest valid NYSE
  trading day, and proposes trades only when a stronger entry or an exit
  condition exists.
* weekends and US market holidays are no-ops when no new trading session is
  available.

Inputs are existing full-rebuild artifacts plus local/GitHub price caches.
The script can refresh a bounded candidate set with yfinance so the daily
workflow does not need to rebuild fundamentals every night.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional for offline local review
    yf = None

from r1000_config import EngineConfig
from r1000_helpers import get_paths, normalize_ticker, safe_mkdir, to_yf_symbol
from r1000_pipeline import (
    CASH_PROXY_TICKER,
    compute_daily_tech_table,
    get_nyse_days,
    load_px,
    prepare_concentrated_frame,
    save_px,
)


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_SUBDIR = "tactical_alpha"
DEFAULT_CLOUD_LATEST = REPO_ROOT / "cloud_results" / "full_rebuild" / "latest_global_alpha_universe"
DEFAULT_CLOUD_TACTICAL = REPO_ROOT / "cloud_results" / "tactical_alpha" / "latest"


@dataclass
class LoadedFrame:
    frame: pd.DataFrame
    path: Optional[Path]


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return None if not math.isfinite(val) else val
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    return str(obj)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_table(path: Path) -> pd.DataFrame:
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _first_existing(paths: Iterable[Path]) -> Optional[Path]:
    for path in paths:
        if path and path.exists():
            return path
    return None


def load_scored_latest(base_dir: Path, explicit: Optional[str] = None) -> LoadedFrame:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(
        [
            base_dir / "outputs" / "scored_latest.csv",
            base_dir / "feature_store" / "scored_latest.parquet",
            DEFAULT_CLOUD_LATEST / "scored_latest.csv",
            REPO_ROOT / "cloud_results" / "full_rebuild" / "20260427_global_alpha_universe" / "scored_latest.csv",
            REPO_ROOT / "research" / "github_runs" / "24974747494" / "artifact" / "scored_latest.csv",
            REPO_ROOT / "research" / "phase14_artifact" / "scored_latest.csv",
        ]
    )
    path = _first_existing(candidates)
    if path is None:
        raise FileNotFoundError("No scored_latest.csv/parquet found. Run a full rebuild first.")
    frame = _read_table(path)
    if frame.empty:
        raise RuntimeError(f"Scored file exists but loaded empty: {path}")
    return LoadedFrame(frame=frame, path=path)


def load_previous_holdings(base_dir: Path, explicit: Optional[str] = None) -> LoadedFrame:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.extend(
        [
            base_dir / "outputs" / DEFAULT_OUTPUT_SUBDIR / "tactical_portfolio_latest.csv",
            DEFAULT_CLOUD_TACTICAL / "tactical_portfolio_latest.csv",
            base_dir / "outputs" / "concentrated_portfolio_latest.csv",
            DEFAULT_CLOUD_LATEST / "concentrated_portfolio_latest.csv",
        ]
    )
    path = _first_existing(candidates)
    if path is None:
        return LoadedFrame(frame=pd.DataFrame(), path=None)
    return LoadedFrame(frame=_read_csv(path), path=path)


def load_previous_summary(base_dir: Path) -> dict[str, Any]:
    candidates = [
        base_dir / "outputs" / DEFAULT_OUTPUT_SUBDIR / "tactical_run_summary.json",
        DEFAULT_CLOUD_TACTICAL / "tactical_run_summary.json",
    ]
    path = _first_existing(candidates)
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def latest_nyse_day_on_or_before(date_like: Any) -> pd.Timestamp:
    dt = pd.to_datetime(date_like, errors="coerce")
    if pd.isna(dt):
        dt = pd.Timestamp.utcnow()
    dt = pd.Timestamp(dt).tz_localize(None).normalize()
    start = dt - pd.Timedelta(days=14)
    days = get_nyse_days(str(start.date()), str(dt.date()))
    days = pd.DatetimeIndex(days)
    days = days[days <= dt]
    if len(days) == 0:
        raise RuntimeError(f"No NYSE trading day found on or before {dt.date()}")
    return pd.Timestamp(days[-1]).normalize()


def latest_snapshot(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp]:
    d = scored.copy()
    if "ticker" not in d.columns:
        raise ValueError("scored frame missing ticker column")
    if "rebalance_date" not in d.columns:
        raise ValueError("scored frame missing rebalance_date column")
    d["ticker"] = d["ticker"].astype(str).map(lambda x: normalize_ticker(x) or str(x).upper())
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce")
    d = d.dropna(subset=["ticker", "rebalance_date"])
    latest_dt = pd.Timestamp(d["rebalance_date"].max()).normalize()
    snap = d[d["rebalance_date"].eq(latest_dt)].copy()
    if snap.empty:
        raise RuntimeError("No latest scored snapshot found")
    return snap, latest_dt


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(float(default), index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").fillna(float(default)).astype(float)


def _rank01(series: pd.Series, default: float = 0.5) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() <= 1:
        return pd.Series(float(default), index=series.index, dtype=float)
    out = s.rank(pct=True)
    return out.fillna(float(default)).astype(float)


def _bool_series(df: pd.DataFrame, col: str, default: bool = False) -> pd.Series:
    if col not in df.columns:
        return pd.Series(bool(default), index=df.index, dtype=bool)
    raw = df[col]
    if raw.dtype == bool:
        return raw.fillna(bool(default)).astype(bool)
    text = raw.astype(str).str.strip().str.lower()
    return text.isin({"1", "true", "t", "yes", "y"}).fillna(bool(default))


def _latest_tech_row(paths: dict[str, Path], ticker: str, as_of: pd.Timestamp) -> dict[str, Any]:
    px = load_px(paths, ticker)
    if px is None or px.empty:
        return {"ticker": ticker, "price_data_status": "missing_price_cache"}
    tech = compute_daily_tech_table(px)
    if tech.empty:
        return {"ticker": ticker, "price_data_status": "empty_tech_table"}
    tech = tech[tech.index <= pd.Timestamp(as_of)]
    if tech.empty:
        return {"ticker": ticker, "price_data_status": "no_price_on_or_before_asof"}
    row = tech.iloc[-1].to_dict()
    row["ticker"] = ticker
    row["price_as_of"] = pd.Timestamp(tech.index[-1]).date().isoformat()
    row["price_data_status"] = "ok"
    return row


def refresh_price_cache(
    paths: dict[str, Path],
    tickers: list[str],
    as_of: pd.Timestamp,
    *,
    max_updates: int,
    period: str = "10y",
) -> dict[str, Any]:
    summary = {
        "requested": int(len(tickers)),
        "max_updates": int(max_updates),
        "updated": 0,
        "skipped_fresh": 0,
        "failed": 0,
        "failures": [],
    }
    if yf is None:
        summary["disabled_reason"] = "yfinance_unavailable"
        return summary
    for ticker in tickers[: max(int(max_updates), 0)]:
        if str(ticker).upper() == CASH_PROXY_TICKER:
            continue
        existing = load_px(paths, ticker)
        if existing is not None and not existing.empty:
            last_dt = pd.Timestamp(existing.index.max()).tz_localize(None).normalize()
            if last_dt >= pd.Timestamp(as_of).normalize():
                summary["skipped_fresh"] += 1
                continue
        try:
            yf_symbol = to_yf_symbol(ticker)
            df = yf.download(
                yf_symbol,
                period=period,
                auto_adjust=False,
                actions=True,
                progress=False,
                threads=False,
            )
            if df is None or df.empty:
                raise RuntimeError("empty yfinance payload")
            save_px(paths, ticker, df)
            summary["updated"] += 1
        except Exception as exc:  # pragma: no cover - network dependent
            summary["failed"] += 1
            if len(summary["failures"]) < 20:
                summary["failures"].append({"ticker": ticker, "error": str(exc)[:180]})
    return summary


def normalize_prev_weights(prev: pd.DataFrame) -> dict[str, float]:
    if prev.empty or "ticker" not in prev.columns:
        return {}
    weight_col = "weight" if "weight" in prev.columns else None
    if weight_col is None:
        return {}
    out: dict[str, float] = {}
    for _, row in prev.iterrows():
        t = normalize_ticker(row.get("ticker"))
        if not t or t.upper() == CASH_PROXY_TICKER:
            continue
        w = pd.to_numeric(pd.Series([row.get(weight_col)]), errors="coerce").iloc[0]
        if pd.notna(w) and float(w) > 0:
            out[t] = out.get(t, 0.0) + float(w)
    total = sum(out.values())
    if total > 0:
        out = {k: float(v / total) for k, v in out.items()}
    return out


def build_candidate_frame(
    cfg: EngineConfig,
    paths: dict[str, Path],
    scored_latest: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    preliminary_limit: int,
    min_price: float,
    min_dollar_vol: float,
) -> pd.DataFrame:
    d = prepare_concentrated_frame(cfg, scored_latest)
    if d.empty:
        return d
    if "score" not in d.columns:
        d["score"] = _num(d, "score_total", 0.0)
    if "concentrated_score" not in d.columns:
        d["concentrated_score"] = _num(d, "score", 0.0)
    if "ranking_eligible" in d.columns:
        eligible = _bool_series(d, "ranking_eligible", True)
        d = d[eligible].copy()
    d = d.sort_values(["concentrated_score", "score"], ascending=False).head(int(preliminary_limit)).copy()

    tech_rows = [_latest_tech_row(paths, str(t), as_of) for t in d["ticker"].astype(str).tolist()]
    tech = pd.DataFrame(tech_rows)
    if tech.empty:
        return d.iloc[0:0].copy()
    merged = d.merge(tech, on="ticker", how="left")
    for col in [
        "px",
        "open_px",
        "dividends_ttm_ps",
        "dividend_yield_ttm",
        "mom_1m",
        "mom_3m",
        "mom_6m",
        "mom_12m",
        "mom_18m",
        "mom_24m",
        "mom_36m",
        "dist_ma200",
        "price_above_ma20",
        "price_above_ma50",
        "price_above_ma200",
        "golden_cross_fresh_20d",
        "death_cross_recent_20d",
        "trend_template_full",
        "trend_template_relaxed",
        "near_52w_high_pct",
        "breakout_distance_63d",
        "breakout_fresh_20d",
        "breakout_volume_z",
        "volume_dryup_20d",
        "volatility_contraction_score",
        "atr14_pct",
        "post_breakout_hold_score",
        "rsi14",
        "macd_hist",
        "bb_pb",
        "obv_trend",
        "vol_252d",
        "dd_1y",
        "dollar_vol_20d",
    ]:
        daily_col = f"{col}_y"
        scored_col = f"{col}_x"
        if daily_col in merged.columns:
            merged[col] = merged[daily_col]
        elif col not in merged.columns and scored_col in merged.columns:
            merged[col] = merged[scored_col]
    merged["px"] = _num(merged, "px", np.nan)
    merged["dollar_vol_20d"] = _num(merged, "dollar_vol_20d", 0.0)

    liquidity_ok = merged["px"].ge(float(min_price)) & merged["dollar_vol_20d"].ge(float(min_dollar_vol))
    data_ok = merged.get("price_data_status", pd.Series("", index=merged.index)).astype(str).eq("ok")
    merged = merged[data_ok & liquidity_ok].copy()
    if merged.empty:
        return merged

    confirmation = _num(merged, "selection_confirmation_score", 0.0)
    exit_risk = _num(merged, "portfolio_hold_policy_exit_risk", 0.0)
    broken = _num(merged, "broken_momentum_penalty", 0.0)
    above20 = _num(merged, "price_above_ma20", 0.0)
    above50 = _num(merged, "price_above_ma50", 0.0)
    above200 = _num(merged, "price_above_ma200", 0.0)
    dist200 = _num(merged, "dist_ma200", 0.0)
    rsi = _num(merged, "rsi14", 50.0)
    death = _num(merged, "death_cross_recent_20d", 0.0)

    merged["tactical_hard_exit"] = (
        ((above20 <= 0.0) & (above50 <= 0.0))
        | (above200 <= 0.0)
        | (dist200 < -0.08)
        | (rsi < 38.0)
        | (death > 0.0)
        | (exit_risk >= 0.75)
    )
    merged["tactical_soft_exit"] = (
        (above20 <= 0.0)
        | (exit_risk >= 0.55)
        | (broken >= 0.55)
        | (confirmation < 0.35)
    )

    terms = [
        1.20 * _rank01(_num(merged, "concentrated_score", 0.0)),
        0.85 * _rank01(_num(merged, "score", 0.0)),
        0.80 * _rank01(_num(merged, "relative_strength_composite", 0.0)),
        0.65 * _rank01(_num(merged, "mom_3m", 0.0)),
        0.55 * _rank01(_num(merged, "mom_6m", 0.0)),
        0.45 * _rank01(_num(merged, "mom_1m", 0.0)),
        0.70 * _num(merged, "portfolio_future_winner_engine_score", 0.0),
        0.55 * _num(merged, "portfolio_early_scout_engine_score", 0.0),
        0.35 * _num(merged, "selection_confirmation_score", 0.0),
        0.45 * _num(merged, "trend_template_full", 0.0),
        0.35 * _num(merged, "price_above_ma20", 0.0),
        0.35 * _num(merged, "price_above_ma50", 0.0),
        0.30 * _num(merged, "price_above_ma200", 0.0),
        0.35 * _num(merged, "breakout_fresh_20d", 0.0),
        0.25 * _num(merged, "post_breakout_hold_score", 0.0),
        0.20 * _num(merged, "minervini_momentum_alive_score", 0.0),
        -0.55 * _num(merged, "portfolio_hold_policy_exit_risk", 0.0),
        -0.30 * _num(merged, "broken_momentum_penalty", 0.0),
    ]
    weight_sum = 8.85
    merged["tactical_rank_score"] = sum(terms) / weight_sum
    merged["tactical_rank_score"] = merged["tactical_rank_score"].clip(lower=0.0, upper=1.0)
    merged["tactical_entry_eligible"] = (
        merged["tactical_rank_score"].ge(0.58)
        & confirmation.ge(0.35)
        & above50.ge(1.0)
        & above200.ge(1.0)
        & ~merged["tactical_hard_exit"].astype(bool)
    )
    merged = merged.sort_values(
        ["tactical_rank_score", "concentrated_score", "score"],
        ascending=False,
    ).reset_index(drop=True)
    merged["tactical_rank"] = np.arange(1, len(merged) + 1)
    return merged


def _normalize_score_weights(selected: pd.DataFrame, max_single_weight: float) -> pd.Series:
    if selected.empty:
        return pd.Series(dtype=float)
    score = _num(selected, "tactical_rank_score", 0.0)
    raw = np.power((score - score.min() + 0.20).clip(lower=0.05), 2.0)
    w = pd.Series(raw, index=selected.index, dtype=float)
    cap = float(max(min(max_single_weight, 1.0), 0.01))
    for _ in range(20):
        total = float(w.sum())
        if total <= 0:
            break
        w = w / total
        over = w > cap
        if not over.any():
            return w / float(w.sum())
        excess = float((w[over] - cap).sum())
        w[over] = cap
        under = ~over
        if not under.any() or excess <= 1e-12:
            break
        under_total = float(w[under].sum())
        if under_total > 0:
            w[under] = w[under] + excess * (w[under] / under_total)
    total = float(w.sum())
    return w / total if total > 0 else pd.Series(1.0 / len(selected), index=selected.index)


def select_tactical_portfolio(
    candidates: pd.DataFrame,
    prev_weights: dict[str, float],
    *,
    target_n: int,
    hold_rank_multiplier: float,
    min_upgrade_gap: float,
    max_single_weight: float,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    target_n = max(int(target_n), 1)
    d = candidates.copy()
    held = set(prev_weights)
    selected_parts: list[pd.DataFrame] = []
    selected: set[str] = set()

    if held:
        hold_limit = int(math.ceil(target_n * float(hold_rank_multiplier)))
        hold_mask = (
            d["ticker"].astype(str).isin(held)
            & d["tactical_rank"].le(max(hold_limit, target_n))
            & ~d["tactical_hard_exit"].astype(bool)
            & ~d["tactical_soft_exit"].astype(bool)
        )
        keep = d[hold_mask].sort_values("tactical_rank").head(target_n).copy()
        if not keep.empty:
            keep["tactical_selection_reason"] = "kept_existing_position"
            selected.update(keep["ticker"].astype(str).tolist())
            selected_parts.append(keep)

    remaining = target_n - len(selected)
    if remaining > 0:
        pool = d[
            d["tactical_entry_eligible"].astype(bool)
            & ~d["ticker"].astype(str).isin(selected)
        ].copy()
        if held and selected_parts:
            weakest_keep_score = min(float(x) for x in selected_parts[0]["tactical_rank_score"].tolist())
            pool = pool[
                pool["tactical_rank_score"].ge(weakest_keep_score + float(min_upgrade_gap))
                | ~pool["ticker"].astype(str).isin(held)
            ].copy()
        add = pool.sort_values("tactical_rank").head(remaining).copy()
        if not add.empty:
            add["tactical_selection_reason"] = "new_or_stronger_candidate"
            selected.update(add["ticker"].astype(str).tolist())
            selected_parts.append(add)

    if not selected_parts:
        return pd.DataFrame()
    out = pd.concat(selected_parts, ignore_index=True)
    out = out.drop_duplicates("ticker", keep="first")
    out = out.sort_values(["tactical_rank_score", "tactical_rank"], ascending=[False, True]).head(target_n).copy()
    weights = _normalize_score_weights(out, max_single_weight=max_single_weight)
    out["weight"] = weights.reindex(out.index).fillna(0.0).to_numpy(dtype=float)
    out = out.sort_values("weight", ascending=False).reset_index(drop=True)
    out["rank"] = np.arange(1, len(out) + 1)
    out["portfolio_mode"] = "tactical_alpha"
    return out


def build_trade_plan(target: pd.DataFrame, candidates: pd.DataFrame, prev_weights: dict[str, float]) -> pd.DataFrame:
    target_weights = {}
    if not target.empty:
        target_weights = {
            str(r.ticker): float(r.weight)
            for r in target[["ticker", "weight"]].itertuples(index=False)
            if pd.notna(r.weight) and float(r.weight) > 0
        }
    tickers = sorted(set(prev_weights) | set(target_weights))
    rows: list[dict[str, Any]] = []
    cand_by_ticker = candidates.set_index(candidates["ticker"].astype(str), drop=False) if not candidates.empty else pd.DataFrame()
    for ticker in tickers:
        current = float(prev_weights.get(ticker, 0.0))
        target_w = float(target_weights.get(ticker, 0.0))
        delta = target_w - current
        if current <= 1e-10 and target_w > 0:
            action = "BUY"
        elif target_w <= 1e-10 and current > 0:
            action = "SELL"
        elif abs(delta) < 0.025:
            action = "HOLD"
        elif delta > 0:
            action = "INCREASE"
        else:
            action = "REDUCE"
        reason = ""
        rank = np.nan
        score = np.nan
        hard_exit = False
        soft_exit = False
        price_as_of = ""
        if not cand_by_ticker.empty and ticker in cand_by_ticker.index:
            row = cand_by_ticker.loc[ticker]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            rank = row.get("tactical_rank", np.nan)
            score = row.get("tactical_rank_score", np.nan)
            hard_exit = bool(row.get("tactical_hard_exit", False))
            soft_exit = bool(row.get("tactical_soft_exit", False))
            price_as_of = str(row.get("price_as_of", "") or "")
        if action == "SELL":
            reason = "hard_exit" if hard_exit else "soft_exit_or_rank_replaced" if soft_exit else "rank_replaced"
        elif action in {"BUY", "INCREASE"}:
            reason = "eligible_higher_rank_candidate"
        elif action == "REDUCE":
            reason = "target_weight_lower"
        else:
            reason = "within_rebalance_band"
        rows.append(
            {
                "ticker": ticker,
                "action": action,
                "current_weight": current,
                "target_weight": target_w,
                "delta_weight": delta,
                "tactical_rank": rank,
                "tactical_rank_score": score,
                "tactical_hard_exit": hard_exit,
                "tactical_soft_exit": soft_exit,
                "price_as_of": price_as_of,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["action", "delta_weight"],
        ascending=[True, False],
    ).reset_index(drop=True)


def write_outputs(
    output_dir: Path,
    candidates: pd.DataFrame,
    target: pd.DataFrame,
    trade_plan: pd.DataFrame,
    summary: dict[str, Any],
) -> None:
    safe_mkdir(output_dir)
    safe_mkdir(output_dir / "reports")
    candidates.to_csv(output_dir / "tactical_candidates_latest.csv", index=False)
    target.to_csv(output_dir / "tactical_portfolio_latest.csv", index=False)
    trade_plan.to_csv(output_dir / "tactical_trade_plan.csv", index=False)
    (output_dir / "tactical_run_summary.json").write_text(
        json.dumps(summary, indent=2, default=_json_default),
        encoding="utf-8",
    )
    lines = [
        "# Tactical Alpha Daily Review",
        "",
        f"- run_status: {summary.get('run_status')}",
        f"- schedule_as_of: {summary.get('schedule_as_of')}",
        f"- target_trading_day: {summary.get('target_trading_day')}",
        f"- data_as_of: {summary.get('data_as_of')}",
        f"- selected_count: {summary.get('selected_count')}",
        f"- trade_count: {summary.get('trade_count')}",
        f"- buys: {summary.get('buy_count')} sells: {summary.get('sell_count')}",
        "",
        "This report is research/paper-trading output, not an order execution file.",
    ]
    (output_dir / "reports" / "tactical_daily_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def mirror_to_cloud_results(output_dir: Path) -> None:
    safe_mkdir(DEFAULT_CLOUD_TACTICAL)
    for name in [
        "tactical_candidates_latest.csv",
        "tactical_portfolio_latest.csv",
        "tactical_trade_plan.csv",
        "tactical_run_summary.json",
    ]:
        src = output_dir / name
        if src.exists():
            (DEFAULT_CLOUD_TACTICAL / name).write_bytes(src.read_bytes())
    reports = output_dir / "reports"
    if reports.exists():
        safe_mkdir(DEFAULT_CLOUD_TACTICAL / "reports")
        for src in reports.glob("*"):
            if src.is_file():
                (DEFAULT_CLOUD_TACTICAL / "reports" / src.name).write_bytes(src.read_bytes())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-dir", default=".", help="Drive/repo base dir containing outputs/cache_prices")
    p.add_argument("--scored-path", default=None, help="Explicit scored_latest csv/parquet")
    p.add_argument("--previous-holdings", default=None, help="Explicit previous tactical/current holdings CSV")
    p.add_argument("--as-of", default=None, help="Calendar date to evaluate. Default: current UTC date")
    p.add_argument("--target-n", type=int, default=5)
    p.add_argument("--preliminary-limit", type=int, default=240)
    p.add_argument("--min-price", type=float, default=5.0)
    p.add_argument("--min-dollar-vol", type=float, default=20_000_000.0)
    p.add_argument("--max-single-weight", type=float, default=0.35)
    p.add_argument("--hold-rank-multiplier", type=float, default=3.0)
    p.add_argument("--min-upgrade-gap", type=float, default=0.04)
    p.add_argument("--update-prices", action="store_true")
    p.add_argument("--max-price-updates", type=int, default=160)
    p.add_argument("--output-dir", default=None)
    p.add_argument("--mirror-cloud-results", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()
    cfg = EngineConfig(base_dir=str(base_dir))
    paths = get_paths(cfg)

    schedule_as_of = (
        pd.Timestamp(args.as_of).normalize()
        if args.as_of
        else pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None)).normalize()
    )
    target_trading_day = latest_nyse_day_on_or_before(schedule_as_of)
    previous_summary = load_previous_summary(base_dir)
    previous_data_as_of = str(previous_summary.get("data_as_of") or "")

    scored = load_scored_latest(base_dir, args.scored_path)
    latest, latest_rebalance_dt = latest_snapshot(scored.frame)

    pre = prepare_concentrated_frame(cfg, latest.copy())
    pre = pre.sort_values(["concentrated_score", "score"], ascending=False) if "concentrated_score" in pre.columns else pre
    refresh_summary = {}
    if args.update_prices:
        update_tickers = pre["ticker"].astype(str).head(int(args.preliminary_limit)).tolist()
        refresh_summary = refresh_price_cache(
            paths,
            update_tickers,
            target_trading_day,
            max_updates=int(args.max_price_updates),
        )

    candidates = build_candidate_frame(
        cfg,
        paths,
        latest,
        as_of=target_trading_day,
        preliminary_limit=int(args.preliminary_limit),
        min_price=float(args.min_price),
        min_dollar_vol=float(args.min_dollar_vol),
    )
    prev = load_previous_holdings(base_dir, args.previous_holdings)
    prev_weights = normalize_prev_weights(prev.frame)
    target = select_tactical_portfolio(
        candidates,
        prev_weights,
        target_n=int(args.target_n),
        hold_rank_multiplier=float(args.hold_rank_multiplier),
        min_upgrade_gap=float(args.min_upgrade_gap),
        max_single_weight=float(args.max_single_weight),
    )
    trade_plan = build_trade_plan(target, candidates, prev_weights)

    data_as_of = ""
    if not candidates.empty and "price_as_of" in candidates.columns:
        mode = candidates["price_as_of"].dropna().astype(str).mode()
        data_as_of = str(mode.iloc[0]) if not mode.empty else str(candidates["price_as_of"].dropna().astype(str).max())
    no_new_session = bool(previous_data_as_of and data_as_of and previous_data_as_of == data_as_of)
    actionable = trade_plan[trade_plan["action"].isin(["BUY", "SELL", "INCREASE", "REDUCE"])] if not trade_plan.empty else pd.DataFrame()
    summary = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_status": "no_new_trading_session" if no_new_session else "review_ready",
        "schedule_as_of": str(schedule_as_of.date()),
        "target_trading_day": str(target_trading_day.date()),
        "data_as_of": data_as_of,
        "latest_scored_rebalance_date": str(latest_rebalance_dt.date()),
        "scored_source": str(scored.path) if scored.path else None,
        "previous_holdings_source": str(prev.path) if prev.path else None,
        "candidate_count": int(len(candidates)),
        "selected_count": int(len(target)),
        "trade_count": int(len(actionable)),
        "buy_count": int(trade_plan["action"].isin(["BUY", "INCREASE"]).sum()) if not trade_plan.empty else 0,
        "sell_count": int(trade_plan["action"].isin(["SELL", "REDUCE"]).sum()) if not trade_plan.empty else 0,
        "target_n": int(args.target_n),
        "max_single_weight": float(args.max_single_weight),
        "min_price": float(args.min_price),
        "min_dollar_vol": float(args.min_dollar_vol),
        "price_refresh": refresh_summary,
        "notes": [
            "Weekends and NYSE holidays map to the last valid NYSE trading day.",
            "No trade is forced: existing positions are kept unless rank/exit rules fail or a stronger candidate clears the upgrade gap.",
            "This is a separate tactical sleeve; it does not change the core portfolio export.",
        ],
    }
    out_dir = Path(args.output_dir).resolve() if args.output_dir else (paths["out"] / DEFAULT_OUTPUT_SUBDIR)
    write_outputs(out_dir, candidates, target, trade_plan, summary)
    if args.mirror_cloud_results:
        mirror_to_cloud_results(out_dir)

    print(json.dumps(summary, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    sys.exit(main())
