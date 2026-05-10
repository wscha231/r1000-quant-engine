#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
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
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "broker_replay" / "main").mkdir(parents=True)
        (root / "broker_replay" / "concentrated").mkdir(parents=True)
        (root / "backtest_metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.60, "max_dd": -0.10, "sharpe": 3.0}),
            encoding="utf-8",
        )
        (root / "concentrated_backtest_metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.70, "max_dd": -0.10, "sharpe": 3.0}),
            encoding="utf-8",
        )
        (root / "broker_replay" / "main" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.20, "max_dd": -0.40, "sharpe": 1.0, "valid_for_production": True}),
            encoding="utf-8",
        )
        (root / "broker_replay" / "concentrated" / "metrics.json").write_text(
            json.dumps({"status": "completed", "cagr": 0.30, "max_dd": -0.40, "sharpe": 1.0, "valid_for_production": True}),
            encoding="utf-8",
        )
        out2 = root / "goal"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "run_portfolio_goal_search.py"),
                "--latest-run",
                str(root),
                "--output-dir",
                str(out2),
            ],
            cwd=REPO_ROOT,
            check=True,
        )
        payload2 = json.loads((out2 / "goal_search_summary.json").read_text(encoding="utf-8"))
        assert payload2["best_main"]["candidate_id"] == "main_latest_champion"
        assert payload2["best_production_main"]["candidate_id"] == "main_broker_ledger_replay"
        assert payload2["best_production_concentrated"]["candidate_id"] == "concentrated_broker_ledger_replay"
        assert payload2["research_target_pass"] is True
        assert payload2["target_pass"] is False
        assert payload2["production_target_pass"] is False
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
