#!/usr/bin/env python3
"""Static dependency-contract check for the scheduled AutoLearning scan."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "daily_autolearning_scan.yml"


def test_daily_autolearning_uses_the_repository_dependency_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    requirements = (ROOT / "requirements_github.txt").read_text(encoding="utf-8")
    for token in [
        "Daily AutoLearning Scan",
        "cache-dependency-path: requirements_github.txt",
        "pip install -r requirements_github.txt",
        "tools/run_concentrated_policy_replay.py",
    ]:
        assert token in text, token
    assert "pandas_market_calendars" in requirements
    assert "pip install pandas numpy yfinance pyyaml pyarrow" not in text


if __name__ == "__main__":
    test_daily_autolearning_uses_the_repository_dependency_contract()
    print("daily_autolearning_workflow_smoke: PASS")
