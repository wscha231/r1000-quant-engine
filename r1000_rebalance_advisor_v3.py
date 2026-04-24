"""r1000_rebalance_advisor_v3 - Hybrid of v1 (quality) and v2 (momentum).

User mandate (2026-04-24):
  "Phase C: v1 + v2 합집합 advisor (v3). 둘 다 검증하는 하이브리드 우선."

Design philosophy:
  - v1 ranks by 정석 model_score (quality/value ML) + gates
  - v2 ranks by Aggressive scanner (technical T1-T4) + gates
  - v3: weighted average of v1 and v2 rankings
        + consensus bonus (stocks in BOTH top-20 get +20% score)
        + min 3 names from each philosophy for diversity

Algorithm:
  1. Run v1 ranking on unified universe (1012) -> get v1_rank dict
  2. Run v2 ranking using scanner cache -> get v2_rank dict
  3. For each ticker in either top-30:
       v1_score = inverse_rank normalized 0-1
       v2_score = inverse_rank normalized 0-1
       consensus = 1.2 if in BOTH top-30 else 1.0
       hybrid_score = (0.50 * v1_score + 0.50 * v2_score) * consensus
  4. Build portfolio with tier caps (18/12/8%), target 12 names
  5. Guarantee at least 3 names from each pure-list (top 3 v1 + top 3 v2)

Output: outputs_advisor_v3/new_top12_proposed.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

# v1: model-score based ranker
from r1000_rebalance_advisor import (
    load_finnhub_as_dict,
    compute_live_rs_for_tickers,
    rank_candidates as v1_rank_candidates,
)


TARGET_N_POSITIONS = 12
TIER_CAPS = [
    (3, 0.18),
    (6, 0.12),
    (999, 0.08),
]

# How many top-N to pull from each source
V1_TOP_N = 30
V2_TOP_N = 30

# Guaranteed minimum quota per philosophy
MIN_V1_EXCLUSIVE = 3
MIN_V2_EXCLUSIVE = 3


# --- v2 ranking helper (reads scanner cache) ------------------------------

ADVISOR_PHASE_MULT = {
    "early":    1.15,
    "maturing": 1.05,
    "peaking":  1.00,
    "unknown":  1.00,
    "dead":     0.50,
    "ending":   0.65,
}


def load_scanner_rankings(scanner_cache_path: Optional[Path] = None) -> dict[str, float]:
    """Load scanner output and re-score with advisor multipliers.

    Returns {ticker: advisor_score} sorted desc.
    """
    import glob
    if scanner_cache_path is None:
        files = sorted(
            glob.glob("aggressive/state/scanner/candidates_*.json"),
            reverse=True,
        )
        if not files:
            return {}
        scanner_cache_path = Path(files[0])
    else:
        scanner_cache_path = Path(scanner_cache_path)

    if not scanner_cache_path.exists():
        return {}
    with open(scanner_cache_path, encoding="utf-8") as f:
        data = json.load(f)

    out: dict[str, float] = {}
    for c in data.get("candidates", []):
        tech = c.get("tech_score", 0)
        phase = c.get("theme_phase", "unknown")
        val_mult = c.get("val_mult", 1.0)
        phase_mult = ADVISOR_PHASE_MULT.get(phase, 1.0)
        # v2 score: tech * advisor-phase * val_mult (recomputed)
        score = tech * phase_mult * val_mult
        out[c["ticker"]] = score
    return out


# --- Hybrid scorer --------------------------------------------------------

@dataclass
class HybridPick:
    ticker: str
    v1_rank: Optional[int]
    v2_rank: Optional[int]
    v1_score: float
    v2_score: float
    consensus: bool
    hybrid_score: float
    proposed_weight: float
    current_weight: float
    action: str
    philosophy: str         # 'both' | 'v1_only' | 'v2_only'
    meta: dict = field(default_factory=dict)


def compute_hybrid_score(
    v1_rankings: dict[str, float],      # ticker -> v1 effective_score
    v2_rankings: dict[str, float],      # ticker -> v2 advisor_score
    top_n: int = V1_TOP_N,
) -> list[HybridPick]:
    """Blend v1 and v2 rankings.

    v1_rankings: higher is better (absolute score).
    v2_rankings: same.
    """
    # Normalize each to 0-1 (percentile)
    def _to_rank(d: dict[str, float]) -> dict[str, int]:
        sorted_pairs = sorted(d.items(), key=lambda x: x[1], reverse=True)
        return {t: i + 1 for i, (t, _) in enumerate(sorted_pairs)}

    v1_ranks = _to_rank(v1_rankings)
    v2_ranks = _to_rank(v2_rankings)

    # Union of top-N from each
    top_v1 = {t for t, r in v1_ranks.items() if r <= top_n}
    top_v2 = {t for t, r in v2_ranks.items() if r <= top_n}
    universe = top_v1 | top_v2

    picks: list[HybridPick] = []
    for t in universe:
        r1 = v1_ranks.get(t)
        r2 = v2_ranks.get(t)
        # Score: inverse rank normalized
        s1 = max(0, (top_n + 1 - r1) / top_n) if r1 and r1 <= top_n else 0.0
        s2 = max(0, (top_n + 1 - r2) / top_n) if r2 and r2 <= top_n else 0.0
        consensus = (r1 and r1 <= top_n) and (r2 and r2 <= top_n)
        hybrid = (0.50 * s1 + 0.50 * s2) * (1.20 if consensus else 1.0)
        # Philosophy tag
        if consensus:
            phi = "both"
        elif r1 and r1 <= top_n:
            phi = "v1_only"
        else:
            phi = "v2_only"
        picks.append(HybridPick(
            ticker=t,
            v1_rank=r1, v2_rank=r2,
            v1_score=s1, v2_score=s2,
            consensus=bool(consensus),
            hybrid_score=hybrid,
            proposed_weight=0.0,
            current_weight=0.0,
            action="TBD",
            philosophy=phi,
        ))

    picks.sort(key=lambda p: p.hybrid_score, reverse=True)
    return picks


def build_portfolio_from_hybrid(
    picks: list[HybridPick],
    current_weights: dict[str, float],
    target_n: int = TARGET_N_POSITIONS,
) -> list[HybridPick]:
    """Select top N with tier caps + diversity quota."""
    selected: list[HybridPick] = []
    v1_only_count = 0
    v2_only_count = 0

    # First pass: respect quotas - guarantee some v1_only and v2_only
    for p in picks:
        if len(selected) >= target_n:
            break
        rank = len(selected) + 1
        tier_cap = 0.08
        for n_up_to, cap in TIER_CAPS:
            if rank <= n_up_to:
                tier_cap = cap
                break
        p.proposed_weight = tier_cap
        p.current_weight = current_weights.get(p.ticker, 0.0)
        if p.current_weight == 0:
            p.action = "BUY"
        elif p.proposed_weight > p.current_weight * 1.1:
            p.action = "ADD"
        elif p.proposed_weight < p.current_weight * 0.9:
            p.action = "TRIM"
        else:
            p.action = "HOLD"

        selected.append(p)
        if p.philosophy == "v1_only":
            v1_only_count += 1
        elif p.philosophy == "v2_only":
            v2_only_count += 1

    # Enforce minimum quotas (swap in if missing)
    def _swap_in(philosophy: str, minimum: int, count: int):
        if count >= minimum:
            return
        need = minimum - count
        pool = [p for p in picks if p.philosophy == philosophy and p not in selected]
        # Swap out lowest-ranked selected NOT from philosophy
        swap_targets = sorted(
            [p for p in selected if p.philosophy != philosophy],
            key=lambda p: p.hybrid_score,
        )
        for i in range(min(need, len(pool), len(swap_targets))):
            if pool[i] not in selected and swap_targets[i] in selected:
                selected.remove(swap_targets[i])
                pool[i].proposed_weight = swap_targets[i].proposed_weight
                pool[i].current_weight = current_weights.get(pool[i].ticker, 0.0)
                pool[i].action = ("BUY" if pool[i].current_weight == 0
                                  else "ADD" if pool[i].proposed_weight > pool[i].current_weight * 1.1
                                  else "TRIM" if pool[i].proposed_weight < pool[i].current_weight * 0.9
                                  else "HOLD")
                selected.append(pool[i])

    _swap_in("v1_only", MIN_V1_EXCLUSIVE, v1_only_count)
    _swap_in("v2_only", MIN_V2_EXCLUSIVE, v2_only_count)

    selected.sort(key=lambda p: p.hybrid_score, reverse=True)

    # Normalize weights
    total = sum(p.proposed_weight for p in selected)
    if total > 1.0:
        for p in selected:
            p.proposed_weight /= total

    return selected


# --- Print + save ---------------------------------------------------------

def print_report(picks: list[HybridPick]) -> None:
    print()
    print("=" * 100)
    print(f"REBALANCE PROPOSAL v3 (HYBRID) - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 100)
    print()
    print("PROPOSED NEW PORTFOLIO (12 names, v1 quality + v2 momentum hybrid):")
    print(f"  {'Rank':<5} {'Ticker':<6} {'Weight':>7} {'Philosophy':<10} "
          f"{'v1_rank':>7} {'v2_rank':>7} {'Hybrid':>7} {'Action':<6}")
    print("  " + "-" * 80)
    for i, p in enumerate(picks, 1):
        v1r = f"#{p.v1_rank}" if p.v1_rank else "--"
        v2r = f"#{p.v2_rank}" if p.v2_rank else "--"
        tag = "***" if p.consensus else ("v1" if p.philosophy == "v1_only" else "v2")
        print(f"  {i:<5} {p.ticker:<6} {p.proposed_weight*100:>6.2f}% "
              f"{p.philosophy:<10} {v1r:>7} {v2r:>7} "
              f"{p.hybrid_score:>7.3f} {p.action:<6} {tag}")
    print(f"\n  TOTAL: {sum(p.proposed_weight for p in picks)*100:.1f}%")
    print()
    consensus_count = sum(1 for p in picks if p.consensus)
    print(f"  Consensus (both v1+v2): {consensus_count}")
    print(f"  v1 exclusive:           {sum(1 for p in picks if p.philosophy=='v1_only')}")
    print(f"  v2 exclusive:           {sum(1 for p in picks if p.philosophy=='v2_only')}")


def save_results(picks: list[HybridPick], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(p) for p in picks]
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "new_top12_proposed.csv", index=False)
    print(f"\n[save] wrote {out_dir / 'new_top12_proposed.csv'}")


# --- Main -----------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scored-csv", default=r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_unified.csv")
    parser.add_argument("--portfolio-csv", default=r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv")
    parser.add_argument("--output-dir", default="outputs_advisor_v3")
    args = parser.parse_args()

    print("=" * 70)
    print(f"r1000 Rebalance Advisor v3 (Hybrid) - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)

    # Load
    scored = pd.read_csv(args.scored_csv)
    align_p = Path(args.portfolio_csv).parent / "portfolio_theme_alignment.csv"
    if align_p.exists():
        align = pd.read_csv(align_p)
        if "theme_phase_primary" in align.columns:
            scored = scored.merge(
                align[["ticker", "theme_primary", "theme_phase_primary"]],
                on="ticker", how="left",
            )
    portfolio = pd.read_csv(args.portfolio_csv)
    current_weights = {}
    for _, r in portfolio.iterrows():
        current_weights[str(r["ticker"]).upper()] = float(r.get("weight") or 0.0)
    print(f"[load] unified scored: {len(scored)} rows")
    print(f"[load] current portfolio: {len(portfolio)} positions")

    # v1 ranking
    print("[v1] computing v1 (quality-first) rankings...")
    fh = load_finnhub_as_dict()
    basic = scored[scored["score"].notna()]
    basic = basic[pd.to_numeric(basic["score"]) >= 1.0]
    basic = basic[pd.to_numeric(basic["market_cap_live"], errors="coerce") >= 5e9]
    cand_tickers = sorted(set(str(t).upper() for t in basic["ticker"].dropna()))
    print(f"[v1] candidates passing basic filter: {len(cand_tickers)}")
    live_rs = compute_live_rs_for_tickers(cand_tickers, verbose=True)
    v1_cands = v1_rank_candidates(scored, fh, live_rs=live_rs)
    v1_rankings = {c.ticker: c.effective_score for c in v1_cands[:V1_TOP_N]}
    print(f"[v1] top {V1_TOP_N} loaded")

    # v2 ranking (from scanner cache)
    print("[v2] loading v2 (momentum) rankings from scanner cache...")
    v2_rankings = load_scanner_rankings()
    print(f"[v2] loaded {len(v2_rankings)} scanner candidates")
    # Keep only top N
    v2_sorted = sorted(v2_rankings.items(), key=lambda x: x[1], reverse=True)[:V2_TOP_N]
    v2_rankings = dict(v2_sorted)

    # Hybrid
    print("[hybrid] building hybrid rankings...")
    picks = compute_hybrid_score(v1_rankings, v2_rankings, top_n=V1_TOP_N)
    print(f"[hybrid] {len(picks)} total candidates in union")

    # Portfolio
    portfolio_picks = build_portfolio_from_hybrid(
        picks, current_weights, target_n=TARGET_N_POSITIONS,
    )

    # Report + save
    print_report(portfolio_picks)
    save_results(portfolio_picks, Path(args.output_dir))

    # Diff vs current
    old_tickers = {t for t, w in current_weights.items() if w > 0 and t != "CASH"}
    new_tickers = {p.ticker for p in portfolio_picks}
    print()
    print(f"DIFF vs current:")
    print(f"  EXIT ({len(old_tickers - new_tickers)}): {sorted(old_tickers - new_tickers)}")
    print(f"  ADD  ({len(new_tickers - old_tickers)}): {sorted(new_tickers - old_tickers)}")
    print(f"  HOLD ({len(old_tickers & new_tickers)}): {sorted(old_tickers & new_tickers)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
