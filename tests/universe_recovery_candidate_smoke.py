#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.prepare_universe_recovery_candidate import classify_recovery_candidate, write_outputs  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_seed(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "Name", "Sector", "Asset Class"])
        writer.writeheader()
        for idx in range(count):
            writer.writerow(
                {
                    "ticker": f"T{idx:03d}",
                    "Name": f"Test {idx}",
                    "Sector": "Technology",
                    "Asset Class": "Equity",
                }
            )


def test_recovery_candidate_materializes_static_seed_review_only() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        seed = root / "data_static" / "iwb_holdings_seed.csv"
        write_seed(seed, 5)
        write_json(
            latest / "universe_health" / "universe_source_audit.json",
            {
                "status": "invalid_universe",
                "promotion_allowed": False,
                "recommended_recovery_source": "committed_static_IWB_seed",
                "recommended_recovery_reason": "fixture static seed",
                "recovery_action": "repair_universe_from_fallback",
                "fallback_source_chain": {
                    "static_iwb_seed": {
                        "available": True,
                        "paths": {
                            "data_static": {"path": str(seed)},
                            "data_raw": {"path": str(root / "missing.csv")},
                        },
                    }
                },
            },
        )

        payload = classify_recovery_candidate(latest, min_r1000_base=5)
        assert payload["status"] == "candidate_ready", payload
        assert payload["candidate_ready_for_review"] is True
        assert payload["production_mutation_allowed"] is False
        assert payload["promotion_allowed"] is False
        assert payload["candidate_row_count"] == 5
        assert payload["source_path"] == str(seed)
        out = root / "candidate"
        write_outputs(payload, out)
        rows = list(csv.DictReader((out / "candidate_universe_recovery.csv").open("r", encoding="utf-8")))
        assert len(rows) == 5
        assert rows[0]["universe_source"] == "committed_static_IWB_seed"
        assert rows[0]["production_mutation_allowed"] == "False"
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["candidate_ready_for_review"] is True
        assert "review-only" in (out / "report.md").read_text(encoding="utf-8").lower()


def test_recovery_candidate_none_required_when_universe_passes() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        write_json(
            latest / "universe_health" / "universe_source_audit.json",
            {
                "status": "pass",
                "promotion_allowed": True,
                "recommended_recovery_source": "none_required",
                "recovery_action": "none_required",
            },
        )

        payload = classify_recovery_candidate(latest, min_r1000_base=5)
        assert payload["status"] == "none_required"
        assert payload["candidate_ready_for_review"] is False
        assert payload["candidate_row_count"] == 0


def test_recovery_candidate_blocks_small_fallback() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        seed = root / "data_static" / "iwb_holdings_seed.csv"
        write_seed(seed, 2)
        write_json(
            latest / "universe_health" / "universe_source_audit.json",
            {
                "status": "invalid_universe",
                "promotion_allowed": False,
                "recommended_recovery_source": "committed_static_IWB_seed",
                "recovery_action": "repair_universe_from_fallback",
                "fallback_source_chain": {
                    "static_iwb_seed": {"available": True, "paths": {"data_static": {"path": str(seed)}}}
                },
            },
        )

        payload = classify_recovery_candidate(latest, min_r1000_base=5)
        assert payload["status"] == "not_ready"
        assert payload["candidate_ready_for_review"] is False
        assert "recovery_candidate_below_floor:2<5" in payload["blockers"]


def main() -> int:
    test_recovery_candidate_materializes_static_seed_review_only()
    test_recovery_candidate_none_required_when_universe_passes()
    test_recovery_candidate_blocks_small_fallback()
    print("universe_recovery_candidate_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
