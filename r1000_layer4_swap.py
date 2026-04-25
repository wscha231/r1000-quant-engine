"""r1000_layer4_swap — Layer 4 (RS-based position swap) bridge.

Provides current-holdings + candidate-pool inputs for
r1000_risk_sensing.evaluate_layer4_swap. Layer 4 swaps weak holdings
(rs_12m_pct < 0, held >= 60 days) for strong alts (rs_12m_pct >= 30).

History:
  c8b5773 (Phase 2)  4-layer risk sensing system (logic)
  6540ec6 (Layer 3)  VIX/SPY-200MA bridge
  977fcd0 (Layer 3)  paper_executor pre-flight wiring
  this    (Layer 4)  RS-based swap bridge

Data sources:
  Portfolio holdings:
    1st choice: portfolio_latest.csv (production 정석 portfolio)
    2nd choice: outputs_advisor/new_top12_proposed.csv (advisor v1)
    columns expected: ticker, weight, agent_entry_date OR entry_date
  Candidate pool:
    scored_unified.csv (1012 names, 정석 + Finnhub synthetic)
    columns expected: ticker, rs_benchmark_12m

Usage as library:
    from r1000_layer4_swap import layer4_swap_suggestions
    swaps = layer4_swap_suggestions()
    for s in swaps: print(s["ticker"], "->", s["swap_to"])

CLI:
    py -3 r1000_layer4_swap.py                  # default Drive paths
    py -3 r1000_layer4_swap.py --portfolio outputs_advisor/new_top12_proposed.csv
    py -3 r1000_layer4_swap.py --json           # machine-readable

Design notes:
  - Layer 4 uses ONLY rs_12m_pct + days_held (not rs_at_entry, peak_price).
    So we don't need historical RS lookups, just current.
  - days_held computed from agent_entry_date / entry_date column.
    Falls back to 90 days if missing (passes swap_weak_min_held_days=60).
  - rs_12m_pct input is in PERCENT (not decimal) — RiskConfig defaults
    swap_strong_rs_threshold=30 mean +30 percentage-point excess vs SPY.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


# Default paths (Windows Drive mirror — override via CLI on Linux)
DEFAULT_PORTFOLIO = r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv"
DEFAULT_SCORED_CSV = r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_unified.csv"

DEFAULT_DAYS_HELD = 90  # fallback when entry_date missing (passes 60d gate)


# ---------------------------------------------------------------------------
# Holding -> PositionState
# ---------------------------------------------------------------------------

def _days_since(date_str: str) -> int:
    if not date_str or str(date_str).lower() in ("nan", "none", ""):
        return DEFAULT_DAYS_HELD
    try:
        # Try a few formats
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                d = datetime.strptime(str(date_str)[:10], fmt)
                return max(0, (datetime.now() - d).days)
            except ValueError:
                continue
        # ISO fallback
        d = datetime.fromisoformat(str(date_str)[:19])
        return max(0, (datetime.now() - d).days)
    except Exception:
        return DEFAULT_DAYS_HELD


def build_position_list(portfolio_csv: Path, rs_lookup: dict[str, float]) -> list:
    """Read portfolio_latest.csv -> list[PositionState].

    rs_lookup: {ticker_upper: rs_12m_pct_in_percentage_points}
    """
    try:
        import pandas as pd
        from r1000_risk_sensing import PositionState
    except ImportError as e:
        print(f"[layer4] dependency missing: {e}", file=sys.stderr)
        return []

    if not portfolio_csv.exists():
        print(f"[layer4] portfolio CSV missing at {portfolio_csv}", file=sys.stderr)
        return []

    df = pd.read_csv(portfolio_csv)
    out = []
    entry_col = None
    for c in ("agent_entry_date", "entry_date", "entered_on"):
        if c in df.columns:
            entry_col = c
            break

    weight_col = "weight" if "weight" in df.columns else "proposed_weight"
    if weight_col not in df.columns:
        print(f"[layer4] no weight/proposed_weight column in {portfolio_csv}", file=sys.stderr)
        return []

    for _, r in df.iterrows():
        ticker = str(r.get("ticker", "")).upper().strip()
        if not ticker or ticker in ("CASH", "NAN"):
            continue
        weight = float(r.get(weight_col) or 0.0)
        if weight <= 0:
            continue
        days_held = _days_since(str(r.get(entry_col, ""))) if entry_col else DEFAULT_DAYS_HELD
        rs = rs_lookup.get(ticker, 0.0)
        # Build PositionState — only fields Layer 4 actually reads:
        # rs_12m_pct + days_held + ticker. Others get safe defaults.
        out.append(PositionState(
            ticker=ticker,
            entry_date=str(r.get(entry_col, "") or ""),
            entry_price=float(r.get("reference_price") or r.get("entry_price") or 0.0),
            current_price=float(r.get("reference_price") or r.get("entry_price") or 0.0),
            peak_price_since_entry=float(r.get("reference_price") or r.get("entry_price") or 0.0),
            weight=weight,
            days_held=days_held,
            rs_12m_pct=rs,
            rs_12m_at_entry=rs,  # Layer 4 doesn't use this
            theme_phase="unknown",
        ))
    return out


# ---------------------------------------------------------------------------
# Candidate pool
# ---------------------------------------------------------------------------

def build_candidate_pool(scored_csv: Path) -> tuple[list[dict], dict[str, float]]:
    """Read scored_unified.csv -> (candidate_dicts, rs_lookup).

    candidate_dicts: list of {"ticker": ..., "rs_12m_pct": ...}
    rs_lookup: {ticker: rs_in_pp} for use by build_position_list.
    """
    try:
        import pandas as pd
    except ImportError:
        return [], {}

    if not scored_csv.exists():
        print(f"[layer4] scored CSV missing at {scored_csv}", file=sys.stderr)
        return [], {}

    df = pd.read_csv(scored_csv)

    # rs_benchmark_12m is in DECIMAL (e.g. 0.32 for +32%).
    # Layer 4 RiskConfig thresholds are in PERCENTAGE POINTS (e.g. 30.0).
    rs_col = None
    for c in ("rs_benchmark_12m", "mom_12m", "rs_12m"):
        if c in df.columns:
            rs_col = c
            break
    if rs_col is None:
        print(f"[layer4] no rs/mom column in {scored_csv}", file=sys.stderr)
        return [], {}

    candidates = []
    rs_lookup = {}
    for _, r in df.iterrows():
        ticker = str(r.get("ticker", "")).upper().strip()
        if not ticker or ticker in ("CASH", "NAN"):
            continue
        v = r.get(rs_col)
        if v is None or pd.isna(v):
            continue
        rs_pp = float(v) * 100.0  # decimal -> percentage points
        rs_lookup[ticker] = rs_pp
        candidates.append({"ticker": ticker, "rs_12m_pct": rs_pp})
    return candidates, rs_lookup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def layer4_swap_suggestions(
    portfolio_csv: Optional[str] = None,
    scored_csv: Optional[str] = None,
) -> list[dict]:
    """Compute Layer 4 swap suggestions. Returns list of plain dicts.

    Each dict: {ticker, swap_to, reason, layer, priority}
    """
    pcsv = Path(portfolio_csv or DEFAULT_PORTFOLIO)
    scsv = Path(scored_csv or DEFAULT_SCORED_CSV)

    candidates, rs_lookup = build_candidate_pool(scsv)
    if not candidates:
        return [{"error": f"could not build candidate pool from {scsv}"}]

    positions = build_position_list(pcsv, rs_lookup)
    if not positions:
        return [{"error": f"could not build position list from {pcsv}"}]

    try:
        from r1000_risk_sensing import (
            PortfolioState, RiskConfig, evaluate_layer4_swap,
        )
    except ImportError as e:
        return [{"error": f"risk_sensing import failed: {e}"}]

    state = PortfolioState(
        nav=1.0, nav_peak_recent=1.0, cash_weight=0.10,
        spy_above_200ma=True, vix_level=20.0,
        positions=positions,
    )
    actions = evaluate_layer4_swap(
        state, candidates, RiskConfig(), held_for_action=set(),
    )
    return [
        {
            "ticker": a.ticker, "swap_to": a.swap_to,
            "type": a.type, "layer": a.layer, "priority": a.priority,
            "reason": a.reason,
        }
        for a in actions
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--portfolio", default=DEFAULT_PORTFOLIO,
                   help="portfolio CSV (with ticker/weight/entry_date columns)")
    p.add_argument("--scored-csv", default=DEFAULT_SCORED_CSV,
                   help="scored universe CSV (with rs_benchmark_12m)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()

    swaps = layer4_swap_suggestions(args.portfolio, args.scored_csv)

    if args.json:
        print(json.dumps({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "portfolio_csv": args.portfolio,
            "scored_csv": args.scored_csv,
            "swap_suggestions": swaps,
        }, indent=2))
        return 0

    print("=" * 70)
    print(f"r1000 Layer 4 Swap Suggestions — {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)
    print(f"  portfolio: {args.portfolio}")
    print(f"  scored:    {args.scored_csv}")
    print()
    if swaps and "error" in swaps[0]:
        print(f"ERROR: {swaps[0]['error']}")
        return 2
    if not swaps:
        print("No swap suggestions (all holdings have RS >= 0 or held < 60 days,")
        print("or no candidate stronger than swap_strong_rs_threshold=30).")
        return 0
    for s in swaps:
        print(f"  SWAP {s['ticker']:<6} -> {s['swap_to']:<6}  pri={s['priority']}  {s['reason']}")
    print()
    print(f"Total: {len(swaps)} swap(s) suggested.")
    print("Note: Layer 4 caps at swap_max_per_cycle=2. Review weights manually.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
