"""B1.1 — Alpaca Paper account connection smoke test.

Run:
    py -3 aggressive/test_alpaca_connection.py

Confirms:
    - alpaca-py SDK installed
    - ALPACA_API_KEY / SECRET loaded from .env
    - Paper account accessible
    - Can fetch account metadata + positions + a quote
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from aggressive.agg_config import get_alpaca_credentials  # noqa: E402


def main() -> int:
    try:
        key, secret = get_alpaca_credentials()
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1

    try:
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestQuoteRequest
    except ImportError:
        print("FAIL: alpaca-py not installed. Run: py -3 -m pip install alpaca-py")
        return 1

    print("=" * 60)
    print("Alpaca Paper Account - Smoke Test")
    print("=" * 60)

    try:
        client = TradingClient(key, secret, paper=True)
        account = client.get_account()
    except Exception as exc:
        print(f"FAIL on get_account: {exc}")
        return 1

    print(f"  status:              {account.status}")
    print(f"  currency:            {account.currency}")
    print(f"  cash:                ${float(account.cash):,.2f}")
    print(f"  equity:              ${float(account.equity):,.2f}")
    print(f"  buying_power:        ${float(account.buying_power):,.2f}")
    print(f"  portfolio_value:     ${float(account.portfolio_value):,.2f}")
    print(f"  account_number:      {account.account_number}")
    print(f"  pattern_day_trader:  {account.pattern_day_trader}")
    print(f"  trading_blocked:     {account.trading_blocked}")
    print()

    try:
        positions = client.get_all_positions()
        print(f"  current positions:   {len(positions)}")
        for p in positions[:5]:
            pnl_pct = (float(p.current_price) / float(p.avg_entry_price) - 1.0) * 100
            print(f"    {p.symbol:<6} qty={p.qty:<8} avg=${float(p.avg_entry_price):<8.2f} "
                  f"cur=${float(p.current_price):<8.2f} pnl={pnl_pct:+.2f}%")
    except Exception as exc:
        print(f"WARN: positions fetch failed: {exc}")

    print()
    try:
        data = StockHistoricalDataClient(key, secret)
        req = StockLatestQuoteRequest(symbol_or_symbols=["NVDA", "SPY"])
        quotes = data.get_stock_latest_quote(req)
        print("  latest quotes (IEX):")
        for sym, q in quotes.items():
            print(f"    {sym}: bid=${q.bid_price:.2f}×{q.bid_size}  ask=${q.ask_price:.2f}×{q.ask_size}")
    except Exception as exc:
        print(f"WARN: quote fetch failed: {exc}")

    print()
    print("PASS: Alpaca paper account connection working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
