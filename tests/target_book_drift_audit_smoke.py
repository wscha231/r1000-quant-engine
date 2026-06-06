#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from argparse import Namespace
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_target_book_drift import build_payload  # noqa: E402


def write_book(root: Path, portfolio: str, rows: list[dict]) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    name = "operating_main_target_book.csv" if portfolio == "main" else "operating_concentrated_target_book.csv"
    pd.DataFrame(rows).to_csv(reports / name, index=False)


def write_candidate(root: Path, rows: list[dict]) -> None:
    out = root / "sec_enriched_candidate_replay"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "candidate_replay_book_sec_enriched.csv", index=False)


def write_metrics(root: Path, portfolio: str, cagr: float, max_dd: float) -> None:
    out = root / "broker_replay" / portfolio
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(
        (
            "{"
            f'"cagr": {cagr}, "max_dd": {max_dd}, "sharpe": 1.0, '
            '"avg_cash_weight": 0.2, "metric_mode": "broker_ledger_next_close", '
            '"valid_for_production": true'
            "}"
        ),
        encoding="utf-8",
    )


def test_target_book_drift_audit_detects_candidate_and_target_drift() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        current = root / "current"
        out = root / "audit"
        candidate_base = [
            {"rebalance_date": "2021-01-29", "ticker": "AAA", "score": 1.0, "evidence_fusion_score": 0.1},
            {"rebalance_date": "2021-01-29", "ticker": "BBB", "score": 0.8, "evidence_fusion_score": 0.2},
        ]
        candidate_current = [
            {"rebalance_date": "2021-01-29", "ticker": "AAA", "score": 0.7, "evidence_fusion_score": 0.1},
            {"rebalance_date": "2021-01-29", "ticker": "BBB", "score": 0.9, "evidence_fusion_score": 0.25},
        ]
        write_candidate(baseline, candidate_base)
        write_candidate(current, candidate_current)
        for portfolio in ["main", "concentrated"]:
            write_book(
                baseline,
                portfolio,
                [
                    {"rebalance_date": "2021-01-29", "ticker": "AAA", "target_weight": 0.6, "period_forward_return": 0.2},
                    {"rebalance_date": "2021-01-29", "ticker": "BBB", "target_weight": 0.4, "period_forward_return": -0.1},
                ],
            )
            write_book(
                current,
                portfolio,
                [
                    {"rebalance_date": "2021-01-29", "ticker": "AAA", "target_weight": 0.2, "period_forward_return": 0.2},
                    {"rebalance_date": "2021-01-29", "ticker": "BBB", "target_weight": 0.8, "period_forward_return": -0.1},
                ],
            )
            write_metrics(baseline, portfolio, cagr=0.4, max_dd=-0.2)
            write_metrics(current, portfolio, cagr=0.3, max_dd=-0.3)

        payload = build_payload(
            Namespace(
                baseline_run=str(baseline),
                current_run=str(current),
                output_dir=str(out),
                cutoff_date="2021-12-31",
                top_n=10,
            )
        )

        assert payload["candidate_score_drift"]["keys_equal"] is True
        assert payload["candidate_score_drift"]["top_changed_columns"][0]["column"] == "score"
        main = payload["portfolios"]["main"]
        assert main["changed_row_count"] == 2
        assert round(main["total_abs_delta_weight"], 6) == 0.8
        assert round(main["proxy_delta_return_sum"], 6) == -0.12
        assert round(main["metrics"]["cagr"]["delta"], 6) == -0.1


if __name__ == "__main__":
    test_target_book_drift_audit_detects_candidate_and_target_drift()
    print("target book drift audit smoke passed")
