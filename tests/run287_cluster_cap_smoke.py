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

from tools.run287_cluster_cap_counterfactual import run  # noqa: E402


class Args:
    pass


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "official_main_target_book.csv"
        sidecar = root / "arm_metrics.csv"
        parity = root / "parity.json"
        rows = []
        for date in ["2021-11-30", "2021-12-31", "2022-01-31", "2022-02-28"]:
            rows.extend(
                [
                    {
                        "rebalance_date": date,
                        "ticker": "AAA",
                        "sector": "Information Technology",
                        "target_weight": 0.40,
                        "period_forward_return": -0.10,
                    },
                    {
                        "rebalance_date": date,
                        "ticker": "BBB",
                        "sector": "Information Technology",
                        "target_weight": 0.30,
                        "period_forward_return": -0.05,
                    },
                    {
                        "rebalance_date": date,
                        "ticker": "CCC",
                        "sector": "Energy",
                        "target_weight": 0.20,
                        "period_forward_return": 0.02,
                    },
                    {
                        "rebalance_date": date,
                        "ticker": "CASH",
                        "sector": "Cash",
                        "target_weight": 0.10,
                        "period_forward_return": 0.0,
                    },
                ]
            )
        pd.DataFrame(rows).to_csv(target, index=False)
        pd.DataFrame(
            [
                {
                    "arm": "generated_book_zero_yield",
                    "portfolio": "main",
                    "status": "completed",
                    "cagr": 0.30,
                    "max_dd": -0.30,
                    "avg_cash_weight": 0.10,
                    "ending_capital_usd": 90000.0,
                    "target_pass": False,
                    "start_date": "2021-11-30",
                    "end_date": "2022-02-28",
                },
                {
                    "arm": "generated_book_cash_carry",
                    "portfolio": "main",
                    "status": "completed",
                    "cagr": 0.31,
                    "max_dd": -0.29,
                    "avg_cash_weight": 0.10,
                    "ending_capital_usd": 91000.0,
                    "target_pass": False,
                    "start_date": "2021-11-30",
                    "end_date": "2022-02-28",
                },
            ]
        ).to_csv(sidecar, index=False)
        write_json(parity, {"runner_parity_status": "parity_documented_gap"})
        args = Args()
        args.target_book = str(target)
        args.metric_sidecar = str(sidecar)
        args.parity_summary = str(parity)
        args.output_dir = str(root / "out")
        args.cluster_column = "sector"
        args.cluster_cap = 0.50
        args.starting_capital = 100000.0
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["fullrun_dispatched"] is False
        assert payload["runner_parity_status"] == "parity_documented_gap"
        assert payload["candidate_allowed"] is False
        assert "proxy_mdd_reaches_minus25" in payload
        assert "mdd_benefit_test_underpowered_reason" in payload
        assert payload["max_freed_weight"] > 0.0
        exposure = pd.read_csv(root / "out" / "cluster_exposure_by_date.csv")
        capped_it = exposure[exposure["cluster"].eq("Information Technology")]
        assert not capped_it.empty
        assert capped_it["post_cap_weight"].max() <= 0.50 + 1e-12
        capped_book = pd.read_csv(root / "out" / "capped_main_target_book.csv")
        assert capped_book[capped_book["ticker"].eq("CASH")]["target_weight"].max() > 0.10
        assert (root / "out" / "summary.json").exists()
        assert (root / "out" / "report.md").exists()
        assert (root / "out" / "arm_metrics.csv").exists()
    print("run287_cluster_cap_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
