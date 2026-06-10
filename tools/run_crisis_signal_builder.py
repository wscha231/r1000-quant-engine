#!/usr/bin/env python3
"""Phase E2 -- Crisis Signal Builder (CODEX_HANDOFF v3.6 Section 17.3)

Builds a daily feature panel for the crisis governor. Each row represents a
single trading day with all features computed using ONLY information that
was available at that day's close (no look-ahead).

PIT discipline (critical):
  - SPY/QQQ MA/DD: rolling windows on cached price history
  - VIX z-score: 60-day rolling z relative to historical mean
  - FRED series (HY OAS, 10Y yield): point-in-time observation dates
  - No forward returns, no future closes, no "future_*" columns

Sources (cached locally; tool gracefully degrades if cache absent):
  - cache_prices/{SPY,QQQ,^VIX}.parquet            (yfinance via collector)
  - cache_macro/fred_hy_oas_BAMLH0A0HYM2.parquet   (FRED H.7 if extant)
  - cache_macro/fred_dgs10_DGS10.parquet           (FRED 10Y)
  - cache_macro/fred_vix_VIXCLS.parquet            (FRED VIX, fallback)
  - cache_macro/fred_sp500_SP500.parquet           (FRED SP500, optional)

Output: outputs/crisis_signals/daily_features.parquet
        outputs/crisis_signals/build_audit.json (source paths + row counts)

Usage:
    py -3 tools/run_crisis_signal_builder.py
    py -3 tools/run_crisis_signal_builder.py --base-dir /alt/path

Plan reference:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md Section 17.3 (Phase E2)
    research/final_integrated_engine_20260524/plan.md Section 2 E2
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_BASE = Path("/content/drive/MyDrive/r1000_top30_institutional")


# ---------------------------------------------------------------------------
# Path discovery (matches r1000_helpers.build_paths)
# ---------------------------------------------------------------------------


def discover_paths(base_dir: Optional[Path]) -> dict:
    """Return dict of cache + output paths, mirroring r1000_helpers.build_paths.

    Search order: explicit --base-dir, then DEFAULT_BASE (Colab), then ROOT.
    """
    candidates = []
    if base_dir is not None:
        candidates.append(base_dir)
    candidates.append(DEFAULT_BASE)
    candidates.append(ROOT)
    base = None
    for cand in candidates:
        if cand.exists():
            cache_prices = cand / "cache_prices"
            cache_macro = cand / "cache_macro"
            if cache_prices.exists() or cache_macro.exists():
                base = cand
                break
    if base is None:
        base = ROOT  # last resort -- outputs only
    return {
        "base": base,
        "cache_prices": base / "cache_prices",
        "cache_macro": base / "cache_macro",
        "out": base / "outputs" if (base / "outputs").exists() else ROOT / "outputs",
    }


# ---------------------------------------------------------------------------
# Loaders -- all return DataFrame with DatetimeIndex (or empty)
# ---------------------------------------------------------------------------


def _read_parquet_safely(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        print(f"WARN: failed to read {path}: {exc}", file=sys.stderr)
        return pd.DataFrame()


def load_price_series(paths: dict, ticker: str) -> pd.Series:
    """Load close price series for ticker (^VIX style or plain ticker)."""
    cache_dir = paths["cache_prices"]
    if not cache_dir.exists():
        return pd.Series(dtype=float)
    # The pipeline's px_cache_name uses a sanitized name. Try a couple of
    # plausible filenames.
    candidates = [
        cache_dir / f"{ticker}.parquet",
        cache_dir / f"{ticker.replace('^', '')}.parquet",
        cache_dir / f"{ticker.replace('^', 'idx_')}.parquet",
    ]
    df = pd.DataFrame()
    for p in candidates:
        df = _read_parquet_safely(p)
        if not df.empty:
            break
    if df.empty:
        return pd.Series(dtype=float)
    # Standardise index + pick best close column
    if df.index.name is None and "Date" in df.columns:
        df = df.set_index("Date")
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()]
    for col in ("Adj Close", "adj_close", "Close", "close"):
        if col in df.columns:
            series = pd.to_numeric(df[col], errors="coerce")
            return series.dropna()
    return pd.Series(dtype=float)


def load_fred_series(paths: dict, name: str, series_id: str) -> pd.Series:
    """Read a cached FRED parquet produced by r1000_pipeline.load_fred_series."""
    cache_path = paths["cache_macro"] / f"fred_{name}_{series_id}.parquet"
    df = _read_parquet_safely(cache_path)
    if df.empty:
        return pd.Series(dtype=float)
    # Expect a single value column + date index OR a "date","value" wide form
    if "value" in df.columns:
        if "date" in df.columns:
            df.index = pd.to_datetime(df["date"], errors="coerce")
        else:
            df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[~df.index.isna()]
        return pd.to_numeric(df["value"], errors="coerce").dropna()
    if len(df.columns) == 1:
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[~df.index.isna()]
        return pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()
    return pd.Series(dtype=float)


# ---------------------------------------------------------------------------
# Feature computation (every column PIT-safe: rolling backward only)
# ---------------------------------------------------------------------------


def compute_market_trend_features(spy: pd.Series, qqq: pd.Series) -> pd.DataFrame:
    if spy.empty and qqq.empty:
        return pd.DataFrame()
    idx = spy.index.union(qqq.index).sort_values()
    out = pd.DataFrame(index=idx)
    if not spy.empty:
        spy_a = spy.reindex(idx).ffill()
        out["spy_close"] = spy_a
        out["spy_ma20"] = spy_a.rolling(20).mean()
        out["spy_ma50"] = spy_a.rolling(50).mean()
        out["spy_ma200"] = spy_a.rolling(200).mean()
        out["spy_below_ma200"] = (spy_a < out["spy_ma200"]).astype(float)
        out["spy_below_ma50"] = (spy_a < out["spy_ma50"]).astype(float)
        out["spy_5d_dd"] = (spy_a / spy_a.rolling(5).max()) - 1.0
        out["spy_20d_dd"] = (spy_a / spy_a.rolling(20).max()) - 1.0
    if not qqq.empty:
        qqq_a = qqq.reindex(idx).ffill()
        out["qqq_close"] = qqq_a
        out["qqq_ma20"] = qqq_a.rolling(20).mean()
        out["qqq_ma50"] = qqq_a.rolling(50).mean()
        out["qqq_ma200"] = qqq_a.rolling(200).mean()
        out["qqq_below_ma200"] = (qqq_a < out["qqq_ma200"]).astype(float)
        out["qqq_5d_dd"] = (qqq_a / qqq_a.rolling(5).max()) - 1.0
        out["qqq_20d_dd"] = (qqq_a / qqq_a.rolling(20).max()) - 1.0
    return out


def compute_volatility_features(vix: pd.Series, idx: pd.DatetimeIndex) -> pd.DataFrame:
    if vix.empty:
        return pd.DataFrame(index=idx)
    vix_a = vix.reindex(idx).ffill()
    out = pd.DataFrame(index=idx)
    out["vix_level"] = vix_a
    # 60d rolling z-score (PIT-safe: shift not needed because window ends at T)
    roll_mean = vix_a.rolling(60).mean()
    roll_std = vix_a.rolling(60).std(ddof=0)
    out["vix_zscore_60d"] = (vix_a - roll_mean) / roll_std.replace(0, np.nan)
    # 3-day spike: today level minus 3-day-ago level normalised by roll_std
    out["vix_spike_3d"] = (vix_a - vix_a.shift(3)) / roll_std.replace(0, np.nan)
    return out


def compute_credit_features(hy_oas: pd.Series, idx: pd.DatetimeIndex) -> pd.DataFrame:
    if hy_oas.empty:
        return pd.DataFrame(index=idx)
    hy_a = hy_oas.reindex(idx).ffill()
    out = pd.DataFrame(index=idx)
    out["hy_oas"] = hy_a
    roll_mean = hy_a.rolling(60).mean()
    roll_std = hy_a.rolling(60).std(ddof=0)
    out["hy_oas_zscore_60d"] = (hy_a - roll_mean) / roll_std.replace(0, np.nan)
    out["hy_oas_5d_change"] = hy_a - hy_a.shift(5)
    return out


def compute_rate_features(dgs10: pd.Series, idx: pd.DatetimeIndex) -> pd.DataFrame:
    if dgs10.empty:
        return pd.DataFrame(index=idx)
    y10 = dgs10.reindex(idx).ffill()
    out = pd.DataFrame(index=idx)
    out["ten_year_yield"] = y10
    out["ten_year_5d_change_bps"] = (y10 - y10.shift(5)) * 100.0
    out["ten_year_20d_change_bps"] = (y10 - y10.shift(20)) * 100.0
    return out


CRISIS_COMPONENT_WEIGHTS: dict[str, float] = {
    "market_trend": 0.25,
    "credit_stress": 0.20,
    "vol_spike": 0.15,
    "breadth": 0.15,
    "liquidity": 0.10,
    "rate_shock": 0.10,
    "portfolio_damage": 0.05,
}


def _clip01(s: pd.Series) -> pd.Series:
    return s.clip(lower=0.0, upper=1.0)


def _build_component_series(features: pd.DataFrame) -> dict[str, pd.Series]:
    """Build each sub-score series. A series is considered "live" by the
    coverage check below only when its source columns exist AND carry at least
    one non-zero observation."""
    idx = features.index
    zero = pd.Series(0.0, index=idx)
    components: dict[str, pd.Series] = {name: zero.copy() for name in CRISIS_COMPONENT_WEIGHTS}
    if "spy_below_ma200" in features and "spy_20d_dd" in features:
        components["market_trend"] = _clip01(
            features["spy_below_ma200"].fillna(0) * 0.5
            + (-features["spy_20d_dd"].clip(upper=0).fillna(0) / 0.15) * 0.5
        )
    if "vix_zscore_60d" in features:
        components["vol_spike"] = _clip01(features["vix_zscore_60d"].fillna(0) / 3.0)
    if "hy_oas_zscore_60d" in features:
        components["credit_stress"] = _clip01(features["hy_oas_zscore_60d"].fillna(0) / 3.0)
    if "spy_below_ma200" in features and "qqq_below_ma200" in features:
        components["breadth"] = _clip01(
            features.get("spy_below_ma200", zero).fillna(0) * 0.5
            + features.get("qqq_below_ma200", zero).fillna(0) * 0.5
        )
    if "ten_year_5d_change_bps" in features:
        components["rate_shock"] = _clip01(features["ten_year_5d_change_bps"].abs().fillna(0) / 50.0)
    # liquidity and portfolio_damage stay zero — placeholder fields, see audit.
    return components


def composite_crisis_coverage(features: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per-component liveness + summary stats, used by the audit. A component
    is "live" only when its series carries at least one non-zero observation —
    so an absent FRED feed (HY OAS / DGS10 / VIX cache) or the structural
    placeholders (liquidity / portfolio_damage) are correctly flagged dead."""
    series = _build_component_series(features)
    coverage: dict[str, dict[str, float]] = {}
    for name, weight in CRISIS_COMPONENT_WEIGHTS.items():
        s = series.get(name, pd.Series(0.0, index=features.index))
        nonzero = float(s.abs().sum())
        coverage[name] = {
            "nominal_weight": float(weight),
            "live": bool(nonzero > 0.0),
            "max": float(s.max()) if len(s) else 0.0,
            "mean": float(s.mean()) if len(s) else 0.0,
        }
    live_weight = sum(c["nominal_weight"] for c in coverage.values() if c["live"])
    for name, info in coverage.items():
        info["effective_weight"] = (
            float(info["nominal_weight"] / live_weight) if info["live"] and live_weight > 0 else 0.0
        )
    return coverage


def compute_composite_crisis_score(features: pd.DataFrame) -> pd.Series:
    """Clipped weighted sum of sub-scores, with the weights of dead
    components redistributed across live ones (so a CI runner without
    HY OAS / VIX / DGS10 cache does not impose an artificial 0.40 score
    ceiling that keeps the governor permanently in the "normal" zone).

    When NO component is live the score is identically zero — the governor
    correctly stays out of the way rather than reacting to noise.

    Per CODEX_HANDOFF v3.6 Section 17.4 with one logical correction: the
    weighted sum used to silently treat structural placeholders (liquidity,
    portfolio_damage) and absent macro feeds as "zero stress", lowering the
    score's effective ceiling. Renormalization preserves the [0, 1] range
    while keeping every live component on its intended relative weight."""
    series = _build_component_series(features)
    live_weight = sum(
        weight for name, weight in CRISIS_COMPONENT_WEIGHTS.items()
        if float(series.get(name, pd.Series(0.0, index=features.index)).abs().sum()) > 0.0
    )
    if live_weight <= 0.0:
        return pd.Series(0.0, index=features.index)
    scale = 1.0 / live_weight
    accumulator = pd.Series(0.0, index=features.index)
    for name, weight in CRISIS_COMPONENT_WEIGHTS.items():
        s = series.get(name, pd.Series(0.0, index=features.index))
        if float(s.abs().sum()) <= 0.0:
            continue
        accumulator = accumulator.add(weight * scale * s, fill_value=0.0)
    return accumulator.clip(lower=0.0, upper=1.0)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


@dataclass
class BuildResult:
    features: pd.DataFrame
    sources: dict
    rows: int


def build_features(paths: dict) -> BuildResult:
    spy = load_price_series(paths, "SPY")
    qqq = load_price_series(paths, "QQQ")
    vix_yf = load_price_series(paths, "^VIX")
    vix_fred = load_fred_series(paths, "vix", "VIXCLS")
    vix = vix_yf if not vix_yf.empty else vix_fred
    hy_oas = load_fred_series(paths, "hy_oas", "BAMLH0A0HYM2")
    dgs10 = load_fred_series(paths, "dgs10", "DGS10")

    trend = compute_market_trend_features(spy, qqq)
    if trend.empty and vix.empty and hy_oas.empty and dgs10.empty:
        return BuildResult(features=pd.DataFrame(), sources={}, rows=0)
    # Use trend index as anchor (or fall back to vix/hy_oas)
    if not trend.empty:
        idx = trend.index
    elif not vix.empty:
        idx = vix.index
    elif not hy_oas.empty:
        idx = hy_oas.index
    else:
        idx = dgs10.index

    vol = compute_volatility_features(vix, idx)
    credit = compute_credit_features(hy_oas, idx)
    rates = compute_rate_features(dgs10, idx)

    features = pd.concat(
        [
            trend.reindex(idx) if not trend.empty else pd.DataFrame(index=idx),
            vol,
            credit,
            rates,
        ],
        axis=1,
    )
    features["crisis_score"] = compute_composite_crisis_score(features)

    sources = {
        "spy_rows": int(spy.shape[0]),
        "qqq_rows": int(qqq.shape[0]),
        "vix_rows": int(vix.shape[0]),
        "vix_source": "yfinance" if not vix_yf.empty else ("fred" if not vix_fred.empty else "none"),
        "hy_oas_rows": int(hy_oas.shape[0]),
        "dgs10_rows": int(dgs10.shape[0]),
    }
    return BuildResult(features=features, sources=sources, rows=int(len(features)))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", type=str, default=None, help="Override base path (default: auto-discover)")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    paths = discover_paths(Path(args.base_dir) if args.base_dir else None)
    result = build_features(paths)
    out_dir = paths["out"] / "crisis_signals"
    out_dir.mkdir(parents=True, exist_ok=True)
    if result.features.empty:
        msg = (
            "No data sources found. Need at least one of:\n"
            f"  - {paths['cache_prices']}/(SPY,QQQ,^VIX).parquet\n"
            f"  - {paths['cache_macro']}/fred_*.parquet\n"
            "Run a pipeline to populate caches first."
        )
        print(f"WARN: {msg}", file=sys.stderr)
        # Write empty audit anyway so downstream tools see a clear signal
        (out_dir / "build_audit.json").write_text(
            json.dumps({"rows": 0, "sources": {}, "status": "no_data"}, indent=2)
        )
        return 1
    out_path = out_dir / "daily_features.parquet"
    result.features.to_parquet(out_path, index=True)
    score_series = result.features.get("crisis_score", pd.Series(0.0, index=result.features.index))
    coverage = composite_crisis_coverage(result.features)
    live_components = sorted(name for name, info in coverage.items() if info["live"])
    dead_components = sorted(name for name, info in coverage.items() if not info["live"])
    # Pre-renormalization theoretical ceiling: with all dead component weights
    # silently treated as zero stress, the score could not exceed this value.
    nominal_live_weight = sum(
        CRISIS_COMPONENT_WEIGHTS[name] for name in live_components
    )
    audit = {
        "rows": result.rows,
        "first_date": result.features.index.min().date().isoformat(),
        "last_date": result.features.index.max().date().isoformat(),
        "sources": result.sources,
        "columns": sorted(result.features.columns.tolist()),
        "crisis_score_stats": {
            "max": float(score_series.max()) if len(score_series) else 0.0,
            "p99": float(score_series.quantile(0.99)) if len(score_series) else 0.0,
            "p95": float(score_series.quantile(0.95)) if len(score_series) else 0.0,
            "p90": float(score_series.quantile(0.90)) if len(score_series) else 0.0,
            "mean": float(score_series.mean()) if len(score_series) else 0.0,
        },
        "component_coverage": coverage,
        "live_components": live_components,
        "dead_components": dead_components,
        "pre_renorm_ceiling": float(nominal_live_weight),
        "renormalization_active": bool(dead_components and nominal_live_weight < 1.0),
        "status": "ok",
    }
    (out_dir / "build_audit.json").write_text(json.dumps(audit, indent=2))
    if not args.quiet:
        print(f"crisis features: {result.rows} rows -> {out_path}")
        print(f"audit:           {out_dir / 'build_audit.json'}")
        print(
            f"crisis coverage: live={live_components} dead={dead_components}"
            f" pre_renorm_ceiling={nominal_live_weight:.2f}"
            f" score_max={audit['crisis_score_stats']['max']:.3f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
