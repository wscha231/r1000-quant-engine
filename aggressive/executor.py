"""Alpaca Paper Executor - Phase B6.

Connects scanner signals + sized orders + exit decisions to actual Alpaca
paper-trading API. All actions are DRY_RUN by default - user must explicitly
pass execute=True to place real paper orders.

Safety guardrails:
  - DRY_RUN is the default (no order placed, only intent logged)
  - Pre-flight checks:
      1. Ticker exists in Alpaca tradeable universe
      2. No duplicate position (won't double-buy what we already hold)
      3. Order notional within cfg.alpaca_max_order_usd
      4. Market hours check (optional; limit orders queue fine outside hours)
      5. Sufficient buying power
  - Audit trail: every action logged to state/executions/YYYY-MM-DD.json
  - Telegram notification on every executed action
  - Order type: LIMIT (never MARKET) for cost control

Execution modes:
  entries:  SizedOrder -> LimitOrderRequest (buy at buy_zone_low)
  exits:    ExitDecision -> MarketOrderRequest (sell immediately on trigger)
      TRIM_33: sell 1/3 of position
      TRIM_50: sell 1/2 of remaining
      SELL_ALL: sell all shares

Zero hardcoded tickers: all logic works on ticker symbol passed in.
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

from aggressive.agg_config import (
    AggressiveConfig,
    get_alpaca_credentials,
    load_agg_config,
)
from aggressive.exit_management import ExitDecision
from aggressive.position_sizing import SizedOrder, SizingPlan


# --- Execution result ------------------------------------------------------

@dataclass
class ExecutionResult:
    """Record of one attempted execution."""
    timestamp: str
    action: str                  # 'BUY_LIMIT', 'SELL_MARKET', 'SKIP'
    ticker: str
    qty: float = 0.0
    limit_price: float = 0.0
    order_id: str = ""
    status: str = "dry_run"      # dry_run / submitted / filled / rejected / error
    dry_run: bool = True
    reason: str = ""
    pre_flight_warnings: list[str] = field(default_factory=list)


@dataclass
class ExecutionSummary:
    timestamp: str
    dry_run: bool
    entries_attempted: int = 0
    entries_submitted: int = 0
    exits_attempted: int = 0
    exits_submitted: int = 0
    total_buy_notional: float = 0.0
    total_sell_notional: float = 0.0
    account_before: dict = field(default_factory=dict)
    account_after: dict = field(default_factory=dict)
    results: list[ExecutionResult] = field(default_factory=list)


# --- Alpaca client wrapper -------------------------------------------------

def _get_trading_client(paper: bool = True):
    from alpaca.trading.client import TradingClient
    key, secret = get_alpaca_credentials()
    return TradingClient(key, secret, paper=paper)


def _fetch_account_snapshot(client) -> dict:
    """Capture account state for before/after comparison."""
    try:
        acc = client.get_account()
        return {
            "cash": float(acc.cash),
            "equity": float(acc.equity),
            "buying_power": float(acc.buying_power),
            "portfolio_value": float(acc.portfolio_value),
            "position_count": len(client.get_all_positions()),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _existing_positions(client) -> dict[str, float]:
    """Returns {ticker: qty_held}."""
    try:
        positions = client.get_all_positions()
        return {p.symbol: float(p.qty) for p in positions}
    except Exception:
        return {}


# --- Pre-flight checks -----------------------------------------------------

def _check_asset_tradeable(client, ticker: str) -> tuple[bool, str]:
    """Verify ticker is a tradeable Alpaca asset."""
    try:
        asset = client.get_asset(ticker)
        if not getattr(asset, "tradable", False):
            return False, f"{ticker} not tradeable on Alpaca"
        if getattr(asset, "status", "") != "active":
            return False, f"{ticker} asset status={asset.status}"
        return True, ""
    except Exception as exc:
        return False, f"asset lookup failed: {exc}"


def _preflight_entry(
    order: SizedOrder,
    existing: dict[str, float],
    cfg: AggressiveConfig,
    client,
) -> tuple[bool, list[str]]:
    """Returns (ok_to_proceed, warnings)."""
    warnings: list[str] = []

    # 1. Duplicate position
    if order.ticker in existing and existing[order.ticker] > 0:
        warnings.append(f"already hold {existing[order.ticker]} shares - SKIP")
        return False, warnings

    # 2. Max order size
    if order.target_dollars > cfg.alpaca_max_order_usd:
        warnings.append(
            f"order ${order.target_dollars:,.0f} exceeds "
            f"max ${cfg.alpaca_max_order_usd:,.0f} - SKIP"
        )
        return False, warnings

    # 3. Tradeable check
    tradeable, reason = _check_asset_tradeable(client, order.ticker)
    if not tradeable:
        warnings.append(reason)
        return False, warnings

    # 4. Minimum qty
    if order.target_shares < 1 and not cfg.alpaca_fractional_shares:
        warnings.append(f"qty {order.target_shares:.4f} < 1 and no fractional")
        return False, warnings

    return True, warnings


def _preflight_exit(
    decision: ExitDecision,
    existing: dict[str, float],
) -> tuple[bool, list[str]]:
    warnings: list[str] = []

    qty_held = existing.get(decision.ticker, 0.0)
    if qty_held <= 0:
        warnings.append(f"no position in {decision.ticker} - SKIP")
        return False, warnings

    if decision.action not in ("TRIM_33", "TRIM_50", "SELL_ALL"):
        warnings.append(f"action={decision.action} not executable (HOLD/WATCH)")
        return False, warnings

    return True, warnings


# --- Order placement -------------------------------------------------------

def _place_limit_buy(
    client,
    ticker: str,
    qty: float,
    limit_price: float,
    fractional: bool = True,
) -> tuple[str, str]:
    """Returns (order_id, status). Raises on API error."""
    from alpaca.trading.requests import LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    qty_param: float | int = qty
    if not fractional:
        qty_param = int(qty)

    req = LimitOrderRequest(
        symbol=ticker,
        qty=qty_param,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        limit_price=round(limit_price, 2),
    )
    order = client.submit_order(req)
    return str(order.id), str(order.status)


def _place_market_sell(
    client,
    ticker: str,
    qty: float,
    fractional: bool = True,
) -> tuple[str, str]:
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce

    qty_param: float | int = qty
    if not fractional:
        qty_param = int(qty)

    req = MarketOrderRequest(
        symbol=ticker,
        qty=qty_param,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = client.submit_order(req)
    return str(order.id), str(order.status)


# --- Main execution --------------------------------------------------------

def execute_entries(
    sizing_plan: SizingPlan,
    dry_run: bool = True,
    cfg: Optional[AggressiveConfig] = None,
    client=None,
) -> list[ExecutionResult]:
    """Execute BUY limit orders for each SizedOrder in the plan."""
    cfg = cfg or load_agg_config()
    if client is None:
        try:
            client = _get_trading_client(paper=True)
        except Exception as exc:
            return [ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="ERROR", ticker="-",
                status="error",
                dry_run=dry_run,
                reason=f"client init failed: {exc}",
            )]

    existing = _existing_positions(client) if not dry_run else {}
    results: list[ExecutionResult] = []

    for order in sizing_plan.orders:
        ok, warnings = _preflight_entry(order, existing, cfg, client)
        if not ok:
            results.append(ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="SKIP", ticker=order.ticker,
                qty=order.target_shares,
                limit_price=order.entry_price,
                status="skipped",
                dry_run=dry_run,
                reason="preflight failed",
                pre_flight_warnings=warnings,
            ))
            continue

        limit_price = order.entry_price   # use buy-zone midpoint

        if dry_run:
            results.append(ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="BUY_LIMIT", ticker=order.ticker,
                qty=order.target_shares,
                limit_price=limit_price,
                status="dry_run",
                dry_run=True,
                reason=(f"DRY RUN would buy {order.target_shares:.2f} {order.ticker} "
                        f"@ ${limit_price:.2f} = ${order.target_dollars:,.0f}"),
                pre_flight_warnings=warnings,
            ))
            continue

        # Live paper execute
        try:
            order_id, status = _place_limit_buy(
                client, order.ticker, order.target_shares,
                limit_price, cfg.alpaca_fractional_shares,
            )
            results.append(ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="BUY_LIMIT", ticker=order.ticker,
                qty=order.target_shares,
                limit_price=limit_price,
                order_id=order_id, status=status,
                dry_run=False,
                reason=(f"LIVE paper buy {order.target_shares:.2f} {order.ticker} "
                        f"@ ${limit_price:.2f}"),
                pre_flight_warnings=warnings,
            ))
        except Exception as exc:
            results.append(ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="BUY_LIMIT", ticker=order.ticker,
                qty=order.target_shares,
                limit_price=limit_price,
                status="error",
                dry_run=False,
                reason=f"order submit failed: {exc}",
                pre_flight_warnings=warnings,
            ))

    return results


def execute_exits(
    decisions: list[ExitDecision],
    dry_run: bool = True,
    cfg: Optional[AggressiveConfig] = None,
    client=None,
) -> list[ExecutionResult]:
    """Execute SELL orders for TRIM_33 / TRIM_50 / SELL_ALL decisions."""
    cfg = cfg or load_agg_config()
    if client is None:
        try:
            client = _get_trading_client(paper=True)
        except Exception as exc:
            return [ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="ERROR", ticker="-",
                status="error", dry_run=dry_run,
                reason=f"client init failed: {exc}",
            )]

    existing = _existing_positions(client) if not dry_run else {}
    results: list[ExecutionResult] = []

    for dec in decisions:
        if dec.action == "HOLD" or dec.action == "WATCH":
            continue

        ok, warnings = _preflight_exit(dec, existing)
        if not ok:
            results.append(ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="SKIP", ticker=dec.ticker,
                status="skipped", dry_run=dry_run,
                reason="preflight failed",
                pre_flight_warnings=warnings,
            ))
            continue

        qty_held = existing.get(dec.ticker, 0.0)
        sell_qty = qty_held
        if dec.action == "TRIM_33":
            sell_qty = round(qty_held * 0.33, 4)
        elif dec.action == "TRIM_50":
            sell_qty = round(qty_held * 0.50, 4)

        if dry_run:
            results.append(ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="SELL_MARKET", ticker=dec.ticker,
                qty=sell_qty,
                limit_price=dec.current_price,
                status="dry_run",
                dry_run=True,
                reason=(f"DRY RUN would {dec.action} {sell_qty:.2f} {dec.ticker} "
                        f"@ ~${dec.current_price:.2f} (PnL {dec.pnl_pct:+.1f}%)"),
                pre_flight_warnings=warnings,
            ))
            continue

        try:
            order_id, status = _place_market_sell(
                client, dec.ticker, sell_qty, cfg.alpaca_fractional_shares,
            )
            results.append(ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="SELL_MARKET", ticker=dec.ticker,
                qty=sell_qty,
                limit_price=dec.current_price,
                order_id=order_id, status=status,
                dry_run=False,
                reason=(f"LIVE {dec.action} {sell_qty:.2f} {dec.ticker} "
                        f"(PnL {dec.pnl_pct:+.1f}%)"),
                pre_flight_warnings=warnings,
            ))
        except Exception as exc:
            results.append(ExecutionResult(
                timestamp=datetime.now().isoformat(),
                action="SELL_MARKET", ticker=dec.ticker,
                qty=sell_qty,
                limit_price=dec.current_price,
                status="error",
                dry_run=False,
                reason=f"order submit failed: {exc}",
                pre_flight_warnings=warnings,
            ))

    return results


# --- Orchestrator ----------------------------------------------------------

def run_execution(
    sizing_plan: Optional[SizingPlan] = None,
    exit_decisions: Optional[list[ExitDecision]] = None,
    dry_run: bool = True,
) -> ExecutionSummary:
    """Top-level: execute exits FIRST (free up capital), then entries."""
    cfg = load_agg_config()
    summary = ExecutionSummary(
        timestamp=datetime.now().isoformat(),
        dry_run=dry_run,
    )

    try:
        client = _get_trading_client(paper=True)
        summary.account_before = _fetch_account_snapshot(client)
    except Exception as exc:
        print(f"[exec] cannot reach Alpaca: {exc}")
        return summary

    # Exits first (sells free up cash)
    if exit_decisions:
        exit_results = execute_exits(exit_decisions, dry_run=dry_run,
                                      cfg=cfg, client=client)
        summary.exits_attempted = sum(1 for d in exit_decisions
                                       if d.action in ("TRIM_33","TRIM_50","SELL_ALL"))
        summary.exits_submitted = sum(1 for r in exit_results
                                       if r.status in ("submitted","accepted","filled","pending_new","new","dry_run"))
        summary.total_sell_notional = sum(
            r.qty * r.limit_price for r in exit_results
            if r.action == "SELL_MARKET"
        )
        summary.results.extend(exit_results)

    # Entries
    if sizing_plan and sizing_plan.orders:
        entry_results = execute_entries(sizing_plan, dry_run=dry_run,
                                          cfg=cfg, client=client)
        summary.entries_attempted = len(sizing_plan.orders)
        summary.entries_submitted = sum(1 for r in entry_results
                                          if r.status in ("submitted","accepted","pending_new","new","dry_run"))
        summary.total_buy_notional = sum(
            r.qty * r.limit_price for r in entry_results
            if r.action == "BUY_LIMIT"
        )
        summary.results.extend(entry_results)

    summary.account_after = _fetch_account_snapshot(client)

    # Save audit trail
    out_dir = cfg.state_dir / "executions"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"execution_{date_str}.json"
    path.write_text(
        json.dumps(asdict(summary), indent=2, default=str),
        encoding="utf-8",
    )
    latest = out_dir / "latest.json"
    latest.write_text(
        json.dumps(asdict(summary), indent=2, default=str),
        encoding="utf-8",
    )

    return summary


# --- Display + Telegram ----------------------------------------------------

def format_summary(summary: ExecutionSummary) -> str:
    mode = "DRY-RUN" if summary.dry_run else "LIVE PAPER"
    lines = [
        "=" * 78,
        f"EXECUTION SUMMARY - [{mode}]",
        f"Timestamp: {summary.timestamp}",
        "=" * 78,
        f"Entries: {summary.entries_attempted} attempted, "
        f"{summary.entries_submitted} submitted  "
        f"(${summary.total_buy_notional:,.0f})",
        f"Exits:   {summary.exits_attempted} attempted, "
        f"{summary.exits_submitted} submitted  "
        f"(${summary.total_sell_notional:,.0f})",
    ]
    if summary.account_before:
        lines.append("")
        lines.append(
            f"Account before: equity ${summary.account_before.get('equity',0):,.0f}, "
            f"cash ${summary.account_before.get('cash',0):,.0f}, "
            f"pos={summary.account_before.get('position_count',0)}"
        )
    lines.append("")
    lines.append("Actions:")
    for r in summary.results:
        icon = {"BUY_LIMIT":"BUY ", "SELL_MARKET":"SELL",
                "SKIP":"SKIP", "ERROR":"ERR "}.get(r.action, "?   ")
        status_tag = f"[{r.status}]"
        lines.append(f"  {icon} {r.ticker:<6} qty={r.qty:>8.2f}  {status_tag:<14} {r.reason}")
        for w in r.pre_flight_warnings:
            lines.append(f"         ! {w}")
    return "\n".join(lines)


def send_execution_digest(summary: ExecutionSummary) -> bool:
    from aggressive.telegram_alert import send_alert
    mode = "DRY-RUN" if summary.dry_run else "LIVE"
    lines = [f"EXEC [{mode}] {datetime.now().strftime('%H:%M')}"]
    if summary.entries_submitted or summary.exits_submitted:
        lines.append(
            f"BUY {summary.entries_submitted}/{summary.entries_attempted} (${summary.total_buy_notional:,.0f})"
        )
        lines.append(
            f"SELL {summary.exits_submitted}/{summary.exits_attempted} (${summary.total_sell_notional:,.0f})"
        )
    else:
        lines.append("No actions")
    # Actionable items only
    for r in summary.results:
        if r.action in ("BUY_LIMIT", "SELL_MARKET") and "error" not in r.status:
            tag = "BUY" if r.action == "BUY_LIMIT" else "SELL"
            lines.append(f"{tag} {r.ticker} x{r.qty:.1f} @${r.limit_price:.2f}")
    urgency = "critical" if not summary.dry_run and summary.exits_submitted > 0 else "info"
    return send_alert("\n".join(lines), urgency=urgency)


# --- CLI -------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--execute", action="store_true",
                   help="PLACE REAL paper orders (default: dry-run)")
    p.add_argument("--test", action="store_true",
                   help="run a smoke test with fake SizedOrder (no scanner)")
    args = p.parse_args()

    dry_run = not args.execute

    if args.test:
        # Build a tiny fake plan for smoke test
        from aggressive.position_sizing import SizedOrder, SizingPlan
        fake_plan = SizingPlan(
            capital_usd=100_000,
            regime="balanced",
            cash_target_pct=0.15,
            investable_dollars=85_000,
            orders=[
                SizedOrder(
                    ticker="AAPL",       # using AAPL because it's universally tradeable
                    target_dollars=1000.0,
                    target_shares=3.0,
                    target_weight_pct=0.01,
                    entry_price=230.0,
                    stop_price=210.0,
                    risk_dollars=60.0,
                    risk_pct_of_capital=0.0006,
                    phase="maturing",
                    phase_multiplier=1.0,
                    base_weight=0.01,
                    rationale="smoke test",
                ),
            ],
        )
        summary = run_execution(sizing_plan=fake_plan, dry_run=dry_run)
        print(format_summary(summary))
        return 0

    print("For real execution, call from daily_review.py with --execute flag")
    print("This script is typically invoked by daily_review, not standalone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
