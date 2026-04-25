"""r1000_layer4_swap — Layer 4 (RS-based position swap) bridge + executor.

Provides current-holdings + candidate-pool inputs for
r1000_risk_sensing.evaluate_layer4_swap. Layer 4 swaps weak holdings
(rs_12m_pct < 0, held >= 60 days) for strong alts (rs_12m_pct >= 30).

History:
  c8b5773 (Phase 2)  4-layer risk sensing system (logic)
  6540ec6 (Layer 3)  VIX/SPY-200MA bridge
  977fcd0 (Layer 3)  paper_executor pre-flight wiring
  78766da (Layer 4)  RS-based swap bridge (suggestions only)
  this    (Phase 3)  --execute flag, 30d throttle, Telegram alert

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
    py -3 r1000_layer4_swap.py                  # dry-run, default Drive paths
    py -3 r1000_layer4_swap.py --portfolio outputs_advisor/new_top12_proposed.csv
    py -3 r1000_layer4_swap.py --json           # machine-readable
    py -3 r1000_layer4_swap.py --execute        # ACTUALLY place Alpaca paper orders
    py -3 r1000_layer4_swap.py --execute --confirm  # bypass interactive prompt

Safety guards (--execute):
  - Throttle: same ticker can't be swapped more than once per 30 days
    (state in outputs/layer4_swap_history.json)
  - Cap: max 2 swaps per call (RiskConfig.swap_max_per_cycle, already enforced)
  - Refuse if Alpaca creds missing or portfolio < 5 positions
  - Telegram alert before + after execution (uses existing secrets)

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
# Throttle (state file: outputs/layer4_swap_history.json)
# ---------------------------------------------------------------------------

THROTTLE_DAYS = 30
HISTORY_PATH = ROOT / "outputs" / "layer4_swap_history.json"


def _load_swap_history() -> dict:
    """Returns {ticker: iso_date_of_last_swap} for both swap_from + swap_to."""
    if not HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_swap_history(hist: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(hist, indent=2, sort_keys=True), encoding="utf-8")


def _filter_throttled(swaps: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (allowed, throttled). Drops swaps whose swap_from OR swap_to was
    touched within THROTTLE_DAYS of the last swap involving that ticker.
    """
    hist = _load_swap_history()
    now = datetime.now()
    allowed: list[dict] = []
    throttled: list[dict] = []
    for s in swaps:
        if "error" in s:
            continue
        block = None
        for t in (s.get("ticker"), s.get("swap_to")):
            if not t:
                continue
            last = hist.get(str(t).upper())
            if not last:
                continue
            try:
                last_dt = datetime.fromisoformat(last)
            except Exception:
                continue
            if (now - last_dt).days < THROTTLE_DAYS:
                block = f"throttle: {t} swapped {(now - last_dt).days}d ago (<{THROTTLE_DAYS}d)"
                break
        if block:
            s = dict(s)
            s["throttle_reason"] = block
            throttled.append(s)
        else:
            allowed.append(s)
    return allowed, throttled


def _record_swap(swap: dict) -> None:
    hist = _load_swap_history()
    now_iso = datetime.now().isoformat(timespec="seconds")
    if swap.get("ticker"):
        hist[str(swap["ticker"]).upper()] = now_iso
    if swap.get("swap_to"):
        hist[str(swap["swap_to"]).upper()] = now_iso
    _save_swap_history(hist)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _telegram_send(msg: str) -> None:
    import os
    import urllib.parse
    import urllib.request
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    try:
        data = urllib.parse.urlencode({
            "chat_id": chat,
            "text": msg,
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
        )
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass  # best-effort


# ---------------------------------------------------------------------------
# Execute (Alpaca paper)
# ---------------------------------------------------------------------------

def execute_swaps(
    swaps: list[dict],
    portfolio_csv: str,
    paper: bool = True,
    confirm: bool = False,
) -> list[dict]:
    """Execute swap actions via Alpaca paper. Returns per-swap result dicts.

    For each swap:
      1. Lookup current shares of swap.ticker (sell target)
      2. Compute swap_to share count to keep notional ≈ same
      3. Sell swap.ticker (market order)
      4. Buy swap.swap_to (limit at small premium)
      5. Update history
    """
    results: list[dict] = []
    if not swaps:
        return results

    try:
        from aggressive.executor import (
            _existing_positions, _fetch_account_snapshot,
            _get_trading_client, _place_limit_buy, _place_market_sell,
        )
    except Exception as e:
        return [{"error": f"alpaca executor unavailable: {e}"}]

    try:
        client = _get_trading_client(paper=paper)
        snapshot = _fetch_account_snapshot(client)
        existing = _existing_positions(client)
    except Exception as e:
        return [{"error": f"alpaca init failed: {e}"}]

    if not existing or len(existing) < 5:
        return [{"error": f"refusing swap: portfolio too small ({len(existing)} positions, need >=5)"}]

    print(f"\n[execute] Alpaca paper account: cash=${snapshot.get('cash', 0):,.0f} "
          f"equity=${snapshot.get('equity', 0):,.0f} positions={len(existing)}")

    if not confirm:
        try:
            ans = input(f"\n⚠ About to execute {len(swaps)} swap(s). Proceed? (yes/no): ")
        except EOFError:
            ans = "no"
        if ans.lower().strip() not in ("yes", "y"):
            print("Cancelled.")
            return [{"cancelled": True}]

    for s in swaps:
        from_t = s["ticker"]
        to_t = s["swap_to"]
        held = existing.get(from_t, 0)
        if held <= 0:
            results.append({**s, "status": "skipped", "reason": "not held in alpaca"})
            print(f"  SKIP   {from_t}: not held in Alpaca account")
            continue
        # Sell swap_from
        try:
            sell_id, sell_status = _place_market_sell(client, from_t, held)
            print(f"  SOLD   {from_t}: {held} shares (status={sell_status} id={sell_id[:8]}...)")
        except Exception as e:
            results.append({**s, "status": "sell_failed", "error": str(e)[:100]})
            print(f"  FAIL   {from_t} sell: {e}")
            continue
        # Buy swap_to (proportional shares — fetch latest quote)
        try:
            from aggressive.data_alpaca import fetch_daily_bars
            bars = fetch_daily_bars(to_t, days=5)
            if bars is None or bars.empty:
                results.append({**s, "status": "buy_quote_failed",
                               "sell_id": sell_id, "error": "no bars for swap_to"})
                continue
            target_price = float(bars["close"].iloc[-1])
            limit_price = round(target_price * 1.005, 2)
            # Compute shares matching sold notional (use sell_id's filled qty later if available;
            # for now estimate via held × prior price ≈ same notional)
            from_bars = fetch_daily_bars(from_t, days=5)
            from_price = float(from_bars["close"].iloc[-1]) if (from_bars is not None and not from_bars.empty) else target_price
            notional = held * from_price
            target_shares = notional / target_price
            buy_id, buy_status = _place_limit_buy(client, to_t, target_shares, limit_price, fractional=True)
            print(f"  BOUGHT {to_t}: {target_shares:.2f} @ ${limit_price} (status={buy_status} id={buy_id[:8]}...)")
            results.append({
                **s, "status": "ok",
                "sell_id": sell_id, "sell_status": str(sell_status),
                "buy_id": buy_id, "buy_status": str(buy_status),
                "shares_sold": held, "shares_bought": round(target_shares, 4),
                "limit_price": limit_price, "notional": round(notional, 2),
            })
            _record_swap(s)
        except Exception as e:
            results.append({**s, "status": "buy_failed",
                           "sell_id": sell_id, "error": str(e)[:100]})
            print(f"  FAIL   {to_t} buy: {e}")

    return results


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
    p.add_argument("--execute", action="store_true",
                   help="ACTUALLY place Alpaca paper orders (default: dry-run)")
    p.add_argument("--confirm", action="store_true",
                   help="bypass interactive yes/no prompt (for CI)")
    p.add_argument("--no-throttle", action="store_true",
                   help="skip 30d throttle check (use for testing only)")
    args = p.parse_args()

    raw_swaps = layer4_swap_suggestions(args.portfolio, args.scored_csv)

    # Apply throttle
    if args.no_throttle:
        swaps = [s for s in raw_swaps if "error" not in s]
        throttled: list[dict] = []
    else:
        swaps, throttled = _filter_throttled(raw_swaps)

    if args.json:
        print(json.dumps({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "portfolio_csv": args.portfolio,
            "scored_csv": args.scored_csv,
            "swap_suggestions": swaps,
            "throttled": throttled,
            "execute": args.execute,
        }, indent=2))
        return 0

    print("=" * 70)
    print(f"r1000 Layer 4 Swap — {datetime.now():%Y-%m-%d %H:%M}  "
          f"{'EXECUTE' if args.execute else 'DRY-RUN'}")
    print("=" * 70)
    print(f"  portfolio: {args.portfolio}")
    print(f"  scored:    {args.scored_csv}")
    print()
    if raw_swaps and "error" in raw_swaps[0]:
        print(f"ERROR: {raw_swaps[0]['error']}")
        return 2
    if not raw_swaps:
        print("No swap suggestions (all holdings have RS >= 0 or held < 60 days,")
        print("or no candidate stronger than swap_strong_rs_threshold=30).")
        return 0
    for s in swaps:
        print(f"  SWAP {s['ticker']:<6} -> {s['swap_to']:<6}  pri={s['priority']}  {s['reason']}")
    if throttled:
        print(f"\n  Throttled ({len(throttled)}):")
        for s in throttled:
            print(f"    {s['ticker']:<6} -> {s['swap_to']:<6}  ({s['throttle_reason']})")
    print()
    print(f"Total proposed: {len(swaps)}, throttled: {len(throttled)}")

    if not args.execute:
        print("\n[DRY-RUN] no orders placed. Add --execute to apply (Alpaca paper).")
        return 0

    if not swaps:
        print("\nNo swaps to execute (all proposals throttled).")
        return 0

    # Pre-execute Telegram
    pre_msg = (
        "🔄 Layer 4 swap EXECUTE start: "
        + ", ".join(f"{s['ticker']}->{s['swap_to']}" for s in swaps)
    )
    _telegram_send(pre_msg)

    results = execute_swaps(swaps, args.portfolio, paper=True, confirm=args.confirm)

    print("\n[execute] results:")
    for r in results:
        if r.get("cancelled"):
            print("  user cancelled")
            return 1
        if "error" in r:
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  {r.get('ticker')}->{r.get('swap_to')} status={r.get('status')}")

    # Post-execute Telegram
    ok_n = sum(1 for r in results if r.get("status") == "ok")
    fail_n = sum(1 for r in results if r.get("status") not in ("ok", None) or "error" in r)
    post_msg = f"✅ Layer 4 swap done: {ok_n} ok, {fail_n} fail. See cloud_results."
    _telegram_send(post_msg)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
