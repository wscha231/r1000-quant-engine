#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_public_portfolio_dashboard import (  # noqa: E402
    build_dashboard,
    latest_close_payload_is_safe,
    validate_public_payload,
)
from tests.run287_paper_ledger_transaction_smoke import (  # noqa: E402
    write_prices,
    write_replay_price_manifest,
)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_market_gate(source: Path, session_date: str) -> None:
    gate = source / "daily_market_session_gate"
    write_json(
        gate / "session.json",
        {
            "status": "READY_COMPLETED_SESSION",
            "ready": True,
            "session_date": session_date,
            "weekend_and_holiday_aware": True,
            "early_close_aware": True,
        },
    )
    write_json(
        gate / "close_price_coverage.json",
        {
            "status": "PASS",
            "session_date": session_date,
            "exact_close_coverage": True,
            "missing_ticker_count": 0,
            "prior_session_fallback_allowed": False,
        },
    )


def write_latest_close_metrics(
    current: Path,
    session_date: str,
    *,
    main_cagr: float = 0.34,
    concentrated_cagr: float = 0.48,
) -> None:
    portfolios = {}
    for portfolio, cagr, max_dd in (
        ("main", main_cagr, -0.25),
        ("concentrated", concentrated_cagr, -0.23),
    ):
        portfolios[portfolio] = {
            "latest_close_chain_linked": {
                "status": "LATEST_CLOSE_DIAGNOSTIC",
                "cagr": cagr,
                "max_drawdown": max_dd,
                "max_drawdown_exact": False,
                "max_drawdown_bound_direction": (
                    "optimistic_lower_bound_on_loss_magnitude;"
                    "exact_chain_mdd_can_be_more_negative"
                ),
                "max_drawdown_method": (
                    "minimum_of_locked_historical_mdd_and_"
                    "paper_operating_mdd"
                ),
                "cagr_endpoint_chain_exact": True,
                "start_date": "2019-06-03",
                "end_date": session_date,
                "metric_mode": (
                    "locked_historical_endpoint_chain_linked_to_"
                    "accepted_paper_marks"
                ),
                "historical_metric_replacement_allowed": False,
                "promotion_evidence_allowed": False,
            },
            "operating_since_seed": {
                "end_date": session_date,
                "total_return": -0.01,
                "max_drawdown": -0.02,
                "durable_catchup_marks_included": True,
                "historical_metric_replacement_allowed": False,
            }
        }
    write_json(
        current / "04_official_metrics.json",
        {
            "main": {
                "cagr": 0.35,
                "max_dd": -0.24,
                "sharpe": 1.7,
                "avg_cash_weight": 0.18,
                "trade_count": 43,
                "windows": {
                    "oos": {"cagr": 0.31, "max_dd": -0.21},
                    "oos2": {"cagr": 0.29, "max_dd": -0.20},
                },
            },
            "concentrated": {
                "cagr": 0.51,
                "max_dd": -0.22,
                "sharpe": 1.6,
                "avg_cash_weight": 0.22,
                "trade_count": 27,
                "windows": {
                    "oos": {"cagr": 0.46, "max_dd": -0.23},
                    "oos2": {"cagr": 0.44, "max_dd": -0.22},
                },
            },
            "latest_close_performance": {
                "schema_version": "run287-latest-close-performance-v1",
                "status": "READY_LATEST_CLOSE_REVIEW_ONLY",
                "as_of_date": session_date,
                "latest_close_exact": True,
                "accepted_close_marks_include_durable_catchup": True,
                "portfolios": portfolios,
                "review_only": True,
                "live_trading_enabled": False,
                "production_activation_allowed": False,
                "historical_cagr_mdd_replacement_allowed": False,
                "promotion_evidence_allowed": False,
                "fullrun_executed": False,
            }
        },
    )


def build_replay_fixture(root: Path) -> Path:
    source = root / "replay"
    for portfolio, ticker, cash, cagr, max_dd in [
        ("main", "AAA", 0.20, 0.35, -0.24),
        ("concentrated", "BBB", 0.35, 0.51, -0.22),
    ]:
        target = source / "replays" / portfolio
        write_csv(
            target / "positions_latest.csv",
            [
                {
                    "as_of_date": "2026-07-10",
                    "ticker": ticker,
                    "shares": "100",
                    "price": "125.5",
                    "market_value_usd": "12550",
                    "weight": str(1.0 - cash),
                    "cost_basis": "90",
                    "unrealized_pnl_usd": "3550",
                }
            ],
        )
        write_csv(
            target / "equity_curve.csv",
            [
                {"date": "2019-06-03", "equity_usd": "100000", "cash_weight": str(cash)},
                {"date": "2026-07-10", "equity_usd": "800000", "cash_weight": str(cash)},
            ],
        )
        write_csv(
            target / "trades.csv",
            [
                {
                    "ticker": ticker,
                    "side": "BUY",
                    "quantity": "100",
                    "fill_price": "100",
                    "gross_value": "10000",
                    "fee_usd": "25",
                    "cash_after": "90000",
                    "shares_after": "100",
                    "date": "2026-07-06",
                    "signal_date": "2026-07-02",
                    "reason": "target_rebalance",
                    "target_weight": str(1.0 - cash),
                    "fill_mode": "next_close",
                }
            ],
        )
        write_json(
            target / "metrics.json",
            {
                "portfolio_kind": portfolio,
                "cagr": cagr,
                "max_dd": max_dd,
                "sharpe": 1.4,
                "avg_cash_weight": cash,
                "trade_count": 42,
                "start_date": "2019-06-03",
                "end_date": "2026-07-10",
                "metric_mode": "broker_ledger_next_close_cash_carry",
                "fill_mode": "next_close",
                "cost_bps_per_side": 25,
                "valid_for_production": False,
                "target_book": r"H:\private\target.csv",
                "starting_capital_usd": 100000,
                "ending_capital_usd": 800000,
            },
        )
    return source


def test_replay_export_is_privacy_safe() -> None:
    with TemporaryDirectory() as tmp:
        source = build_replay_fixture(Path(tmp))
        payload = build_dashboard(source)
        validate_public_payload(payload)

        assert payload["as_of_close"] == "2026-07-10"
        assert payload["status"]["review_only"] is True
        assert payload["status"]["live_trading_enabled"] is False
        assert payload["portfolios"]["main"]["cash_weight"] == 0.20
        assert payload["portfolios"]["main"]["holdings"][0]["ticker"] == "AAA"
        assert payload["portfolios"]["main"]["trades"][0]["side"] == "BUY"
        assert payload["portfolios"]["main"]["trades"][0]["record_type"] == "BACKTEST"

        encoded = json.dumps(payload).lower()
        for forbidden in [
            '"market_value_usd":',
            '"shares_after":',
            '"quantity":',
            '"cost_basis":',
            '"unrealized_pnl_usd":',
            '"ending_capital_usd":',
            r"h:\private",
        ]:
            assert forbidden not in encoded, forbidden


def test_daily_artifact_refreshes_holdings_but_not_fake_trades() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = build_dashboard(build_replay_fixture(root))
        base_path = root / "dashboard.json"
        write_json(base_path, base)

        current = root / "daily" / "user_current"
        write_market_gate(root / "daily", "2026-07-11")
        write_json(
            current / "summary.json",
            {
                "review_only": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "source_run_id": "123",
                "source_commit_sha": "abc",
            },
        )
        write_csv(
            current / "01_current_holdings.csv",
            [
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "NEW",
                    "current_weight": "0.70",
                    "current_shares": "77",
                    "current_price": "200",
                    "as_of_date": "2026-07-11",
                },
                {
                    "portfolio_kind": "main",
                    "row_type": "cash",
                    "ticker": "CASH",
                    "current_weight": "0.30",
                    "current_shares": "0",
                    "current_price": "1",
                    "as_of_date": "2026-07-11",
                },
                {
                    "portfolio_kind": "concentrated",
                    "row_type": "equity",
                    "ticker": "BBB",
                    "current_weight": "0.65",
                    "current_shares": "99",
                    "current_price": "130",
                    "as_of_date": "2026-07-11",
                },
            ],
        )
        write_csv(
            current / "02_target_weights.csv",
            [
                {"portfolio_kind": "main", "ticker": "NEW", "target_weight": "0.75"},
                {"portfolio_kind": "main", "ticker": "CASH", "target_weight": "0.25"},
            ],
        )
        write_csv(
            current / "03_order_preview.csv",
            [
                {
                    "portfolio_kind": "main",
                    "ticker": "NEW",
                    "action": "REVIEW_REQUIRED",
                    "current_weight": "0.70",
                    "target_weight": "0.75",
                    "delta_weight": "0.05",
                    "reference_price": "200",
                    "quantity": "15",
                }
            ],
        )
        write_json(
            current / "08_rebalance_decision.json",
            {"decision": "REVIEW_REQUIRED", "live_trading_enabled": False},
        )
        write_latest_close_metrics(
            current,
            "2026-07-11",
            main_cagr=0.341,
            concentrated_cagr=0.481,
        )

        payload = build_dashboard(root / "daily", base_json=base_path)
        validate_public_payload(payload)
        assert payload["as_of_close"] == "2026-07-11"
        assert payload["source"]["mode"] == "daily_operating_review_artifact"
        assert payload["source"]["trade_history_status"] == "retained_from_last_validated_replay"
        assert payload["portfolios"]["main"]["holdings"][0]["ticker"] == "NEW"
        assert payload["portfolios"]["main"]["target_cash_weight"] == 0.25
        assert payload["portfolios"]["main"]["trades"][0]["ticker"] == "AAA"
        assert payload["portfolios"]["main"]["metrics"]["cagr"] == 0.341
        assert payload["portfolios"]["main"]["metrics"]["sharpe"] == 1.7
        assert payload["portfolios"]["main"]["metrics"]["oos_cagr"] == 0.31
        assert payload["portfolios"]["main"]["metrics"]["trade_count"] == 43
        assert (
            payload["portfolios"]["main"]["metrics"][
                "max_drawdown_exact"
            ]
            is False
        )
        assert payload["portfolios"]["main"]["metrics"]["end_date"] == (
            "2026-07-11"
        )
        assert payload["order_previews"][0]["executed"] is False
        assert '"quantity":' not in json.dumps(payload).lower()


def test_daily_artifact_merges_only_safe_forward_paper_fills() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = build_dashboard(build_replay_fixture(root))
        base_path = root / "dashboard.json"
        write_json(base_path, base)

        daily = root / "daily"
        write_market_gate(daily, "2026-07-14")
        current = daily / "user_current"
        write_json(
            current / "summary.json",
            {
                "review_only": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "source_run_id": "456",
                "source_commit_sha": "def",
            },
        )
        write_csv(
            current / "01_current_holdings.csv",
            [
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "NEW",
                    "current_weight": "0.70",
                    "current_price": "201",
                    "as_of_date": "2026-07-14",
                },
                {
                    "portfolio_kind": "concentrated",
                    "row_type": "equity",
                    "ticker": "BBB",
                    "current_weight": "0.65",
                    "current_price": "131",
                    "as_of_date": "2026-07-14",
                },
            ],
        )
        write_csv(current / "02_target_weights.csv", [{"portfolio_kind": "main", "ticker": "NEW", "target_weight": "0.70"}])
        write_csv(current / "03_order_preview.csv", [])
        write_json(current / "08_rebalance_decision.json", {"decision": "HOLD", "live_trading_enabled": False})
        write_latest_close_metrics(current, "2026-07-14")

        ledger = daily / "daily_simulated_fill_ledger"
        write_json(
            ledger / "summary.json",
            {
                "review_only": True,
                "simulated": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
            },
        )
        for portfolio, count in [("main", 1), ("concentrated", 0)]:
            write_json(
                ledger / portfolio / "manifest.json",
                {
                    "review_only": True,
                    "simulated": True,
                    "live_trading_enabled": False,
                    "production_mutation_allowed": False,
                    "historical_cagr_mdd_replacement_allowed": False,
                    "fill_mode": "next_close",
                    "cost_bps_per_side": 25.0,
                    "fill_count": count,
                },
            )
        write_csv(
            ledger / "main" / "fills.csv",
            [
                {
                    "event_type": "FILL",
                    "execution_status": "SIMULATED_FILL",
                    "date": "2026-07-14",
                    "signal_date": "2026-07-13",
                    "ticker": "NEW",
                    "side": "BUY",
                    "quantity": "12",
                    "fill_price": "201",
                    "fee_usd": "6.03",
                    "cash_after": "12345",
                    "target_weight": "0.70",
                    "reason": "target_rebalance",
                    "fill_mode": "next_close",
                    "review_only": "True",
                    "simulated": "True",
                    "live_trading_enabled": "False",
                    "production_mutation_allowed": "False",
                }
            ],
        )
        write_csv(ledger / "concentrated" / "fills.csv", [])

        payload = build_dashboard(daily, base_json=base_path)
        validate_public_payload(payload)
        trades = payload["portfolios"]["main"]["trades"]
        assert trades[0]["ticker"] == "NEW"
        assert trades[0]["record_type"] == "FORWARD_PAPER"
        assert payload["source"]["trade_history_status"] == "validated_replay_plus_forward_paper_fills"
        assert payload["source"]["forward_paper_fill_count"] == 1
        encoded = json.dumps(payload).lower()
        for forbidden in ['"quantity":', '"fee_usd":', '"cash_after":']:
            assert forbidden not in encoded, forbidden

        write_prices(
            root / "prices",
            "AAA",
            ["2026-07-14"],
            [100.0],
        )
        write_prices(
            root / "prices",
            "BBB",
            ["2026-07-14"],
            [100.0],
        )
        write_replay_price_manifest(root, "2026-07-14")
        shutil.copytree(
            root / "prices",
            ledger / "replay_price_evidence" / "2026-07-14",
        )
        replay_payload = build_dashboard(
            daily,
            base_json=base_path,
        )
        replay_trades = replay_payload["portfolios"]["main"]["trades"]
        assert replay_trades[0]["record_type"] == "FORWARD_PAPER_REPLAY"
        assert replay_payload["source"]["forward_paper_fill_count"] == 0
        assert replay_payload["source"]["replay_paper_fill_count"] == 1


def test_daily_artifact_rejects_stale_or_missing_close_gate() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = build_dashboard(build_replay_fixture(root))
        base_path = root / "dashboard.json"
        write_json(base_path, base)
        daily = root / "daily"
        current = daily / "user_current"
        write_json(
            current / "summary.json",
            {"review_only": True, "live_trading_enabled": False, "production_mutation_allowed": False},
        )
        write_csv(
            current / "01_current_holdings.csv",
            [
                {
                    "portfolio_kind": "main",
                    "row_type": "equity",
                    "ticker": "AAA",
                    "current_weight": "0.8",
                    "as_of_date": "2026-07-14",
                }
            ],
        )
        write_csv(current / "02_target_weights.csv", [])
        write_csv(current / "03_order_preview.csv", [])
        write_json(current / "08_rebalance_decision.json", {"decision": "HOLD"})
        write_latest_close_metrics(current, "2026-07-11")

        try:
            build_dashboard(daily, base_json=base_path)
        except ValueError as exc:
            assert "market-session gate" in str(exc)
        else:
            raise AssertionError("missing market gate must block public refresh")

        write_market_gate(daily, "2026-07-11")
        try:
            build_dashboard(daily, base_json=base_path)
        except ValueError as exc:
            assert "does not match completed session" in str(exc)
        else:
            raise AssertionError("stale market gate must block public refresh")


def test_latest_close_safety_contract_rejects_incomplete_payloads() -> None:
    with TemporaryDirectory() as tmp:
        current = Path(tmp)
        write_latest_close_metrics(current, "2026-07-24")
        official = json.loads(
            (current / "04_official_metrics.json").read_text(
                encoding="utf-8"
            )
        )
        safe = official["latest_close_performance"]
        assert latest_close_payload_is_safe(
            safe,
            expected_session_date="2026-07-24",
        )

        mutations = [
            lambda payload: payload.update(
                {"latest_close_exact": False}
            ),
            lambda payload: payload.update(
                {"as_of_date": "2026-07-23"}
            ),
            lambda payload: payload.update(
                {"fullrun_executed": True}
            ),
            lambda payload: payload["portfolios"].pop("concentrated"),
            lambda payload: payload["portfolios"]["main"].pop(
                "operating_since_seed"
            ),
            lambda payload: payload["portfolios"]["main"][
                "latest_close_chain_linked"
            ].pop("max_drawdown_bound_direction"),
        ]
        for mutate in mutations:
            candidate = json.loads(json.dumps(safe))
            mutate(candidate)
            assert not latest_close_payload_is_safe(
                candidate,
                expected_session_date="2026-07-24",
            )


def test_static_site_references_only_public_assets() -> None:
    html = (ROOT / "docs" / "public" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "docs" / "public" / "app.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "docs" / "public" / "styles.css").read_text(encoding="utf-8")
    assert "./styles.css" in html
    assert "./app.js" in html
    assert 'id="allocation-donuts"' in html
    assert 'id="trade-section"' in html and "매수·매도 기록" in html
    assert 'id="load-more-trades"' in html
    assert "data-ledger-portfolio" in javascript
    assert "conic-gradient" in javascript
    assert "openTradeLedger" in javascript and "closeTradeLedger" in javascript
    assert "FORWARD_PAPER" in javascript and "Forward 모의" in javascript
    assert ".donut-chart" in stylesheet and ".ledger-open" in stylesheet and ".record-forward" in stylesheet
    assert "CODEX_" not in html
    assert "AGENT_SHARED" not in html
    assert "noindex, nofollow" in html


def main() -> int:
    test_replay_export_is_privacy_safe()
    test_daily_artifact_refreshes_holdings_but_not_fake_trades()
    test_daily_artifact_merges_only_safe_forward_paper_fills()
    test_daily_artifact_rejects_stale_or_missing_close_gate()
    test_latest_close_safety_contract_rejects_incomplete_payloads()
    test_static_site_references_only_public_assets()
    print("public_portfolio_dashboard_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
