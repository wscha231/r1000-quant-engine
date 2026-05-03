#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "run_portfolio_goal_search.py")],
        cwd=REPO_ROOT,
        check=True,
    )
    out = REPO_ROOT / "outputs" / "portfolio_goal_search" / "goal_search_summary.json"
    assert out.exists(), "goal_search_summary.json was not written"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "best_main" in payload
    assert "best_concentrated" in payload
    assert isinstance(payload.get("main_candidates"), list)
    assert isinstance(payload.get("concentrated_candidates"), list)
    report = REPO_ROOT / "outputs" / "portfolio_goal_search" / "goal_search_report.md"
    assert report.exists(), "goal_search_report.md was not written"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
