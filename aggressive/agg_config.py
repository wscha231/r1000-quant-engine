"""Aggressive engine configuration (Track 2 — CAGR 100% target).

User decisions (2026-04-23):
- Paper capital: $100k
- MaxDD tolerance: -30% (force pause threshold)
- Leverage: deferred to Phase 17 (empirical after paper validation)
- Cron: local Windows Task Scheduler for Phase D, migrate to AWS Lambda for Phase E
- Alerts: Telegram

API credentials are read from environment variables (never commit to git):
    ALPACA_API_KEY
    ALPACA_API_SECRET
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AggressiveConfig:
    """Aggressive-engine tunables. One source of truth for Track 2."""

    # ----- portfolio ---------------------------------------------------
    portfolio_n: int = 3                        # concentrated N=2 or 3
    min_position_weight: float = 0.20           # never hold < 20% of capital
    max_position_weight: float = 0.50           # never hold > 50% per name
    cash_target_bull: float = 0.00              # bull regime: fully invested
    cash_target_balanced: float = 0.15          # balanced: 15% cash
    cash_target_bear: float = 0.50              # bear: 50% cash
    cash_target_regime_turn: float = 1.00       # regime turn: 100% cash

    # ----- entry triggers ---------------------------------------------
    earnings_beat_entry: bool = True            # buy on beat + raise guidance
    insider_cluster_threshold: int = 3          # ≥3 C-suite buys in 2 weeks
    theme_phase_entry: str = "maturing"         # enter when theme=maturing
    momentum_breakout_required: bool = True     # confirm with price breakout
    volume_surge_threshold: float = 1.5         # 1.5x 20-day avg volume

    # ----- exit triggers ----------------------------------------------
    trailing_stop_pct: float = 0.10             # -10% peak drawdown → exit
    hard_stop_pct: float = 0.15                 # -15% intraday → immediate
    theme_exit_immediate: bool = True           # theme=ending → exit all members
    regime_turn_full_cash: bool = True          # regime turn → liquidate to cash
    earnings_miss_exit: bool = True             # miss + guidance cut → exit
    rs_break_exit: bool = True                  # RS top-decile → bottom-30% → exit

    # ----- risk guardrails --------------------------------------------
    daily_drawdown_force_cash: float = -0.05    # -5% single day → full cash
    max_drawdown_tolerance: float = -0.30       # -30% → pause engine, alert user
    max_drawdown_alert: float = -0.15           # -15% → send warning alert

    # ----- leverage (Phase 17, default OFF) ---------------------------
    leverage_enabled: bool = False
    leverage_max: float = 2.0
    leverage_regime_allow: list[str] = field(default_factory=lambda: ["bull_strong"])
    leverage_deleverage_on_turn: bool = True

    # ----- Alpaca API -------------------------------------------------
    alpaca_mode: str = "paper"                  # 'paper' | 'live'
    alpaca_base_url_paper: str = "https://paper-api.alpaca.markets"
    alpaca_base_url_live: str = "https://api.alpaca.markets"
    alpaca_data_url: str = "https://data.alpaca.markets"
    alpaca_capital_usd: float = 100_000.0
    alpaca_max_order_usd: float = 50_000.0      # max single-order notional
    alpaca_fractional_shares: bool = True       # enable fractional
    alpaca_limit_orders_only: bool = True       # no market orders

    # ----- timing -----------------------------------------------------
    cron_main_interval_minutes: int = 5         # main loop every 5 min during market hours
    cron_eod_time_et: str = "15:55"             # end-of-day check 5 min before close
    event_reaction_min_delay_seconds: int = 60  # wait at least 60s after event
    event_reaction_max_delay_seconds: int = 600  # must act within 10 min

    # ----- universe filter --------------------------------------------
    universe_source: str = "themes"             # 'themes' (theme members only) | 'r1000' | 'custom'
    universe_theme_filter: list[str] = field(default_factory=lambda: [])  # [] = all themes
    min_dollar_volume_20d: float = 10_000_000.0  # $10M avg daily volume (liquidity)

    # ----- backtest ---------------------------------------------------
    backtest_horizon_years: int = 5
    backtest_frequency: str = "daily"           # 'daily' | 'weekly'
    backtest_cost_bps_per_side: float = 10.0    # Alpaca: zero commission but ~10 bps slippage

    # ----- alerts -----------------------------------------------------
    telegram_alerts_enabled: bool = True
    alert_on_trade: bool = True
    alert_on_drawdown_warning: bool = True
    alert_on_regime_turn: bool = True
    alert_on_engine_pause: bool = True
    alert_daily_summary: bool = True
    alert_daily_summary_time_kst: str = "23:00"  # before US market open

    # ----- paths ------------------------------------------------------
    state_dir: Path = field(default_factory=lambda: Path(__file__).parent / "state")
    cache_dir: Path = field(default_factory=lambda: Path(__file__).parent / "cache")


def load_agg_config() -> AggressiveConfig:
    """Factory — may override from env var in future."""
    cfg = AggressiveConfig()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


def get_alpaca_credentials() -> tuple[str, str]:
    """Load Alpaca API credentials from environment.

    User must set (PowerShell):
        $env:ALPACA_API_KEY = "your_key_here"
        $env:ALPACA_API_SECRET = "your_secret_here"

    Get credentials from:
        https://app.alpaca.markets/paper/dashboard/overview
        → left sidebar → 'API Keys' → 'Generate New Key'
    """
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_API_SECRET", "").strip()
    if not key or not secret:
        raise RuntimeError(
            "ALPACA_API_KEY and ALPACA_API_SECRET must be set as environment variables.\n"
            "Get from: https://app.alpaca.markets/paper/dashboard/overview"
        )
    return key, secret


def get_telegram_credentials() -> tuple[str, str]:
    """Load Telegram bot credentials from environment.

    Setup steps:
      1. Talk to @BotFather on Telegram, create new bot, get BOT_TOKEN
      2. Start conversation with your bot (send any message)
      3. Get CHAT_ID by visiting:
         https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
         → find your chat_id in the JSON response
      4. Set env vars:
         $env:TELEGRAM_BOT_TOKEN = "123456:ABC-..."
         $env:TELEGRAM_CHAT_ID = "123456789"
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return token, chat_id


if __name__ == "__main__":
    # Quick sanity check — run `py -3 aggressive/agg_config.py`
    cfg = load_agg_config()
    print("AggressiveConfig loaded:")
    print(f"  portfolio_n:                  {cfg.portfolio_n}")
    print(f"  alpaca_capital_usd:           ${cfg.alpaca_capital_usd:,.0f}")
    print(f"  max_drawdown_tolerance:       {cfg.max_drawdown_tolerance*100:.0f}%")
    print(f"  leverage_enabled:             {cfg.leverage_enabled}")
    print(f"  state_dir:                    {cfg.state_dir}")
    print(f"  telegram_alerts_enabled:      {cfg.telegram_alerts_enabled}")
    try:
        key, _ = get_alpaca_credentials()
        print(f"  ALPACA_API_KEY:              {key[:6]}... (OK)")
    except RuntimeError as e:
        print(f"  ALPACA_API_KEY:              NOT SET ({e})")
    token, chat = get_telegram_credentials()
    print(f"  TELEGRAM_BOT_TOKEN:           {'OK' if token else 'NOT SET'}")
    print(f"  TELEGRAM_CHAT_ID:             {chat if chat else 'NOT SET'}")
