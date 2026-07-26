#!/usr/bin/env python3
"""Auto-learning can propose a challenger but can never mutate the champion."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "auto_learning_promote.py"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        main_metrics = root / "main.json"
        conc_metrics = root / "conc.json"
        grades = root / "grades.csv"
        candidate = root / "candidate.yaml"
        active = root / "active.yaml"
        decision = root / "decision.json"

        main_metrics.write_text(
            json.dumps({"cagr": 0.40, "sharpe": 1.8, "max_dd": -0.18}),
            encoding="utf-8",
        )
        conc_metrics.write_text(json.dumps({"cagr": 0.60}), encoding="utf-8")
        grades.write_text("trade_id,grade\n" + "\n".join(f"{i},A" for i in range(300)), encoding="utf-8")
        candidate.write_text("candidate: true\n", encoding="utf-8")
        sentinel = "champion: preserve-me\n"
        active.write_text(sentinel, encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--main-metrics",
                str(main_metrics),
                "--concentrated-metrics",
                str(conc_metrics),
                "--grades",
                str(grades),
                "--candidate-gates",
                str(candidate),
                "--active-gates",
                str(active),
                "--decision-out",
                str(decision),
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(decision.read_text(encoding="utf-8"))
        assert payload["eligible_for_review"] is True
        assert payload["approved"] is True
        assert payload["automatic_promotion_allowed"] is False
        assert payload["proposal_only"] is True
        assert payload["promoted"] is False
        assert payload["dry_run"] is True
        assert active.read_text(encoding="utf-8") == sentinel

    print("auto_learning_proposal_only_smoke: ok")


if __name__ == "__main__":
    main()
