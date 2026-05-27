#!/usr/bin/env python3
"""Smoke checks for the Market Leader historical broker-ledger sidecar."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price(cache: Path, ticker: str, start: float, daily_ret: float) -> None:
    dates = pd.date_range("2024-01-02", "2025-08-29", freq="B")
    values = [start * ((1.0 + daily_ret) ** i) for i in range(len(dates))]
    pd.DataFrame({"date": dates, "Adj Close": values, "Close": values, "Open": values}, index=dates).to_parquet(cache / px_cache_name(ticker))


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dt in ("2025-04-30", "2025-05-30", "2025-06-30", "2025-07-31"):
        for ticker, name, sector, ret, dv, strength in [
            ("DUAL", "Dual Leader", "Technology", 0.10, 500_000_000, 2.0),
            ("SPYONLY", "SPY Only", "Industrials", 0.03, 500_000_000, 1.0),
            ("LOWLIQ", "Low Liquidity", "Technology", 0.20, 1_000_000, 1.5),
            ("LAGG", "Lagging", "Technology", -0.05, 500_000_000, -1.0),
        ]:
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "Name": name,
                    "sector": sector,
                    "industry_group": sector,
                    "subindustry": sector,
                    "period_forward_return": ret,
                    "score": 1.0,
                    "industry_group_strength_score": strength,
                    "industry_within_leader_rank": strength,
                    "oneil_leadership_score": strength,
                    "sub_industry_rs_score": strength,
                    "industry_leader_gap": strength,
                    "future_winner_confirmation_score": 1.0 if ticker != "LAGG" else 0.0,
                    "quality_growth_score": 0.8,
                    "entry_quality_score": 0.7,
                    "dollar_vol_20d": dv,
                    "market_cap_live": 50_000_000_000,
                    "price_above_ma50": 1 if ticker != "LAGG" else 0,
                    "price_above_ma200": 1,
                    "sec_form4_cluster_buy_score": 0.5 if ticker == "DUAL" else "",
                }
            )
    return rows


def run_tool(root: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(ROOT / "tools" / "run_market_leader_challenger.py"),
        "--latest-run",
        str(root / "latest"),
        "--price-cache",
        str(root / "cache_prices"),
        "--output-dir",
        str(root / "out"),
        "--allow-missing-baseline-lock",
        "--default-only",
    ]
    if extra:
        cmd.extend(extra)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def test_market_leader_challenger_builds_historical_target_books() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest" / "reports"
        cache = root / "cache_prices"
        latest.mkdir(parents=True)
        cache.mkdir()
        for ticker, ret in {"SPY": 0.0005, "QQQ": 0.0010, "DUAL": 0.0018, "SPYONLY": 0.0007, "LOWLIQ": 0.0020, "LAGG": -0.0005}.items():
            write_price(cache, ticker, 100, ret)
        pd.DataFrame(candidate_rows()).to_csv(latest / "candidate_replay_book.csv", index=False)

        proc = run_tool(root)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        out = root / "out"
        main_book = pd.read_csv(out / "main_target_book.csv")
        conc_book = pd.read_csv(out / "concentrated_target_book.csv")
        summary = pd.read_json(out / "summary.json", typ="series")
        assert summary["status"] == "completed"
        assert main_book["rebalance_date"].nunique() >= 3
        assert conc_book["rebalance_date"].nunique() >= 3
        assert "target_weight" in main_book.columns
        assert set(conc_book.loc[conc_book["ticker"].ne("CASH"), "leader_tier"]) == {"DUAL_LEADER"}
        assert (out / "broker_replay" / "main_N15_cap15_sub50_theme70" / "metrics.json").exists()
        rejected = pd.read_csv(out / "rejected_leaders.csv")
        assert rejected["rejection_reason"].astype(str).str.len().min() > 0
        stability = pd.read_csv(out / "parameter_stability.csv")
        assert not stability.empty
        churn = pd.read_csv(out / "holding_churn_diagnostics.csv")
        assert {"monthly_turnover_proxy", "avg_name_overlap", "median_holding_months"}.issubset(churn.columns)
        cost = pd.read_csv(out / "cost_sensitivity.csv")
        assert set(cost["cost_bps"].round(0).astype(int)) >= {25, 50, 75, 100}


def test_latest_only_is_blocked_from_broker_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        cache = root / "cache_prices"
        latest.mkdir()
        cache.mkdir()
        pd.DataFrame(candidate_rows()[:4]).assign(rebalance_date="2025-07-31").to_csv(latest / "scored_latest.csv", index=False)
        proc = run_tool(root)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        summary = pd.read_json(root / "out" / "summary.json", typ="series")
        assert summary["status"] == "blocked"
        assert summary["metric_mode"] == "DO_NOT_USE"


def test_no_feature_store_mutation_or_duplicate_seed_path() -> None:
    tool = (ROOT / "tools" / "run_market_leader_challenger.py").read_text(encoding="utf-8")
    engine = (ROOT / "r1000_market_leader_engine.py").read_text(encoding="utf-8")
    for forbidden in ["add_total_score_columns", "hard_sanitize", "keep_cols", "score_total ="]:
        assert forbidden not in tool
        assert forbidden not in engine
    assert not (ROOT / "data" / "universe" / "r1000_offline_seed.csv").exists()
    assert (ROOT / "data_static" / "iwb_holdings_seed.csv").exists()


def main() -> int:
    test_market_leader_challenger_builds_historical_target_books()
    test_latest_only_is_blocked_from_broker_metrics()
    test_no_feature_store_mutation_or_duplicate_seed_path()
    print("market_leader_challenger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
