#!/usr/bin/env python3
"""Smoke tests for the standalone OOS lock audit sidecar."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_oos_lock_audit import run  # noqa: E402


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def seed_portfolio(root: Path, portfolio: str, *, oos_end_equity: float) -> None:
    broker = root / "broker_replay" / portfolio
    rows = [
        ("2018-06-01", 100000.0),
        ("2020-01-02", 125000.0),
        ("2022-01-03", 160000.0),
        ("2024-06-28", 210000.0),
        ("2024-07-01", 210000.0),
        ("2025-01-02", (210000.0 + oos_end_equity) / 2.0),
        ("2026-06-12", oos_end_equity),
    ]
    write_text(
        broker / "equity_curve.csv",
        "date,equity_usd,cash_usd,cash_weight,stock_value_usd,position_count,fill_mode\n"
        + "".join(f"{date},{equity},10000,0.1,{equity - 10000},3,next_close\n" for date, equity in rows),
    )
    write_text(broker / "trades.csv", "date,ticker,side,fee_usd,gross_value\n")
    write_text(
        broker / "metrics.json",
        json.dumps({"status": "completed", "metric_mode": "broker_ledger_next_close"}, indent=2),
    )


def write_config(path: Path) -> None:
    write_text(
        path,
        "\n".join(
            [
                "schema_version: oos-lock-v1",
                "oos_start: 2024-07-01",
                "oos2_start: 2023-01-01",
                "max_degradation_floor_pp: 5.0",
                "max_degradation_is_fraction: 0.20",
                "max_oos_is_cagr_ratio: 3.0",
                "min_oos_trading_days: 3",
                "baseline_is_cagr:",
                "  main: 0.25",
                "  concentrated: 0.30",
                "",
            ]
        ),
    )


def test_oos_lock_audit_passes_when_holdout_does_not_degrade() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        seed_portfolio(latest, "main", oos_end_equity=260000.0)
        seed_portfolio(latest, "concentrated", oos_end_equity=285000.0)
        config = root / "oos_lock.yaml"
        write_config(config)
        out = root / "out"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out), config=str(config), portfolios="main,concentrated"))
        assert payload["status"] == "pass"
        assert payload["lock_pass"] is True
        assert payload["production_activation_allowed"] is False
        assert payload["portfolios"]["main"]["oos_degradation_pp"] <= payload["portfolios"]["main"]["max_allowed_degradation_pp"]
        assert (out / "oos_report.json").exists()
        assert (out / "report.md").exists()


def test_oos_lock_audit_blocks_large_holdout_degradation() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        seed_portfolio(latest, "main", oos_end_equity=150000.0)
        seed_portfolio(latest, "concentrated", oos_end_equity=285000.0)
        config = root / "oos_lock.yaml"
        write_config(config)
        payload = run(Namespace(latest_run=str(latest), output_dir=str(root / "out"), config=str(config), portfolios="main,concentrated"))
        assert payload["status"] == "fail"
        assert payload["lock_pass"] is False
        assert "oos_cagr_degradation_above_lock" in payload["portfolios"]["main"]["failures"]
        assert payload["failures"]["main"]


if __name__ == "__main__":
    test_oos_lock_audit_passes_when_holdout_does_not_degrade()
    test_oos_lock_audit_blocks_large_holdout_degradation()
    print("oos_lock_audit_smoke: PASS")
