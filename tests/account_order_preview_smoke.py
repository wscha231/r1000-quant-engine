#!/usr/bin/env python3
"""Smoke checks for account-ledger order preview."""
from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_account_order_preview import (  # noqa: E402
    latest_price,
    normalize_target,
    run,
    select_target_snapshot,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.security_lifecycle import REQUIRED_COLUMNS  # noqa: E402


@contextmanager
def raises_value_error(match: str):
    try:
        yield
    except ValueError as exc:
        assert match in str(exc), str(exc)
    else:
        raise AssertionError(f"ValueError containing {match!r} was not raised")


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    ).to_parquet(cache_dir / px_cache_name(ticker))


class Args:
    pass


def test_order_preview_builds_sell_first_orders() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 100.0, 100.0])
        _write_px(cache, "BBB", [50.0, 50.0, 50.0])
        account = {
            "as_of_date": "2026-01-02",
            "cash_usd": 1000.0,
            "positions": [
                {"ticker": "AAA", "shares": 80.0, "cost_basis": 90.0},
            ],
        }
        account_path = root / "account_state_latest.json"
        account_path.write_text(json.dumps(account), encoding="utf-8")
        target = root / "target.csv"
        pd.DataFrame(
            [
                {"ticker": "AAA", "weight": 0.30},
                {"ticker": "BBB", "weight": 0.60},
            ]
        ).to_csv(target, index=False)
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = ""
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["account_state_as_of_date"] == "2026-01-02"
        assert payload["as_of_date"] == "2026-01-06"
        orders = pd.read_csv(out / "orders_preview.csv")
        assert not orders.empty
        assert orders.iloc[0]["side"] == "SELL"
        assert {"SELL", "BUY"}.issubset(set(orders["side"]))
        sells = orders[orders["side"].eq("SELL")]
        assert set(sells["sell_taxonomy"]) == {"EXECUTION_RECONCILIATION"}
        assert payload["unclassified_sell_count"] == 0
        assert (orders["quantity"] % 1 == 0).all()
        assert "client_order_id" in orders.columns
        assert "idempotency_key" in orders.columns
        assert orders["client_order_id"].is_unique
        assert (out / "positions_current.csv").exists()
        assert (out / "projected_positions_after_orders.csv").exists()
        assert (out / "preview_metrics.json").exists()
        assert "projected_cash_weight" in payload
        assert "target_cash_weight" in payload
        assert abs(payload["target_cash_weight"] - 0.10) < 1e-9
        projected = pd.read_csv(out / "projected_positions_after_orders.csv")
        assert "projected_weight" in projected.columns
        assert "CASH" in set(projected["ticker"])
        manifest = json.loads((out / "order_batch_manifest.json").read_text(encoding="utf-8"))
        assert manifest["order_count"] == len(orders)
        assert manifest["order_batch_id"] == payload["order_batch_id"]


def test_concentrated_target_normalization_does_not_force_n3() -> None:
    frame = pd.DataFrame(
        [
            {"rebalance_date": "2026-06-01", "ticker": "AAA", "target_weight": 0.30, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "BBB", "target_weight": 0.25, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "CCC", "target_weight": 0.20, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "DDD", "target_weight": 0.15, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "EEE", "target_weight": 0.10, "target_stock_names": 5},
            {"rebalance_date": "2026-06-01", "ticker": "OLD", "target_weight": 1.00, "target_stock_names": 3},
            {"rebalance_date": "2026-06-01", "ticker": "CASH", "target_weight": 0.00, "target_stock_names": 5},
        ]
    )
    out = normalize_target(frame, "concentrated")
    assert set(out["ticker"]) == {"AAA", "BBB", "CCC", "DDD", "EEE"}
    assert abs(float(out["target_weight"].sum()) - 1.0) < 1e-9


def test_order_preview_uses_explicit_cash_target_weight() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 100.0, 100.0])
        account = {
            "as_of_date": "2026-01-02",
            "cash_usd": 6000.0,
            "positions": [{"ticker": "AAA", "shares": 40.0, "cost_basis": 90.0}],
        }
        account_path = root / "account_state_latest.json"
        account_path.write_text(json.dumps(account), encoding="utf-8")
        target = root / "target.csv"
        pd.DataFrame(
            [
                {"ticker": "CASH", "target_weight": 0.60},
                {"ticker": "AAA", "target_weight": 0.40},
            ]
        ).to_csv(target, index=False)
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = ""
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        payload = run(args)
        assert payload["status"] == "completed"
        assert abs(payload["target_cash_weight"] - 0.60) < 1e-9
        assert abs(payload["target_stock_weight"] - 0.40) < 1e-9


def test_lifecycle_price_switches_only_after_predecessor_last_trade() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        _write_px(cache, "OLD", [100.0, 101.0], start="2026-01-02")
        _write_px(cache, "NEW", [120.0, 121.0], start="2026-01-05")
        overrides = {"OLD": "NEW"}
        links = {
            "OLD": {
                "last_trading_date": "2026-01-05",
                "effective_date": "2026-01-06",
            }
        }
        before_date, before_price = latest_price(
            cache,
            "OLD",
            pd.Timestamp("2026-01-05"),
            overrides,
            links,
        )
        after_date, after_price = latest_price(
            cache,
            "OLD",
            pd.Timestamp("2026-01-06"),
            overrides,
            links,
        )
        assert before_date == pd.Timestamp("2026-01-05")
        assert before_price == 101.0
        assert after_date == pd.Timestamp("2026-01-06")
        assert after_price == 121.0


def test_lifecycle_price_does_not_cross_cutover_on_missing_successor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        _write_px(cache, "OLD", [100.0, 101.0], start="2026-01-02")
        with raises_value_error("lifecycle_successor_price_missing"):
            latest_price(
                cache,
                "OLD",
                pd.Timestamp("2026-01-06"),
                {"OLD": "NEW"},
                {
                    "OLD": {
                        "last_trading_date": "2026-01-05",
                        "effective_date": "2026-01-06",
                    }
                },
            )


def test_lifecycle_price_rejects_stale_successor_after_cutover() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        _write_px(cache, "OLD", [100.0, 101.0], start="2026-01-02")
        _write_px(cache, "NEW", [120.0], start="2026-01-05")
        with raises_value_error("lifecycle_successor_price_missing"):
            latest_price(
                cache,
                "OLD",
                pd.Timestamp("2026-01-06"),
                {"OLD": "NEW"},
                {
                    "OLD": {
                        "last_trading_date": "2026-01-05",
                        "effective_date": "2026-01-06",
                    }
                },
            )
        _write_px(cache, "NEW", [121.0], start="2026-01-06")
        with raises_value_error("lifecycle_successor_exact_close_missing"):
            latest_price(
                cache,
                "OLD",
                pd.Timestamp("2026-01-07"),
                {"OLD": "NEW"},
                {
                    "OLD": {
                        "last_trading_date": "2026-01-05",
                        "effective_date": "2026-01-06",
                    }
                },
            )


def test_lifecycle_price_rejects_future_only_successor_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        _write_px(cache, "OLD", [100.0, 101.0], start="2026-01-02")
        _write_px(cache, "NEW", [122.0], start="2026-01-07")
        with raises_value_error("lifecycle_successor_exact_close_missing"):
            latest_price(
                cache,
                "OLD",
                pd.Timestamp("2026-01-06"),
                {"OLD": "NEW"},
                {
                    "OLD": {
                        "last_trading_date": "2026-01-05",
                        "effective_date": "2026-01-06",
                    }
                },
            )


def test_post_cutover_orders_use_successor_ticker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "OLD", [100.0, 101.0], start="2026-01-02")
        _write_px(cache, "NEW", [120.0], start="2026-01-06")
        account_path = root / "account.json"
        account_path.write_text(
            json.dumps(
                {
                    "as_of_date": "2026-01-06",
                    "cash_usd": 0.0,
                    "positions": [
                        {"ticker": "OLD", "shares": 10.0, "cost_basis": 90.0}
                    ],
                }
            ),
            encoding="utf-8",
        )
        target_path = root / "target.csv"
        pd.DataFrame([{"ticker": "CASH", "weight": 1.0}]).to_csv(
            target_path, index=False
        )
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target_path)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = "2026-01-06"
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        args.provider_symbol_override = ["OLD=NEW"]
        payload = run(
            args,
            provider_symbol_links={
                "OLD": {
                    "last_trading_date": "2026-01-05",
                    "effective_date": "2026-01-06",
                    "successor_ticker": "NEW",
                }
            },
        )
        assert payload["status"] == "completed"
        orders = pd.read_csv(out / "orders_preview.csv")
        assert set(orders["ticker"]) == {"NEW"}
        assert set(orders["ledger_ticker"]) == {"OLD"}
        positions = pd.read_csv(out / "positions_current.csv")
        assert positions.loc[0, "ticker"] == "NEW"
        assert positions.loc[0, "logical_ticker"] == "OLD"


def test_standalone_lifecycle_resolves_successor_before_as_of_inference() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "OLD", [101.0], start="2026-01-05")
        _write_px(cache, "NEW", [120.0], start="2026-01-06")
        account_path = root / "account.json"
        account_path.write_text(
            json.dumps(
                {
                    "as_of_date": "2026-01-05",
                    "cash_usd": 0.0,
                    "positions": [
                        {"ticker": "OLD", "shares": 10.0, "cost_basis": 90.0}
                    ],
                }
            ),
            encoding="utf-8",
        )
        target_path = root / "target.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-06",
                    "valuation_close_date": "2026-01-06",
                    "ticker": "OLD",
                    "weight": 1.0,
                    "selector_decision_time_utc": "2026-01-06T21:00:00Z",
                }
            ]
        ).to_csv(target_path, index=False)
        lifecycle_path = root / "security_lifecycle_events.csv"
        event = {column: "" for column in REQUIRED_COLUMNS}
        event.update(
            {
                "stable_security_id": "SEC_OLD",
                "stable_issuer_id": "ISSUER_OLD",
                "ticker": "OLD",
                "aliases": "OLD",
                "event_type": "ticker_change",
                "available_from": "2026-01-06T20:30:00Z",
                "effective_date": "2026-01-06",
                "last_trading_date": "2026-01-05",
                "predecessor_security_id": "SEC_OLD",
                "successor_security_id": "SEC_OLD",
                "successor_ticker": "NEW",
                "currency": "USD",
                "source_url": "https://example.test/lifecycle",
                "stable_event_id": "EVENT_OLD_NEW",
                "source_sha256": "a" * 64,
                "exact_available_from": "true",
                "evidence_status": "verified",
                "review_status": "approved",
            }
        )
        pd.DataFrame([event]).to_csv(lifecycle_path, index=False)
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target_path)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = ""
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        args.provider_symbol_override = []
        args.security_lifecycle_events = str(lifecycle_path)
        args.decision_time_utc = "2026-01-06T21:00:00Z"
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["as_of_date"] == "2026-01-06"
        positions = pd.read_csv(out / "positions_current.csv")
        assert positions.loc[0, "ticker"] == "NEW"
        assert positions.loc[0, "logical_ticker"] == "OLD"
        assert positions.loc[0, "price"] == 120.0


def test_post_cutover_new_target_requires_successor_exact_close() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "OLD", [100.0, 101.0], start="2026-01-02")
        _write_px(cache, "NEW", [120.0], start="2026-01-05")
        account_path = root / "account.json"
        account_path.write_text(
            json.dumps(
                {"as_of_date": "2026-01-06", "cash_usd": 1000.0, "positions": []}
            ),
            encoding="utf-8",
        )
        target_path = root / "target.csv"
        pd.DataFrame([{"ticker": "OLD", "weight": 0.5}]).to_csv(
            target_path, index=False
        )
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target_path)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = "2026-01-06"
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        args.provider_symbol_override = ["OLD=NEW"]
        with raises_value_error("lifecycle_successor_price_missing"):
            run(
                args,
                provider_symbol_links={
                    "OLD": {
                        "last_trading_date": "2026-01-05",
                        "effective_date": "2026-01-06",
                        "successor_ticker": "NEW",
                    }
                },
            )


def test_cli_and_operational_invocations_require_lifecycle_evidence() -> None:
    tool = (ROOT / "tools" / "run_account_order_preview.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--security-lifecycle-events"' in tool
    assert 'parser.add_argument("--decision-time-utc"' in tool
    for path in (
        ROOT / ".github" / "workflows" / "alphaops_replay_sidecars_manual.yml",
        ROOT / "tools" / "run_full_rebuild_sidecars.py",
    ):
        source = path.read_text(encoding="utf-8")
        invocations = [
            line
            for line in source.splitlines()
            if "python tools/run_account_order_preview.py" in line
        ]
        assert invocations
        assert all("--security-lifecycle-events" in line for line in invocations)
        assert all("--decision-time-utc" in line for line in invocations)
        assert all("account_order_preview" not in line or "|| true" not in line for line in invocations)
    quick_rescore = (
        ROOT / ".github" / "workflows" / "phase_ab_quick_rescore_manual.yml"
    ).read_text(encoding="utf-8")
    sidecar_invocations = [
        line
        for line in quick_rescore.splitlines()
        if "python tools/run_full_rebuild_sidecars.py" in line
    ]
    assert sidecar_invocations
    assert all("|| true" not in line for line in sidecar_invocations)
    assert "SIDECAR_DECISION_ARGS" in quick_rescore
    assert "--decision-time-utc" in quick_rescore
    assert "predates lifecycle decision-time CLI" in quick_rescore


def test_terminal_lifecycle_ticker_blocks_standalone_preview() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0, 101.0], start="2026-01-02")
        account_path = root / "account.json"
        account_path.write_text(
            json.dumps(
                {
                    "as_of_date": "2026-01-06",
                    "cash_usd": 0.0,
                    "positions": [
                        {"ticker": "AAA", "shares": 10.0, "cost_basis": 90.0}
                    ],
                }
            ),
            encoding="utf-8",
        )
        target_path = root / "target.csv"
        pd.DataFrame([{"ticker": "CASH", "weight": 1.0}]).to_csv(
            target_path, index=False
        )
        lifecycle_path = root / "security_lifecycle_events.csv"
        pd.DataFrame(
            [
                {
                    "stable_security_id": "SECURITY:AAA",
                    "stable_issuer_id": "ISSUER:AAA",
                    "ticker": "AAA",
                    "aliases": "AAA",
                    "event_type": "cash_merger",
                    "available_from": "2026-01-06T13:00:00Z",
                    "effective_date": "2026-01-06",
                    "last_trading_date": "2026-01-05",
                    "predecessor_security_id": "",
                    "successor_security_id": "",
                    "successor_ticker": "",
                    "cash_consideration": "110.00",
                    "delisting_proceeds": "",
                    "currency": "USD",
                    "source_url": "https://example.test/aaa",
                    "accession_number": "0000000000-26-000001",
                    "stable_event_id": "EVENT:AAA:20260106",
                    "source_sha256": "a" * 64,
                    "exact_available_from": "true",
                    "evidence_status": "verified",
                    "review_status": "approved",
                    "notes": "terminal preview fixture",
                }
            ],
            columns=sorted(REQUIRED_COLUMNS),
        ).to_csv(lifecycle_path, index=False)
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target_path)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = "2026-01-06"
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        args.provider_symbol_override = []
        args.security_lifecycle_events = str(lifecycle_path)
        args.decision_time_utc = "2026-01-06T23:00:00Z"
        with raises_value_error("lifecycle_terminal_ticker_untradeable:AAA"):
            run(args)


def test_cli_lifecycle_uses_selected_target_decision_time() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        out = root / "preview"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0], start="2026-01-06")
        _write_px(cache, "BBB", [110.0], start="2026-01-06")
        account_path = root / "account.json"
        account_path.write_text(
            json.dumps(
                {
                    "as_of_date": "2026-01-02",
                    "cash_usd": 1000.0,
                    "positions": [],
                }
            ),
            encoding="utf-8",
        )
        target_path = root / "target.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "AAA",
                    "weight": 0.50,
                    "selector_decision_time_utc": "2026-01-02T21:00:00Z",
                },
                {
                    "rebalance_date": "2026-01-06",
                    "ticker": "BBB",
                    "weight": 0.50,
                    "selector_decision_time_utc": "2026-01-06T21:00:00Z",
                },
            ]
        ).to_csv(target_path, index=False)
        lifecycle_path = root / "security_lifecycle_events.csv"
        pd.DataFrame(columns=sorted(REQUIRED_COLUMNS)).to_csv(
            lifecycle_path, index=False
        )
        args = Args()
        args.account_state = str(account_path)
        args.target = str(target_path)
        args.price_cache = str(cache)
        args.portfolio_kind = "main"
        args.output_dir = str(out)
        args.as_of_date = ""
        args.target_date = ""
        args.cost_bps = 25.0
        args.limit_margin_pct = 0.25
        args.min_trade_usd = 25.0
        args.fractional_shares = False
        args.provider_symbol_override = []
        args.security_lifecycle_events = str(lifecycle_path)
        args.decision_time_utc = ""
        payload = run(args)
        assert payload["status"] == "completed"
        assert payload["as_of_date"] == "2026-01-06"
        assert payload["lifecycle_decision_time_utc"] == "2026-01-06T21:00:00+00:00"
        selected_target = pd.read_csv(out / "target_weights.csv")
        assert set(selected_target["ticker"]) == {"BBB", "CASH"}
        assert abs(float(selected_target["target_weight"].sum()) - 1.0) < 1e-12
        args.decision_time_utc = "2026-01-05T21:00:00Z"
        with raises_value_error("lifecycle_decision_time_mismatch_with_selected_target"):
            run(args)


def test_target_date_uses_the_same_older_snapshot_decision_time() -> None:
    frame = pd.DataFrame(
        [
            {
                "rebalance_date": "2026-01-02",
                "ticker": "AAA",
                "weight": 0.50,
                "selector_decision_time_utc": "2026-01-02T21:00:00Z",
            },
            {
                "rebalance_date": "2026-01-06",
                "ticker": "BBB",
                "weight": 0.50,
                "selector_decision_time_utc": "2026-01-06T21:00:00Z",
            },
        ]
    )
    selected = select_target_snapshot(
        frame,
        target_date="2026-01-02",
        as_of_date=pd.Timestamp("2026-01-06"),
    )
    assert selected["ticker"].tolist() == ["AAA"]
    assert selected["selector_decision_time_utc"].tolist() == ["2026-01-02T21:00:00Z"]


def main() -> int:
    test_order_preview_builds_sell_first_orders()
    test_concentrated_target_normalization_does_not_force_n3()
    test_order_preview_uses_explicit_cash_target_weight()
    test_lifecycle_price_switches_only_after_predecessor_last_trade()
    test_lifecycle_price_does_not_cross_cutover_on_missing_successor()
    test_lifecycle_price_rejects_stale_successor_after_cutover()
    test_lifecycle_price_rejects_future_only_successor_cache()
    test_post_cutover_orders_use_successor_ticker()
    test_standalone_lifecycle_resolves_successor_before_as_of_inference()
    test_post_cutover_new_target_requires_successor_exact_close()
    test_cli_and_operational_invocations_require_lifecycle_evidence()
    test_terminal_lifecycle_ticker_blocks_standalone_preview()
    test_cli_lifecycle_uses_selected_target_decision_time()
    test_target_date_uses_the_same_older_snapshot_decision_time()
    print("account_order_preview_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
