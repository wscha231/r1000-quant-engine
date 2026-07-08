import pandas as pd

from tools.run287_13f_fixedbook_ab import load_miss_set, revert_rows
from tools.run287_13f_pit_gate import audit_13f_pit


def test_13f_pit_gate_uses_available_from_not_period_end(tmp_path):
    holdings = pd.DataFrame(
        [
            {
                "manager_cik": "1",
                "report_period": "2024-03-31",
                "accepted_at": "2024-05-15T20:00:00Z",
                "available_from": "2024-05-15T20:00:00Z",
                "ticker_mapped": "AAA",
                "shares": 100,
                "market_value_usd": 1000,
            },
            {
                "manager_cik": "1",
                "report_period": "2024-06-30",
                "accepted_at": "2024-08-14T20:00:00Z",
                "available_from": "2024-08-14T20:00:00Z",
                "ticker_mapped": "AAA",
                "shares": 200,
                "market_value_usd": 2500,
            },
        ]
    )
    holdings_path = tmp_path / "holdings.csv"
    holdings.to_csv(holdings_path, index=False)
    miss = pd.DataFrame(
        [
            {
                "rebalance_date": "2024-08-30",
                "latest_13f_available_from": "2024-08-14T20:00:00Z",
            }
        ]
    )
    miss_path = tmp_path / "miss.csv"
    miss.to_csv(miss_path, index=False)

    payload = audit_13f_pit(holdings_path, miss_path)

    assert payload["pit_gate_status"] == "clean"
    assert payload["available_from_field"] == "available_from"
    assert payload["uses_period_end"] is False
    assert payload["median_lag_days_period_end_to_available_from"] >= 40
    assert payload["rows_with_available_from_after_decision_date"] == 0


def test_13f_pit_gate_blocks_period_end_like_available_from(tmp_path):
    holdings = pd.DataFrame(
        [
            {
                "manager_cik": "1",
                "report_period": "2024-03-31",
                "accepted_at": "2024-03-31T20:00:00Z",
                "available_from": "2024-03-31T20:00:00Z",
                "ticker_mapped": "AAA",
                "shares": 100,
                "market_value_usd": 1000,
            }
        ]
    )
    holdings_path = tmp_path / "holdings.csv"
    holdings.to_csv(holdings_path, index=False)
    miss_path = tmp_path / "miss.csv"
    pd.DataFrame([{"rebalance_date": "2024-04-30", "latest_13f_available_from": "2024-03-31T20:00:00Z"}]).to_csv(
        miss_path, index=False
    )

    payload = audit_13f_pit(holdings_path, miss_path)

    assert payload["pit_gate_status"] == "leaky_period_end"
    assert payload["uses_period_end"] is True


def test_13f_confirmed_candidate_reverts_only_unconfirmed_replacements(tmp_path):
    miss = pd.DataFrame(
        [
            {
                "rebalance_date": "2024-07-31",
                "ticker": "WIN",
                "concentrated_replacement_quality_added_ticker": "WIN",
                "concentrated_replacement_quality_removed_ticker": "OLD",
                "concentrated_replacement_quality_replacement_weight": 0.2,
                "period_forward_return": 0.10,
                "latest_13f_available_from": "2024-05-15T20:00:00Z",
            },
            {
                "rebalance_date": "2024-08-30",
                "ticker": "MISS",
                "concentrated_replacement_quality_added_ticker": "MISS",
                "concentrated_replacement_quality_removed_ticker": "DONOR",
                "concentrated_replacement_quality_replacement_weight": 0.2,
                "period_forward_return": -0.10,
                "latest_13f_available_from": "2024-05-15T20:00:00Z",
            },
        ]
    )
    miss_path = tmp_path / "miss.csv"
    miss.to_csv(miss_path, index=False)
    lookup = pd.DataFrame(
        [
            {"rebalance_date": "2024-07-31", "ticker": "WIN", "w4_13f_score": 0.25},
            {"rebalance_date": "2024-08-30", "ticker": "MISS", "w4_13f_score": -0.05},
        ]
    )

    loaded, meta = load_miss_set(miss_path, lookup)
    base = pd.DataFrame(
        [
            {"rebalance_date": "2024-07-31", "ticker": "WIN", "Name": "WIN", "weight": 0.2, "target_weight": 0.2},
            {"rebalance_date": "2024-07-31", "ticker": "CASH", "Name": "CASH", "weight": 0.8, "target_weight": 0.8},
            {"rebalance_date": "2024-08-30", "ticker": "MISS", "Name": "MISS", "weight": 0.2, "target_weight": 0.2},
            {"rebalance_date": "2024-08-30", "ticker": "CASH", "Name": "CASH", "weight": 0.8, "target_weight": 0.8},
        ]
    )

    hook_off, hook_off_swaps = revert_rows(base, loaded, revert_confirmed=True)
    candidate, candidate_reverts = revert_rows(base, loaded, revert_confirmed=False)

    assert meta["confirmed_swap_count"] == 1
    assert set(hook_off["ticker"]) == {"OLD", "DONOR", "CASH"}
    assert set(candidate["ticker"]) == {"WIN", "DONOR", "CASH"}
    assert len(hook_off_swaps[hook_off_swaps["action"].eq("revert_added_to_removed")]) == 2
    assert len(candidate_reverts[candidate_reverts["action"].eq("revert_added_to_removed")]) == 1
