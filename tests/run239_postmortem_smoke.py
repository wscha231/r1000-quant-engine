#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run239_postmortem import run  # noqa: E402


class Args:
    pass


def test_run239_postmortem_builds_three_way_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prev = root / "prev"
        cur = root / "cur"
        prev.mkdir()
        cur.mkdir()
        pd.DataFrame(
            [
                {"portfolio": "concentrated", "ticker": "AAA", "current_weight": 0.40},
                {"portfolio": "concentrated", "ticker": "BBB", "current_weight": 0.30},
                {"portfolio": "concentrated", "ticker": "CASH", "current_weight": 0.30},
            ]
        ).to_csv(prev / "01_current_holdings.csv", index=False)
        pd.DataFrame(
            [
                {"portfolio": "concentrated", "ticker": "CCC", "target_weight": 0.50},
                {"portfolio": "concentrated", "ticker": "AAA", "target_weight": 0.20},
                {"portfolio": "concentrated", "ticker": "CASH", "target_weight": 0.30},
            ]
        ).to_csv(prev / "02_target_weights.csv", index=False)
        pd.DataFrame(
            [
                {"portfolio": "concentrated", "ticker": "AAA", "current_weight": 0.10},
                {"portfolio": "concentrated", "ticker": "CCC", "current_weight": 0.50},
                {"portfolio": "concentrated", "ticker": "CASH", "current_weight": 0.40},
            ]
        ).to_csv(cur / "01_current_holdings.csv", index=False)
        pd.DataFrame(
            [
                {"portfolio": "concentrated", "ticker": "CCC", "target_weight": 0.60},
                {"portfolio": "concentrated", "ticker": "CASH", "target_weight": 0.40},
            ]
        ).to_csv(cur / "02_target_weights.csv", index=False)
        metrics = root / "metrics.json"
        metrics.write_text(
            json.dumps(
                {
                    "portfolios": {
                        "main": {"cagr": 0.30, "max_dd": -0.26, "sharpe": 1.1, "target_pass": False},
                        "concentrated": {"cagr": 0.44, "max_dd": -0.23, "sharpe": 1.3, "target_pass": False},
                    }
                }
            ),
            encoding="utf-8",
        )
        log = root / "failed.log"
        log.write_text("BROKER-LEDGER VERDICT -- DEFERRED TO SIDECAR STEP\nProcess completed with exit code 1\n", encoding="utf-8")
        args = Args()
        args.run_id = "test"
        args.previous_user_current_dir = str(prev)
        args.current_user_current_dir = str(cur)
        args.current_official_metrics = str(metrics)
        args.failed_log = str(log)
        args.output_dir = str(root / "out")
        payload = run(args)
        assert payload["status"] == "completed"
        report = (root / "out" / "report.md").read_text(encoding="utf-8")
        assert "Official Broker Metrics" in report
        rows = pd.read_csv(root / "out" / "rotation_three_way.csv")
        aaa = rows[rows["ticker"].eq("AAA")].iloc[0]
        assert aaa["classification"] == "exit_from_operating"
        ccc = rows[rows["ticker"].eq("CCC")].iloc[0]
        assert ccc["classification"] == "new_target_entry"


def main() -> int:
    test_run239_postmortem_builds_three_way_report()
    print("run239_postmortem_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
