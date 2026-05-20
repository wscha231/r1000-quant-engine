from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_features import load_sec_evidence_overlay  # noqa: E402


def test_form4_loader_rebuilds_tiny_latest_from_canonical_transactions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        outputs = root / "outputs"
        latest_dir = outputs / "sec_ownership_signals"
        latest_dir.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "latest_available_from": "2024-04-03T00:00:00Z",
                    "early_evidence_score": 0.0,
                    "evidence_confidence_score": 0.0,
                }
            ]
        ).to_csv(latest_dir / "form4_latest.csv", index=False)

        pit = root / "data_pit" / "sec"
        pit.mkdir(parents=True)
        rows = []
        for i in range(301):
            rows.append(
                {
                    "issuer_ticker": f"T{i:03d}",
                    "reporting_owner_cik": f"{i:010d}",
                    "officer_title": "Chief Executive Officer",
                    "is_director": False,
                    "is_officer": True,
                    "transaction_date": "2026-05-18",
                    "accepted_at": "2026-05-19T20:00:00Z",
                    "available_from": "2026-05-19T20:00:00Z",
                    "transaction_code": "P",
                    "transaction_value": 1_000_000.0,
                }
            )
        pd.DataFrame(rows).to_parquet(pit / "form4_transactions.parquet", index=False)

        overlay = load_sec_evidence_overlay(base_dir=outputs, min_form4_signal_tickers=300)
        assert overlay["ticker"].nunique() >= 301
        assert "early_evidence_score" in overlay.columns

        health_path = outputs / "full_rebuild_logs" / "sec_evidence_overlay_health.json"
        assert health_path.exists()
        health = json.loads(health_path.read_text(encoding="utf-8"))
        assert health["categories"]["ownership"]["rebuilt_from_canonical"] is True


if __name__ == "__main__":
    test_form4_loader_rebuilds_tiny_latest_from_canonical_transactions()
    print("sec_overlay_consistency_smoke: PASS")
