#!/usr/bin/env python3
"""Smoke checks for fast replay official-account freshness.

The replay workflow may run focused challenger grids without refreshing the
operating account ledger. That mode must be explicit and must not emit a normal
official account evaluation. The default mode must continue into operating
broker replays before `run_account_evaluation.py`.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "alphaops_replay_sidecars_manual.yml"


def test_fast_replay_has_explicit_modes_and_no_unconditional_focused_exit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "replay_mode:" in text, "workflow must expose replay_mode"
    assert "official_operating" in text, "default official_operating mode missing"
    assert "focused_challenger_notice.json" in text, "focused mode must write non-official notice"
    assert "official_operating_replay_refreshed" in text, "focused notice must mark official replay stale"

    focused_notice = text.index("focused_challenger_notice.json")
    operating_replay = text.index("--output-dir outputs/broker_replay/main")
    final_eval = text.rindex("tools/run_account_evaluation.py")
    assert focused_notice < operating_replay < final_eval, (
        "official operating broker replay must run before final account evaluation in default mode"
    )

    old_message = "focused alpha-selector loop complete; skipping broad operational sidecars"
    assert old_message not in text, "old unconditional focused-exit path should not remain"


def main() -> int:
    test_fast_replay_has_explicit_modes_and_no_unconditional_focused_exit()
    print("fast_replay_official_freshness_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
