#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import csv
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_universe_health_audit import build_payload  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_audit(root: Path, latest: Path, min_base: int = 400) -> dict:
    output = root / "audit" / "universe_health"
    args = Namespace(
        latest_run=str(latest),
        price_cache=str(root / "cache_prices"),
        output_dir=str(output),
        min_r1000_base=min_base,
        universe_mode="global_alpha_universe",
        strict=False,
    )
    return build_payload(args)


def test_universe_health_allows_broad_r1000_base() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        reports.mkdir(parents=True)
        cache.mkdir(parents=True)
        rows = [
            {
                "ticker": f"T{i:04d}",
                "feature_date": "2026-06-15",
                "universe_source": "current_constituents_proxy_static_seed",
                "cik10": f"{i:010d}",
            }
            for i in range(450)
        ]
        write_csv(latest / "scored_latest.csv", rows)
        write_csv(
            reports / "candidate_replay_book.csv",
            [
                {
                    "ticker": f"T{i:04d}",
                    "rebalance_date": "2026-06-15",
                    "universe_source": "current_constituents_proxy_static_seed",
                }
                for i in range(470)
            ],
        )
        for ticker in ["T0000", "T0001", "T0002"]:
            (cache / f"{ticker}.csv").write_text("date,close\n2026-06-15,1\n", encoding="utf-8")

        payload = run_audit(root, latest)
        assert payload["status"] == "pass"
        assert payload["verdict_code"] == "PASS"
        assert payload["promotion_allowed"] is True
        assert payload["hard_fail_before_expensive_rebuild"] is False
        assert payload["monthly_universe_health_pass"] is True
        assert payload["min_monthly_membership_count"] == 450
        assert payload["min_monthly_scored_count"] == 450
        assert payload["r1000_base_count"] == 450
        assert (root / "audit" / "universe_health" / "universe_source_audit.json").exists()
        assert (root / "audit" / "universe_health" / "universe_fallback_decision.md").exists()
        assert (root / "audit" / "universe_health" / "universe_membership_by_month.csv").exists()
        assert (root / "audit" / "universe_health" / "tradeable_universe_by_month.csv").exists()


def test_universe_health_blocks_starved_universe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        reports.mkdir(parents=True)
        rows = [
            {
                "ticker": f"L{i:04d}",
                "feature_date": "2026-06-15",
                "universe_source": "leader_rescue_only",
            }
            for i in range(259)
        ]
        write_csv(latest / "scored_latest.csv", rows)
        write_csv(
            reports / "candidate_replay_book.csv",
            [
                {
                    "ticker": f"L{i:04d}",
                    "rebalance_date": "2026-06-15",
                    "universe_source": "leader_rescue_only",
                }
                for i in range(300)
            ],
        )

        payload = run_audit(root, latest)
        assert payload["status"] == "invalid_universe"
        assert payload["verdict_code"] == "INVALID_UNIVERSE"
        assert payload["promotion_allowed"] is False
        assert payload["hard_fail_before_expensive_rebuild"] is True
        assert payload["monthly_universe_health_pass"] is False
        assert payload["r1000_base_count"] == 0
        assert any("below floor" in item for item in payload["blockers"])
        assert any("monthly universe health below floor" in item for item in payload["blockers"])
        decision = (root / "audit" / "universe_health" / "universe_fallback_decision.md").read_text(encoding="utf-8")
        assert "DO_NOT_PROMOTE" in decision
        assert "hard_fail_before_expensive_rebuild" in decision
        summary = load_json(root / "audit" / "universe_health" / "summary.json")
        assert summary["production_mutation_allowed"] is False


def test_universe_health_blocks_unclear_source_even_when_count_is_broad() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        reports.mkdir(parents=True)
        rows = [
            {
                "ticker": f"U{i:04d}",
                "feature_date": "2026-06-15",
            }
            for i in range(450)
        ]
        write_csv(latest / "scored_latest.csv", rows)
        write_csv(
            reports / "candidate_replay_book.csv",
            [
                {
                    "ticker": f"U{i:04d}",
                    "rebalance_date": "2026-06-15",
                }
                for i in range(450)
            ],
        )

        payload = run_audit(root, latest)
        assert payload["status"] == "invalid_universe"
        assert payload["source_unclear"] is True
        assert payload["hard_fail_before_expensive_rebuild"] is True
        assert any("source is missing or unclear" in item for item in payload["blockers"])


if __name__ == "__main__":
    test_universe_health_allows_broad_r1000_base()
    test_universe_health_blocks_starved_universe()
    test_universe_health_blocks_unclear_source_even_when_count_is_broad()
    print("universe_health_audit_smoke: PASS")
