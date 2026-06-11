#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from run_local import parse_args, print_verdict
from tools.run_portfolio_system_guard import portfolio_status


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def main() -> int:
    args = parse_args()
    assert args.gate_mode == "broker"

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        out = base / "outputs"
        write_json(out / "backtest_metrics.json", {"cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})
        write_csv(out / "scored_latest.csv", [{"ticker": "AAA", "portfolio_sleeve_label": "core_compounder"}])
        write_json(
            out / "weights_latest.json",
            {
                "sleeve_target_weights": {"core_compounder": 1.0},
                "sleeve_actual_weights": {"core_compounder": 1.0},
                "sleeve_selected_counts": {"early_scout": 4},
            },
        )
        write_csv(out / "portfolio_latest.csv", [{"ticker": "AAA", "weight": 1.0}])

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = print_verdict(base, gate_mode="broker")
        text = buffer.getvalue()
        assert code == 1
        assert "DO_NOT_USE" in text
        assert "legacy/proxy metrics exist" in text

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            target_code = print_verdict(base, gate_mode="target")
        target_text = buffer.getvalue()
        assert target_code == 0
        assert "DEPRECATED TARGET-WEIGHT RESEARCH VERDICT" in target_text
        assert "Production SHIP still requires --gate-mode broker" in target_text

    legacy_status = portfolio_status(
        "main",
        {"_metric_source": "legacy_weight_backtest", "valid_for_production": False, "cagr": 0.99, "max_dd": -0.01},
        0.30,
        -0.25,
    )
    assert legacy_status["official_source_pass"] is False
    assert legacy_status["target_pass"] is False

    broker_status = portfolio_status(
        "main",
        {"_metric_source": "broker_ledger_next_close", "valid_for_production": True, "cagr": 0.31, "max_dd": -0.24},
        0.30,
        -0.25,
    )
    assert broker_status["official_source_pass"] is True
    assert broker_status["target_pass"] is True

    print("broker_gate_contract_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
