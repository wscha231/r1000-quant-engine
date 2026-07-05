#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run287_rolling_window_deficit import run  # noqa: E402


class Args:
    pass


def test_rolling_window_deficit_outputs_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for portfolio, multiplier in [("main", 1.001), ("concentrated", 1.002)]:
            p = root / "sidecar" / portfolio
            p.mkdir(parents=True)
            dates = pd.bdate_range("2025-01-02", periods=320)
            values = []
            equity = 100000.0
            for idx, dt in enumerate(dates):
                equity *= multiplier
                if idx == len(dates) - 1:
                    equity *= 0.95
                values.append({"date": dt.date().isoformat(), "equity_usd": equity, "cash_weight": 0.2})
            pd.DataFrame(values).to_csv(p / "equity_curve.csv", index=False)
            (p / "metrics.json").write_text(
                '{"starting_capital_usd": 100000, "metric_mode": "broker_ledger_next_close_cash_carry"}\n',
                encoding="utf-8",
            )
        args = Args()
        args.root = str(root / "sidecar")
        args.output_dir = str(root / "out")
        args.min_trading_days = 252
        args.lookback_windows = "20,63"
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["fullrun_dispatched"] is False
        assert payload["threshold_tuning_performed"] is False
        assert "main" in payload["portfolios"]
        assert (root / "out" / "end_date_metrics.csv").exists()
        assert (root / "out" / "report.md").exists()


def main() -> int:
    test_rolling_window_deficit_outputs_summary()
    print("run287_rolling_window_deficit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
