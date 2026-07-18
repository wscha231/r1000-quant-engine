#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_run287_growth_embargo import run


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture(root: Path, *, future_leak: bool = False, late_candidate_rate: float = 0.16) -> argparse.Namespace:
    dates = pd.bdate_range("2022-01-03", "2026-07-02")
    baseline = 100000.0 * (1.0 + 0.10) ** ((dates - dates[0]).days / 365.25)
    split = pd.Timestamp("2024-07-01")
    candidate = []
    for date, base in zip(dates, baseline):
        rate = 0.14 if date <= split else late_candidate_rate
        candidate.append(100000.0 * (1.0 + rate) ** ((date - dates[0]).days / 365.25))
    replay = root / "replay"
    for name, values in (("baseline", baseline), ("candidate", candidate)):
        path = replay / name / "equity_curve.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"date": dates, "equity_usd": values}).to_csv(path, index=False)
    decision = pd.Timestamp("2023-01-31")
    available = pd.Timestamp("2023-02-01") if future_leak else pd.Timestamp("2023-01-30")
    target = root / "target.csv"
    pd.DataFrame(
        {
            "rebalance_date": [decision.date().isoformat()],
            "ticker": ["AAA"],
            "latest_available_from": [available.isoformat()],
            "fusion_score_source_rebalance_date": [decision.date().isoformat()],
            "period_forward_return": [0.25],
        }
    ).to_csv(target, index=False)
    source = root / "source.json"
    write_json(source, {"used_forward_return_in_ranking": False})
    contract = root / "contract.json"
    write_json(
        contract,
        {
            "policy": {"signal": "growth_confirmation_score", "arm": "tilt10"},
            "folds": [
                {"name": "a", "train_end": "2022-12-30", "test_end": "2024-06-28"},
                {"name": "b", "train_end": "2024-06-28", "test_end": "2026-07-02"},
            ],
            "gates": {
                "embargo_sessions": 126,
                "minimum_test_sessions_per_fold": 60,
                "each_fold_minimum_delta_sharpe": -0.05,
                "future_row_violation_count": 0,
                "used_forward_return_in_ranking": False,
            },
        },
    )
    return argparse.Namespace(
        contract=str(contract),
        replay_root=str(replay),
        target_book=str(target),
        source_summary=str(source),
        output_dir=str(root / "out"),
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        args = fixture(Path(temp))
        payload = run(args)
        assert payload["status"] == "PASS_FIXED_POLICY_EMBARGO"
        assert payload["fixed_policy_embargo_pass"] is True
        assert payload["walk_forward_retraining_completed"] is False
        assert len(payload["folds"]) == 2
        assert all(row["embargo_sessions"] == 126 for row in payload["folds"])
        assert all(row["delta_cagr_pp"] > 0 for row in payload["folds"])
        assert all(row["test_sessions"] >= 60 for row in payload["folds"])
        assert math.isfinite(payload["folds"][0]["delta_sharpe"])
        assert set(payload["inputs"]) == {
            "contract",
            "baseline_equity",
            "candidate_equity",
            "target_book",
            "source_summary",
        }

    with tempfile.TemporaryDirectory() as temp:
        payload = run(fixture(Path(temp), future_leak=True))
        assert payload["status"] == "BLOCKED_FUTURE_ROW_LEAKAGE"
        assert payload["fixed_policy_embargo_pass"] is False
        assert payload["provenance"]["future_row_violation_count"] == 1

    with tempfile.TemporaryDirectory() as temp:
        payload = run(fixture(Path(temp), late_candidate_rate=0.05))
        assert payload["status"] == "REJECT_EMBARGO_FOLD"
        assert payload["fixed_policy_embargo_pass"] is False
        assert payload["folds"][1]["pass"] is False

    print("run287_growth_embargo_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
