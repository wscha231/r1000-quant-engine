from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_10y_backtest_readiness import run


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_target_book(path: Path, start: str, end: str) -> None:
    dates = pd.date_range(start, end, freq="MS")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [{"rebalance_date": dt.date().isoformat(), "ticker": "AAA", "weight": 1.0} for dt in dates]
    ).to_csv(path, index=False)


def args(root: Path, *, min_years: float = 9.8, output_name: str = "ten_year_backtest_readiness") -> Namespace:
    return Namespace(
        latest_run=str(root / "latest"),
        coverage=str(root / "data_pit" / "free" / "coverage_audit.json"),
        manifest=str(root / "manifests" / "free_data" / "latest_manifest.json"),
        price_cache=str(root / "cache_prices"),
        price_manifest=str(root / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json"),
        min_years=min_years,
        output_dir=str(root / "outputs" / output_name),
        ref="codex/self-sustaining-loop-20260615",
        repo="wscha231/r1000-quant-engine",
    )


def test_ten_year_readiness_distinguishes_proxy_from_official() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        write_target_book(latest / "reports" / "main_monthly_weights.csv", "2019-05-01", "2026-05-01")
        write_target_book(latest / "reports" / "concentrated_strategy_holdings.csv", "2019-05-01", "2026-05-01")
        write_json(
            latest / "broker_replay" / "main" / "metrics.json",
            {"status": "completed", "start_date": "2019-05-01", "end_date": "2026-05-08", "cagr": 0.2},
        )
        write_json(
            latest / "broker_replay" / "concentrated" / "metrics.json",
            {"status": "completed", "start_date": "2019-05-01", "end_date": "2026-05-08", "cagr": 0.3},
        )
        write_json(
            root / "data_pit" / "free" / "coverage_audit.json",
            {
                "readiness": "ready_for_proxy_replay",
                "pit_label": "pit_proxy_universe",
                "sources": {
                    "prices": {
                        "cache_data_file_count": 514,
                        "required_target_book_ticker_count": 386,
                    },
                    "sec_companyfacts": {"status": "missing"},
                },
                "known_gaps": ["historical Russell 1000 membership is not proven PIT-safe in the free tier"],
            },
        )
        write_json(root / "manifests" / "free_data" / "latest_manifest.json", {"generated_at_utc": "2026-05-10T00:00:00Z"})
        write_json(
            root / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json",
            {"start": "2016-01-01", "end": "2026-05-12", "book_ticker_count": 386, "ticker_count": 514},
        )
        payload = run(args(root))
        assert payload["status"] == "proxy_10y_price_ready"
        assert payload["window_slug"] == "ten_year"
        assert payload["proxy_price_ready"] is True
        assert payload["proxy_10y_price_ready"] is True
        assert payload["official_10y_ready"] is False
        assert any("monthly target books" in item for item in payload["blockers"])
        dispatches = payload["workflow_dispatch_payloads"]
        assert [row["plan_id"] for row in dispatches] == ["full_rebuild_ten_year_official_window"]
        assert dispatches[0]["workflow_id"] == "full_rebuild_manual.yml"
        assert dispatches[0]["depends_on_plan_ids"] == []
        assert dispatches[0]["inputs"]["backtest_years"] == "10"
        assert dispatches[0]["inputs"]["portfolio_policy"] == "alphaops_vnext_production"


def test_ten_year_readiness_can_pass_official_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        write_target_book(latest / "reports" / "main_monthly_weights.csv", "2016-01-01", "2026-05-01")
        write_target_book(latest / "reports" / "concentrated_strategy_holdings.csv", "2016-01-01", "2026-05-01")
        for portfolio in ["main", "concentrated"]:
            write_json(
                latest / "broker_replay" / portfolio / "metrics.json",
                {
                    "status": "completed",
                    "start_date": "2016-01-01",
                    "end_date": "2026-05-08",
                    "cagr": 0.3,
                    "valid_for_production": True,
                },
            )
        write_json(
            root / "data_pit" / "free" / "coverage_audit.json",
            {
                "readiness": "ready_for_proxy_replay",
                "pit_label": "pit_safe",
                "sources": {
                    "prices": {
                        "cache_data_file_count": 386,
                        "required_target_book_ticker_count": 386,
                    },
                    "sec_companyfacts": {"status": "available"},
                },
                "known_gaps": [],
            },
        )
        write_json(root / "manifests" / "free_data" / "latest_manifest.json", {"generated_at_utc": "2026-05-10T00:00:00Z"})
        write_json(
            root / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json",
            {"start": "2016-01-01", "end": "2026-05-12", "book_ticker_count": 386, "ticker_count": 386},
        )
        payload = run(args(root))
        assert payload["status"] == "official_10y_ready"
        assert payload["official_window_ready"] is True
        assert payload["workflow_dispatch_payload_count"] == 0
        assert payload["broker_replay"]["window_ready"] is True
        assert (root / "outputs" / "ten_year_backtest_readiness" / "summary.json").exists()
        assert (root / "outputs" / "ten_year_backtest_readiness" / "report.md").exists()


def test_eight_year_readiness_reports_official_window_separately() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        write_target_book(latest / "reports" / "main_monthly_weights.csv", "2018-06-01", "2026-06-01")
        write_target_book(latest / "reports" / "concentrated_strategy_holdings.csv", "2018-06-01", "2026-06-01")
        for portfolio in ["main", "concentrated"]:
            write_json(
                latest / "broker_replay" / portfolio / "metrics.json",
                {
                    "status": "completed",
                    "start_date": "2018-06-01",
                    "end_date": "2026-06-12",
                    "cagr": 0.3,
                    "valid_for_production": True,
                },
            )
        write_json(
            root / "data_pit" / "free" / "coverage_audit.json",
            {
                "readiness": "ready_for_proxy_replay",
                "pit_label": "pit_safe",
                "sources": {
                    "prices": {
                        "cache_data_file_count": 500,
                        "required_target_book_ticker_count": 400,
                    },
                    "sec_companyfacts": {"status": "available"},
                },
                "known_gaps": [],
            },
        )
        write_json(root / "manifests" / "free_data" / "latest_manifest.json", {"generated_at_utc": "2026-06-15T00:00:00Z"})
        write_json(
            root / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json",
            {"start": "2018-05-15", "end": "2026-06-12", "book_ticker_count": 400, "ticker_count": 500},
        )
        payload = run(args(root, min_years=8.0, output_name="eight_year_backtest_readiness"))
        assert payload["status"] == "official_eight_year_ready"
        assert payload["window_slug"] == "eight_year"
        assert payload["official_window_ready"] is True
        assert payload["official_10y_ready"] is False
        assert payload["workflow_dispatch_payload_count"] == 0
        assert payload["price_cache"]["window_ready"] is True
        assert (root / "outputs" / "eight_year_backtest_readiness" / "summary.json").exists()
        assert "8-year" in (root / "outputs" / "eight_year_backtest_readiness" / "report.md").read_text(encoding="utf-8")


def test_eight_year_readiness_emits_bootstrap_dependency_when_price_not_ready() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        write_target_book(latest / "reports" / "main_monthly_weights.csv", "2019-06-01", "2026-06-01")
        write_target_book(latest / "reports" / "concentrated_strategy_holdings.csv", "2019-06-01", "2026-06-01")
        for portfolio in ["main", "concentrated"]:
            write_json(
                latest / "broker_replay" / portfolio / "metrics.json",
                {
                    "status": "completed",
                    "start_date": "2019-06-03",
                    "end_date": "2026-06-12",
                    "cagr": 0.3,
                },
            )
        write_json(
            root / "data_pit" / "free" / "coverage_audit.json",
            {
                "readiness": "manifest_only",
                "pit_label": "pit_proxy_universe",
                "sources": {
                    "prices": {
                        "cache_data_file_count": 50,
                        "required_target_book_ticker_count": 400,
                    },
                    "sec_companyfacts": {"status": "missing"},
                },
                "known_gaps": [],
            },
        )
        write_json(root / "manifests" / "free_data" / "latest_manifest.json", {"generated_at_utc": "2026-06-15T00:00:00Z"})
        write_json(
            root / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json",
            {"start": "2019-06-03", "end": "2026-06-12", "book_ticker_count": 400, "ticker_count": 50},
        )
        payload = run(args(root, min_years=8.0, output_name="eight_year_backtest_readiness"))
        assert payload["status"] == "not_ready"
        assert payload["workflow_dispatch_payload_count"] == 2
        dispatches = payload["workflow_dispatch_payloads"]
        assert [row["plan_id"] for row in dispatches] == [
            "bootstrap_free_data_for_eight_year_window",
            "full_rebuild_eight_year_official_window",
        ]
        assert dispatches[0]["workflow_id"] == "free_data_lake_bootstrap.yml"
        assert dispatches[0]["inputs"]["latest_run"] == "cloud_results/full_rebuild/latest_global_alpha_universe"
        assert dispatches[0]["inputs"]["price_mode"] == "target_books"
        assert dispatches[0]["inputs"]["max_price_tickers"] == "0"
        assert dispatches[1]["depends_on_plan_ids"] == ["bootstrap_free_data_for_eight_year_window"]
        commands = (root / "outputs" / "eight_year_backtest_readiness" / "workflow_dispatch_commands.sh").read_text(encoding="utf-8")
        assert "gh workflow run free_data_lake_bootstrap.yml" in commands
        assert "backtest_years=8" in commands


def main() -> int:
    test_ten_year_readiness_distinguishes_proxy_from_official()
    test_ten_year_readiness_can_pass_official_gate()
    test_eight_year_readiness_reports_official_window_separately()
    test_eight_year_readiness_emits_bootstrap_dependency_when_price_not_ready()
    print("ten year backtest readiness smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
