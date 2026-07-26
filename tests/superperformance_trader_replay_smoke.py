#!/usr/bin/env python3
"""Smoke checks for superperformance trade replay sidecar."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price(cache: Path, ticker: str, trend: float, start: float = 50.0) -> None:
    # The last synthetic target is dated 2025-04-30 and the broker contract
    # fills at the next close, so the fixture must include post-signal prices.
    dates = pd.bdate_range("2024-01-02", "2025-05-02")
    values = [start * ((1.0 + trend) ** i) for i in range(len(dates))]
    volume = [1_000_000] * len(dates)
    frame = pd.DataFrame(
        {
            "Open": values,
            "Close": values,
            "Adj Close": values,
            "Volume": volume,
        },
        index=dates,
    )
    frame.to_parquet(cache / px_cache_name(ticker))


def candidate_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dt in ("2025-01-31", "2025-02-28", "2025-03-31"):
        for ticker, sector, strength, dv in [
            ("MU", "Semiconductors", 1.0, 900_000_000),
            ("WDC", "Semiconductors", 0.9, 700_000_000),
            ("ON", "Semiconductors", 0.8, 600_000_000),
            ("PR", "Energy", 0.1, 400_000_000),
            ("ETR", "Utilities", 0.1, 300_000_000),
            ("PEG", "Utilities", 0.1, 300_000_000),
            ("LEAK", "Technology", 1.0, 500_000_000),
        ]:
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "Name": f"{ticker} Corp",
                    "sector": sector,
                    "industry_group": sector,
                    "subindustry": sector,
                    "score": strength,
                    "oneil_leadership_score": strength,
                    "industry_group_strength_score": strength,
                    "future_winner_confirmation_score": strength,
                    "portfolio_monster_early_score": strength,
                    "evidence_fusion_score": strength,
                    "smart_money_shadow_score": strength,
                    "sec_combined_evidence_score": strength,
                    "institutional_evidence_score": strength,
                    "etf_holdings_score": strength,
                    "evidence_confidence_score": 1.0 if strength > 0 else 0.0,
                    "latest_available_from": "2026-01-15" if ticker == "LEAK" else "2025-01-15",
                    "macro_risk_score": 0.0,
                    "liquidity_capacity_score": 1.0,
                    "dollar_vol_20d": dv,
                }
            )
    return rows


def run_tool(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "run_superperformance_trader_replay.py"),
            "--latest-run",
            str(root / "latest"),
            "--price-cache",
            str(root / "cache_prices"),
            "--output-dir",
            str(root / "out"),
            "--cost-bps",
            "25",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_superperformance_replay_builds_dated_buy_sell_books() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reports = root / "latest" / "reports"
        cache = root / "cache_prices"
        reports.mkdir(parents=True)
        cache.mkdir()
        for ticker, trend in {
            "SPY": 0.0007,
            "QQQ": 0.0010,
            "MU": 0.0040,
            "WDC": 0.0036,
            "ON": 0.0032,
            "PR": -0.0015,
            "ETR": -0.0010,
            "PEG": -0.0010,
            "LEAK": 0.0040,
        }.items():
            write_price(cache, ticker, trend)
        pd.DataFrame(candidate_rows()).to_csv(reports / "candidate_replay_book.csv", index=False)

        proc = run_tool(root)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        out = root / "out"
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["status"] == "completed"
        signals = pd.read_csv(out / "setup_signals.csv")
        assert {"evidence_component", "monster_component", "macro_risk_component", "evidence_guard"}.issubset(signals.columns)
        assert signals.loc[signals["ticker"].eq("MU"), "evidence_component"].max() > 0
        assert signals.loc[signals["ticker"].eq("LEAK"), "evidence_guard"].astype(str).str.contains("evidence_available_after_signal").any()
        entries = pd.read_csv(out / "entry_events.csv")
        assert {"evidence_component", "monster_component", "macro_risk_component"}.issubset(entries.columns)
        assert "LEAK" not in set(entries["ticker"].astype(str))
        assert {"MU", "WDC", "ON"}.issubset(set(entries["ticker"].astype(str)))
        main_book = pd.read_csv(out / "main_target_book.csv")
        conc_book = pd.read_csv(out / "concentrated_target_book.csv")
        assert not main_book["selection_reason"].astype(str).str.contains("target_refresh").any()
        assert not conc_book["selection_reason"].astype(str).str.contains("target_refresh").any()
        assert {"MU", "WDC", "ON"}.issubset(set(main_book["ticker"].astype(str)))
        assert not {"PR", "ETR", "PEG"}.intersection(set(conc_book["ticker"].astype(str)))
        conc_metrics = json.loads((out / "broker_replay" / "concentrated" / "metrics.json").read_text(encoding="utf-8"))
        assert conc_metrics["metric_mode"] == "broker_ledger_next_close"
        assert conc_metrics["target_book_filter_source"] == "disabled_explicit"


def main() -> int:
    test_superperformance_replay_builds_dated_buy_sell_books()
    print("superperformance_trader_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
