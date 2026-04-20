"""r1000 Quant Engine — pure utility helpers.

This module owns small, dependency-free utility functions extracted from
`r1000_top30_institutional.py` during Refactor Phase A Stage 2.

Stage 2a (this commit): the smallest/safest helpers — git commit SHA
resolver, phase-toggle env-var check, timestamp + log print helpers.
All stdlib-only; no numpy/pandas, no r1000_config, no r1000_top30.

Import discipline
-----------------
    r1000_config.py           (pure data, stdlib)
        ^
        |
    r1000_helpers.py          (pure helpers, stdlib + maybe numpy/pandas
                               in later sub-stages)
        ^                     ^
        |                     |
    r1000_top30_institutional.py
        ^
        |
    r1000_data_collector.py
    r1000_operator.py
    r1000_portfolio_state.py

r1000_helpers.py may import from r1000_config.py (e.g. EngineConfig for
`to_cfg`), but NEVER from the main engine or collectors. This keeps the
dependency graph acyclic.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
import pandas as pd
from dataclasses import asdict
from typing import Optional
from r1000_config import EngineConfig


# ---------------------------------------------------------------------
# Git commit SHA provenance (Stage 2a)
# ---------------------------------------------------------------------

def _resolve_engine_commit_sha() -> str:
    """Return short git SHA of the engine repo for run provenance.

    Printed in every run banner so logs/notebooks self-identify which
    code version produced them. Falls back to '(unknown)' if git isn't
    available (e.g. engine installed as a wheel instead of a clone, or
    the git binary is missing from PATH).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        sha = (result.stdout or "").strip()
        return sha if sha else "(unknown)"
    except Exception:
        return "(unknown)"


# Evaluated once at import time. The main engine imports this symbol for
# run-banner prints. If pre-computing at import is undesirable (e.g. for
# test isolation), callers can invoke `_resolve_engine_commit_sha()`
# directly instead.
ENGINE_COMMIT_SHA = _resolve_engine_commit_sha()


# ---------------------------------------------------------------------
# Phase toggle dual-gate: cfg flag + PHASE_<KEY>_ENABLED env var (Stage 2a)
# ---------------------------------------------------------------------
# Every phase (1 .. 9) has a pair:
#     cfg.phaseN_*_enabled: bool  (programmatic override)
#     PHASE_PHASEN_*_ENABLED env  (runtime override, wins vs cfg)
# This function reads the env; the cfg branch is handled at call site.
#
# Usage (main engine or notebook):
#     import os
#     os.environ["PHASE_PHASE1_ALPHA_ENABLED"] = "0"       # disable Phase 1
#     os.environ["PHASE_PHASE2_INDUSTRY_ENABLED"] = "0"    # disable Phase 2
#
# Any of: "0", "false", "no", "off", "disabled" (case-insensitive) turns
# a phase OFF.  Anything else (including unset) leaves it at the default.

def phase_is_enabled(phase_key: str, default: bool = True) -> bool:
    """Check env var PHASE_{KEY}_ENABLED.  Returns `default` when unset."""
    env_name = f"PHASE_{phase_key.upper()}_ENABLED"
    raw = os.environ.get(env_name, "")
    val = str(raw).strip().lower()
    if val == "":
        return bool(default)
    if val in ("0", "false", "no", "off", "disabled"):
        return False
    if val in ("1", "true", "yes", "on", "enabled"):
        return True
    return bool(default)


# ---------------------------------------------------------------------
# Timestamp + log helpers (Stage 2a)
# ---------------------------------------------------------------------

def now_ts() -> str:
    """Return current local time as YYYYMMDD_HHMMSS (used in archive paths)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def log(msg: str) -> None:
    """Stamp `msg` with [HH:MM:SS] and print to stdout.

    Intentionally simple — all engine progress logging uses this single
    function so a future switch to `logging.getLogger` is one-file.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ---------------------------------------------------------------------
# Config helpers (Stage 2b) — transform EngineConfig instances
# ---------------------------------------------------------------------
# All 3 functions operate on EngineConfig (from r1000_config) or dict
# form thereof. Require pandas for date arithmetic in
# configure_last_n_years_backtest.

def apply_fast_mode(cfg: "EngineConfig") -> "EngineConfig":
    """Apply runtime-reduction overrides when cfg.fast_mode is True.

    Phase 1/2 savings:
      - live fundamentals refresh limited to the highest-liquidity subset
      - slower-changing statement supplements refreshed less often
      - yfinance quarterly supplement capped to a smaller stale subset

    Phase 4 savings:
      - CatBoost iterations cut ~40%: reg 350→200, cls 350→200, rank 250→150
      - ranking_enabled disabled: ~30% faster per retrain cycle
      - retrain frequency halved: 3m→6m  (fewer training windows)

    Phase 5 savings:
      - regime-per-regime comparison disabled (-12 backtests)
      - AI four-sleeve comparison disabled (-13 backtests)
      - regime-map-method comparison disabled (-2 backtests)
      - standalone sleeve comparison disabled (-6 backtests)
      - sleeve-cap policy candidates reduced to 3 (-3 backtests vs default 6)
    Net: ~5 backtests instead of ~44.  Estimated runtime: ~1.5h vs ~8h.
    """
    if not cfg.fast_mode:
        return cfg
    # Phase 1/2 — collector I/O and supplement refresh
    cfg.live_refresh_days = max(int(cfg.live_refresh_days), 2)
    cfg.max_live_refresh_tickers = min(int(cfg.max_live_refresh_tickers), 400)
    cfg.latest_statement_repair_refresh_days = max(int(cfg.latest_statement_repair_refresh_days), 14)
    cfg.yf_quarterly_refresh_days = max(int(cfg.yf_quarterly_refresh_days), 14)
    cfg.yf_quarterly_max_tickers_per_run = min(int(cfg.yf_quarterly_max_tickers_per_run), 120)
    # Phase 4 — model complexity
    cfg.cat_reg_iterations = 200
    cfg.cat_cls_iterations = 200
    cfg.cat_rank_iterations = 150
    cfg.ranking_enabled = False
    cfg.walkforward_retrain_frequency_months = 6
    cfg.cat_validation_months = 4
    # Phase 5 — comparison suites
    cfg.run_sleeve_regime_comparison = False
    cfg.run_ai_four_sleeve_comparison = False
    cfg.run_regime_map_method_comparison = False
    cfg.run_standalone_sleeve_backtest_comparison = False
    cfg.run_concentrated_backtest_comparison = True
    # Phase 9 CE (2026-04-18): fast_mode used to strip concentrated grid to
    # [N=1,2,3] × [monthly] × [conviction_curve] = 3 backtests. Expand to the
    # CE grid so fast_mode runs still measure the full concentration ladder.
    # Cost: 7 × 3 × 3 = 63 concentrated backtests × ~6s each = ~6.3 min extra,
    # negligible next to walk-forward training time.
    cfg.concentrated_top_n_candidates = [1, 2, 3, 4, 5, 7, 10]
    cfg.concentrated_rebalance_intervals = [1, 2, 3]
    cfg.concentrated_weighting_modes = ["conviction_curve", "winner_take_all", "score_power"]
    cfg.sleeve_cap_policy_max_candidates = 3
    log("[fast_mode] ON -- lighter collector refresh + ~5 backtests, retrain every 6m; Phase 9 CE concentrated grid expanded to 63 combos.")
    return cfg

def to_cfg(cfg: Optional[dict | EngineConfig]) -> EngineConfig:
    if cfg is None:
        return EngineConfig()
    if isinstance(cfg, EngineConfig):
        return cfg
    base = EngineConfig()
    allowed = set(asdict(base).keys())
    for k, v in cfg.items():
        if k in allowed:
            setattr(base, k, v)
    if not base.alpha_vantage_api_key:
        base.alpha_vantage_api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not base.sec_user_agent or "your_email" in base.sec_user_agent:
        base.sec_user_agent = os.getenv("SEC_USER_AGENT", base.sec_user_agent)
    return base

def configure_last_n_years_backtest(
    cfg: Optional[dict | EngineConfig] = None,
    years: int = 5,
    *,
    end_date: Optional[str] = None,
    train_lookback_years: Optional[int] = None,
) -> EngineConfig:
    cfg_obj = to_cfg(cfg)
    years = int(years)
    if years < 1:
        raise ValueError("years must be >= 1")
    end_ts = pd.Timestamp(end_date or cfg_obj.end_date).normalize()
    if pd.isna(end_ts):
        raise ValueError("end_date could not be parsed")
    start_ts = (end_ts - pd.DateOffset(years=years)).normalize()
    cfg_obj.start_date = str(start_ts.date())
    cfg_obj.end_date = str(end_ts.date())
    if train_lookback_years is not None:
        cfg_obj.train_lookback_years = int(train_lookback_years)
    return cfg_obj


__all__ = [
    "_resolve_engine_commit_sha",
    "phase_is_enabled",
    "now_ts",
    "log",
    "apply_fast_mode",
    "to_cfg",
    "configure_last_n_years_backtest",
    "ENGINE_COMMIT_SHA",
]
