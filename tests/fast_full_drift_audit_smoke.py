#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_fast_full_drift_audit import run


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def write_artifact(root: Path, *, main_cagr: float, main_dd: float, conc_cagr: float, conc_dd: float) -> None:
    write_json(root / "account_evaluation" / "official_metrics.json", {"official_metric_mode": "broker_ledger_next_close"})
    for portfolio, cagr, max_dd in [
        ("main", main_cagr, main_dd),
        ("concentrated", conc_cagr, conc_dd),
    ]:
        write_json(
            root / "broker_replay" / portfolio / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": True,
                "cagr": cagr,
                "max_dd": max_dd,
                "sharpe": 1.0,
                "avg_cash_weight": 0.20,
                "total_fees_usd": 100.0,
                "trade_count": 2,
            },
        )
    for name in ["operating_main_target_book.csv", "operating_concentrated_target_book.csv"]:
        write_csv(
            root / "reports" / name,
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.80},
                {"rebalance_date": "2026-01-31", "ticker": "CASH", "weight": 0.20},
                {"rebalance_date": "2026-02-28", "ticker": "BBB", "weight": 0.75},
                {"rebalance_date": "2026-02-28", "ticker": "CASH", "weight": 0.25},
            ],
        )
    write_csv(root / "reports" / "candidate_replay_book.csv", [{"ticker": "AAA"}, {"ticker": "BBB"}])
    write_csv(root / "scored_latest.csv", [{"ticker": "AAA"}, {"ticker": "BBB"}])


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        full = root / "full"
        fast = root / "fast"
        out = root / "out"

        write_artifact(full, main_cagr=0.334, main_dd=-0.262, conc_cagr=0.406, conc_dd=-0.299)
        write_artifact(fast, main_cagr=0.352, main_dd=-0.232, conc_cagr=0.508, conc_dd=-0.230)

        payload = run(full, fast, out)
        assert payload["fast_full_gate"] == "partial_fast_only"
        assert payload["portfolios"]["main"]["drift_status"] == "fast_only_pass"
        assert payload["portfolios"]["concentrated"]["drift_status"] == "fast_only_pass"
        assert (out / "fast_full_drift_summary.json").exists()
        assert (out / "fast_full_drift_summary.csv").exists()

    print("fast_full_drift_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
