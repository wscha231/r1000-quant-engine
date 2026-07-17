#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_run287_cagr_first_objective import audit, reference_attribution, write_outputs  # noqa: E402


def contract() -> dict[str, object]:
    return {
        "core_gates": {
            "minimum_delta_sharpe": -0.05,
            "fill_mode": "next_close",
            "integer_shares": True,
            "reference_cost_bps_per_side": 25.0,
        },
        "required_sensitivities": {
            "cash_modes": ["cash_carry", "zero_yield"],
            "cost_bps_per_side": [25, 50, 100],
        },
    }


def write_metrics(path: Path, cagr: float, oos: float, oos2: float, max_dd: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cagr": cagr,
        "max_dd": max_dd,
        "fill_mode": "next_close",
        "integer_shares": True,
        "cost_bps_per_side": 25.0,
        "windows": {"oos": {"cagr": oos}, "oos2": {"cagr": oos2}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture(tmp: Path) -> tuple[pd.DataFrame, Path]:
    arm_dir = tmp / "signal_replays" / "growth_confirmation_score" / "main"
    broker_path = arm_dir / "candidate" / "metrics.json"
    write_metrics(broker_path, 0.36, 0.70, 0.52, -0.26)
    (arm_dir / "summary.json").write_text(
        json.dumps({"used_forward_return_in_ranking": False}), encoding="utf-8"
    )
    inventory = pd.DataFrame(
        [
            {
                "file": str(arm_dir / "arm_metrics.csv"),
                "arm": "growth_confirmation_top_quintile_tilt10",
                "cagr": 0.36,
                "max_dd": -0.26,
                "delta_cagr_pp": 2.0,
                "delta_windows.oos.cagr_pp": 2.6,
                "delta_windows.oos2.cagr_pp": 3.7,
                "delta_sharpe": 0.06,
                "delta_max_dd_pp": -0.56,
                "broker_metrics_path": str(broker_path),
                "target_book_path": str(arm_dir / "target.csv"),
                "ab_verdict": "reject_mdd_worse",
            }
        ]
    )
    return inventory, tmp / "sensitivity"


def populate_sensitivity(root: Path, negative_oos: bool = False) -> None:
    for mode in ("cash_carry", "zero_yield"):
        for bps in (25, 50, 100):
            write_metrics(root / "replays" / mode / f"{bps}bps" / "baseline" / "metrics.json", 0.34, 0.67, 0.48, -0.25)
            candidate_oos = 0.66 if negative_oos and mode == "zero_yield" and bps == 100 else 0.69
            write_metrics(root / "replays" / mode / f"{bps}bps" / "candidate" / "metrics.json", 0.35, candidate_oos, 0.50, -0.26)


def test_ready_then_pass() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        inventory, sensitivity = fixture(tmp)
        registry = {"entries": [{"id": "direct_growth_tilt", "signal": "growth_confirmation", "blocked_reuse": True}]}
        result = audit(inventory, contract(), registry)
        assert result[0]["status"] == "READY_TARGETED_SENSITIVITY_ONLY"
        selected = result[0]["selected_arm"]
        assert selected["core_growth_gate_pass"] is True
        assert selected["do_not_repeat_match_ids"] == "direct_growth_tilt"
        assert selected["new_grid_allowed"] is False
        populate_sensitivity(sensitivity)
        result = audit(inventory, contract(), registry, sensitivity)
        assert result[0]["status"] == "READY_INCREMENTAL_PNL_ATTRIBUTION"
        assert result[0]["sensitivity_pass"] is True
        output = tmp / "output"
        write_outputs(output, result)
        assert (output / "manifest.json").exists()
        assert (output / "candidate_ranking.csv").exists()


def test_negative_sensitivity_rejects() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        inventory, sensitivity = fixture(tmp)
        populate_sensitivity(sensitivity, negative_oos=True)
        result = audit(inventory, contract(), {"entries": []}, sensitivity)
        assert result[0]["status"] == "REJECT_GROWTH_FIRST_SENSITIVITY"
        assert result[0]["sensitivity_pass"] is False


def write_account(root: Path, ticker: str, last_price: float, last_equity: float) -> None:
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"date": "2025-01-02", "ticker": ticker, "market_value_usd": 100.0},
            {"date": "2025-01-03", "ticker": ticker, "market_value_usd": last_price},
        ]
    ).to_csv(root / "holdings_daily.csv", index=False)
    pd.DataFrame(
        [{"date": "2025-01-02", "ticker": ticker, "side": "BUY", "gross_value": 100.0, "fee_usd": 0.0}]
    ).to_csv(root / "trades.csv", index=False)
    pd.DataFrame(
        [
            {"date": "2025-01-02", "equity_usd": 100000.0, "cash_interest_daily": 0.0},
            {"date": "2025-01-03", "equity_usd": last_equity, "cash_interest_daily": 0.0},
        ]
    ).to_csv(root / "equity_curve.csv", index=False)


def test_reference_attribution_detects_concentration() -> None:
    with tempfile.TemporaryDirectory() as raw:
        sensitivity = Path(raw)
        reference = sensitivity / "replays" / "cash_carry" / "25bps"
        write_account(reference / "baseline", "A", 110.0, 100010.0)
        write_account(reference / "candidate", "B", 120.0, 100020.0)
        summary, ticker, era = reference_attribution(
            sensitivity,
            {"generalization_gates": {
                "maximum_single_ticker_share_of_net_incremental_pnl": 0.5,
                "maximum_single_era_share_of_net_incremental_pnl": 0.5,
            }},
        )
        assert summary["total_incremental_ending_equity_usd"] == 10.0
        assert summary["top_ticker"] == "B"
        assert summary["top_ticker_share_of_net_incremental_pnl"] == 2.0
        assert summary["top_era_share_of_net_incremental_pnl"] == 1.0
        assert summary["single_ticker_and_era_concentration_pass"] is False
        assert set(ticker["ticker"]) >= {"A", "B"}
        assert era.iloc[0]["era"] == "2025_plus"


def main() -> None:
    test_ready_then_pass()
    test_negative_sensitivity_rejects()
    test_reference_attribution_detects_concentration()
    print("run287_cagr_first_objective_smoke: PASS")


if __name__ == "__main__":
    main()
