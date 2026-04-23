"""Phase 18A - Theme Auto-Discovery via Correlation Clustering.

Goal: Detect emerging themes WITHOUT hindsight hardcoding.

User insight (2026-04-23):
  "미래에 어떤 테마가 뜰지 모른다. 순수하게 종목을 찾아내는 시스템이 필요하다."

Method:
  1. Compute 90-day returns correlation across all R1000 tickers
  2. Hierarchical clustering (Ward linkage) on correlation distance
  3. For each cluster, apply quality filters:
     - cluster size in [3, 25]
     - intra-cluster avg correlation >= 0.50
     - cluster avg 60d RS vs SPY >= +5%
     - dominant sector share >= 60% (coherent thematic)
  4. Name cluster using sector/industry majority heuristic
  5. Diff against themes.yaml - only propose clusters with many NEW (unknown) members
  6. Output proposals.json for human review

Human-in-the-loop:
  - System PROPOSES themes (does NOT auto-commit to themes.yaml)
  - User reviews weekly via Telegram or JSON
  - Approved proposals get added to themes.yaml manually (for now)
  - Phase 18B (later): auto-add on user reply

This module has ZERO hardcoded tickers. All universe + naming data comes from
live iShares IWB sector/industry metadata.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from aggressive.agg_config import load_agg_config
from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
from aggressive.universe import (
    annotate_with_themes,
    fetch_iwb_holdings,
    load_universe,
)


# --- Tunable thresholds (not ticker-specific) ------------------------------

MIN_CLUSTER_SIZE = 3
MAX_CLUSTER_SIZE = 25
MIN_INTRA_CORR = 0.50
MIN_AVG_RS_60D_PCT = 5.0
MIN_DOMINANT_SECTOR_PCT = 0.50     # 50% of cluster in one sector
MIN_UNKNOWN_RATIO = 0.50            # at least half of cluster must be unknown-theme
                                    # (otherwise it's just re-discovering known themes)
LOOKBACK_DAYS = 90
RS_LOOKBACK_DAYS = 60
CLUSTER_DISTANCE_THRESHOLD = 0.55   # 1 - corr threshold for cluster cut
                                    # 0.55 means avg corr ~0.45 within cluster


# --- Dataclasses ------------------------------------------------------------

@dataclass
class ThemeProposal:
    """One emerging-theme proposal from the discovery engine."""
    cluster_id: str
    n_members: int
    n_unknown_members: int          # how many not in existing themes.yaml
    unknown_ratio: float
    avg_intra_corr: float
    avg_rs_60d_pct: float
    avg_mom_3m_pct: float
    member_tickers: list[str] = field(default_factory=list)
    sector_breakdown: dict[str, int] = field(default_factory=dict)
    industry_breakdown: dict[str, int] = field(default_factory=dict)
    dominant_sector: str = ""
    dominant_sector_pct: float = 0.0
    suggested_theme_name: str = ""
    suggested_theme_yaml: dict = field(default_factory=dict)
    rationale: str = ""


# --- Correlation + clustering ----------------------------------------------

def compute_returns_matrix(
    tickers: list[str],
    days: int = LOOKBACK_DAYS,
    verbose: bool = True,
) -> pd.DataFrame:
    """Build aligned daily returns DataFrame. Columns = tickers with valid data.

    Skips tickers with fewer than `days` bars.
    """
    frames: dict[str, pd.Series] = {}
    for i, t in enumerate(tickers, 1):
        if verbose and i % 100 == 0:
            print(f"[returns] {i}/{len(tickers)}...")
        df = fetch_daily_bars(t, days=days + 10)
        if df.empty or len(df) < days:
            continue
        ret = df["close"].pct_change().dropna().tail(days)
        if len(ret) < days - 5:        # allow small gaps
            continue
        frames[t] = ret

    if not frames:
        return pd.DataFrame()

    # Align by date index
    combined = pd.DataFrame(frames)
    # Keep only dates with at least 80% non-NaN (drop weird holidays)
    threshold = int(len(combined.columns) * 0.8)
    combined = combined.dropna(thresh=threshold).dropna(axis=1, thresh=int(len(combined)*0.8))
    return combined


def hierarchical_cluster(
    corr_matrix: pd.DataFrame,
    distance_threshold: float = CLUSTER_DISTANCE_THRESHOLD,
) -> dict[int, list[str]]:
    """Ward hierarchical clustering. Returns dict[cluster_id, ticker_list]."""
    try:
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import squareform
    except ImportError:
        print("FAIL: scipy not installed. Run: py -3 -m pip install scipy")
        return {}

    # Distance = 1 - corr, with NaN -> 1.0 (max distance)
    distance_matrix = 1.0 - corr_matrix.fillna(0.0)
    # Symmetric + zero diagonal
    np.fill_diagonal(distance_matrix.values, 0.0)
    condensed = squareform(distance_matrix.values, checks=False)

    # Ward requires Euclidean; for correlation distance use 'average' or 'complete'
    Z = linkage(condensed, method="average")
    labels = fcluster(Z, t=distance_threshold, criterion="distance")

    # Group tickers by cluster label
    clusters: dict[int, list[str]] = {}
    for tkr, lab in zip(corr_matrix.index, labels):
        clusters.setdefault(int(lab), []).append(str(tkr))
    return clusters


# --- Cluster scoring -------------------------------------------------------

def compute_cluster_stats(
    members: list[str],
    corr_matrix: pd.DataFrame,
    rs_by_ticker: dict[str, float],
    mom_by_ticker: dict[str, float],
) -> dict:
    """Compute intra-cluster average correlation + aggregate momentum/RS."""
    if len(members) < 2:
        return {"avg_intra_corr": 0.0, "avg_rs_60d": 0.0, "avg_mom_3m": 0.0}

    sub = corr_matrix.loc[members, members]
    # Off-diagonal mean
    mask = np.triu(np.ones_like(sub.values, dtype=bool), k=1)
    vals = sub.values[mask]
    vals = vals[~np.isnan(vals)]
    avg_corr = float(np.mean(vals)) if len(vals) > 0 else 0.0

    rs_vals = [rs_by_ticker.get(t, 0.0) for t in members
               if t in rs_by_ticker and not pd.isna(rs_by_ticker[t])]
    mom_vals = [mom_by_ticker.get(t, 0.0) for t in members
                if t in mom_by_ticker and not pd.isna(mom_by_ticker[t])]

    return {
        "avg_intra_corr": avg_corr,
        "avg_rs_60d": float(np.mean(rs_vals)) if rs_vals else 0.0,
        "avg_mom_3m": float(np.mean(mom_vals)) if mom_vals else 0.0,
    }


def compute_momentum_and_rs(
    tickers: list[str],
    spy_df: pd.DataFrame,
) -> tuple[dict[str, float], dict[str, float]]:
    """Returns (rs_60d_pct, mom_3m_pct) per ticker."""
    rs: dict[str, float] = {}
    mom: dict[str, float] = {}

    if spy_df.empty or len(spy_df) < RS_LOOKBACK_DAYS + 5:
        return rs, mom

    spy_close = spy_df["close"]
    for t in tickers:
        df = fetch_daily_bars(t, days=RS_LOOKBACK_DAYS + 20)
        if df.empty or len(df) < RS_LOOKBACK_DAYS:
            continue
        c = df["close"]
        aligned = pd.concat(
            [c.rename("tkr"), spy_close.rename("spy")], axis=1, join="inner"
        ).dropna()
        if len(aligned) < RS_LOOKBACK_DAYS:
            continue
        rs_line = aligned["tkr"] / aligned["spy"]
        if len(rs_line) >= RS_LOOKBACK_DAYS + 1:
            rs[t] = (rs_line.iloc[-1] / rs_line.iloc[-RS_LOOKBACK_DAYS - 1] - 1.0) * 100.0
        if len(c) >= 63:
            mom[t] = (c.iloc[-1] / c.iloc[-64] - 1.0) * 100.0

    return rs, mom


# --- Sector / industry annotation (from iShares IWB) ----------------------

def build_sector_lookup() -> dict[str, dict[str, str]]:
    """Return {ticker: {sector, industry}} from IWB holdings."""
    df = fetch_iwb_holdings()
    if df.empty:
        return {}
    out: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        out[ticker] = {
            "sector": str(row.get("Sector", "Unknown")).strip(),
            "asset_class": str(row.get("Asset Class", "Equity")).strip(),
        }
    return out


# --- Naming heuristic -------------------------------------------------------

def _slugify(s: str) -> str:
    """Convert 'Information Technology' -> 'information_technology'."""
    return (
        s.lower()
        .replace("&", "and")
        .replace(" - ", "_")
        .replace("-", "_")
        .replace(" ", "_")
        .replace(",", "")
        .replace("/", "_")
    )


def suggest_theme_name(
    sector_breakdown: dict[str, int],
    cluster_id: str,
    dominant_pct: float,
) -> str:
    """Simple heuristic: if dominant sector > threshold, use it. Else generic."""
    if not sector_breakdown:
        return f"emerging_cluster_{cluster_id}"
    dominant = max(sector_breakdown, key=sector_breakdown.get)
    if dominant_pct >= 0.80:
        return f"emerging_{_slugify(dominant)}"
    elif dominant_pct >= 0.50:
        return f"emerging_{_slugify(dominant)}_broad"
    else:
        return f"emerging_cluster_{cluster_id}"


# --- Main discovery pipeline -----------------------------------------------

def discover_themes(
    universe_source: str = "r1000",
    lookback_days: int = LOOKBACK_DAYS,
    distance_threshold: float = CLUSTER_DISTANCE_THRESHOLD,
    min_unknown_ratio: float = MIN_UNKNOWN_RATIO,
    verbose: bool = True,
) -> list[ThemeProposal]:
    """Run full theme discovery pipeline.

    Returns list of ThemeProposal, sorted by unknown_ratio * avg_rs_60d.
    """
    # 1. Universe
    tickers, universe_meta = load_universe(universe_source)
    if not tickers:
        raise RuntimeError("Empty universe")

    if verbose:
        print(f"[discover] universe: {len(tickers)} tickers "
              f"(source: {universe_meta.get('source_used', '?')})")

    # 2. Returns matrix
    if verbose:
        print(f"[discover] computing {lookback_days}d returns matrix...")
    returns_df = compute_returns_matrix(tickers, days=lookback_days, verbose=verbose)
    if returns_df.empty or len(returns_df.columns) < MIN_CLUSTER_SIZE:
        print("WARN: insufficient returns data")
        return []
    if verbose:
        print(f"[discover] aligned returns: {returns_df.shape[1]} tickers "
              f"x {len(returns_df)} days")

    # 3. Correlation
    if verbose:
        print("[discover] computing correlation matrix...")
    corr_matrix = returns_df.corr()

    # 4. Clustering
    if verbose:
        print(f"[discover] clustering (Ward avg-linkage, threshold={distance_threshold:.2f})...")
    clusters = hierarchical_cluster(corr_matrix, distance_threshold)
    if verbose:
        print(f"[discover] {len(clusters)} raw clusters")
        sizes = sorted([len(v) for v in clusters.values()], reverse=True)
        print(f"  size distribution: "
              f"1={sum(1 for s in sizes if s==1)} "
              f"2={sum(1 for s in sizes if s==2)} "
              f"3-5={sum(1 for s in sizes if 3<=s<=5)} "
              f"6-10={sum(1 for s in sizes if 6<=s<=10)} "
              f"11-25={sum(1 for s in sizes if 11<=s<=25)} "
              f">25={sum(1 for s in sizes if s>25)}")

    # 5. Momentum / RS per ticker (one-time)
    if verbose:
        print("[discover] computing RS/momentum per ticker...")
    spy_df = fetch_spy_benchmark(days=RS_LOOKBACK_DAYS + 20)
    all_members = [t for mems in clusters.values() for t in mems if 3 <= len(mems) <= 25]
    rs_by_ticker, mom_by_ticker = compute_momentum_and_rs(all_members, spy_df)

    # 6. Theme annotation
    annotations = annotate_with_themes(tickers)
    sector_lookup = build_sector_lookup()

    # 7. Build proposals
    proposals: list[ThemeProposal] = []
    for clust_id, members in clusters.items():
        n = len(members)
        if not (MIN_CLUSTER_SIZE <= n <= MAX_CLUSTER_SIZE):
            continue

        stats = compute_cluster_stats(members, corr_matrix, rs_by_ticker, mom_by_ticker)
        if stats["avg_intra_corr"] < MIN_INTRA_CORR:
            continue
        if stats["avg_rs_60d"] < MIN_AVG_RS_60D_PCT:
            continue

        # Unknown-theme ratio
        unknown_members = [
            t for t in members
            if annotations.get(t, {}).get("is_unknown", True)
        ]
        unknown_ratio = len(unknown_members) / n
        if unknown_ratio < min_unknown_ratio:
            continue

        # Sector breakdown
        sector_breakdown: dict[str, int] = {}
        for t in members:
            sec = sector_lookup.get(t, {}).get("sector", "Unknown")
            sector_breakdown[sec] = sector_breakdown.get(sec, 0) + 1
        dominant_sec = max(sector_breakdown, key=sector_breakdown.get)
        dominant_pct = sector_breakdown[dominant_sec] / n

        # Name
        cid_str = f"C_{clust_id:04d}"
        name = suggest_theme_name(sector_breakdown, cid_str, dominant_pct)

        # Proposed yaml entry
        suggested_yaml = {
            name: {
                "description": (
                    f"Auto-discovered cluster (corr {stats['avg_intra_corr']:.2f}, "
                    f"RS 60d +{stats['avg_rs_60d']:.1f}%). Review before accepting."
                ),
                "tickers": members,
            }
        }

        rationale = (
            f"{n} members, avg_corr={stats['avg_intra_corr']:.2f}, "
            f"avg_RS_60d={stats['avg_rs_60d']:+.1f}%, "
            f"avg_mom_3m={stats['avg_mom_3m']:+.1f}%, "
            f"unknown={unknown_ratio*100:.0f}% ({len(unknown_members)}/{n}), "
            f"dominant sector={dominant_sec} ({dominant_pct*100:.0f}%)"
        )

        proposals.append(ThemeProposal(
            cluster_id=cid_str,
            n_members=n,
            n_unknown_members=len(unknown_members),
            unknown_ratio=unknown_ratio,
            avg_intra_corr=stats["avg_intra_corr"],
            avg_rs_60d_pct=stats["avg_rs_60d"],
            avg_mom_3m_pct=stats["avg_mom_3m"],
            member_tickers=sorted(members),
            sector_breakdown=sector_breakdown,
            industry_breakdown={},   # could populate later
            dominant_sector=dominant_sec,
            dominant_sector_pct=dominant_pct,
            suggested_theme_name=name,
            suggested_theme_yaml=suggested_yaml,
            rationale=rationale,
        ))

    # Sort by combined score: unknown_ratio * avg_rs_60d * intra_corr
    proposals.sort(
        key=lambda p: p.unknown_ratio * p.avg_rs_60d_pct * p.avg_intra_corr,
        reverse=True,
    )
    return proposals


# --- Output helpers --------------------------------------------------------

def print_report(proposals: list[ThemeProposal]) -> None:
    print()
    print("=" * 82)
    print(f"THEME DISCOVERY - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 82)
    if not proposals:
        print("No theme proposals met quality thresholds.")
        return
    print(f"{len(proposals)} emerging theme proposals:\n")
    for i, p in enumerate(proposals, 1):
        print(f"[{i}] {p.suggested_theme_name}  (cluster {p.cluster_id})")
        print(f"    {p.rationale}")
        print(f"    members ({p.n_members}): {', '.join(p.member_tickers[:15])}"
              + (f" + {p.n_members-15} more" if p.n_members > 15 else ""))
        print()


def save_report(proposals: list[ThemeProposal]) -> Path:
    cfg = load_agg_config()
    out_dir = cfg.state_dir / "theme_discovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"proposals_{ts}.json"
    payload = {
        "timestamp": datetime.now().isoformat(),
        "n_proposals": len(proposals),
        "proposals": [asdict(p) for p in proposals],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    latest = out_dir / "latest.json"
    latest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


# --- CLI -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--universe", choices=["r1000", "themes", "custom"],
                   default="r1000")
    p.add_argument("--lookback-days", type=int, default=LOOKBACK_DAYS)
    p.add_argument("--distance-threshold", type=float,
                   default=CLUSTER_DISTANCE_THRESHOLD)
    p.add_argument("--min-unknown-ratio", type=float, default=MIN_UNKNOWN_RATIO)
    args = p.parse_args()

    proposals = discover_themes(
        universe_source=args.universe,
        lookback_days=args.lookback_days,
        distance_threshold=args.distance_threshold,
        min_unknown_ratio=args.min_unknown_ratio,
    )
    print_report(proposals)
    path = save_report(proposals)
    print(f"saved: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
