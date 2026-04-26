"""r1000_paper_executor - Submit advisor portfolio to Alpaca paper.

User mandate (2026-04-25):
  Phase G — start Alpaca paper portfolio with advisor's picks.

Loads advisor output (v1/v3/concentrated/core) and converts to Alpaca
limit orders. Default: DRY-RUN (logs only). Use --execute to place real
paper orders.

  !! v4 is DEPRECATED (commit c13fa6a, 2026-04-25) — ML alpha was leakage.
     Validated alternatives:
       - v1            정석 ML quality, +9.45pp validated
       - v3            v1+v2 hybrid (recommended)
       - concentrated  3-name, +19.68pp validated
       - core          17-name 정석 v1 production portfolio

Usage:
    py -3 r1000_paper_executor.py --advisor v3                # dry-run v3 (recommended)
    py -3 r1000_paper_executor.py --advisor concentrated      # dry-run 3-name
    py -3 r1000_paper_executor.py --advisor core --execute    # live paper core
    py -3 r1000_paper_executor.py --advisor v3 --execute --confirm  # bypass prompt
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

from aggressive.executor import (
    _existing_positions,
    _fetch_account_snapshot,
    _get_trading_client,
    _place_limit_buy,
    _place_market_sell,
)
from aggressive.telegram_alert import send_alert


# ADVISOR_PATHS: primary path → list of fallback paths.
# Local Drive paths are first preference (where production runs write).
# Cloud / non-Drive fallbacks try repo-relative paths committed by
# full_rebuild_manual.yml (cloud_results/full_rebuild/latest_*).
ADVISOR_PATHS = {
    "v1": ["outputs_advisor/new_top12_proposed.csv"],
    "v3": ["outputs_advisor_v3/new_top12_proposed.csv"],
    "v4": ["outputs_advisor_v4/new_top12_proposed.csv"],
    "concentrated": [
        r"G:/내 드라이브/r1000_top30_institutional/outputs/concentrated_portfolio_latest.csv",
        # Fallback to latest cloud rebuild (committed by full_rebuild_manual.yml)
        "cloud_results/full_rebuild/latest_r1000+adr/concentrated_portfolio_latest.csv",
        "cloud_results/full_rebuild/latest_r1000/concentrated_portfolio_latest.csv",
        "outputs/concentrated_portfolio_latest.csv",
    ],
    "core": [
        r"G:/내 드라이브/r1000_top30_institutional/outputs/portfolio_latest.csv",
        # Fallback to latest cloud rebuild
        "cloud_results/full_rebuild/latest_r1000+adr/portfolio_latest.csv",
        "cloud_results/full_rebuild/latest_r1000/portfolio_latest.csv",
        "outputs/portfolio_latest.csv",
    ],
}


def load_advisor_picks(advisor: str) -> pd.DataFrame:
    """Load picks CSV for the given advisor mode.

    Iterates through fallback paths so cloud workflows can find recent rebuild
    outputs in cloud_results/ even when the user's Drive path is unavailable.
    """
    paths = ADVISOR_PATHS.get(advisor, [])
    if isinstance(paths, str):
        paths = [paths]
    for p_str in paths:
        p = Path(p_str)
        if p.exists():
            return pd.read_csv(p)
    raise FileNotFoundError(
        f"Advisor {advisor} output not found in any of: {paths}. "
        f"Run advisor (or full_rebuild) first."
    )
    return pd.read_csv(path)


def normalize_picks(df: pd.DataFrame, capital: float, advisor: str = "v3") -> list[dict]:
    """Normalize columns across v1/v3/v4/core/concentrated schemas. Returns list of dicts.

    Schemas:
      v1/v3/v4:     ticker, proposed_weight, entry_price (or current_price_live), action
      concentrated: ticker, weight, entry_price, reference_price (premade portfolio)
      core:         ticker, weight (production portfolio_latest.csv)
    """
    out = []
    for _, r in df.iterrows():
        ticker = str(r.get("ticker", "")).upper()
        if not ticker or ticker == "CASH":
            continue

        # Weight: 'proposed_weight' (advisor) or 'weight' (production)
        weight = float(r.get("proposed_weight") or r.get("weight") or 0.0)
        if weight <= 0:
            continue

        # Entry price: prefer 'entry_price', fallback 'reference_price', then 'current_price_live'
        entry = 0.0
        for col in ("entry_price", "reference_price", "current_price_live"):
            v = r.get(col)
            if v and pd.notna(v):
                try:
                    entry = float(v)
                    if entry > 0:
                        break
                except (TypeError, ValueError):
                    continue

        # If still no price, query Alpaca live
        if entry <= 0:
            try:
                from aggressive.data_alpaca import fetch_daily_bars
                bars = fetch_daily_bars(ticker, days=5)
                if not bars.empty:
                    entry = float(bars["close"].iloc[-1])
            except Exception:
                continue

        if entry <= 0:
            continue

        target_dollars = capital * weight
        target_shares = target_dollars / entry
        out.append({
            "ticker": ticker,
            "weight": weight,
            "target_dollars": target_dollars,
            "entry_price": entry,
            "target_shares": target_shares,
            "current_weight": float(r.get("current_weight") or 0.0),
            "action": str(r.get("action", "BUY") or "BUY"),
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--advisor",
                   choices=["v1", "v3", "v4", "concentrated", "core"],
                   default="concentrated",
                   help="concentrated = 84mo proven 33pp CAGR (3 names, RECOMMENDED). "
                        "v4 is DEPRECATED (was leakage-driven, see commit c13fa6a).")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--execute", action="store_true",
                   help="actually place orders (default: dry-run)")
    p.add_argument("--confirm", action="store_true",
                   help="skip confirmation prompt")
    p.add_argument("--limit-margin-pct", type=float, default=0.5,
                   help="limit price = entry × (1 + margin/100)")
    p.add_argument("--allow-deprecated-v4", action="store_true",
                   help="explicit ack required to use --advisor v4 (deprecated)")
    p.add_argument("--override-regime-halt", action="store_true",
                   help="proceed with --execute even when Layer 3 emits HALT_NEW "
                        "(VIX>=30 or other regime block). Use only with deliberate intent.")
    p.add_argument("--skip-regime-check", action="store_true",
                   help="skip Layer 3 regime pre-flight entirely (not recommended for --execute)")
    args = p.parse_args()

    if args.advisor == "v4" and not args.allow_deprecated_v4:
        print("=" * 70, file=sys.stderr)
        print("ERROR: --advisor v4 is DEPRECATED", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("v4's '+75.7% alpha' was forward-return leakage (commit c13fa6a).", file=sys.stderr)
        print("After fix, ML decile spread = 0.00% (random). Do NOT use for live paper.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Validated alternatives (84mo bootstrap):", file=sys.stderr)
        print("  --advisor concentrated   CAGR 33.17%, P(excess>0) = 97.9%  (RECOMMENDED)", file=sys.stderr)
        print("  --advisor core           CAGR 22.95%, P(excess>0) = 99.5%", file=sys.stderr)
        print("  --advisor v3             v1+v2 hybrid, top 12 names", file=sys.stderr)
        print("  --advisor v1             정석 quality, top 12 names", file=sys.stderr)
        print("", file=sys.stderr)
        print("Pass --allow-deprecated-v4 to override (research only, not for live).", file=sys.stderr)
        return 1

    print("=" * 70)
    if args.advisor == "v4":
        print(f"r1000 Paper Executor - advisor=v4 [DEPRECATED] "
              f"{'LIVE' if args.execute else 'DRY-RUN'}")
    else:
        print(f"r1000 Paper Executor - advisor={args.advisor} "
              f"{'LIVE' if args.execute else 'DRY-RUN'}")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 70)

    # Layer 3 regime pre-flight (VIX/SPY-200MA gate)
    if not args.skip_regime_check:
        try:
            from r1000_regime_data import current_regime, layer3_actions_for_snapshot
            snap = current_regime()
            actions = layer3_actions_for_snapshot(snap)
            print()
            print(f"[regime] {snap.regime_label:12s} "
                  f"VIX={snap.vix_level:.1f}({snap.vix_source}) "
                  f"SPY=${snap.spy_close:.2f} "
                  f"{'>' if snap.spy_above_200ma else '<'}200MA(${snap.spy_ma200:.2f})")
            halt_actions = [a for a in actions
                            if isinstance(a, dict) and a.get("type") == "HALT_NEW"]
            cash_actions = [a for a in actions
                            if isinstance(a, dict) and a.get("type") == "INCREASE_CASH"]
            for a in halt_actions:
                print(f"  HALT_NEW    pri={a['priority']}  {a['reason']}")
            for a in cash_actions:
                tgt = a.get("target_weight") or 0.0
                print(f"  CASH_BUFFER pri={a['priority']}  target={tgt:.0%}  {a['reason']}")
            if args.execute and halt_actions and not args.override_regime_halt:
                print()
                print("=" * 70, file=sys.stderr)
                print("REFUSING --execute: Layer 3 emitted HALT_NEW", file=sys.stderr)
                print("=" * 70, file=sys.stderr)
                for a in halt_actions:
                    print(f"  {a['reason']}", file=sys.stderr)
                print("", file=sys.stderr)
                print("Options:", file=sys.stderr)
                print("  - drop --execute (run dry-run; orders not placed)", file=sys.stderr)
                print("  - pass --override-regime-halt (deliberate, take responsibility)", file=sys.stderr)
                print("  - pass --skip-regime-check (no Layer 3 evaluation at all)", file=sys.stderr)
                return 1
            if args.execute and cash_actions:
                print(f"  [warn] cash buffer suggested but not auto-applied — review weights")
        except Exception as e:
            print(f"\n[regime] WARNING: pre-flight failed ({type(e).__name__}: {e})")
            if args.execute:
                print(f"[regime] proceeding with --execute despite regime-check failure", file=sys.stderr)

    # Load advisor output
    df = load_advisor_picks(args.advisor)
    picks = normalize_picks(df, args.capital, args.advisor)
    print(f"\n[load] {args.advisor} picks: {len(picks)} positions")
    if args.advisor == "concentrated":
        print(f"  [Backtest: 84mo CAGR 33.17% / Sharpe 1.18 / MaxDD -27.10% / IR 0.95]")
    elif args.advisor == "core":
        print(f"  [Backtest: 84mo CAGR 22.95% / Sharpe 1.17 / MaxDD -26.21% / IR 0.94]")

    # Alpaca client
    client = _get_trading_client(paper=True)
    snapshot = _fetch_account_snapshot(client)
    existing = _existing_positions(client)
    print(f"\n[account] cash=${snapshot.get('cash', 0):,.0f} "
          f"equity=${snapshot.get('equity', 0):,.0f} "
          f"existing positions: {len(existing)}")

    # Plan + display
    print()
    print(f"{'Ticker':<7} {'Weight':>7} {'Shares':>9} {'Entry':>9} "
          f"{'Limit':>9} {'$Notional':>11} {'Action':<8}")
    print("-" * 75)
    total_notional = 0.0
    plans = []
    for p_ in picks:
        # Limit price = entry × (1 + small margin)
        limit_price = round(p_["entry_price"] * (1 + args.limit_margin_pct / 100), 2)
        notional = p_["target_shares"] * limit_price
        total_notional += notional
        # Skip if already at target
        held = existing.get(p_["ticker"], 0)
        if held > 0 and abs(held - p_["target_shares"]) < 0.5:
            action = "ALREADY_HELD"
        else:
            action = p_["action"]
        plans.append({**p_, "limit_price": limit_price, "notional": notional, "action": action})
        print(f"{p_['ticker']:<7} {p_['weight']*100:>6.2f}% "
              f"{p_['target_shares']:>9.2f} ${p_['entry_price']:>8.2f} "
              f"${limit_price:>8.2f} ${notional:>10,.0f} {action:<8}")
    print("-" * 75)
    print(f"TOTAL Notional: ${total_notional:,.0f}")

    if not args.execute:
        print("\n[DRY-RUN] no orders placed. Use --execute to go live.")
        return 0

    # Confirmation prompt
    if not args.confirm:
        print()
        print(f"⚠  About to place {len(plans)} REAL paper orders totaling "
              f"${total_notional:,.0f}.")
        ans = input("Proceed? (yes/no): ")
        if ans.lower().strip() not in ("yes", "y"):
            print("Cancelled.")
            return 1

    # Execute
    print("\n[EXECUTE] Placing limit orders...")
    results = []
    for plan in plans:
        if plan["action"] in ("ALREADY_HELD",):
            results.append({**plan, "status": "skipped_held"})
            print(f"  {plan['ticker']:<6} SKIP (already held)")
            continue
        try:
            order_id, status = _place_limit_buy(
                client, plan["ticker"], plan["target_shares"],
                plan["limit_price"], fractional=True,
            )
            results.append({**plan, "status": str(status), "order_id": order_id})
            print(f"  {plan['ticker']:<6} OK  status={status} id={order_id[:8]}...")
        except Exception as e:
            err = str(e)[:80]
            results.append({**plan, "status": "error", "error": err})
            print(f"  {plan['ticker']:<6} FAIL  {err}")

    # Save audit trail
    audit_dir = Path("aggressive/state/paper_executions")
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"exec_{datetime.now():%Y%m%d_%H%M%S}.json"
    audit_path.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(),
        "advisor": args.advisor,
        "capital": args.capital,
        "results": results,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\n[audit] {audit_path}")

    # Telegram
    n_ok = sum(1 for r in results if "error" not in r.get("status", ""))
    msg = (f"PAPER EXEC ({args.advisor}) {datetime.now():%Y-%m-%d %H:%M}\n"
           f"placed: {n_ok}/{len(results)}\n"
           f"notional: ${total_notional:,.0f}")
    send_alert(msg, urgency="info")

    return 0


if __name__ == "__main__":
    sys.exit(main())
