"""Aggressive Early Entry Scanner — Phase B2.

Orchestrates:
  1. Theme taxonomy (r1000_themes) + phase classification (early/maturing/peaking/ending/dead)
  2. Technical signals (signals_technical) — 4 tiers
  3. Fundamental minimum quality gate (liquidity + not-dead-theme)
  4. Composite ranking: tech_score × theme_phase_multiplier - penalties
  5. Top-N output + Telegram alert

Signal flow:
    universe = theme members (or explicit ticker list)
    → per ticker: fetch bars → compute RS/mom → 4-tier technical eval
    → aggregate theme stats → classify phase
    → apply phase multiplier to tech score
    → apply liquidity gate (min dollar volume 20d)
    → rank, output top-N
    → alert if new signal or score change

Design principle: technical primary (80%), fundamental/theme as context (20%).
Answers user's question: chart-only early-rise detection IS viable for Aggressive track.

Usage:
    py -3 aggressive/scanner.py                  # default: scan all theme members
    py -3 aggressive/scanner.py --themes semi_memory,optical_communications
    py -3 aggressive/scanner.py --dry-run        # no Telegram alerts
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
from aggressive.entry_precision import (
    TradeCard,
    build_trade_card,
    format_trade_card_brief,
)
from aggressive.signals_technical import (
    TechnicalSignalResult,
    evaluate_ticker,
    pct_change,
    sma,
    slope_pct,
)
from r1000_themes import (
    classify_theme_phase,
    compute_theme_aggregates,
    load_themes,
    map_tickers_to_themes,
)


# --- Theme phase multipliers ------------------------------------------------
# Applied to technical composite score as (score * multiplier).
# These implement the user's insight: "theme lifecycle matters; late-phase
# winners have worse reward/risk than early-phase leaders."
THEME_PHASE_MULTIPLIER = {
    "early":    1.25,   # 25% bonus — earliest entry, highest reward/risk
    "maturing": 1.15,   # 15% bonus — sweet spot (trend confirmed, not saturated)
    "peaking":  0.70,   # 30% penalty — late entry, high drawdown risk
    "ending":   0.40,   # 60% penalty — exit zone, should be selling
    "dead":     0.20,   # 80% penalty — disqualified in most cases
    "unknown":  1.00,   # neutral
}

THEME_PHASE_DISQUALIFY = {"dead", "ending"}    # zero-out final score


# --- Candidate dataclass ----------------------------------------------------

@dataclass
class ScannerCandidate:
    ticker: str
    tech_score: float                # max tier score (0-100)
    best_tier: int
    theme_primary: Optional[str]
    theme_phase: str
    phase_multiplier: float
    liquidity_ok: bool
    disqualified: bool
    final_score: float
    signals_fired: list[str] = field(default_factory=list)
    rationale: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    trade_card: Optional[TradeCard] = None   # B3: complete entry plan


# --- Per-ticker stats (for theme aggregation) -------------------------------

def _compute_ticker_stats(df: pd.DataFrame, spy_df: pd.DataFrame) -> dict[str, float]:
    """Compute momentum + RS stats needed by compute_theme_aggregates."""
    out: dict[str, float] = {}
    if df.empty or len(df) < 25:
        return out
    c = df["close"]; v = df["volume"]

    # Absolute momentum
    out["mom_1m"] = pct_change(c, 21)
    if len(df) >= 64:
        out["mom_3m"] = pct_change(c, 63)
    if len(df) >= 127:
        out["mom_6m"] = pct_change(c, 126)
    if len(df) >= 253:
        out["mom_12m"] = pct_change(c, 252)

    # Relative strength vs SPY
    if not spy_df.empty:
        aligned = pd.concat(
            [c.rename("tkr"), spy_df["close"].rename("spy")],
            axis=1, join="inner",
        ).dropna()
        if len(aligned) >= 64:
            rs = aligned["tkr"] / aligned["spy"]
            for n, label in [(63, "rs_benchmark_3m"), (126, "rs_benchmark_6m"), (252, "rs_benchmark_12m")]:
                if len(rs) >= n + 1:
                    out[label] = (rs.iloc[-1] / rs.iloc[-1 - n] - 1.0) * 100.0

    # Breadth helper: is close > SMA200?
    if len(df) >= 200:
        ma200 = sma(c, 200)
        out["price_above_ma200"] = 1.0 if float(c.iloc[-1]) > float(ma200.iloc[-1]) else 0.0

    # Liquidity: 20d avg dollar volume
    if len(df) >= 20:
        dollar_vol = (c * v).tail(20).mean()
        out["dollar_volume_20d"] = float(dollar_vol)

    return out


# --- Core scan -------------------------------------------------------------

def scan(
    tickers: Optional[list[str]] = None,
    theme_filter: Optional[list[str]] = None,
    min_tech_score: float = 50.0,
    top_n: int = 20,
    verbose: bool = True,
) -> list[ScannerCandidate]:
    """Run full early-entry scan.

    Args:
        tickers: explicit list; if None, use all theme members
        theme_filter: restrict to these themes only
        min_tech_score: filter out candidates below this tech score
        top_n: return top N by final_score
        verbose: print progress

    Returns list of ScannerCandidate, sorted by final_score descending.
    """
    cfg = load_agg_config()
    themes = load_themes()
    if not themes:
        raise RuntimeError("themes.yaml failed to load")

    ticker_to_themes = map_tickers_to_themes(themes)

    # Build universe
    if tickers is None:
        if theme_filter:
            selected = set()
            for tn in theme_filter:
                if tn in themes:
                    selected |= themes[tn]["tickers"]
            tickers = sorted(selected)
        else:
            tickers = sorted(ticker_to_themes.keys())

    if verbose:
        print(f"[scan] universe: {len(tickers)} tickers across {len(themes)} themes")

    # Fetch SPY benchmark once
    spy_df = fetch_spy_benchmark(days=260)
    if spy_df.empty:
        raise RuntimeError("Could not fetch SPY benchmark")

    # Per-ticker: fetch, compute stats, run technical signals, build trade card
    rows_for_theme_agg: list[dict] = []
    tech_results: dict[str, TechnicalSignalResult] = {}
    bar_cache: dict[str, pd.DataFrame] = {}    # keep bars for B3 trade card

    for i, t in enumerate(tickers, 1):
        if verbose and i % 10 == 0:
            print(f"[scan] {i}/{len(tickers)}...")
        df = fetch_daily_bars(t, days=260)
        if df.empty or len(df) < 30:
            continue
        stats = _compute_ticker_stats(df, spy_df)
        stats["ticker"] = t
        rows_for_theme_agg.append(stats)
        tech_results[t] = evaluate_ticker(t, df, spy_df)
        bar_cache[t] = df

    if not tech_results:
        raise RuntimeError("No tickers returned valid data")

    ticker_df = pd.DataFrame(rows_for_theme_agg)

    # Theme-level aggregates & phase classification
    theme_agg = compute_theme_aggregates(ticker_df, themes)
    theme_phase_map: dict[str, str] = {}
    if not theme_agg.empty:
        for _, r in theme_agg.iterrows():
            theme_phase_map[r["theme_name"]] = str(r.get("theme_phase", "unknown"))

    if verbose and theme_phase_map:
        n_phases = pd.Series(list(theme_phase_map.values())).value_counts()
        print(f"[scan] theme phases: {dict(n_phases)}")

    # Build candidates
    candidates: list[ScannerCandidate] = []
    for t, res in tech_results.items():
        themes_of_t = ticker_to_themes.get(t, [])
        # Primary theme: first one with a non-dead phase, else first
        primary_theme = None
        primary_phase = "unknown"
        if themes_of_t:
            # Choose best non-dead phase
            phase_rank = {"early": 5, "maturing": 4, "peaking": 3,
                          "unknown": 2, "ending": 1, "dead": 0}
            best = max(
                themes_of_t,
                key=lambda tn: phase_rank.get(theme_phase_map.get(tn, "unknown"), 2),
            )
            primary_theme = best
            primary_phase = theme_phase_map.get(best, "unknown")

        mult = THEME_PHASE_MULTIPLIER.get(primary_phase, 1.0)

        # Liquidity gate
        stats = next((r for r in rows_for_theme_agg if r.get("ticker") == t), {})
        dollar_vol = stats.get("dollar_volume_20d", 0.0)
        liquidity_ok = dollar_vol >= cfg.min_dollar_volume_20d

        # Signals fired list
        fired_sigs = [f"T{tier.tier}:{tier.name}" for tier in res.tiers if tier.fired]

        # Disqualify conditions
        disqualified = primary_phase in THEME_PHASE_DISQUALIFY or not liquidity_ok

        # Final score
        final_score = res.composite_score * mult
        if disqualified:
            final_score *= 0.1  # near-zero but still visible for diagnostic

        # Rationale
        rationale = (
            f"tech={res.composite_score:.0f}[T{res.best_tier}] x "
            f"phase_mult={mult:.2f}({primary_phase}) = {final_score:.0f}"
        )
        if not liquidity_ok:
            rationale += f" | LOW-LIQUIDITY ${dollar_vol/1e6:.1f}M/day"
        if disqualified:
            rationale += " | DISQUALIFIED"

        # B3: build trade card from bars
        df_t = bar_cache.get(t)
        trade_card: Optional[TradeCard] = None
        if df_t is not None and not df_t.empty:
            best_tier_obj = max(res.tiers, key=lambda x: x.score)
            trade_card = build_trade_card(
                t, df_t, res.best_tier, best_tier_obj.name
            )

        cand = ScannerCandidate(
            ticker=t,
            tech_score=res.composite_score,
            best_tier=res.best_tier,
            theme_primary=primary_theme,
            theme_phase=primary_phase,
            phase_multiplier=mult,
            liquidity_ok=liquidity_ok,
            disqualified=disqualified,
            final_score=final_score,
            signals_fired=fired_sigs,
            rationale=rationale,
            metrics={
                "dollar_volume_20d_musd": dollar_vol / 1e6,
                "mom_1m": stats.get("mom_1m", float("nan")),
                "mom_3m": stats.get("mom_3m", float("nan")),
                "rs_benchmark_3m": stats.get("rs_benchmark_3m", float("nan")),
            },
            trade_card=trade_card,
        )
        candidates.append(cand)

    # Filter + sort
    candidates = [c for c in candidates if c.tech_score >= min_tech_score]
    candidates.sort(key=lambda c: c.final_score, reverse=True)
    return candidates[:top_n]


# --- Output helpers ---------------------------------------------------------

def print_report(candidates: list[ScannerCandidate]) -> None:
    print()
    print("=" * 82)
    print(f"EARLY-ENTRY SIGNALS - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 82)
    if not candidates:
        print("no qualifying candidates")
        return
    header = (
        f"{'Rank':>4}  {'Ticker':<6} {'Final':>6} {'Tech':>5} {'Tier':>4} "
        f"{'Theme':<22} {'Phase':<10} {'Mult':>5}  Fired"
    )
    print(header)
    print("-" * 82)
    for i, c in enumerate(candidates, 1):
        mark = " " if not c.disqualified else "X"
        theme = (c.theme_primary or "-")[:22]
        fired = ",".join(s.split(":")[0] for s in c.signals_fired) or "-"
        print(
            f"{mark}{i:>3}  {c.ticker:<6} {c.final_score:>6.1f} {c.tech_score:>5.1f} "
            f"T{c.best_tier:<3} {theme:<22} {c.theme_phase:<10} "
            f"{c.phase_multiplier:>5.2f}  {fired}"
        )
    print()
    print("Top 5 trade cards:")
    for c in candidates[:5]:
        if c.disqualified:
            continue
        mom_1m = c.metrics.get("mom_1m", float("nan"))
        rs_3m = c.metrics.get("rs_benchmark_3m", float("nan"))
        dv = c.metrics.get("dollar_volume_20d_musd", float("nan"))
        print(f"  {c.ticker}: mom_1m={mom_1m:+.1f}%  rs_3m={rs_3m:+.1f}%  "
              f"$vol=${dv:.0f}M/day")
        if c.trade_card:
            print(f"    {format_trade_card_brief(c.trade_card)}")


def save_report(candidates: list[ScannerCandidate]) -> Path:
    cfg = load_agg_config()
    out_dir = cfg.state_dir / "scanner"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"candidates_{ts}.json"
    payload = {
        "timestamp": datetime.now().isoformat(),
        "candidates": [asdict(c) for c in candidates],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # Also save a "latest" pointer
    latest = out_dir / "latest.json"
    latest.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def send_telegram_digest(candidates: list[ScannerCandidate], top: int = 5) -> bool:
    from aggressive.telegram_alert import send_alert
    if not candidates:
        return send_alert("Early-Entry Scan: no qualifying signals", urgency="info",
                          disable_notification=True)
    top_list = [c for c in candidates if not c.disqualified][:top]
    if not top_list:
        return send_alert("Early-Entry Scan: all candidates disqualified", urgency="info")
    lines = ["EARLY-ENTRY SIGNALS\n"]
    for i, c in enumerate(top_list, 1):
        fired = ",".join(s.split(":")[0] for s in c.signals_fired) or "-"
        lines.append(
            f"{i}. {c.ticker} (T{c.best_tier}) score={c.final_score:.0f} "
            f"| {c.theme_primary}/{c.theme_phase} | {fired}"
        )
    return send_alert("\n".join(lines), urgency="info")


# --- CLI -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--themes", type=str, default="",
                   help="comma-separated theme filter (e.g. semi_memory,optical_communications)")
    p.add_argument("--tickers", type=str, default="",
                   help="comma-separated explicit ticker list (overrides themes)")
    p.add_argument("--min-score", type=float, default=50.0,
                   help="minimum tech composite score")
    p.add_argument("--top", type=int, default=20,
                   help="top N to output")
    p.add_argument("--dry-run", action="store_true", help="skip Telegram alert")
    p.add_argument("--no-save", action="store_true", help="skip JSON save")
    args = p.parse_args()

    theme_filter = [t.strip() for t in args.themes.split(",") if t.strip()] or None
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or None

    candidates = scan(
        tickers=tickers,
        theme_filter=theme_filter,
        min_tech_score=args.min_score,
        top_n=args.top,
    )
    print_report(candidates)

    if not args.no_save:
        path = save_report(candidates)
        print(f"\nsaved to: {path}")

    if not args.dry_run:
        ok = send_telegram_digest(candidates)
        print(f"telegram digest: {'sent' if ok else 'failed/disabled'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
