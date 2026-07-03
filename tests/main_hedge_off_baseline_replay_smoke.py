#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_main_hedge_off_baseline_replay import build_hedge_off_book  # noqa: E402


def test_build_hedge_off_book_moves_sh_weight_to_cash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "target.csv"
        out = root / "hedge_off.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2020-02-28", "ticker": "AAA", "weight": 0.40, "target_weight": 0.40},
                {"rebalance_date": "2020-02-28", "ticker": "CASH", "weight": 0.50, "target_weight": 0.50},
                {"rebalance_date": "2020-02-28", "ticker": "SH", "weight": 0.10, "target_weight": 0.10},
                {"rebalance_date": "2020-03-31", "ticker": "AAA", "weight": 0.70, "target_weight": 0.70},
                {"rebalance_date": "2020-03-31", "ticker": "CASH", "weight": 0.30, "target_weight": 0.30},
            ]
        ).to_csv(source, index=False)
        removed, stats = build_hedge_off_book(target_book=source, output_path=out, hedge_ticker="SH")
        generated = pd.read_csv(out)
        assert len(removed) == 1
        assert stats["hedge_rows_removed"] == 1
        assert stats["hedge_signal_date_count"] == 1
        assert "SH" not in set(generated["ticker"].astype(str).str.upper())
        feb = generated[generated["rebalance_date"].eq("2020-02-28")]
        assert abs(float(feb.loc[feb["ticker"].eq("CASH"), "weight"].iloc[0]) - 0.60) < 1e-12
        assert abs(float(feb["weight"].sum()) - 1.0) < 1e-12
        assert abs(float(generated[generated["rebalance_date"].eq("2020-03-31")]["weight"].sum()) - 1.0) < 1e-12
        assert (out.parent / "removed_hedge_rows.csv").exists()


def test_build_hedge_off_book_creates_cash_when_absent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "target.csv"
        out = root / "hedge_off.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2020-02-28", "ticker": "AAA", "weight": 0.80, "target_weight": 0.80},
                {"rebalance_date": "2020-02-28", "ticker": "SH", "weight": 0.20, "target_weight": 0.20},
            ]
        ).to_csv(source, index=False)
        _removed, stats = build_hedge_off_book(target_book=source, output_path=out, hedge_ticker="SH")
        generated = pd.read_csv(out)
        assert stats["cash_replacement_policy"] == "move_removed_hedge_weight_to_cash"
        assert "CASH" in set(generated["ticker"].astype(str).str.upper())
        assert abs(float(generated["weight"].sum()) - 1.0) < 1e-12


def main() -> int:
    test_build_hedge_off_book_moves_sh_weight_to_cash()
    test_build_hedge_off_book_creates_cash_when_absent()
    print("main_hedge_off_baseline_replay_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
