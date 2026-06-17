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

from tools.build_proxy_10y_universe_substrate import classify_proxy_10y_universe_substrate, write_outputs  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_candidate(root: Path, tickers: list[str]) -> None:
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
            "status": "candidate_ready",
            "recommended_recovery_source": "committed_static_IWB_seed",
            "recovery_action": "repair_universe_from_fallback",
            "outputs": {"candidate_csv": str(out / "candidate_universe_recovery.csv")},
        },
    )
    write_json(
        root / "universe_recovery_candidate_readiness" / "summary.json",
        {
            "status": "candidate_readiness_pass",
            "ready_for_clean_7y_substrate_repair_review": True,
        },
    )


def write_price(cache: Path, ticker: str, *, start: str = "2016-08-26", end: str = "2026-06-15") -> None:
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"{ticker}.csv").write_text(f"date,close\n{start},10\n{end},20\n", encoding="utf-8")


def test_proxy_10y_universe_substrate_passes_review_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        write_candidate(root, tickers)
        for ticker in [*tickers, "SPY", "QQQ", "SMH", "SOXX"]:
            write_price(root / "cache_prices", ticker)

        payload, rows = classify_proxy_10y_universe_substrate(
            root,
            price_cache=root / "cache_prices",
            start_date="2016-08-26",
            end_date="2016-10-31",
            min_membership_count=5,
            min_price_coverage_pct=1.0,
        )
        assert payload["status"] == "proxy_10y_universe_ready", payload
        assert payload["pit_label"] == "pit_proxy_universe"
        assert payload["official_russell_1000"] is False
        assert payload["promotion_allowed"] is False
        assert payload["production_mutation_allowed"] is False
        assert payload["ready_for_proxy_10y_rebuild_review"] is True
        assert len(rows) == 3
        assert all(row["proxy_month_pass"] for row in rows)

        out = root / "out"
        write_outputs(payload, rows, out)
        assert (out / "summary.json").exists()
        assert (out / "proxy_universe_membership_by_month.csv").exists()
        assert (out / "report.md").exists()


def test_proxy_10y_universe_substrate_blocks_missing_benchmark() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        write_candidate(root, tickers)
        for ticker in [*tickers, "SPY", "QQQ", "SMH"]:
            write_price(root / "cache_prices", ticker)

        payload, _rows = classify_proxy_10y_universe_substrate(
            root,
            price_cache=root / "cache_prices",
            start_date="2016-08-26",
            end_date="2016-10-31",
            min_membership_count=5,
            min_price_coverage_pct=1.0,
        )
        assert payload["status"] == "not_ready"
        assert "required_benchmark_price_missing:SOXX" in payload["blockers"]
        assert payload["official_russell_1000"] is False


def test_proxy_10y_universe_substrate_requires_candidate_readiness() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        write_candidate(root, tickers)
        write_json(root / "universe_recovery_candidate_readiness" / "summary.json", {"status": "not_ready"})
        for ticker in [*tickers, "SPY", "QQQ", "SMH", "SOXX"]:
            write_price(root / "cache_prices", ticker)

        payload, _rows = classify_proxy_10y_universe_substrate(
            root,
            price_cache=root / "cache_prices",
            start_date="2016-08-26",
            end_date="2016-10-31",
            min_membership_count=5,
        )
        assert payload["status"] == "not_ready"
        assert "universe_recovery_candidate_readiness_status:not_ready" in payload["blockers"]
        assert payload["allowed_uses"] == ["diagnostics"]


if __name__ == "__main__":
    test_proxy_10y_universe_substrate_passes_review_only()
    test_proxy_10y_universe_substrate_blocks_missing_benchmark()
    test_proxy_10y_universe_substrate_requires_candidate_readiness()
    print("proxy_10y_universe_substrate_smoke: PASS")
