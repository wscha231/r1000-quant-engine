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


__all__ = [
    "_resolve_engine_commit_sha",
    "ENGINE_COMMIT_SHA",
    "phase_is_enabled",
    "now_ts",
    "log",
]
