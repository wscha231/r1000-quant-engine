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

from tools.run287_survivorship_bound import run  # noqa: E402


class Args:
    pass


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        book_root = root / "books"
        candidate = root / "candidate.csv"
        official = root / "official_metrics.json"
        sidecar = root / "sidecar.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-31",
                    "ticker": "AAA",
                    "px": 10.0,
                    "source_universe": "current_constituents_proxy",
                },
                {
                    "rebalance_date": "2026-02-28",
                    "ticker": "BBB",
                    "px": 20.0,
                    "source_universe": "current_constituents_proxy",
                },
            ]
        ).to_csv(candidate, index=False)
        rows = [
            {
                "rebalance_date": "2026-01-31",
                "ticker": "BBB",
                "target_weight": 0.5,
                "period_forward_return": 0.10,
                "source_universe": "current_constituents_proxy",
            },
            {
                "rebalance_date": "2026-01-31",
                "ticker": "AAA",
                "target_weight": 0.5,
                "period_forward_return": 0.02,
                "source_universe": "current_constituents_proxy",
            },
        ]
        for portfolio in ["main", "concentrated"]:
            path = book_root / f"official_{portfolio}_target_book.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_csv(path, index=False)
        write_json(
            official,
            {
                "portfolios": {
                    "main": {"cagr": 0.34, "max_dd": -0.253},
                    "concentrated": {"cagr": 0.48, "max_dd": -0.23},
                }
            },
        )
        pd.DataFrame(
            [
                {
                    "arm": "generated_book_cash_carry",
                    "portfolio": "main",
                    "metric_mode": "broker_ledger_next_close_cash_carry",
                    "cagr": 0.341,
                    "max_dd": -0.251,
                },
                {
                    "arm": "generated_book_cash_carry",
                    "portfolio": "concentrated",
                    "metric_mode": "broker_ledger_next_close_cash_carry",
                    "cagr": 0.481,
                    "max_dd": -0.23,
                },
            ]
        ).to_csv(sidecar, index=False)
        args = Args()
        args.candidate_book = str(candidate)
        args.book_root = str(book_root)
        args.official_metrics = str(official)
        args.sidecar_arm_metrics = str(sidecar)
        args.output_dir = str(root / "out")
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["fullrun_dispatched"] is False
        assert payload["label"] == "proxy"
        assert payload["unmeasured_component"] == "delisted_exclusion"
        assert payload["survivorship_dominant_component"] == "delisted_exclusion"
        assert payload["survivorship_dominant_component_measured"] is False
        assert payload["survivorship_zero_bound_quote_allowed"] is False
        assert payload["portfolios"]["main"]["metric_mode"] == "broker_ledger_next_close_cash_carry"
        assert payload["portfolios"]["main"]["late_inclusion_violation_rows"] == 1
        assert payload["survivorship_inflation_estimate_cagr_pp"] > 0.0
        assert (root / "out" / "membership_delta.csv").exists()
        assert (root / "out" / "report.md").exists()
    print("run287_survivorship_bound_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
