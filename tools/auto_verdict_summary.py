#!/usr/bin/env python3
"""auto_verdict_summary — generate Telegram-ready verdict text from outputs.

Reads:
  outputs/backtest_metrics.json
  outputs/concentrated_backtest_metrics.json
  outputs/portfolio_latest.csv
  outputs/concentrated_portfolio_latest.csv
  outputs/scored_latest.csv

Compares to CURRENT_BASELINE in run_local.py.
Emits multi-line text suitable for Telegram sendMessage (uses \\n separators).

Usage:
    py -3 tools/auto_verdict_summary.py
    py -3 tools/auto_verdict_summary.py --base outputs/

Output goes to stdout; pipe into Telegram curl.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def safe_load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def safe_load_csv(path: Path):
    if not path.exists():
        return None
    try:
        import pandas as pd
        return pd.read_csv(path)
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="outputs", help="output directory")
    p.add_argument("--mode", default="r1000+adr", help="universe_mode label")
    args = p.parse_args()

    out = Path(args.base)

    # 1. Load CURRENT_BASELINE
    sys.path.insert(0, str(ROOT))
    try:
        from run_local import CURRENT_BASELINE as bl
    except Exception:
        bl = {"name": "?", "cagr": 0, "sharpe": 0, "max_dd": 0, "ir": 0}

    # 2. Load main backtest metrics
    main_metrics = safe_load_json(out / "backtest_metrics.json")
    conc_metrics = safe_load_json(out / "concentrated_backtest_metrics.json")
    portfolio = safe_load_csv(out / "portfolio_latest.csv")
    conc_port = safe_load_csv(out / "concentrated_portfolio_latest.csv")

    lines: list[str] = []
    lines.append(f"📊 r1000 [{args.mode}]")
    lines.append("")

    # 3. Verdict via compare_adr_backtest logic
    if main_metrics:
        try:
            from tools.compare_adr_backtest import verdict, SHIP_GATE
            v, deltas = verdict(bl, main_metrics)
            emoji = {"SHIP": "✅", "PARTIAL": "🟡", "REGRESS": "❌"}.get(v, "❓")
            lines.append(f"{emoji} verdict: {v}")
            lines.append("")
            lines.append("Main diversified:")
            lines.append(f"  CAGR    {deltas['baseline_cagr']*100:+5.2f}% → {deltas['variant_cagr']*100:+5.2f}%   Δ{deltas['delta_cagr_pp']:+.2f}pp")
            lines.append(f"  Sharpe  {deltas['baseline_sharpe']:5.3f} → {deltas['variant_sharpe']:5.3f}   Δ{deltas['delta_sharpe']:+.3f}")
            lines.append(f"  MaxDD   {deltas['baseline_max_dd']*100:+5.2f}% → {deltas['variant_max_dd']*100:+5.2f}%   Δ{deltas['delta_max_dd_pp']:+.2f}pp")
            lines.append("")
            lines.append(f"Ship gate: ΔCAGR≥{SHIP_GATE['delta_cagr_min_pp']}pp ΔSharpe≥{SHIP_GATE['delta_sharpe_min']} ΔMaxDD≥{SHIP_GATE['delta_max_dd_min_pp']}pp")
        except Exception as e:
            lines.append(f"verdict comparison failed: {e}")
    else:
        lines.append("⚠️ no backtest_metrics.json — pipeline likely failed")

    # 4. Concentrated metrics
    if conc_metrics and "strategy_cagr" in conc_metrics:
        lines.append("")
        lines.append("Concentrated 3-name:")
        lines.append(f"  CAGR  {conc_metrics.get('strategy_cagr', 0)*100:+5.2f}%  Sharpe  {conc_metrics.get('sharpe', 0):.3f}  MaxDD  {conc_metrics.get('max_dd', 0)*100:+.2f}%")

    # 5. Sleeve composition
    if portfolio is not None and not portfolio.empty:
        lines.append("")
        lines.append(f"Portfolio: {len(portfolio)} positions")
        if "portfolio_sleeve_label" in portfolio.columns:
            sleeves = portfolio["portfolio_sleeve_label"].value_counts()
            sleeve_str = " / ".join(f"{k}:{v}" for k, v in sleeves.items())
            lines.append(f"  Sleeves: {sleeve_str}")
        # Top 5 by weight
        if "ticker" in portfolio.columns and "weight" in portfolio.columns:
            top5 = portfolio.nlargest(5, "weight")[["ticker", "weight"]]
            top_str = ", ".join(f"{r['ticker']} {r['weight']*100:.1f}%" for _, r in top5.iterrows())
            lines.append(f"  Top 5: {top_str}")

    # 6. Concentrated portfolio
    if conc_port is not None and not conc_port.empty:
        if "ticker" in conc_port.columns and "weight" in conc_port.columns:
            cstr = ", ".join(f"{r['ticker']} {r['weight']*100:.0f}%" for _, r in conc_port.head(3).iterrows())
            lines.append(f"  Concentrated: {cstr}")

    # 7. Action recommendation
    lines.append("")
    if main_metrics:
        try:
            from tools.compare_adr_backtest import verdict as _v
            v, _ = _v(bl, main_metrics)
            if v == "SHIP":
                lines.append("→ Action: rotate CURRENT_BASELINE (run_local.py + CLAUDE.md + CHANGELOG)")
            elif v == "PARTIAL":
                lines.append("→ Action: investigate sleeve/regime; tune; retest")
            elif v == "REGRESS":
                lines.append("→ Action: isolate ADR vs Phase 14 fault (3rd workflow with phase14_off)")
        except Exception:
            pass

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
