#!/usr/bin/env python3
"""Smoke for the Family A (fast-crash defense) A/B env-override hook in
EngineConfig (`_apply_fast_crash_env_overrides`).

The 7Y A/B plan (docs/CODEX_AB_EXECUTION_7Y_CAGR_MDD_*.md) tunes the
fast-crash MDD levers — multi-level drawdown breaker + VIX-level guard —
via the full_rebuild_manual.yml experiment_env_json mechanism, which only
allows env keys matching `^(PHASE_|R1000_|ALPHAOPS_)[A-Z0-9_]+$`. This hook
lets each whitelisted EngineConfig field be overridden by
`R1000_<FIELD_NAME_UPPER>` so an A/B run can pass e.g.
{"R1000_DRAWDOWN_BREAKER_LEVEL_1_THRESHOLD": "0.08"} with no code change.

Contract verified here:
  - defaults are unchanged when no env is set (measurement infra, not policy)
  - float and bool overrides apply via R1000_<FIELD>
  - malformed values are ignored (default kept), never crash a run
  - only whitelisted fields are env-overridable
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import r1000_config as C  # noqa: E402

# Every R1000_<FIELD> key this smoke may set, cleared before/after each test.
_MANAGED_ENV = {
    "R1000_" + name.upper() for name in C.FAST_CRASH_ENV_OVERRIDE_FIELDS
} | {"R1000_NOT_A_REAL_FIELD"}


def _clear_env() -> None:
    for k in _MANAGED_ENV:
        os.environ.pop(k, None)


def test_defaults_unchanged_when_no_env() -> None:
    _clear_env()
    cfg = C.EngineConfig()
    assert cfg.drawdown_breaker_level_1_threshold == 0.12
    assert cfg.vix_level_tier1_cash_floor == 0.10
    assert cfg.drawdown_breaker_multilevel_enabled is True
    assert cfg.vix_level_guard_enabled is True


def test_float_override_applied() -> None:
    _clear_env()
    os.environ["R1000_DRAWDOWN_BREAKER_LEVEL_1_THRESHOLD"] = "0.08"
    os.environ["R1000_VIX_LEVEL_TIER1_CASH_FLOOR"] = "0.20"
    try:
        cfg = C.EngineConfig()
        assert cfg.drawdown_breaker_level_1_threshold == 0.08
        assert cfg.vix_level_tier1_cash_floor == 0.20
        # untouched field keeps its default
        assert cfg.drawdown_breaker_level_2_threshold == 0.20
    finally:
        _clear_env()


def test_bool_override_applied() -> None:
    _clear_env()
    os.environ["R1000_VIX_LEVEL_GUARD_ENABLED"] = "false"
    os.environ["R1000_DRAWDOWN_BREAKER_MULTILEVEL_ENABLED"] = "0"
    try:
        cfg = C.EngineConfig()
        assert cfg.vix_level_guard_enabled is False
        assert cfg.drawdown_breaker_multilevel_enabled is False
    finally:
        _clear_env()


def test_malformed_value_ignored_no_crash() -> None:
    _clear_env()
    os.environ["R1000_DRAWDOWN_BREAKER_LEVEL_2_THRESHOLD"] = "notanumber"
    try:
        cfg = C.EngineConfig()  # must not raise
        assert cfg.drawdown_breaker_level_2_threshold == 0.20  # default kept
    finally:
        _clear_env()


def test_non_whitelisted_field_not_overridable() -> None:
    _clear_env()
    # base_dir is a real field but NOT in the fast-crash whitelist -> ignored
    os.environ["R1000_BASE_DIR"] = "/tmp/should_not_apply"
    os.environ["R1000_NOT_A_REAL_FIELD"] = "1"
    try:
        cfg = C.EngineConfig()
        assert cfg.base_dir != "/tmp/should_not_apply"
    finally:
        _clear_env()


def test_whitelist_is_complete_and_exported() -> None:
    assert "FAST_CRASH_ENV_OVERRIDE_FIELDS" in C.__all__
    fields = C.FAST_CRASH_ENV_OVERRIDE_FIELDS
    # the two headline MDD levers from the A/B plan must be present
    assert "drawdown_breaker_level_1_threshold" in fields
    assert "vix_level_tier1_cash_floor" in fields
    # every whitelisted name must be a real EngineConfig field
    cfg = C.EngineConfig()
    for name in fields:
        assert hasattr(cfg, name), f"whitelisted field missing on EngineConfig: {name}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    try:
        for fn in tests:
            fn()
            print(f"PASS {fn.__name__}")
        print(f"\n{len(tests)}/{len(tests)} passed")
    finally:
        _clear_env()
