#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.validate_target_book_cash_contract import validate_contract


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good_book = root / "good_target_book.csv"
        bad_book = root / "bad_target_book.csv"
        broker = root / "broker"

        write_csv(
            good_book,
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.80},
                {"rebalance_date": "2026-01-31", "ticker": "CASH", "weight": 0.20},
                {"rebalance_date": "2026-02-28", "ticker": "AAA", "weight": 0.75},
                {"rebalance_date": "2026-02-28", "ticker": "CASH", "weight": 0.25},
            ],
        )
        write_csv(
            bad_book,
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.80},
                {"rebalance_date": "2026-02-28", "ticker": "AAA", "weight": 0.75},
            ],
        )
        write_csv(
            broker / "cash_ledger.csv",
            [
                {"date": "2026-01-31", "cash_weight": 0.205},
                {"date": "2026-02-28", "cash_weight": 0.245},
            ],
        )

        good, by_date, drift = validate_contract(target_book=good_book, broker_dir=broker)
        assert good["cash_contract_pass"] is True
        assert int(good["target"]["date_count"]) == 2
        assert good["drift"]["mean_cash_drift_pp"] <= 2.0
        assert good["drift"]["rebalance_day_cash_drift_pass"] is True
        assert good["drift"]["month_mean_cash_drift_pass"] is True
        assert "rebalance_day_mean_cash_drift_pp" in good["drift"]
        assert "month_mean_cash_drift_pp" in good["drift"]
        assert not by_date.empty
        assert not drift.empty

        bad, _bad_by_date, _bad_drift = validate_contract(target_book=bad_book, broker_dir=broker)
        assert bad["cash_contract_pass"] is False
        assert bad["target"]["missing_explicit_cash_date_count"] == 2

    print("cash_contract_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
