#!/usr/bin/env python3
"""Smoke tests for broker-position-risk grid sweep."""
from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import run_broker_position_risk_grid_sweep as grid  # noqa: E402


def test_parse_grid_supports_disabled_hard_stop() -> None:
    out = grid.parse_grid("disabled,-0.20", allow_disabled=True)
    assert out == [grid.DISABLED_STOP_VALUE, -0.20]


def test_parse_grid_rejects_disabled_when_not_allowed() -> None:
    try:
        grid.parse_grid("disabled,-0.25", allow_disabled=False)
    except ValueError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("disabled must be rejected when allow_disabled=False")


def test_target_book_prefers_alphaops_official_books(tmp_path: Path) -> None:
    latest = tmp_path / "outputs"
    alphaops = latest / "alphaops_vnext"
    reports = latest / "reports"
    alphaops.mkdir(parents=True)
    reports.mkdir(parents=True)
    official = alphaops / "official_main_target_book.csv"
    legacy = reports / "operating_main_target_book.csv"
    official.write_text("rebalance_date,ticker,weight\n2020-01-31,AAA,1.0\n", encoding="utf-8")
    legacy.write_text("rebalance_date,ticker,weight\n2020-01-31,BBB,1.0\n", encoding="utf-8")

    assert grid.target_book_for(latest, "main") == official


def test_rank_grid_prefers_mdd_gain_without_large_cagr_drag() -> None:
    baseline = {"cagr": 0.33, "max_dd": -0.26}
    fake = {
        (grid.DISABLED_STOP_VALUE, -0.25): {"status": "completed", "cagr": 0.30, "max_dd": -0.18, "sharpe": 1.2, "risk_exit_count": 9, "trade_count": 100},
        (grid.DISABLED_STOP_VALUE, -0.35): {"status": "completed", "cagr": 0.34, "max_dd": -0.25, "sharpe": 1.3, "risk_exit_count": 2, "trade_count": 93},
        (-0.12, -0.25): {"status": "completed", "cagr": 0.20, "max_dd": -0.15, "sharpe": 0.9, "risk_exit_count": 60, "trade_count": 150},
    }

    def loader(hard: float, trailing: float) -> dict:
        return fake[(hard, trailing)]

    ranked = grid.rank_grid(list(fake.keys()), loader, baseline)

    assert ranked[0]["hard_stop"] == grid.DISABLED_STOP_VALUE
    assert ranked[0]["trailing_stop"] in (-0.25, -0.35)
    assert ranked[-1]["hard_stop"] == -0.12
    assert ranked[-1]["drag_penalty"] > 0.0


def test_missing_baseline_blocks_activation(tmp_path: Path) -> None:
    result = grid.evaluate_portfolio(
        portfolio="main",
        latest=tmp_path / "missing",
        price_cache=tmp_path / "cache",
        output_dir=tmp_path / "out",
        hard_grid=[grid.DISABLED_STOP_VALUE],
        trailing_grid=[-0.25],
        trailing_activation=0.30,
        relative_trim_threshold=-99.0,
        relative_exit_threshold=-99.0,
        disable_distribution_exit=True,
        keep_intermediate=False,
    )

    assert result["status"] == "missing_baseline"
    assert result["production_activation_allowed"] is False


def test_render_report_marks_research_only() -> None:
    baseline = {"cagr": 0.33, "max_dd": -0.26, "sharpe": 1.2}
    ranked = [
        {
            "status": "ok",
            "hard_stop_label": "disabled",
            "trailing_stop_label": "-35.00%",
            "overlay_cagr": 0.34,
            "overlay_max_dd": -0.25,
            "cagr_gap_pp": -1.0,
            "mdd_improvement_pp": 1.0,
            "overlay_risk_exit_count": 2,
            "overlay_trade_count": 93,
            "composite": 0.345,
        }
    ]

    text = grid.render_report("main", baseline, ranked)

    assert "Research-only" in text
    assert "Production activation remains false" in text
    assert "-35.00%" in text


if __name__ == "__main__":
    test_parse_grid_supports_disabled_hard_stop()
    test_parse_grid_rejects_disabled_when_not_allowed()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_target_book_prefers_alphaops_official_books(Path(tmp))
        test_missing_baseline_blocks_activation(Path(tmp))
    test_rank_grid_prefers_mdd_gain_without_large_cagr_drag()
    test_render_report_marks_research_only()
    print("broker_position_risk_grid_sweep_smoke: PASS")
