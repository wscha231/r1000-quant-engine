#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_cross_sector_leadership_rotation_screen import run_screen  # noqa: E402


def _row(
    date: str,
    ticker: str,
    sector: str,
    industry: str,
    *,
    rs: float,
    forward: float,
    leader_tier: str = "DUAL_LEADER",
) -> dict[str, object]:
    return {
        "rebalance_date": date,
        "ticker": ticker,
        "Name": f"{ticker} Inc",
        "sector": sector,
        "industry_group": industry,
        "theme_phase_primary": "clinical_breakout" if "Bio" in industry else "neutral",
        "relative_strength_composite": rs,
        "market_leader_lane_score": rs,
        "oneil_leadership_score": rs,
        "industry_group_strength_score": rs,
        "sector_leadership_score": rs,
        "rs_benchmark_3m": rs,
        "rs_benchmark_6m": rs,
        "mom_3m": rs,
        "leader_tier": leader_tier,
        "period_forward_return": forward,
    }


def test_biotech_rotation_is_detected_without_forward_ranking() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="cross_sector_leadership_smoke_"))
    try:
        rows: list[dict[str, object]] = []
        for date, prefix in [("2021-06-30", "IS"), ("2025-06-30", "OOS")]:
            for i in range(4):
                rows.append(
                    _row(
                        date,
                        f"{prefix}BIO{i}",
                        "Health Care",
                        "Biotechnology",
                        rs=0.90 + i / 100,
                        forward=0.10 + i / 100,
                    )
                )
            for i in range(4):
                rows.append(
                    _row(
                        date,
                        f"{prefix}RET{i}",
                        "Consumer Discretionary",
                        "Retail",
                        rs=0.10 + i / 100,
                        forward=-0.05,
                        leader_tier="LAGGING",
                    )
                )

        input_path = tmp / "target_book.csv"
        pd.DataFrame(rows).to_csv(input_path, index=False)
        out_dir = tmp / "out"
        summary = run_screen(input_path, out_dir, oos_start="2024-06-03", min_group_count=3, leader_quantile=0.60)

        assert summary["screen_pass"] is True
        assert summary["used_forward_return_in_ranking"] is False
        assert summary["forward_returns_audit_only"] is True
        assert summary["production_activation_allowed"] is False
        assert summary["thesis_bucket_counts"]["BIOTECH_PLATFORM"] == 8

        stats = pd.read_csv(out_dir / "group_leadership_stats.csv")
        biotech = stats[
            (stats["group_field"] == "industry_group")
            & (stats["group_value"] == "Biotechnology")
            & (stats["split"] == "oos")
        ]
        assert not biotech.empty
        assert float(biotech.iloc[0]["mean_forward_label"]) > 0

        payload = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert payload["status"] == "screen_passed"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_biotech_rotation_is_detected_without_forward_ranking()
    print("cross_sector_leadership_rotation_screen_smoke passed")
