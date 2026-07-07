#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run287_financial_proxy_screen import run  # noqa: E402


class Args:
    pass


def test_financial_proxy_screen_outputs_research_only_candidate_block() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rows = []
        for idx in range(80):
            oos = idx >= 50
            signal = float(idx % 10)
            rows.append(
                {
                    "rebalance_date": "2025-01-31" if oos else "2022-01-31",
                    "ticker": f"T{idx:03d}",
                    "Name": f"Ticker {idx}",
                    "sector": "Technology",
                    "industry_group": "Semiconductors",
                    "actual_results_score": signal,
                    "eps_revision_score": signal,
                    "sales_growth_yoy": signal,
                    "period_forward_return": signal / 100.0,
                }
            )
        inp = root / "candidate.csv"
        out = root / "out"
        pd.DataFrame(rows).to_csv(inp, index=False)
        args = Args()
        args.input = str(inp)
        args.output_dir = str(out)
        args.oos_start = "2024-07-01"
        args.min_rows = 10
        args.min_oos_high_count = 3
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["candidate_allowed"] is False
        assert payload["fullrun_dispatched"] is False
        assert payload["used_forward_return_in_ranking"] is False
        assert payload["production_promotion_allowed"] is False
        assert "actual_results_score" in payload["signal_columns_checked"]
        assert (out / "summary.json").exists()
        assert (out / "signal_stats.csv").exists()
        assert (out / "report.md").exists()


def main() -> int:
    test_financial_proxy_screen_outputs_research_only_candidate_block()
    print("run287_financial_proxy_screen_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
