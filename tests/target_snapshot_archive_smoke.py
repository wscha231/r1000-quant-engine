#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.archive_target_snapshots import build  # noqa: E402


def test_archive_target_snapshots_writes_dated_recommendations_and_books() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        reports.mkdir(parents=True)
        pd.DataFrame({"ticker": ["AAA"], "weight": [1.0], "feature_date": ["2026-05-11"]}).to_csv(latest / "portfolio_latest.csv", index=False)
        pd.DataFrame({"ticker": ["BBB"], "weight": [1.0], "feature_date": ["2026-05-11"]}).to_csv(
            latest / "concentrated_portfolio_latest.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["AAA"], "weight": [1.0]}).to_csv(
            reports / "operating_main_target_book.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["BBB"], "weight": [1.0]}).to_csv(
            reports / "operating_concentrated_target_book.csv", index=False
        )
        (reports / "operating_target_books_summary.json").write_text('{"status":"completed"}', encoding="utf-8")

        out = root / "snapshots"
        payload = build(Namespace(latest_run=str(latest), price_cache=str(root / "cache_prices"), output_dir=str(out), date=""))
        assert payload["status"] == "completed"
        assert payload["snapshot_date"] == "2026-05-11"
        snap = out / "2026-05-11"
        assert (snap / "main_recommendation.csv").exists()
        assert (snap / "concentrated_recommendation.csv").exists()
        assert (snap / "operating_main_target_book.csv").exists()
        assert (snap / "operating_concentrated_target_book.csv").exists()
        assert (snap / "manifest.json").exists()
        assert (out / "latest_manifest.json").exists()


if __name__ == "__main__":
    test_archive_target_snapshots_writes_dated_recommendations_and_books()
    print("target_snapshot_archive_smoke: PASS")
