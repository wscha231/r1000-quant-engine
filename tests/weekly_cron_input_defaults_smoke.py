#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_full_rebuild_schedule_inputs_have_shell_defaults() -> None:
    workflow = (ROOT / ".github" / "workflows" / "full_rebuild_manual.yml").read_text(encoding="utf-8")
    assert "schedule:" in workflow
    assert "INPUT_SKIP_COLLECTOR: ${{ inputs.skip_collector || 'true' }}" in workflow
    assert "INPUT_FAST_MODE: ${{ inputs.fast_mode || 'true' }}" in workflow
    assert 'UNIVERSE_MODE="${UNIVERSE_MODE:-global_alpha_universe}"' in workflow
    assert 'BACKTEST_YEARS="${BACKTEST_YEARS:-7}"' in workflow
    assert 'LEADER_RESCUE_MODE="${LEADER_RESCUE_MODE:-latest_only}"' in workflow
    assert 'REQUESTED_SKIP_COLLECTOR="${INPUT_SKIP_COLLECTOR:-true}"' in workflow
    assert 'FAST_MODE_FLAG="${INPUT_FAST_MODE:-true}"' in workflow
    assert 'FAST_MODE_FLAG="${{ inputs.fast_mode }}"' not in workflow
    assert 'if [ "${{ inputs.skip_collector }}" = "true" ]; then' not in workflow


def main() -> int:
    test_full_rebuild_schedule_inputs_have_shell_defaults()
    print("weekly_cron_input_defaults_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
