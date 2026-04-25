"""r1000_paper_executor - Submit advisor portfolio to Alpaca paper.

User mandate (2026-04-25):
  Phase G — start Alpaca paper portfolio with advisor's picks.

Loads advisor v3 (hybrid) or v4 (ML-primary) output and converts to Alpaca
limit orders. Default: DRY-RUN (logs only). Use --execute to place real
paper orders.

Usage:
    py -3 r1000_paper_executor.py --advisor v3                # dry-run v3
    py -3 r1000_paper_executor.py --advisor v4 --execute      # live paper v4
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


ADVISOR_PATHS = {
    "v1": "outputs_advisor/new_top12_proposed.csv",
    "v3": "outputs_advisor_v3/new_top12_proposed.csv",
    "v4": "outputs_advisor_v4/new_top12_proposed.csv",
}


def load_advisor_picks(advisor: str) -> pd.DataFrame:
    path = Path(ADVISOR_PATHS.get(advisor, ""))
    if not path.exists():
        raise FileNotFoundError(f"Advisor {advisor} output not found at {path}. "
                                  "Run advisor first.")
    return pd.read_csv(path)


def normalize_picks(df: pd.DataFrame, capital: float) -> list[dict]:
    """Normalize columns across v1/v3/v4 schemas. Returns list of dicts."""
    out = []
    for _, r in df.iterrows():
        ticker = str(r["ticker"]).upper()
        # v3 uses 'proposed_weight'; v4 uses 'proposed_weight'; v1 uses 'proposed_weight'
        weight = float(r.get("proposed_weight") or 0.0)
        # entry price
        entry = (float(r.get("entry_price") or 0.0)
                  if r.get("entry_price") else 0.0)
        # If no entry_price, try latest from Alpaca quote (live)
        if entry <= 0:
            try:
                from aggressive.data_alpaca import fetch_daily_bars
                bars = fetch_daily_bars(ticker, days=5)
                if not bars.empty:
                    entry = float(bars["close"].iloc[-1])
            except Exception:
                continue
        target_dollars = capital * weight
        target_shares = target_dollars / entry if entry > 0 else 0
        out.append({
            "ticker": ticker,
            "weight": weight,
            "target_dollars": target_dollars,
            "entry_price": entry,
            "target_shares": target_shares,
            "current_weight": float(r.get("current_weight") or 0.0),
            "action": str(r.get("action", "BUY")),
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--advisor", choices=["v1", "v3", "v4"], default="v3")
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--execute", action="store_true",
                   help="actually place orders (default: dry-run)")
    p.add_argument("--confirm", action="store_true",
                   help="skip confirmation prompt")
    p.add_argument("--limit-margin-pct", type=float, default=0.5,
                   help="limit price = entry × (1 + margin/100)")
    args = p.parse_args()

    print("=" * 70)
    print(f"r1000 Paper Executor - advisor={args.advisor} "
          f"{'LIVE' if args.execute else 'DRY-RUN'}")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 70)

    # Load advisor output
    df = load_advisor_picks(args.advisor)
    picks = normalize_picks(df, args.capital)
    print(f"\n[load] {args.advisor} picks: {len(picks)} positions")

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
