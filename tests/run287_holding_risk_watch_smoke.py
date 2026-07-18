#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_holding_risk_watch import build_watch, write_outputs  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


ASOF = pd.Timestamp("2026-07-13")


def write_price(cache: Path, ticker: str, close: np.ndarray, *, add_future: bool = False) -> None:
    dates = pd.bdate_range(end=ASOF, periods=len(close))
    frame = pd.DataFrame(
        {
            "Open": np.r_[close[0], close[:-1]] * 1.001,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )
    if add_future:
        frame.loc[pd.Timestamp("2026-07-14")] = [200.0, 205.0, 195.0, 200.0, 200.0, 1_000_000]
    cache.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache / px_cache_name(ticker))


def write_account(path: Path, portfolio: str) -> None:
    positions = [
        {"ticker": "NORMAL", "shares": 100.0},
        {"ticker": "SHOCK", "shares": 100.0},
        {"ticker": "TREND", "shares": 100.0},
        {"ticker": "MISSING", "shares": 100.0},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "portfolio_kind": portfolio,
                "as_of_date": "2026-07-10",
                "cash_usd": 10_000.0,
                "positions": positions,
                "review_only": True,
                "live_trading_enabled": False,
            }
        ),
        encoding="utf-8",
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        sessions = 340
        spy = np.linspace(100.0, 130.0, sessions)
        normal = np.linspace(80.0, 120.0, sessions)
        shock = np.linspace(90.0, 130.0, sessions)
        shock[-1] = 78.0
        trend = np.r_[np.linspace(70.0, 120.0, sessions - 70), np.linspace(118.0, 62.0, 70)]
        write_price(cache, "SPY", spy)
        write_price(cache, "NORMAL", normal)
        write_price(cache, "SHOCK", shock, add_future=True)
        write_price(cache, "TREND", trend)
        main_account = root / "main.json"
        concentrated_account = root / "concentrated.json"
        write_account(main_account, "main")
        write_account(concentrated_account, "concentrated")
        contract_path = ROOT / "docs" / "run287_holding_risk_watch_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))

        summary, rows = build_watch(
            account_paths={"main": main_account, "concentrated": concentrated_account},
            price_cache=cache,
            contract=contract,
            contract_path=contract_path,
            asof=ASOF,
            available_from="2026-07-13T20:30:00Z",
            require_exact_close=False,
        )
        assert summary["status"] == "READY_REVIEW_ONLY_WITH_DATA_INSUFFICIENT"
        assert summary["orders_generated"] is False
        assert summary["target_books_mutated"] is False
        assert summary["historical_cagr_mdd_evidence_changed"] is False
        main_rows = rows[rows["portfolio_kind"].eq("main")].set_index("ticker")
        assert main_rows.loc["SHOCK", "risk_state"] == "ALERT"
        assert bool(main_rows.loc["SHOCK", "idiosyncratic_shock"]) is True
        assert int(main_rows.loc["SHOCK", "future_price_rows_excluded"]) == 1
        assert main_rows.loc["SHOCK", "latest_price_date"] == "2026-07-13"
        assert main_rows.loc["TREND", "risk_state"] in {"WATCH", "ALERT"}
        assert main_rows.loc["MISSING", "risk_state"] == "DATA_INSUFFICIENT"
        assert main_rows.loc["MISSING", "advisory_action"] == "MISSING_NEUTRAL_NO_ACTION"
        assert rows["orders_generated"].eq(False).all()
        assert rows["target_weight_changed"].eq(False).all()

        exact_accounts = {}
        for portfolio in ("main", "concentrated"):
            path = root / f"{portfolio}_exact.json"
            path.write_text(
                json.dumps(
                    {
                        "portfolio_kind": portfolio,
                        "as_of_date": "2026-07-13",
                        "cash_usd": 10_000.0,
                        "positions": [{"ticker": "NORMAL", "shares": 100.0}],
                    }
                ),
                encoding="utf-8",
            )
            exact_accounts[portfolio] = path
        exact_summary, _ = build_watch(
            account_paths=exact_accounts,
            price_cache=cache,
            contract=contract,
            contract_path=contract_path,
            asof=ASOF,
            available_from="2026-07-13T20:30:00Z",
            require_exact_close=True,
        )
        assert exact_summary["status"] == "READY_REVIEW_ONLY"
        assert exact_summary["missing_exact_close_rows"] == []

        output = root / "holding_risk_watch"
        first = write_outputs(output, summary, rows)
        first_history = (output / "risk_history.jsonl").read_text(encoding="utf-8")
        retry_rows = rows.copy()
        retry_rows["available_from"] = "2026-07-14T01:00:00Z"
        retry_summary = {**summary, "available_from": "2026-07-14T01:00:00Z"}
        second = write_outputs(output, retry_summary, retry_rows)
        assert first["history_appended_count"] == len(rows)
        assert second["history_appended_count"] == 0
        assert retry_rows["available_from"].eq("2026-07-13T20:30:00Z").all()
        assert (output / "risk_history.jsonl").read_text(encoding="utf-8") == first_history
        assert (output / "holding_risk_watch.csv").exists()
        assert (output / "risk_history.jsonl").exists()
        assert len((output / "risk_history.jsonl").read_text(encoding="utf-8").splitlines()) == len(rows)
        assert "FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW" in (output / "report.md").read_text(encoding="utf-8")

        changed_rows = rows.copy()
        changed_rows.loc[changed_rows.index[0], "risk_state"] = "CHANGED"
        try:
            write_outputs(output, summary, changed_rows)
        except ValueError as exc:
            assert "same-date holding risk event changed" in str(exc)
        else:
            raise AssertionError("same-date semantic mutation must fail closed")

    print("run287_holding_risk_watch_smoke: PASS")


if __name__ == "__main__":
    main()
