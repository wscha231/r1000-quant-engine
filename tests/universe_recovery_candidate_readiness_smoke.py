#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_universe_recovery_candidate_readiness import (  # noqa: E402
    classify_universe_recovery_candidate_readiness,
    write_outputs,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_candidate(root: Path, tickers: list[str], *, status: str = "candidate_ready") -> None:
    out = root / "universe_recovery_candidate"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "candidate_universe_recovery.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "name",
                "sector",
                "asset_class",
                "universe_source",
                "recovery_source_path",
                "review_only",
                "production_mutation_allowed",
            ],
        )
        writer.writeheader()
        for ticker in tickers:
            writer.writerow(
                {
                    "ticker": ticker,
                    "name": f"{ticker} Inc",
                    "sector": "Technology",
                    "asset_class": "Equity",
                    "universe_source": "committed_static_IWB_seed",
                    "recovery_source_path": "data_static/iwb_holdings_seed.csv",
                    "review_only": "True",
                    "production_mutation_allowed": "False",
                }
            )
    write_json(
        out / "summary.json",
        {
            "status": status,
            "recommended_recovery_source": "committed_static_IWB_seed",
            "recovery_action": "repair_universe_from_fallback",
            "outputs": {"candidate_csv": str(out / "candidate_universe_recovery.csv")},
        },
    )


def write_price_files(cache: Path, tickers: list[str]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    for ticker in tickers:
        (cache / f"{ticker}.csv").write_text("date,close\n2026-06-15,100\n", encoding="utf-8")


def test_candidate_readiness_passes_when_broad_and_price_covered() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        write_candidate(root, tickers)
        write_price_files(root / "cache_prices", [*tickers, "SPY", "QQQ", "SMH", "SOXX"])

        payload = classify_universe_recovery_candidate_readiness(
            root,
            price_cache=root / "cache_prices",
            min_r1000_base=5,
            min_price_coverage_pct=1.0,
        )
        assert payload["status"] == "candidate_readiness_pass"
        assert payload["ready_for_clean_7y_substrate_repair_review"] is True
        assert payload["production_mutation_allowed"] is False
        assert payload["automatic_repair_allowed"] is False
        assert payload["candidate_price_coverage_pct"] == 1.0
        assert payload["benchmark_coverage"]["pass"] is True

        out = root / "out"
        write_outputs(payload, out)
        assert (out / "summary.json").exists()
        assert (out / "report.md").exists()
        assert (out / "missing_price_tickers.csv").exists()


def test_candidate_readiness_blocks_low_price_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        write_candidate(root, tickers)
        write_price_files(root / "cache_prices", ["AAA", "BBB", "SPY", "QQQ", "SMH", "SOXX"])

        payload = classify_universe_recovery_candidate_readiness(
            root,
            price_cache=root / "cache_prices",
            min_r1000_base=5,
            min_price_coverage_pct=0.8,
        )
        assert payload["status"] == "not_ready"
        assert payload["ready_for_clean_7y_substrate_repair_review"] is False
        assert any("candidate_price_coverage_below_floor" in item for item in payload["blockers"])
        assert payload["candidate_price_missing_count"] == 3


def test_candidate_readiness_none_required_when_recovery_not_needed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_candidate(root, [], status="none_required")

        payload = classify_universe_recovery_candidate_readiness(
            root,
            price_cache=root / "cache_prices",
            min_r1000_base=5,
        )
        assert payload["status"] == "none_required"
        assert payload["blockers"] == []
        assert payload["production_mutation_allowed"] is False
        assert payload["live_trading_enabled"] is False


if __name__ == "__main__":
    test_candidate_readiness_passes_when_broad_and_price_covered()
    test_candidate_readiness_blocks_low_price_coverage()
    test_candidate_readiness_none_required_when_recovery_not_needed()
    print("universe_recovery_candidate_readiness_smoke: PASS")
