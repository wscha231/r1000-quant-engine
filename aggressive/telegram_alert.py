"""Telegram alert helper for Aggressive engine.

Usage:
    from aggressive.telegram_alert import send_alert
    send_alert("Trade: bought NVDA @ $182.50 for $33,000 (33% of portfolio)")

Env vars required (not committed to git):
    TELEGRAM_BOT_TOKEN    — from @BotFather
    TELEGRAM_CHAT_ID      — your chat ID with the bot

Setup:
    1. Telegram: talk to @BotFather
       /newbot → give name (e.g. "r1000_aggressive_alerts") and username
       → receive BOT_TOKEN like 123456:ABC-DEF-xyz...

    2. Send any message to your new bot in Telegram.

    3. Visit in browser (replace <TOKEN>):
       https://api.telegram.org/bot<TOKEN>/getUpdates
       → Find "chat":{"id": <CHAT_ID>, ...}

    4. Set PowerShell env vars:
       $env:TELEGRAM_BOT_TOKEN = "123456:ABC..."
       $env:TELEGRAM_CHAT_ID = "123456789"
       (add to $PROFILE to persist)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Allow direct execution: `py -3 aggressive/telegram_alert.py`
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import requests  # already a dependency in 정석

from aggressive.agg_config import get_telegram_credentials


def send_alert(
    message: str,
    urgency: str = "info",
    disable_notification: bool = False,
) -> bool:
    """Send a Telegram message. Returns True on success.

    Args:
        message: UTF-8 text body (emoji OK; keep under 4096 chars)
        urgency: 'info' | 'warning' | 'critical' — prefixed to message
        disable_notification: True for silent alerts (e.g. daily summary)

    Falls back to stdout print if TELEGRAM_BOT_TOKEN not set.
    """
    token, chat_id = get_telegram_credentials()
    prefix_map = {
        "info": "[INFO]",
        "warning": "[WARN]",
        "critical": "[ALERT]",
    }
    prefix = prefix_map.get(urgency, "[INFO]")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{prefix} {ts}\n{message}"

    if not token or not chat_id:
        # Graceful fallback — just log
        print(f"[telegram_alert DISABLED] {text}")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_notification": disable_notification,
    }
    try:
        r = requests.post(url, json=payload, timeout=8)
        if r.status_code == 200:
            return True
        print(f"[telegram_alert FAIL] {r.status_code}: {r.text[:200]}")
        return False
    except Exception as exc:
        print(f"[telegram_alert EXC] {exc}")
        return False


def send_trade_alert(ticker: str, side: str, qty: float, price: float, reason: str) -> bool:
    """Formatted trade alert."""
    action = "BUY" if side.upper() == "BUY" else "SELL"
    notional = qty * price
    msg = (
        f"TRADE {action} {ticker}\n"
        f"  qty: {qty:.4f}\n"
        f"  price: ${price:.2f}\n"
        f"  notional: ${notional:,.0f}\n"
        f"  reason: {reason}"
    )
    urgency = "warning" if action == "SELL" and "stop" in reason.lower() else "info"
    return send_alert(msg, urgency=urgency)


def send_drawdown_alert(current_dd: float, threshold: float) -> bool:
    """Warning when approaching MaxDD threshold."""
    urgency = "critical" if current_dd <= threshold else "warning"
    msg = (
        f"DRAWDOWN {current_dd*100:.2f}%\n"
        f"threshold: {threshold*100:.0f}%\n"
        f"engine action: {'PAUSE (full cash)' if current_dd <= threshold else 'monitor'}"
    )
    return send_alert(msg, urgency=urgency)


def send_regime_turn_alert(from_regime: str, to_regime: str, signals: dict) -> bool:
    """Regime turn detected → major event."""
    sig_str = ", ".join(f"{k}={v}" for k, v in signals.items())
    msg = (
        f"REGIME TURN: {from_regime} → {to_regime}\n"
        f"signals: {sig_str}\n"
        f"engine action: portfolio rebalance triggered"
    )
    return send_alert(msg, urgency="critical")


def send_theme_end_alert(theme: str, phase_before: str, members_held: list[str]) -> bool:
    """A theme in the portfolio has entered 'ending' phase."""
    msg = (
        f"THEME ENDING: {theme} ({phase_before} → ending)\n"
        f"holdings affected: {', '.join(members_held)}\n"
        f"engine action: theme_exit_trigger fired, selling all members"
    )
    return send_alert(msg, urgency="warning")


def send_daily_summary(
    nav: float, daily_pnl_pct: float,
    positions: list[tuple[str, float]],  # [(ticker, weight), ...]
    cash_pct: float,
) -> bool:
    """Silent end-of-day summary."""
    pos_str = "\n".join(f"  {t}: {w*100:.1f}%" for t, w in positions[:5])
    msg = (
        f"DAILY SUMMARY\n"
        f"NAV: ${nav:,.0f}\n"
        f"daily P&L: {daily_pnl_pct*100:+.2f}%\n"
        f"positions:\n{pos_str}\n"
        f"cash: {cash_pct*100:.1f}%"
    )
    return send_alert(msg, urgency="info", disable_notification=True)


if __name__ == "__main__":
    # Smoke test — send ping
    ok = send_alert("Aggressive engine telegram_alert.py smoke test (2026-04-23)")
    print(f"ping sent: {ok}")
