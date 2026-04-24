"""r1000_rebalance_advisor_v2 - Scanner-based rebalance advisor.

User mandate (2026-04-24 evening):
  "시스템을 완성하자. 새로운 데이터 소스로 에러없이 제대로 종목들을 선정하는지부터."

v1 problem: 정석 scored_latest covers only 610/1008 (60%) R1000 names.
            402 names invisible (AMKR/FLUT/AFRM/ALGM/ABNB/ACHC etc).
            Model score biased to quality megacaps, misses RS leaders.
            Zero overlap with Aggressive scanner output.

v2 fix: Use the Aggressive scanner's R1000 output as base, apply concentration
        rules on top. Scanner already:
          - scans full R1000 (1008)
          - uses 4-tier technical (Weinstein/Minervini/PEAD/RS)
          - applies Finnhub gates (PEG, insider, earnings)
          - applies theme phase multipliers
        We just need: rank + tier cap + diff vs current.

If 정석 scored_latest exists, use its model_score as a supplemental quality
tiebreak (not primary). Names with model_score > threshold get small bonus.

Outputs (same as v1):
  outputs_advisor_v2/new_top12_proposed.csv
  outputs_advisor_v2/rebalance_diff.csv
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

# Scanner will handle universe + tech signals + gates
from aggressive.scanner import ScannerCandidate, scan


TARGET_N_POSITIONS = 12
TIER_CAPS = [
    (3, 0.18),
    (6, 0.12),
    (999, 0.08),
]
SUBSECTOR_CAP_PCT = 0.70


# --- Model score bonus (optional supplemental) -----------------------------

def model_score_bonus(ticker: str, model_scores: dict[str, float]) -> float:
    """Small bonus for names with high 정석 model_score. Supplemental only."""
    if not model_scores or ticker not in model_scores:
        return 1.0
    s = model_scores[ticker]
    if s >= 5.0:
        return 1.10
    if s >= 3.0:
        return 1.05
    if s < 1.0:
        return 0.95
    return 1.00


def load_model_scores(scored_csv: str) -> dict[str, float]:
    """Load 정석 engine's model_score as supplemental data."""
    path = Path(scored_csv)
    if not path.exists():
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    out = {}
    for _, row in df.iterrows():
        t = str(row.get("ticker", "")).upper().strip()
        s = row.get("score")
        if t and pd.notna(s):
            out[t] = float(s)
    return out


def load_current_portfolio(portfolio_csv: str) -> pd.DataFrame:
    path = Path(portfolio_csv)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


# --- Rank + concentration logic --------------------------------------------

@dataclass
class PortfolioPick:
    ticker: str
    scanner_score: float
    model_score_bonus: float
    final_score: float
    proposed_weight: float
    current_weight: float
    action: str
    theme: str
    phase: str
    tier: int
    warnings: list[str] = field(default_factory=list)


def build_top_n(
    candidates: list[ScannerCandidate],
    model_scores: dict[str, float],
    current_weights: dict[str, float],
    target_n: int = TARGET_N_POSITIONS,
) -> list[PortfolioPick]:
    """Recompute score with ADVISOR-specific multipliers.

    User insight (2026-04-24): "peaking은 여전히 강하다" - don't penalize like
    Aggressive engine does. Scanner uses 0.70x for peaking (aggressive exit),
    but for advisor/portfolio rebalance, peaking names are still acceptable
    if individual RS strong.

    Advisor phase multiplier (softer than scanner):
      early    1.15x
      maturing 1.05x
      peaking  1.00x  (user: "여전히 강함")
      unknown  1.00x
      dead     0.50x
      ending   0.65x
    """
    ADVISOR_PHASE_MULT = {
        "early":    1.15,
        "maturing": 1.05,
        "peaking":  1.00,    # user preference: don't penalize
        "unknown":  1.00,
        "dead":     0.50,
        "ending":   0.65,
    }

    ranked = []
    for c in candidates:
        if c.disqualified:
            continue
        if c.trade_card and c.trade_card.entry_status in ("FAILED", "EARLY"):
            continue

        # Rebuild effective_score from tech_score (undo scanner's aggressive penalty)
        adv_phase_mult = ADVISOR_PHASE_MULT.get(c.theme_phase, 1.0)
        bonus = model_score_bonus(c.ticker, model_scores)
        final_score = c.tech_score * adv_phase_mult * c.val_mult * bonus
        ranked.append((c, bonus, final_score))

    ranked.sort(key=lambda x: x[2], reverse=True)

    picks: list[PortfolioPick] = []

    for cand, bonus, fscore in ranked:
        if len(picks) >= target_n:
            break
        if fscore < 40.0:   # baseline quality floor (post-gates)
            continue

        rank = len(picks) + 1
        tier_cap = 0.08
        for n_up_to, cap in TIER_CAPS:
            if rank <= n_up_to:
                tier_cap = cap
                break

        # v2: sector cap disabled (user: "섹터 역할 축소").
        # Scanner already has theme phase gate for soft diversification.
        target = tier_cap
        if target < 0.03:
            continue

        cw = current_weights.get(cand.ticker, 0.0)
        if cw == 0:
            action = "BUY"
        elif target > cw * 1.1:
            action = "ADD"
        elif target < cw * 0.9:
            action = "TRIM"
        else:
            action = "HOLD"

        picks.append(PortfolioPick(
            ticker=cand.ticker,
            scanner_score=cand.final_score,
            model_score_bonus=bonus,
            final_score=fscore,
            proposed_weight=target,
            current_weight=cw,
            action=action,
            theme=cand.theme_primary or "-",
            phase=cand.theme_phase,
            tier=cand.best_tier,
            warnings=cand.fundamental_warnings,
        ))

    # Normalize to 100%
    total = sum(p.proposed_weight for p in picks)
    if total > 1.0:
        for p in picks:
            p.proposed_weight /= total

    return picks


# --- Report ----------------------------------------------------------------

def print_report(picks: list[PortfolioPick], current_portfolio: pd.DataFrame) -> None:
    print()
    print("=" * 100)
    print(f"REBALANCE PROPOSAL v2 (Scanner-based) - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 100)

    print()
    print("PROPOSED NEW PORTFOLIO (12 names, from R1000 scanner):")
    print(f"  {'Rank':<5} {'Ticker':<6} {'Weight':>7} {'ScanS':>6} {'Bonus':>6} "
          f"{'Final':>6} {'Tier':>4} {'Phase':<10} {'Action':<6} Warnings")
    print("  " + "-" * 95)
    total = 0.0
    for i, p in enumerate(picks, 1):
        warns = ", ".join(p.warnings[:2])[:30]
        print(f"  {i:<5} {p.ticker:<6} {p.proposed_weight*100:>6.2f}% "
              f"{p.scanner_score:>6.1f} {p.model_score_bonus:>6.2f} "
              f"{p.final_score:>6.1f} T{p.tier:<3} {p.phase:<10} "
              f"{p.action:<6} {warns}")
        total += p.proposed_weight
    print(f"  TOTAL: {total*100:.1f}%")

    # Diff
    old_tickers = set()
    if not current_portfolio.empty and "ticker" in current_portfolio.columns:
        old_tickers = {str(t).upper() for t in current_portfolio["ticker"]
                        if str(t).upper() != "CASH"}
    new_tickers = {p.ticker for p in picks}

    to_exit = old_tickers - new_tickers
    to_add = new_tickers - old_tickers
    to_hold = old_tickers & new_tickers

    print()
    print(f"DIFF vs current:")
    print(f"  EXIT ({len(to_exit)}):  {sorted(to_exit)}")
    print(f"  ADD  ({len(to_add)}):   {sorted(to_add)}")
    print(f"  HOLD ({len(to_hold)}):  {sorted(to_hold)}")


def save_results(picks: list[PortfolioPick], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(p) for p in picks]
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "new_top12_proposed.csv", index=False)
    print(f"\n[save] wrote {out_dir / 'new_top12_proposed.csv'}")


# --- CLI -------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scored-csv", type=str,
                        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_latest.csv")
    parser.add_argument("--portfolio-csv", type=str,
                        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv")
    parser.add_argument("--output-dir", type=str, default="outputs_advisor_v2")
    parser.add_argument("--min-tech-score", type=float, default=60.0)
    parser.add_argument("--scanner-top", type=int, default=60,
                        help="top-N candidates to pull from scanner")
    parser.add_argument("--target-n", type=int, default=12)
    parser.add_argument("--use-cached-scanner", action="store_true",
                        help="load previous scanner output instead of rescanning (dev)")
    args = parser.parse_args()

    print("=" * 70)
    print("Advisor v2 - Scanner-based selection")
    print("=" * 70)

    # Load auxiliary data
    model_scores = load_model_scores(args.scored_csv)
    print(f"[load] 정석 model_scores: {len(model_scores)} tickers")
    portfolio = load_current_portfolio(args.portfolio_csv)
    print(f"[load] current portfolio: {len(portfolio)} positions")
    current_weights = {}
    if not portfolio.empty and "ticker" in portfolio.columns:
        for _, r in portfolio.iterrows():
            current_weights[str(r["ticker"]).upper()] = float(r.get("weight") or 0.0)

    # Run full R1000 scan OR load cached
    if args.use_cached_scanner:
        import json, glob, os
        cache_files = sorted(glob.glob("aggressive/state/scanner/candidates_*.json"),
                              reverse=True)
        if cache_files:
            print(f"\n[scan] loading cached: {cache_files[0]}")
            with open(cache_files[0], encoding="utf-8") as f:
                cached = json.load(f)
            # Reconstruct minimal candidates from JSON
            candidates = []
            for c in cached.get("candidates", []):
                tc = c.get("trade_card")
                from aggressive.entry_precision import TradeCard
                trade_card = None
                if tc:
                    trade_card = TradeCard(
                        ticker=tc.get("ticker", ""),
                        entry_status=tc.get("entry_status", "READY"),
                    )
                candidates.append(ScannerCandidate(
                    ticker=c["ticker"],
                    tech_score=c.get("tech_score", 0),
                    best_tier=c.get("best_tier", 0),
                    theme_primary=c.get("theme_primary"),
                    theme_phase=c.get("theme_phase", "unknown"),
                    phase_multiplier=c.get("phase_multiplier", 1.0),
                    liquidity_ok=c.get("liquidity_ok", True),
                    disqualified=c.get("disqualified", False),
                    final_score=c.get("final_score", 0),
                    signals_fired=c.get("signals_fired", []),
                    rationale=c.get("rationale", ""),
                    metrics=c.get("metrics", {}),
                    trade_card=trade_card,
                    is_unknown_theme=c.get("is_unknown_theme", False),
                    val_mult=c.get("val_mult", 1.0),
                    fundamental_warnings=c.get("fundamental_warnings", []),
                    finnhub_features=c.get("finnhub_features", {}),
                ))
        else:
            print("\n[scan] no cached scanner output - running fresh")
            candidates = scan(universe_source="r1000",
                              min_tech_score=args.min_tech_score,
                              top_n=args.scanner_top, verbose=True)
    else:
        print("\n[scan] running full R1000 scanner (this takes ~10-15 min)...")
        candidates = scan(
            universe_source="r1000",
            min_tech_score=args.min_tech_score,
            top_n=args.scanner_top,
            verbose=True,
        )
    print(f"[scan] scanner returned {len(candidates)} candidates")

    # Build picks with concentration
    picks = build_top_n(
        candidates, model_scores, current_weights,
        target_n=args.target_n,
    )
    print(f"[build] final picks: {len(picks)}")

    # Report + save
    print_report(picks, portfolio)
    save_results(picks, Path(args.output_dir))

    return 0


if __name__ == "__main__":
    sys.exit(main())
