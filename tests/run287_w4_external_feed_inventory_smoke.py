#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run287_w4_external_feed_inventory import run  # noqa: E402


class Args:
    pass


def test_w4_external_feed_inventory_marks_sec_sources_usable_without_guidance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        form4 = root / "form4.parquet"
        sec13f = root / "13f.parquet"
        pd.DataFrame(
            [
                {
                    "issuer_ticker": "NVDA",
                    "transaction_date": "2025-01-02",
                    "filing_date": "2025-01-04",
                    "available_from": "2025-01-04T21:00:00Z",
                    "transaction_code": "P",
                }
            ]
        ).to_parquet(form4, index=False)
        pd.DataFrame(
            [
                {
                    "manager_cik": "0000001",
                    "report_period": "2024-12-31",
                    "filing_date": "2025-02-14",
                    "available_from": "2025-02-14T21:00:00Z",
                    "ticker_mapped": "NVDA",
                    "market_value_usd": 1000000.0,
                }
            ]
        ).to_parquet(sec13f, index=False)
        args = Args()
        args.form4_path = str(form4)
        args.sec13f_path = str(sec13f)
        args.earnings_revision_signals = str(root / "missing.parquet")
        args.output_dir = str(root / "out")
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["research_only"] is True
        assert payload["candidate_allowed"] is False
        assert payload["hook_allowed"] is False
        assert payload["fullrun_dispatched"] is False
        assert payload["production_promotion_allowed"] is False
        assert payload["usable_external_source_count"] == 2
        assert payload["true_revision_guidance_ready"] is False
        assert payload["decision_label"] == "sec_w4_sources_available_but_guidance_feed_missing"
        assert (root / "out" / "summary.json").exists()
        assert (root / "out" / "report.md").exists()


def main() -> int:
    test_w4_external_feed_inventory_marks_sec_sources_usable_without_guidance()
    print("run287_w4_external_feed_inventory_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
