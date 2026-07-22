#!/usr/bin/env python3
"""Smoke checks for the canonical ReserveAssetPolicy."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.reserve_asset_policy import (  # noqa: E402
    BIL_TOTAL_RETURN,
    BLOCKED_SHORT_HISTORY,
    BROKER_CASH_OR_MMF,
    DEFAULT_CURRENT_PAPER_MODE,
    DEFAULT_HISTORICAL_MODE,
    DGS3MO_CARRY,
    RESERVE_REASONS,
    RESERVE_REASON_SOURCE_HASH_FIELD,
    SGOV_TOTAL_RETURN,
    account_reserve_reason_reconciliation,
    apply_reserve_asset_to_targets,
    assert_no_double_count,
    ensure_explicit_cash_row,
    reserve_history_status,
    reserve_reason_reconciliation,
    resolve_reserve_asset_policy,
)
from tools.run_broker_ledger_replay import replay  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_prices(cache: Path, ticker: str, closes: list[float], start: str) -> None:
    index = pd.bdate_range(start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": 1_000_000,
        },
        index=index,
    ).to_parquet(cache / px_cache_name(ticker))


def test_modes_and_reason_reconciliation() -> None:
    assert resolve_reserve_asset_policy(None, context="historical").mode == DEFAULT_HISTORICAL_MODE
    assert resolve_reserve_asset_policy(None, context="current_paper").mode == DEFAULT_CURRENT_PAPER_MODE
    assert resolve_reserve_asset_policy("none").mode == BROKER_CASH_OR_MMF
    assert resolve_reserve_asset_policy("risk_free_rate").mode == DGS3MO_CARRY
    target = pd.DataFrame(
        [
            {"ticker": "AAA", "weight": 0.60},
            {
                "ticker": "CASH",
                "weight": 0.40,
                "crisis_reserve": 0.10,
                "capacity_unallocated": 0.25,
                "transaction_buffer": 0.05,
            },
        ]
    )
    for reason in RESERVE_REASONS:
        if reason not in target:
            target[reason] = 0.0
    broker = resolve_reserve_asset_policy(BROKER_CASH_OR_MMF)
    audit = reserve_reason_reconciliation(target, policy=broker, weight_col="weight")
    assert audit["reconciled"] is True
    assert abs(audit["reason_weight_sum"] - 0.40) < 1e-12
    account_audit = account_reserve_reason_reconciliation(
        audit,
        actual_reserve_weight=0.405,
    )
    assert abs(account_audit["reason_weight_sum"] - 0.405) < 1e-12
    assert account_audit["reason_weights"]["crisis_reserve"] > 0
    assert account_audit["reason_weights"]["capacity_unallocated"] > 0
    assert account_audit[RESERVE_REASON_SOURCE_HASH_FIELD] == audit[
        RESERVE_REASON_SOURCE_HASH_FIELD
    ]
    target[RESERVE_REASON_SOURCE_HASH_FIELD] = audit[
        RESERVE_REASON_SOURCE_HASH_FIELD
    ]
    assert reserve_reason_reconciliation(
        target, policy=broker, weight_col="weight"
    )[RESERVE_REASON_SOURCE_HASH_FIELD] == audit[RESERVE_REASON_SOURCE_HASH_FIELD]
    implicit = ensure_explicit_cash_row(
        pd.DataFrame([{"ticker": "AAA", "weight": 0.60}]),
        weight_col="weight",
    )
    assert set(implicit["ticker"]) == {"AAA", "CASH"}
    assert abs(float(implicit["weight"].sum()) - 1.0) < 1e-12
    bil = resolve_reserve_asset_policy(BIL_TOTAL_RETURN)
    transformed, rows = apply_reserve_asset_to_targets(target, policy=bil, weight_col="weight")
    assert set(transformed["ticker"]) == {"AAA", "BIL"}
    assert float(transformed.loc[transformed["ticker"].eq("AAA"), "weight"].iloc[0]) == 0.60
    assert bool(rows["reconciled"].all())
    assert transformed[RESERVE_REASON_SOURCE_HASH_FIELD].nunique() == 1


def test_history_and_double_count_gate() -> None:
    bil = resolve_reserve_asset_policy(BIL_TOTAL_RETURN)
    prices = pd.DataFrame({"close": [100.0, 101.0]}, index=pd.to_datetime(["2020-01-02", "2020-01-03"]))
    ready = reserve_history_status(
        prices,
        policy=bil,
        required_start="2020-01-02",
        required_end="2020-01-03",
    )
    assert ready["status"] == "READY"
    sgov = resolve_reserve_asset_policy(SGOV_TOTAL_RETURN)
    blocked = reserve_history_status(
        prices,
        policy=sgov,
        required_start="2019-01-02",
        required_end="2020-01-03",
    )
    assert blocked["status"] == BLOCKED_SHORT_HISTORY
    try:
        assert_no_double_count(bil, cash_interest_enabled=True)
    except ValueError as exc:
        assert "may not be credited together" in str(exc)
    else:
        raise AssertionError("ETF interest double count was not blocked")


def test_bil_trades_like_a_security_and_sgov_blocks_short_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        cache.mkdir()
        write_prices(cache, "AAA", [100.0] * 8, "2026-01-02")
        write_prices(cache, "BIL", [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0], "2026-01-02")
        write_prices(cache, "SGOV", [100.0, 101.0], "2026-01-09")
        target = root / "target.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-02", "ticker": "CASH", "weight": 0.50},
            ]
        ).to_csv(target, index=False)
        bil_out = root / "bil"
        bil = replay(
            target_book=target,
            price_cache=cache,
            output_dir=bil_out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            reserve_mode=BIL_TOTAL_RETURN,
        )
        assert bil["status"] == "completed", bil
        assert bil["reserve_asset_ticker"] == "BIL"
        assert bil["reserve_cash_interest_enabled"] is False
        assert bil["reserve_distribution_separately_credited"] is False
        assert bil["reserve_trade_count"] >= 1
        assert bil["valid_for_production"] is False
        assert bil["research_only"] is True
        assert bil["production_activation_allowed"] is False
        bil_account = json.loads(
            (bil_out / "account_state_latest.json").read_text(encoding="utf-8")
        )
        assert bil_account["position_count_total"] == (
            bil_account["equity_position_count"]
            + bil_account["reserve_position_count"]
        )
        assert bil_account["position_count"] == bil_account["equity_position_count"]
        assert bil_account["reserve_position_count"] == 1
        assert bil_account[RESERVE_REASON_SOURCE_HASH_FIELD] == bil[
            RESERVE_REASON_SOURCE_HASH_FIELD
        ]
        trades = pd.read_csv(bil_out / "trades.csv")
        assert "BIL" in set(trades["ticker"])
        curve = pd.read_csv(bil_out / "equity_curve.csv")
        assert {"reserve_asset_value_usd", "reserve_weight"}.issubset(curve.columns)
        blocked = replay(
            target_book=target,
            price_cache=cache,
            output_dir=root / "sgov",
            portfolio_kind="main",
            starting_capital=10_000.0,
            reserve_mode=SGOV_TOTAL_RETURN,
        )
        assert blocked["status"] == BLOCKED_SHORT_HISTORY


def main() -> int:
    test_modes_and_reason_reconciliation()
    test_history_and_double_count_gate()
    test_bil_trades_like_a_security_and_sgov_blocks_short_history()
    print("reserve_asset_policy_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
