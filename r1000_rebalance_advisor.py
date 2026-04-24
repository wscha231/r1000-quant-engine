"""r1000 Rebalance Advisor - Phase V+F Post-Processor.

Reads current 정석 engine output (scored_latest.csv) and applies the new
4-gate filter system, producing a rebalance proposal WITHOUT touching
the production pipeline / backtest code.

User mandate (2026-04-24):
  "집중투자 > 분산 (필요없는 분산보다). 섹터 분산은 약한 역할.
   개별종목 RS 가 제일 중요. peaking은 여전히 강하고, dead는 안좋다.
   GOOG는 다각화 기업이라 단일테마로 잘못 분류됨 (ai_software DEAD).
   과대평가 (PEG 극단) 피하기. 시스템이 스스로 찾아내야 함 (하드코딩 X)."

The 4 gates applied to every candidate:
  Layer 1: Model Score           (existing ML ensemble)
  Layer 2: Individual RS Gate    (12m RS vs SPY)
  Layer 3: Valuation Gate        (Finnhub PEG + sector relative)
  Layer 4: Theme Soft-Gate       (dead + weak RS only)

Concentration rules:
  - 12 names target (from 18)
  - Tier caps: top 3 -> 18%, 4-6 -> 12%, 7+ -> 8%
  - Sub-sector cap 35% (soft)
  - Sleeve 65 / 25 / 10 (core / future / early)

Outputs:
  outputs/rebalance_proposal.csv        - side-by-side old vs new weights
  outputs/rebalance_diff.txt            - human-readable trade list
  outputs/new_top12_proposed.csv        - the proposed new portfolio

Usage:
  py -3 r1000_rebalance_advisor.py
  py -3 r1000_rebalance_advisor.py --output-dir outputs_local/
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Add sys.path for aggressive module access
sys.path.insert(0, str(Path(__file__).parent))


# =========================================================================
# Configuration - tunable via CLI or direct import
# =========================================================================

TARGET_N_POSITIONS = 12
TIER_CAPS = [
    (3, 0.18),    # Top 3 up to 18%
    (6, 0.12),    # Next 3 up to 12%
    (999, 0.08),  # Rest up to 8%
]
# User preference (2026-04-24): "집중투자 > 분산. 오른놈들끼리 오르는 성향".
# Sector cap effectively disabled (70% = very generous) to let top RS leaders
# in same sector coexist. The tier caps (18/12/8) provide sufficient concentration
# control. If top 5 RS names are all IT, let them all in.
SUBSECTOR_CAP_PCT = 0.70
SLEEVE_TARGETS = {
    "core_compounder": 0.65,
    "future_winner":   0.25,
    "early_scout":     0.10,
}


# Individual RS Gate (Layer 2) — 12m RS vs SPY tiered multiplier
def rs_multiplier(rs_12m_pct: float) -> float:
    """User: strong RS lets winners compound; negative RS is the real signal."""
    if rs_12m_pct is None or np.isnan(rs_12m_pct):
        return 1.0
    if rs_12m_pct >= 100:
        return 1.30    # Absolute strength (LITE/WDC tier)
    if rs_12m_pct >= 50:
        return 1.20
    if rs_12m_pct >= 20:
        return 1.10
    if rs_12m_pct >= 0:
        return 1.00
    if rs_12m_pct >= -20:
        return 0.70
    if rs_12m_pct >= -50:
        return 0.40
    return 0.15         # Severe underperformance = near-exit


# Theme Soft-Gate (Layer 4) — ONLY penalize dead+weak RS (user's insight)
def theme_soft_multiplier(theme_phase: str, rs_12m_pct: float) -> float:
    """User: 'peaking은 여전히 강하다. dead는 안좋다. 다만 개별이 RS 강하면 봐줘.'"""
    if rs_12m_pct is None:
        rs_12m_pct = 0.0
    # User's rule: dead theme is a penalty ONLY IF individual RS also weak
    if theme_phase == "dead":
        return 0.50 if rs_12m_pct < 20 else 0.95    # GOOG case gets 0.95 not 0.50
    if theme_phase == "ending":
        return 0.70 if rs_12m_pct < 0 else 1.00
    if theme_phase == "peaking":
        return 1.00                                    # no penalty (user preference)
    if theme_phase == "maturing":
        return 1.05                                    # slight bonus
    if theme_phase == "early":
        return 1.15                                    # growth runway
    return 1.00                                        # unknown, neutral


# =========================================================================
# Valuation Gate (Layer 3) — Finnhub + sector relative
# =========================================================================

def valuation_multiplier(
    fh_row: dict,
    sector_median_peg: float,
    sector_median_pe: float,
) -> tuple[float, list[str]]:
    """Return (val_mult, reasons). User: avoid absurd overvaluation."""
    mult = 1.0
    reasons = []
    if not fh_row:
        return mult, ["no Finnhub data"]

    pe = fh_row.get("fh_peExclExtra_ttm")
    g5 = fh_row.get("fh_epsGrowth5Y")
    gq = fh_row.get("fh_epsGrowthQuarterlyYoy")
    g3 = fh_row.get("fh_epsGrowth3Y")

    # Blended growth (5% floor, 30% cap) to avoid cyclical bias
    growths = [g for g in (g5, g3, gq) if g is not None and not np.isnan(g)]
    growths = [max(5.0, min(30.0, float(g))) for g in growths]
    blended_growth = np.median(growths) if growths else 10.0

    # Effective PEG using blended growth
    eff_peg = None
    if pe and blended_growth > 0:
        eff_peg = float(pe) / blended_growth

    # Raw growth for slow-growth detection
    is_slow = bool(
        (gq is None or abs(float(gq) if gq else 0) < 10)
        and (g5 is None or abs(float(g5) if g5 else 0) < 10)
    )

    # Valuation vs sector (if sector medians available)
    peg_vs_sector = None
    pe_vs_sector = None
    if eff_peg and sector_median_peg and sector_median_peg > 0:
        peg_vs_sector = eff_peg / sector_median_peg
    if pe and sector_median_pe and sector_median_pe > 0:
        pe_vs_sector = float(pe) / sector_median_pe

    # Gates:
    # 1. Extreme overvaluation (PEG eff > 4 + slow growth) - AAPL case
    if eff_peg and eff_peg > 4.0 and is_slow:
        mult *= 0.50
        reasons.append(f"PEG eff {eff_peg:.1f} + slow growth")

    # 2. Elevated PEG (>3.0) with slow growth
    elif eff_peg and eff_peg > 3.0 and is_slow:
        mult *= 0.75
        reasons.append(f"PEG {eff_peg:.1f} elevated+slow")

    # 3. Sector-relative PE extreme (> 2.5x sector median AND individual slow)
    if pe_vs_sector and pe_vs_sector > 2.5 and is_slow:
        mult *= 0.80
        reasons.append(f"PE {pe_vs_sector:.1f}x sector")

    # 4. Earnings event risk (< 7 days)
    dte = fh_row.get("fh_days_to_next_earnings")
    if dte is not None and 0 <= dte <= 7:
        mult *= 0.80
        reasons.append(f"earnings in {dte}d")

    # 5. Strong insider buying cluster
    cluster = fh_row.get("fh_insider_cluster_30d_score")
    if cluster and cluster >= 50:
        mult *= 1.15
        reasons.append(f"insider cluster {cluster:.0f}")

    # 6. Strongly bullish analyst consensus
    bull = fh_row.get("fh_rec_bull_ratio")
    if bull and bull >= 0.80:
        mult *= 1.05
        reasons.append(f"analysts bullish {bull*100:.0f}%")

    return mult, reasons


# =========================================================================
# Main advisor
# =========================================================================

@dataclass
class RankedCandidate:
    ticker: str
    name: str
    sector: str
    sleeve: str
    # Scores
    model_score: float
    rs_12m: float
    effective_score: float
    # Multipliers
    rs_mult: float
    val_mult: float
    theme_mult: float
    # Context
    theme_phase: str
    theme_primary: Optional[str]
    price: float
    mktcap: float
    # Valuation
    peg_eff: Optional[float]
    pe_ttm: Optional[float]
    # Warnings
    warnings: list[str]
    # Proposed weight (filled later)
    proposed_weight: float = 0.0
    current_weight: float = 0.0
    action: str = "HOLD"


def load_finnhub_as_dict(
    parquet_path: Optional[Path] = None,
) -> dict[str, dict]:
    """Load Finnhub features into dict[ticker, row]."""
    if parquet_path is None:
        parquet_path = Path(__file__).parent / "aggressive" / "state" / "finnhub" / "r1000_features.parquet"
    if not parquet_path.exists():
        print(f"WARN: Finnhub parquet not found at {parquet_path}")
        return {}
    df = pd.read_parquet(parquet_path)
    out = {}
    for _, row in df.iterrows():
        ticker = str(row["ticker"]).upper()
        r = {}
        for k, v in row.items():
            if pd.notna(v) and v is not None:
                if hasattr(v, "item"):
                    v = v.item()
                r[k] = v
        out[ticker] = r
    return out


def compute_sector_medians(df: pd.DataFrame) -> dict[str, dict]:
    """Sector median PEG + PE for relative gate logic."""
    out = {}
    for sector in df["sector"].dropna().unique():
        sub = df[df["sector"] == sector]
        peg_vals = pd.to_numeric(sub.get("peg_eff"), errors="coerce")
        pe_vals = pd.to_numeric(sub.get("pe_ttm"), errors="coerce")
        out[sector] = {
            "peg_median": float(peg_vals[(peg_vals > 0) & (peg_vals < 50)].median() or 1.5),
            "pe_median": float(pe_vals[(pe_vals > 0) & (pe_vals < 200)].median() or 20.0),
        }
    return out


def compute_live_rs_for_tickers(tickers: list[str], verbose: bool = True) -> dict[str, float]:
    """Compute live 12m RS vs SPY using Alpaca bars. Returns dict[ticker, rs_pct]."""
    try:
        from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
    except Exception as e:
        print(f"[rs] Alpaca not available: {e}")
        return {}

    spy = fetch_spy_benchmark(days=260)
    if spy.empty or len(spy) < 252:
        return {}

    out: dict[str, float] = {}
    for i, t in enumerate(tickers, 1):
        if verbose and i % 50 == 0:
            print(f"[rs] {i}/{len(tickers)}...")
        df = fetch_daily_bars(t, days=260)
        if df.empty or len(df) < 252:
            continue
        aligned = pd.concat([df["close"].rename("t"), spy["close"].rename("s")],
                              axis=1, join="inner").dropna()
        if len(aligned) < 252:
            continue
        rs12 = ((aligned["t"].iloc[-1] / aligned["t"].iloc[-252] - 1.0) -
                (aligned["s"].iloc[-1] / aligned["s"].iloc[-252] - 1.0)) * 100.0
        out[t.upper()] = float(rs12)
    return out


def rank_candidates(
    scored_df: pd.DataFrame,
    finnhub_dict: dict[str, dict],
    live_rs: Optional[dict[str, float]] = None,
    min_model_score: float = 1.0,
    min_mktcap: float = 5e9,
) -> list[RankedCandidate]:
    """Apply 4 gates and produce ranked candidate list."""
    d = scored_df.copy()
    d = d[d["score"].notna()]
    d = d[pd.to_numeric(d["score"], errors="coerce") >= min_model_score]

    # Filter by market cap if available
    if "market_cap_live" in d.columns:
        mcap = pd.to_numeric(d["market_cap_live"], errors="coerce")
        d = d[mcap >= min_mktcap]

    # Precompute PEG-eff + PE for sector medians
    temp_rows = []
    for _, row in d.iterrows():
        ticker = str(row["ticker"]).upper()
        fh = finnhub_dict.get(ticker, {})
        pe = fh.get("fh_peExclExtra_ttm")
        g5 = fh.get("fh_epsGrowth5Y")
        gq = fh.get("fh_epsGrowthQuarterlyYoy")
        g3 = fh.get("fh_epsGrowth3Y")
        growths = [g for g in (g5, g3, gq) if g is not None]
        growths = [max(5.0, min(30.0, float(g))) for g in growths if not np.isnan(float(g))]
        blended = np.median(growths) if growths else 10.0
        peg_eff = (float(pe) / blended) if pe and blended > 0 else None
        temp_rows.append({
            "ticker": ticker,
            "sector": row.get("sector", "Unknown"),
            "peg_eff": peg_eff,
            "pe_ttm": float(pe) if pe else None,
        })
    temp_df = pd.DataFrame(temp_rows)
    sector_medians = compute_sector_medians(temp_df)

    # Build candidates
    candidates: list[RankedCandidate] = []
    for _, row in d.iterrows():
        ticker = str(row["ticker"]).upper()
        fh = finnhub_dict.get(ticker, {})
        sector = str(row.get("sector", "Unknown"))
        sec_med = sector_medians.get(sector, {"peg_median": 1.5, "pe_median": 20.0})

        # Individual RS - prefer live Alpaca recompute over stale scored_latest value
        rs_12m_pct = 0.0
        if live_rs and ticker in live_rs:
            rs_12m_pct = live_rs[ticker]
        elif "rs_benchmark_12m" in row and pd.notna(row["rs_benchmark_12m"]):
            rs_12m_pct = float(row["rs_benchmark_12m"]) * 100.0

        # Theme phase
        theme_phase = str(row.get("theme_phase_primary", "unknown") or "unknown")
        theme_primary = row.get("theme_primary")
        if pd.isna(theme_primary):
            theme_primary = None

        # Model score
        model_score = float(row.get("score") or 0.0)

        # Multipliers
        rs_mult = rs_multiplier(rs_12m_pct)
        val_mult, val_warnings = valuation_multiplier(
            fh, sec_med["peg_median"], sec_med["pe_median"],
        )
        theme_mult = theme_soft_multiplier(theme_phase, rs_12m_pct)

        eff_score = model_score * rs_mult * val_mult * theme_mult

        # Compute eff PEG for display
        pe = fh.get("fh_peExclExtra_ttm")
        g5 = fh.get("fh_epsGrowth5Y")
        gq = fh.get("fh_epsGrowthQuarterlyYoy")
        g3 = fh.get("fh_epsGrowth3Y")
        growths = [g for g in (g5, g3, gq) if g is not None]
        growths = [max(5.0, min(30.0, float(g))) for g in growths if not np.isnan(float(g))]
        blended = np.median(growths) if growths else 10.0
        peg_eff = (float(pe) / blended) if pe and blended > 0 else None

        warnings_combined = list(val_warnings)
        if rs_12m_pct < -20:
            warnings_combined.append(f"RS 12m {rs_12m_pct:+.0f}% weak")
        if theme_phase == "dead" and rs_12m_pct < 20:
            warnings_combined.append(f"dead theme + weak RS")

        cand = RankedCandidate(
            ticker=ticker,
            name=str(row.get("Name", "")),
            sector=sector,
            sleeve=str(row.get("portfolio_sleeve_label") or "core_compounder"),
            model_score=model_score,
            rs_12m=rs_12m_pct,
            effective_score=eff_score,
            rs_mult=rs_mult,
            val_mult=val_mult,
            theme_mult=theme_mult,
            theme_phase=theme_phase,
            theme_primary=theme_primary,
            price=float(row.get("current_price_live") or 0.0),
            mktcap=float(row.get("market_cap_live") or 0.0),
            peg_eff=peg_eff,
            pe_ttm=float(pe) if pe else None,
            warnings=warnings_combined,
        )
        candidates.append(cand)

    candidates.sort(key=lambda c: c.effective_score, reverse=True)
    return candidates


def build_new_portfolio(
    candidates: list[RankedCandidate],
    current_portfolio: pd.DataFrame,
) -> list[RankedCandidate]:
    """Build the proposed 12-name portfolio.

    Strategy: rank-first packing (simpler + respects user's concentration intent).
      1. Rank candidates by effective_score
      2. Pick top N (default 12)
      3. Assign tier cap by portfolio rank (not sleeve rank)
      4. Sub-sector cap 35% soft (disallow >35% in one subsector)
      5. Normalize to sum to <= 100%
    """
    current_weights = {}
    if "ticker" in current_portfolio.columns and "weight" in current_portfolio.columns:
        for _, r in current_portfolio.iterrows():
            t = str(r["ticker"]).upper()
            current_weights[t] = float(r.get("weight") or 0.0)

    selected: list[RankedCandidate] = []
    sector_totals: dict[str, float] = {}

    for cand in candidates:
        if len(selected) >= TARGET_N_POSITIONS:
            break
        if cand.effective_score < 1.0:
            continue

        # Determine tier cap by portfolio rank
        rank_among_selected = len(selected) + 1
        tier_cap = 0.08
        for n_up_to, cap in TIER_CAPS:
            if rank_among_selected <= n_up_to:
                tier_cap = cap
                break

        # Check sub-sector cap (soft)
        sector_used = sector_totals.get(cand.sector, 0.0)
        sector_remaining = SUBSECTOR_CAP_PCT - sector_used
        if sector_remaining <= 0.02:
            continue  # sector saturated, skip

        target_weight = min(tier_cap, sector_remaining)
        if target_weight < 0.03:
            continue

        cand.proposed_weight = target_weight
        cand.current_weight = current_weights.get(cand.ticker, 0.0)
        if cand.current_weight == 0:
            cand.action = "BUY"
        elif target_weight > cand.current_weight * 1.1:
            cand.action = "ADD"
        elif target_weight < cand.current_weight * 0.9:
            cand.action = "TRIM"
        else:
            cand.action = "HOLD"

        selected.append(cand)
        sector_totals[cand.sector] = sector_used + target_weight

    # Normalize to sum to at most 100%
    total = sum(c.proposed_weight for c in selected)
    if total > 1.0:
        scale = 1.0 / total
        for c in selected:
            c.proposed_weight *= scale

    return selected


# =========================================================================
# Reporting
# =========================================================================

def print_rebalance_report(
    new_portfolio: list[RankedCandidate],
    old_portfolio: pd.DataFrame,
) -> None:
    print()
    print("=" * 100)
    print(f"REBALANCE PROPOSAL - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 100)

    # NEW portfolio table
    print()
    print("PROPOSED NEW PORTFOLIO (12 names, concentrated + V+F gated):")
    print(f"  {'Ticker':<6} {'Weight':>7} {'Sleeve':<16} {'Phase':<10} "
          f"{'Score':>7} {'RS12m':>7} {'RSMul':>6} {'ValMul':>6} {'ThMul':>6} "
          f"{'Action':<6}")
    print("  " + "-" * 95)
    total_new = 0.0
    for c in new_portfolio:
        print(f"  {c.ticker:<6} {c.proposed_weight*100:>6.2f}% {c.sleeve[:16]:<16} "
              f"{c.theme_phase:<10} {c.effective_score:>7.2f} {c.rs_12m:>+7.1f} "
              f"{c.rs_mult:>6.2f} {c.val_mult:>6.2f} {c.theme_mult:>6.2f} "
              f"{c.action:<6}")
        total_new += c.proposed_weight
    print(f"  TOTAL: {total_new*100:.1f}%  cash={100*(1-total_new):.1f}%")

    # Old portfolio diff
    old_tickers = set()
    if "ticker" in old_portfolio.columns:
        old_tickers = set(str(t).upper() for t in old_portfolio["ticker"])
    new_tickers = set(c.ticker for c in new_portfolio)

    to_exit = old_tickers - new_tickers - {"CASH"}
    to_add = new_tickers - old_tickers
    to_hold = old_tickers & new_tickers

    print()
    print(f"DIFF vs current portfolio:")
    print(f"  TO EXIT ({len(to_exit)}):  {sorted(to_exit)}")
    print(f"  TO ADD  ({len(to_add)}):  {sorted(to_add)}")
    print(f"  HOLD    ({len(to_hold)}): {sorted(to_hold)}")

    # Rationale for exits
    if to_exit:
        print()
        print("Exit rationale (from candidates that didn't make cut):")
        for t in sorted(to_exit):
            # Look up this ticker's rejection reasons
            matches = [c for c in new_portfolio if c.ticker == t]
            if matches:
                continue
            # Find in the broader candidate list (via scored_df) - simpler: show current weight + name
            oldrow = old_portfolio[old_portfolio["ticker"] == t]
            if not oldrow.empty:
                r = oldrow.iloc[0]
                w = float(r.get("weight") or 0.0)
                name = str(r.get("Name", ""))[:25]
                print(f"  {t:<6} ({w*100:.1f}% current) {name}")


def save_rebalance_files(
    new_portfolio: list[RankedCandidate],
    old_portfolio: pd.DataFrame,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Proposed CSV
    rows = []
    for c in new_portfolio:
        rows.append({
            "ticker": c.ticker,
            "name": c.name,
            "sector": c.sector,
            "sleeve": c.sleeve,
            "theme_phase": c.theme_phase,
            "proposed_weight": c.proposed_weight,
            "current_weight": c.current_weight,
            "action": c.action,
            "model_score": c.model_score,
            "effective_score": c.effective_score,
            "rs_12m_pct": c.rs_12m,
            "rs_mult": c.rs_mult,
            "val_mult": c.val_mult,
            "theme_mult": c.theme_mult,
            "peg_eff": c.peg_eff,
            "pe_ttm": c.pe_ttm,
            "mktcap_b": c.mktcap / 1e9,
            "warnings": "; ".join(c.warnings),
        })
    new_df = pd.DataFrame(rows)
    new_df.to_csv(output_dir / "new_top12_proposed.csv", index=False)

    # 2. Side-by-side diff CSV
    old_w = {}
    if not old_portfolio.empty:
        for _, r in old_portfolio.iterrows():
            old_w[str(r["ticker"]).upper()] = float(r.get("weight") or 0.0)
    all_tickers = set(new_df["ticker"]) | set(old_w.keys())
    diff_rows = []
    for t in sorted(all_tickers):
        new_row = new_df[new_df["ticker"] == t]
        new_w = float(new_row["proposed_weight"].iloc[0]) if not new_row.empty else 0.0
        old_w_val = old_w.get(t, 0.0)
        delta = new_w - old_w_val
        diff_rows.append({
            "ticker": t,
            "old_weight": old_w_val,
            "new_weight": new_w,
            "delta": delta,
            "action": "BUY" if (old_w_val == 0 and new_w > 0) else
                      "EXIT" if (old_w_val > 0 and new_w == 0) else
                      "ADD" if delta > 0.01 else
                      "TRIM" if delta < -0.01 else
                      "HOLD",
        })
    diff_df = pd.DataFrame(diff_rows).sort_values("delta", key=abs, ascending=False)
    diff_df.to_csv(output_dir / "rebalance_diff.csv", index=False)

    print(f"\n[save] wrote {output_dir / 'new_top12_proposed.csv'}")
    print(f"[save] wrote {output_dir / 'rebalance_diff.csv'}")


# =========================================================================
# CLI
# =========================================================================

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scored-csv", type=str,
                        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_latest.csv")
    parser.add_argument("--portfolio-csv", type=str,
                        default=r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv")
    parser.add_argument("--output-dir", type=str, default="outputs_advisor")
    parser.add_argument("--min-mktcap-b", type=float, default=5.0,
                        help="min market cap in $B (default 5)")
    parser.add_argument("--min-model-score", type=float, default=1.0)
    args = parser.parse_args()

    # Load inputs
    scored_df = pd.read_csv(args.scored_csv)
    portfolio_df = pd.read_csv(args.portfolio_csv)
    print(f"[load] scored: {len(scored_df)} rows")
    print(f"[load] portfolio: {len(portfolio_df)} rows")

    # Merge theme_phase from portfolio_theme_alignment if available
    alignment_path = Path(args.portfolio_csv).parent / "portfolio_theme_alignment.csv"
    if alignment_path.exists():
        align = pd.read_csv(alignment_path)
        if "theme_phase_primary" in align.columns:
            scored_df = scored_df.merge(
                align[["ticker", "theme_primary", "theme_phase_primary"]],
                on="ticker", how="left",
            )
    # Also merge theme status for broader coverage
    theme_status_path = Path(args.portfolio_csv).parent / "theme_status_latest.csv"

    finnhub_dict = load_finnhub_as_dict()
    print(f"[load] Finnhub: {len(finnhub_dict)} tickers")

    # Compute live RS for candidates passing basic filter (to avoid full R1000 fetch)
    basic_filter = scored_df[scored_df["score"].notna()]
    basic_filter = basic_filter[pd.to_numeric(basic_filter["score"], errors="coerce") >= args.min_model_score]
    if "market_cap_live" in basic_filter.columns:
        mcap = pd.to_numeric(basic_filter["market_cap_live"], errors="coerce")
        basic_filter = basic_filter[mcap >= args.min_mktcap_b * 1e9]
    candidate_tickers = sorted(set(str(t).upper() for t in basic_filter["ticker"].dropna()))
    print(f"[load] computing live RS for {len(candidate_tickers)} candidates via Alpaca...")
    live_rs = compute_live_rs_for_tickers(candidate_tickers, verbose=True)
    print(f"[load] live RS computed: {len(live_rs)} tickers")

    # Rank all candidates
    candidates = rank_candidates(
        scored_df, finnhub_dict, live_rs=live_rs,
        min_model_score=args.min_model_score,
        min_mktcap=args.min_mktcap_b * 1e9,
    )
    print(f"[rank] {len(candidates)} candidates passed basic filters")
    print(f"       top 5 by effective_score:")
    for c in candidates[:5]:
        print(f"         {c.ticker:<6} eff={c.effective_score:.2f} "
              f"model={c.model_score:.2f} rs={c.rs_12m:+.1f}% "
              f"rs*val*thm = {c.rs_mult:.2f}*{c.val_mult:.2f}*{c.theme_mult:.2f}")

    # Build new portfolio with concentration rules
    new_portfolio = build_new_portfolio(candidates, portfolio_df)

    # Report + save
    print_rebalance_report(new_portfolio, portfolio_df)
    save_rebalance_files(new_portfolio, portfolio_df, Path(args.output_dir))

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
