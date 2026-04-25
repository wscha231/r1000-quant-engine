"""r1000_themes — Phase 16 theme taxonomy loader + aggregates.

Shared module used by both tracks:
  - 정석 (r1000 main engine): theme features for sleeve composites
  - aggressive: real-time theme phase detection for entry/exit

Public API:
  load_themes(path) -> dict[theme_name, {description, tickers: set}]
  map_tickers_to_themes(themes) -> dict[ticker, list[theme_name]]
  compute_theme_aggregates(df, themes) -> DataFrame (one row per theme)
  classify_theme_phase(agg_row) -> str (early / maturing / peaking / ending / dead)
  attach_per_ticker_theme_features(df, themes) -> DataFrame with theme_primary,
                                                   theme_count, theme_memberships columns

Design principles:
  - Zero dependency on engine internals (uses only pandas + yaml + pathlib)
  - Failsafe: missing themes.yaml or malformed entries -> empty result
  - Idempotent: same inputs -> same outputs
  - Fast: O(n × k) where n=tickers, k=themes × members_per_theme

See PHASE_16_THEMES_PROPOSAL.md for design details.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_THEMES_PATH = Path(__file__).parent / "themes.yaml"


# ---------------------------------------------------------------------------
# Phase 14 (2026-04-25): theme phase -> multiplier mapping for ML consumption.
# Stored as module constant so callers (including 정석 r1000_features.py) get
# a stable interface. Values calibrated to research/phase16 backtest signals
# without overfitting (early gets +15% boost, dead gets -50% penalty).
# ---------------------------------------------------------------------------

THEME_PHASE_MULTIPLIER = {
    "early":    1.15,   # rising from base, RS turning positive
    "maturing": 1.05,   # full momentum, breadth > 50%
    "peaking":  0.95,   # breadth saturated, acceleration negative
    "ending":   0.80,   # RS deteriorating with breadth collapse
    "dead":     0.50,   # sustained negative, broken
    "unknown":  1.00,   # neutral when classification not possible
}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_themes(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load themes.yaml → dict of theme_name -> {description, tickers: set[str]}.

    Returns empty dict on missing / malformed file (failsafe).
    """
    p = Path(path) if path else DEFAULT_THEMES_PATH
    if not p.exists():
        return {}
    try:
        import yaml
    except ImportError:
        try:
            import json
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    else:
        try:
            payload = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    if not isinstance(payload, dict):
        return {}
    themes_raw = payload.get("themes", {}) or {}
    if not isinstance(themes_raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, rec in themes_raw.items():
        if not isinstance(rec, dict):
            continue
        tickers = rec.get("tickers", []) or []
        if not isinstance(tickers, list):
            continue
        clean_tickers = {
            str(t).strip().upper()
            for t in tickers
            if isinstance(t, str) and t.strip()
        }
        if not clean_tickers:
            continue
        out[str(name)] = {
            "description": str(rec.get("description", "")),
            "tickers": clean_tickers,
        }
    # Apply overrides (if any) — these ADD to membership
    overrides = payload.get("overrides", {}) or {}
    if isinstance(overrides, dict):
        for ticker, theme_list in overrides.items():
            if not isinstance(theme_list, list):
                continue
            t_up = str(ticker).strip().upper()
            if not t_up:
                continue
            for th in theme_list:
                th_name = str(th).strip()
                if th_name in out:
                    out[th_name]["tickers"].add(t_up)
    # Drop deprecated themes
    dead = payload.get("dead_themes", []) or []
    if isinstance(dead, list):
        for d in dead:
            out.pop(str(d), None)
    return out


def map_tickers_to_themes(themes: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Reverse map: ticker -> list of theme names (in themes.yaml declaration order)."""
    out: dict[str, list[str]] = {}
    for theme_name, rec in themes.items():
        for t in rec.get("tickers", set()):
            out.setdefault(str(t).upper(), []).append(theme_name)
    return out


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

_AGG_NUMERIC_COLS = (
    "mom_1m", "mom_3m", "mom_6m", "mom_12m", "mom_24m",
    "rs_benchmark_3m", "rs_benchmark_6m", "rs_benchmark_12m",
    "rs_industry_1m", "rs_industry_3m", "rs_industry_6m", "rs_industry_12m",
    "vol_252d", "mktcap",
)

_AGG_BINARY_COLS = (
    "price_above_ma200", "price_above_ma50",
)


def compute_theme_aggregates(
    df: pd.DataFrame,
    themes: dict[str, dict[str, Any]],
    ticker_col: str = "ticker",
) -> pd.DataFrame:
    """Per-theme aggregate stats. Expects df to have ticker + momentum/RS columns.

    Returns: DataFrame one row per theme with columns:
      theme_name, n_members_universe, n_members_present,
      theme_mom_1m/3m/6m/12m/24m (means),
      theme_rs_benchmark_3m/6m/12m (means),
      theme_rs_industry_{X}m (means),
      theme_vol_252d_mean, theme_mktcap_median,
      theme_breadth_above_ma200 (if price_above_ma200 col exists),
      theme_acceleration (mom_1m - mom_6m),
      theme_rs_acceleration (rs_benchmark_3m - rs_benchmark_12m),
      theme_phase (early / maturing / peaking / ending / dead)
    """
    if df is None or df.empty or not themes:
        return pd.DataFrame()
    df = df.copy()
    df[ticker_col] = df[ticker_col].astype(str).str.upper()
    rows: list[dict[str, Any]] = []
    for theme_name, rec in themes.items():
        members = rec.get("tickers", set())
        if not members:
            continue
        sub = df[df[ticker_col].isin(members)].copy()
        row: dict[str, Any] = {
            "theme_name": theme_name,
            "description": rec.get("description", ""),
            "n_members_universe": len(members),
            "n_members_present": int(len(sub)),
        }
        if sub.empty:
            # Still emit row so downstream joins don't break
            rows.append(row)
            continue
        for col in _AGG_NUMERIC_COLS:
            if col in sub.columns:
                vals = pd.to_numeric(sub[col], errors="coerce").dropna()
                row[f"theme_{col}_mean"] = float(vals.mean()) if not vals.empty else np.nan
                if col == "mktcap":
                    row["theme_mktcap_median"] = float(vals.median()) if not vals.empty else np.nan
        for col in _AGG_BINARY_COLS:
            if col in sub.columns:
                vals = pd.to_numeric(sub[col], errors="coerce").fillna(0.0)
                row[f"theme_breadth_{col}"] = float((vals > 0.5).mean()) if len(vals) else np.nan

        # Derived: acceleration + drawdown helpers
        m1 = row.get("theme_mom_1m_mean", np.nan)
        m6 = row.get("theme_mom_6m_mean", np.nan)
        m12 = row.get("theme_mom_12m_mean", np.nan)
        rb3 = row.get("theme_rs_benchmark_3m_mean", np.nan)
        rb12 = row.get("theme_rs_benchmark_12m_mean", np.nan)
        row["theme_acceleration"] = (m1 - m6) if (pd.notna(m1) and pd.notna(m6)) else np.nan
        row["theme_rs_acceleration"] = (rb3 - rb12) if (pd.notna(rb3) and pd.notna(rb12)) else np.nan
        # 12m vs 1m: ratio of recent vs long-run strength (user's 'accel' framework)
        row["theme_ratio_1m_over_12m"] = (m1 / m12) if (pd.notna(m1) and pd.notna(m12) and m12 != 0) else np.nan

        # Phase classification
        row["theme_phase"] = classify_theme_phase(row)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        "theme_rs_benchmark_12m_mean", ascending=False, na_position="last"
    ).reset_index(drop=True)


def classify_theme_phase(agg_row: dict[str, Any] | pd.Series) -> str:
    """Classify theme lifecycle phase based on aggregates.

    Returns one of:
      early     - rising from a base (12m RS negative flipping positive, breadth expanding)
      maturing  - full momentum (RS positive, acceleration positive, breadth > 50%)
      peaking   - breadth saturated (breadth > 70%) but acceleration turning negative
      ending    - RS deteriorating with breadth collapse
      dead      - sustained negative, broken
      unknown   - insufficient data
    """
    if isinstance(agg_row, pd.Series):
        row = agg_row.to_dict()
    else:
        row = dict(agg_row)

    rs_12m = row.get("theme_rs_benchmark_12m_mean", np.nan)
    rs_1m = row.get("theme_rs_benchmark_3m_mean", np.nan)  # use 3m as "short" proxy
    accel = row.get("theme_acceleration", np.nan)
    rs_accel = row.get("theme_rs_acceleration", np.nan)
    breadth = row.get("theme_breadth_price_above_ma200", np.nan)

    # Not enough data
    if pd.isna(rs_12m) and pd.isna(breadth):
        return "unknown"
    # Defaults when some missing
    rs_12m = 0.0 if pd.isna(rs_12m) else rs_12m
    rs_1m = 0.0 if pd.isna(rs_1m) else rs_1m
    accel = 0.0 if pd.isna(accel) else accel
    rs_accel = 0.0 if pd.isna(rs_accel) else rs_accel
    breadth = 0.5 if pd.isna(breadth) else breadth

    # Heuristic rules (tuneable thresholds)
    if rs_12m < -0.05 and breadth < 0.25:
        return "dead"
    if rs_12m < 0.0 and breadth > 0.40 and (rs_1m > 0.0 or accel > 0.03):
        return "early"
    if rs_12m > 0.10 and breadth > 0.70 and (accel < 0 or rs_accel < 0):
        return "peaking"
    if rs_12m > 0.05 and breadth > 0.40 and accel > 0:
        return "maturing"
    if rs_12m > 0 and breadth < 0.40:
        return "ending"
    # Fallback
    return "maturing" if rs_12m > 0 else "dead"


# ---------------------------------------------------------------------------
# Per-ticker attach
# ---------------------------------------------------------------------------

def attach_per_ticker_theme_features(
    df: pd.DataFrame,
    themes: dict[str, dict[str, Any]] | None = None,
    theme_aggregates: pd.DataFrame | None = None,
    ticker_col: str = "ticker",
) -> pd.DataFrame:
    """Add per-ticker theme features to df.

    New columns:
      theme_primary         - first theme this ticker belongs to (declared-order)
      theme_count           - number of themes this ticker is in
      theme_memberships     - comma-joined list of theme names
      theme_phase_primary   - phase of the primary theme
      theme_leadership_rank - rank within primary theme by mom_6m (1 = top leader)
      theme_is_leader       - 1 if theme_leadership_rank ≤ 3 else 0
    """
    if df is None or df.empty:
        return df
    if themes is None:
        themes = load_themes()
    if not themes:
        return df
    t2themes = map_tickers_to_themes(themes)

    out = df.copy()
    out[ticker_col] = out[ticker_col].astype(str).str.upper()
    out["theme_memberships"] = out[ticker_col].map(
        lambda t: ",".join(t2themes.get(t, []))
    ).fillna("")
    out["theme_count"] = out[ticker_col].map(
        lambda t: len(t2themes.get(t, []))
    ).fillna(0).astype(int)
    out["theme_primary"] = out[ticker_col].map(
        lambda t: t2themes.get(t, [""])[0] if t2themes.get(t) else ""
    )

    # Phase from aggregates
    if theme_aggregates is not None and not theme_aggregates.empty:
        phase_map = dict(zip(
            theme_aggregates["theme_name"].astype(str),
            theme_aggregates["theme_phase"].astype(str)
        ))
        out["theme_phase_primary"] = out["theme_primary"].map(phase_map).fillna("unknown")
    else:
        out["theme_phase_primary"] = "unknown"

    # Numeric multipliers — for ML consumption (Phase 14, 2026-04-25).
    # Maps each phase label to a continuous multiplier so ML/sleeve composite can
    # ingest as a feature. theme_phase_multiplier_primary is from primary theme;
    # _max takes max across all themes a ticker is in (ticker may be in multiple).
    out["theme_phase_multiplier_primary"] = out["theme_phase_primary"].map(
        THEME_PHASE_MULTIPLIER
    ).fillna(THEME_PHASE_MULTIPLIER["unknown"])

    if theme_aggregates is not None and not theme_aggregates.empty:
        # Build per-theme multiplier
        mult_map = {
            n: THEME_PHASE_MULTIPLIER.get(p, THEME_PHASE_MULTIPLIER["unknown"])
            for n, p in phase_map.items()
        }
        # Per-ticker max multiplier across memberships
        def _max_mult(memberships_str: str) -> float:
            if not memberships_str:
                return THEME_PHASE_MULTIPLIER["unknown"]
            mults = [
                mult_map.get(m, THEME_PHASE_MULTIPLIER["unknown"])
                for m in memberships_str.split(",")
                if m
            ]
            return max(mults) if mults else THEME_PHASE_MULTIPLIER["unknown"]
        out["theme_phase_multiplier_max"] = out["theme_memberships"].map(_max_mult)
    else:
        out["theme_phase_multiplier_max"] = THEME_PHASE_MULTIPLIER["unknown"]

    # Leadership rank within primary theme by mom_6m
    if "mom_6m" in out.columns:
        # rank within each theme
        out["theme_leadership_rank"] = (
            out.groupby("theme_primary")["mom_6m"]
            .rank(method="min", ascending=False)
            .fillna(99)
            .astype(int)
        )
        out["theme_is_leader"] = (out["theme_leadership_rank"] <= 3).astype(int)
    else:
        out["theme_leadership_rank"] = 99
        out["theme_is_leader"] = 0

    return out


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def main_demo() -> None:
    """Demo run against current scored_latest.csv on G drive."""
    print("=" * 70)
    print("r1000_themes.py demo")
    print("=" * 70)
    themes = load_themes()
    print(f"Loaded {len(themes)} themes:")
    for name in list(themes.keys())[:8]:
        print(f"  {name:<28}{len(themes[name]['tickers']):>3} members")
    print()
    t2th = map_tickers_to_themes(themes)
    print(f"Tickers with theme membership: {len(t2th)}")
    sample = [t for t in ["NVDA", "AVGO", "LITE", "CIEN", "LLY", "FTI", "CEG", "KLAC"] if t in t2th]
    for t in sample:
        print(f"  {t}: {t2th[t]}")
    print()

    # Try to load scored_latest and compute aggregates
    scored_path = Path(r"G:\내 드라이브\r1000_top30_institutional\outputs\scored_latest.csv")
    if scored_path.exists():
        df = pd.read_csv(scored_path)
        print(f"Loaded scored_latest.csv: {len(df):,} rows")
        agg = compute_theme_aggregates(df, themes)
        print(f"Theme aggregates: {len(agg)} themes ranked by rs_benchmark_12m")
        cols_show = [c for c in ["theme_name", "n_members_present",
                                  "theme_rs_benchmark_12m_mean", "theme_mom_12m_mean",
                                  "theme_acceleration", "theme_breadth_price_above_ma200",
                                  "theme_phase"] if c in agg.columns]
        print(agg[cols_show].head(15).to_string(index=False))
        print()
        phase_counts = agg["theme_phase"].value_counts()
        print(f"Phase distribution:")
        print(phase_counts.to_string())
        print()

        # Per-ticker attach
        attached = attach_per_ticker_theme_features(df, themes, agg)
        leaders = attached[attached["theme_is_leader"] == 1].copy()
        print(f"Theme leaders (top-3 by mom_6m within each theme): {len(leaders)} tickers")
        print(leaders[["ticker", "theme_primary", "theme_phase_primary",
                        "theme_leadership_rank", "mom_6m"]]
              .sort_values(["theme_phase_primary", "mom_6m"], ascending=[True, False])
              .head(20)
              .to_string(index=False))
    else:
        print(f"scored_latest not found at {scored_path}")


if __name__ == "__main__":
    main_demo()
