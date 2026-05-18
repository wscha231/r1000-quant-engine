#!/usr/bin/env python3
"""Smoke checks for reviewed SEC 13F manager universe list generation."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_sec_13f_manager_universe import run  # noqa: E402


def test_manager_universe_builds_verified_priority_cik_tokens() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        universe = root / "managers.csv"
        ciks = root / "manager_ciks.txt"
        summary_path = root / "summary.json"
        pd.DataFrame(
            [
                {
                    "label": "SITUATIONAL",
                    "manager_name": "Situational Awareness LP",
                    "cik10": "2045724",
                    "active": "true",
                    "verified_cik": "true",
                    "user_priority": "1",
                    "performance_26q1": "0.3642",
                    "aum_13f_usd": "13680000000",
                },
                {
                    "label": "UNVERIFIED",
                    "manager_name": "Unverified Manager",
                    "cik10": "123",
                    "active": "true",
                    "verified_cik": "false",
                    "user_priority": "2",
                },
            ]
        ).to_csv(universe, index=False)

        payload = run(
            argparse.Namespace(
                input=str(universe),
                output_ciks=str(ciks),
                output_summary=str(summary_path),
                extra="DUQUESNE:0001536411",
                min_aum_usd=0.0,
                max_managers=10,
                require_verified=True,
            )
        )

        assert payload["status"] == "completed"
        text = ciks.read_text(encoding="utf-8")
        assert "SITUATIONAL:0002045724" in text
        assert "DUQUESNE:0001536411" in text
        assert "UNVERIFIED" not in text
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["annual_review_required"] is True


if __name__ == "__main__":
    test_manager_universe_builds_verified_priority_cik_tokens()
    print("sec_13f_manager_universe_smoke: PASS")
