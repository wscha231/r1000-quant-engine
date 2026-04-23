"""Aggressive Daily Review - Phase B3+B4 orchestrator.

Combines entry scanner + exit management into one daily decision pass:
  1. Load current positions (from Alpaca or aggressive/state/positions.json)
  2. For each position: run exit_management.evaluate_position()
     -> HOLD / WATCH / TRIM_33 / TRIM_50 / SELL_ALL decisions
  3. Run scanner.scan() on theme universe -> entry candidates with trade cards
  4. Rank candidates by final_score, filter READY status
  5. Generate daily report + Telegram digest

Usage:
    py -3 aggressive/daily_review.py --dry-run      # no Telegram
    py -3 aggressive/daily_review.py                # full pass with alerts
    py -3 aggressive/daily_review.py --positions-json custom_state.json

Design:
    - READ-ONLY: does NOT place orders (Phase B5 will add that)
    - Outputs: state/daily_review/{YYYY-MM-DD}_decisions.json
    - Telegram: critical decisions (SELL_ALL, SELL_HARD) get separate urgent alert
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from aggressive.agg_config import (
    get_alpaca_credentials,
    load_agg_config,
)
from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
from aggressive.entry_precision import format_trade_card_brief
from aggressive.exit_management import (
    ExitDecision,
    PositionSnapshot,
    evaluate_position,
    format_decision_brief,
)
from aggressive.scanner import (
    ScannerCandidate,
    scan,
    send_telegram_digest,
)
from aggressive.telegram_alert import send_alert
from r1000_themes import (
    load_themes,
    map_tickers_to_themes,
)


# --- Position loading ------------------------------------------------------

def load_positions_from_alpaca() -> list[PositionSnapshot]:
    """Fetch current positions from Alpaca paper account.

    Theme phase is inferred from themes.yaml membership.
    """
    try:
        from alpaca.trading.client import TradingClient
    except ImportError:
        print("alpaca-py not installed; returning empty positions")
        return []

    try:
        key, secret = get_alpaca_credentials()
    except RuntimeError:
        print("Alpaca credentials not set; returning empty positions")
        return []

    client = TradingClient(key, secret, paper=True)
    try:
        raw_positions = client.get_all_positions()
    except Exception as exc:
        print(f"Alpaca positions fetch failed: {exc}")
        return []

    themes = load_themes()
    ticker_to_themes = map_tickers_to_themes(themes)

    positions: list[PositionSnapshot] = []
    for p in raw_positions:
        ticker = p.symbol
        themes_of_t = ticker_to_themes.get(ticker, [])
        # Naive phase guess: "unknown" for now, overridden later by scanner
        positions.append(PositionSnapshot(
            ticker=ticker,
            entry_price=float(p.avg_entry_price),
            entry_date=datetime.now().strftime("%Y-%m-%d"),
            qty=float(p.qty),
            theme_phase="unknown",
        ))
    return positions


def load_positions_from_json(path: Path) -> list[PositionSnapshot]:
    """Load positions from state JSON file.

    Format:
    {
      "positions": [
        {"ticker": "AMD", "entry_price": 150.0, "entry_date": "2026-01-15",
         "qty": 100, "theme_phase": "peaking", "peak_price": 310.0,
         "trim_level_hit": 0},
        ...
      ]
    }
    """
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to parse positions JSON: {exc}")
        return []
    out: list[PositionSnapshot] = []
    for p in payload.get("positions", []):
        out.append(PositionSnapshot(
            ticker=p["ticker"],
            entry_price=float(p["entry_price"]),
            entry_date=p.get("entry_date", datetime.now().strftime("%Y-%m-%d")),
            qty=float(p.get("qty", 0.0)),
            theme_phase=p.get("theme_phase", "unknown"),
            peak_price=p.get("peak_price"),
            trim_level_hit=int(p.get("trim_level_hit", 0)),
        ))
    return out


# --- Theme phase annotation ------------------------------------------------

def _annotate_positions_with_phases(
    positions: list[PositionSnapshot],
    candidates: list[ScannerCandidate],
) -> None:
    """Fill in theme_phase on positions using scanner output."""
    phase_by_ticker = {c.ticker: c.theme_phase for c in candidates}
    for pos in positions:
        if pos.theme_phase == "unknown" and pos.ticker in phase_by_ticker:
            pos.theme_phase = phase_by_ticker[pos.ticker]


# --- Main review -----------------------------------------------------------

def run_daily_review(
    positions_source: str = "alpaca",
    positions_json_path: Optional[Path] = None,
    scan_universe_source: str = "r1000",   # dynamic R1000 (no hardcoded)
    scan_min_score: float = 60.0,
    scan_top_n: int = 15,
    run_theme_discovery: bool = False,     # Phase 18A: weekly cron
    dry_run: bool = False,
    verbose: bool = True,
) -> dict:
    """Execute full daily review pass.

    Returns dict with positions, exit_decisions, entry_candidates.
    """
    cfg = load_agg_config()

    # 1. Load positions
    if positions_source == "json" and positions_json_path:
        positions = load_positions_from_json(positions_json_path)
    else:
        positions = load_positions_from_alpaca()

    if verbose:
        print(f"[review] positions loaded: {len(positions)}")

    # 2. Run scanner (needed for theme phases + entry candidates)
    if verbose:
        print("[review] running scanner...")
    candidates = scan(
        tickers=None,
        theme_filter=None,
        universe_source=scan_universe_source,
        min_tech_score=scan_min_score,
        top_n=scan_top_n,
        verbose=False,
    )

    # 3. Annotate positions with theme phase
    _annotate_positions_with_phases(positions, candidates)

    # 4. Fetch data for each position & evaluate exits
    if verbose:
        print("[review] evaluating exits...")
    spy_df = fetch_spy_benchmark(days=260)
    exit_decisions: list[ExitDecision] = []
    for pos in positions:
        df = fetch_daily_bars(pos.ticker, days=260)
        if df.empty:
            continue
        dec = evaluate_position(pos, df, spy_df)
        exit_decisions.append(dec)

    # 5. Filter entry candidates to READY status only (no EARLY/EXTENDED/FAILED)
    ready_candidates = [
        c for c in candidates
        if c.trade_card and c.trade_card.entry_status == "READY" and not c.disqualified
    ]

    # 5b. Phase 18A - Theme auto-discovery (only when requested, slow operation)
    theme_proposals: list[dict] = []
    if run_theme_discovery:
        try:
            from aggressive.theme_discovery import discover_themes
            if verbose:
                print("[review] running theme discovery (Phase 18A)...")
            props = discover_themes(universe_source=scan_universe_source,
                                    verbose=False)
            theme_proposals = [asdict(p) for p in props]
            if verbose:
                print(f"[review] theme discovery: {len(props)} emerging proposals")
        except Exception as exc:
            print(f"[review] theme discovery failed: {exc}")

    # 6. Output
    result = {
        "timestamp": datetime.now().isoformat(),
        "positions_count": len(positions),
        "exit_decisions": [asdict(d) for d in exit_decisions],
        "entry_candidates_ready": [
            _candidate_to_dict(c) for c in ready_candidates
        ],
        "all_candidates": [
            _candidate_to_dict(c) for c in candidates
        ],
        "theme_proposals": theme_proposals,
    }

    # 7. Save
    out_dir = cfg.state_dir / "daily_review"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"review_{ts}.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    latest = out_dir / "latest.json"
    latest.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    if verbose:
        print(f"[review] saved to {path}")

    # 8. Print summary
    _print_summary(positions, exit_decisions, ready_candidates, candidates)

    # 9. Telegram digest (if not dry-run)
    if not dry_run:
        _send_telegram_digest(exit_decisions, ready_candidates)

    return result


def _candidate_to_dict(c: ScannerCandidate) -> dict:
    d = asdict(c)
    if c.trade_card:
        d["trade_card"] = asdict(c.trade_card)
    return d


def _print_summary(
    positions: list[PositionSnapshot],
    exit_decisions: list[ExitDecision],
    ready_candidates: list[ScannerCandidate],
    all_candidates: list[ScannerCandidate],
) -> None:
    print()
    print("=" * 82)
    print(f"DAILY REVIEW - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 82)

    # Positions
    print(f"\n[POSITIONS] {len(positions)} held")
    if exit_decisions:
        action_count = {}
        for d in exit_decisions:
            action_count[d.action] = action_count.get(d.action, 0) + 1
        print(f"  action breakdown: {action_count}")
        print()
        for d in exit_decisions:
            print(f"  {format_decision_brief(d)}")

    # Urgent alerts
    urgent = [d for d in exit_decisions if d.urgency == "critical"]
    if urgent:
        print(f"\n[!] URGENT DECISIONS: {len(urgent)}")
        for d in urgent:
            print(f"  {d.ticker} -> {d.action}")
            for sig in d.signals_fired:
                print(f"    - {sig}")

    # Entry candidates
    print(f"\n[ENTRY CANDIDATES] READY: {len(ready_candidates)} / "
          f"total scanned: {len(all_candidates)}")
    for c in ready_candidates[:10]:
        if c.trade_card:
            print(f"  T{c.best_tier} {c.theme_phase:<9}  "
                  f"{format_trade_card_brief(c.trade_card)}  "
                  f"[final={c.final_score:.0f}]")


def _send_telegram_digest(
    exit_decisions: list[ExitDecision],
    ready_candidates: list[ScannerCandidate],
) -> None:
    lines = [f"DAILY REVIEW {datetime.now().strftime('%Y-%m-%d %H:%M')}"]

    # Urgent actions first
    urgent = [d for d in exit_decisions if d.urgency == "critical"]
    if urgent:
        lines.append(f"\n*** {len(urgent)} URGENT ***")
        for d in urgent:
            lines.append(
                f"{d.ticker}: {d.action} (PnL {d.pnl_pct:+.1f}%)"
            )

    warnings_ = [d for d in exit_decisions if d.urgency == "warning"]
    if warnings_:
        lines.append(f"\n{len(warnings_)} warnings:")
        for d in warnings_[:5]:
            lines.append(f"{d.ticker}: {d.action} (PnL {d.pnl_pct:+.1f}%)")

    # Top entries
    if ready_candidates:
        lines.append(f"\nTop READY entries:")
        for c in ready_candidates[:5]:
            if c.trade_card:
                lines.append(
                    f"{c.ticker}: buy ${c.trade_card.buy_zone_low:.2f}-"
                    f"{c.trade_card.buy_zone_high:.2f} stop "
                    f"${c.trade_card.stop_loss:.2f} t2 ${c.trade_card.target_2:.2f} "
                    f"(R:R {c.trade_card.risk_reward_ratio:.1f})"
                )

    if len(lines) == 1:
        lines.append("No actionable decisions today.")

    urgency = "critical" if urgent else ("warning" if warnings_ else "info")
    send_alert("\n".join(lines), urgency=urgency)


# --- CLI -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--positions-source", choices=["alpaca", "json"],
                   default="alpaca", help="where to load positions from")
    p.add_argument("--positions-json", type=str, default="",
                   help="path to positions JSON (if source=json)")
    p.add_argument("--universe", choices=["r1000", "themes", "custom"],
                   default="r1000",
                   help="universe source (default r1000 live from iShares IWB)")
    p.add_argument("--min-score", type=float, default=60.0)
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--discover-themes", action="store_true",
                   help="also run Phase 18A theme discovery (slow, weekly)")
    p.add_argument("--dry-run", action="store_true", help="skip Telegram alerts")
    args = p.parse_args()

    json_path = Path(args.positions_json) if args.positions_json else None
    run_daily_review(
        positions_source=args.positions_source,
        positions_json_path=json_path,
        scan_universe_source=args.universe,
        scan_min_score=args.min_score,
        scan_top_n=args.top,
        run_theme_discovery=args.discover_themes,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
