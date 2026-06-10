from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_features import load_etf_holdings_overlay  # noqa: E402
from tools.run_etf_holdings_refresh import parse_args, run  # noqa: E402


def test_etf_holdings_refresh_builds_shadow_signals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fixture = root / "holdings.csv"
        pd.DataFrame(
            [
                {"etf_ticker": "SMH", "holding_ticker": "NVDA", "holding_weight": 0.20, "theme": "semiconductors"},
                {"etf_ticker": "SOXX", "holding_ticker": "NVDA", "holding_weight": 0.12, "theme": "semiconductors"},
                {"etf_ticker": "BOTZ", "holding_ticker": "NVDA", "holding_weight": 0.08, "theme": "robotics_ai"},
                {"etf_ticker": "SMH", "holding_ticker": "AMD", "holding_weight": 0.06, "theme": "semiconductors"},
            ]
        ).to_csv(fixture, index=False)

        args = parse_args()
        args.input_holdings = str(fixture)
        args.pit_dir = str(root / "data_pit" / "etf_holdings")
        args.output_dir = str(root / "outputs" / "etf_thematic_signals")
        args.as_of = "2026-05-20T00:00:00Z"
        args.max_holdings = 25
        payload = run(args)
        assert payload["signal_tickers"] >= 2

        overlay = load_etf_holdings_overlay(base_dir=root / "outputs")
        nvda = overlay[overlay["ticker"].eq("NVDA")].iloc[0]
        assert int(nvda["etf_consensus_count"]) == 3
        assert float(nvda["etf_holdings_score"]) > 0.0


if __name__ == "__main__":
    test_etf_holdings_refresh_builds_shadow_signals()
    print("etf_holdings_overlay_smoke: PASS")
