#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_pit_estimate_guidance_sample_request import build_request, write_outputs  # noqa: E402


def current_universe() -> pd.DataFrame:
    sectors = ["Technology", "Financials", "Health Care", "Industrials"]
    rows = []
    for index in range(24):
        rows.append(
            {
                "ticker": f"T{index:02d}",
                "Name": f"Issuer {index:02d}",
                "sector": sectors[index % len(sectors)],
                "is_equity_issuer": True,
                "is_adr_global_listing": index < 4,
            }
        )
    rows.append(
        {
            "ticker": "CASH",
            "Name": "Cash",
            "sector": "",
            "is_equity_issuer": False,
            "is_adr_global_listing": False,
        }
    )
    return pd.DataFrame(rows)


def delisted_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "security_id": "PERM-OLD-1",
                "ticker": "OLD1",
                "name": "Old Issuer 1",
                "sector": "Technology",
                "is_delisted": True,
                "is_adr_global_listing": False,
            },
            {
                "security_id": "PERM-OLD-2",
                "ticker": "OLD2",
                "name": "Old Issuer 2",
                "sector": "Industrials",
                "is_delisted": True,
                "is_adr_global_listing": False,
            },
        ]
    )


def outcome_contract() -> dict[str, object]:
    return {
        "schema_version": "fixture-v1",
        "horizons": [
            {"trading_days": 21, "role": "short_support"},
            {"trading_days": 63, "role": "primary"},
            {"trading_days": 126, "role": "intermediate_support"},
            {"trading_days": 252, "role": "long_confirmation"},
            {"trading_days": 504, "role": "long_sensitivity"},
        ],
    }


def test_complete_request_is_deterministic_and_long_horizon_ready() -> None:
    args = {
        "current_universe": current_universe(),
        "delisted_candidates": delisted_candidates(),
        "outcome_contract": outcome_contract(),
        "sample_size": 10,
        "delisted_count": 2,
        "min_adr": 2,
        "seed": "fixed-seed",
    }
    summary, sample, full_request = build_request(**args)
    summary2, sample2, _ = build_request(**args)
    assert summary["status"] == "READY_ZERO_COST_SCHEMA_REQUEST"
    assert summary2["status"] == summary["status"]
    assert sample["request_row_id"].tolist() == sample2["request_row_id"].tolist()
    assert sample["ticker"].tolist() == sample2["ticker"].tolist()
    assert len(sample) == 10
    assert int(sample["is_delisted"].sum()) == 2
    assert int(sample["is_adr_global_listing"].sum()) == 2
    assert sample["required_horizons_trading_days"].eq("21|63|126|252|504").all()
    assert len(full_request) == 24
    assert summary["historical_union_security_count"] is None
    assert summary["selection_uses_return_labels"] is False
    assert summary["purchase_authorized"] is False
    assert summary["returns_joined"] is False
    assert summary["fullrun_dispatched"] is False
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp)
        write_outputs(output, summary, sample, full_request)
        persisted = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert persisted["required_return_horizons_trading_days"] == [21, 63, 126, 252, 504]
        assert len(persisted["output_hashes"]["sample_request_sha256"]) == 64
        assert len(persisted["output_hashes"]["provider_request_sha256"]) == 64
        assert (output / "sample_request.csv").exists()
        provider_request = (output / "provider_request.md").read_text(encoding="utf-8")
        assert "no-cost schema and coverage evaluation request" in provider_request
        assert "not a purchase order" in provider_request
        assert "252 days is powered long confirmation" in provider_request
        assert "five deterministic historical-delisted query slots" in provider_request


def test_missing_delisted_source_emits_deterministic_provider_slots() -> None:
    summary, sample, _ = build_request(
        current_universe=current_universe(),
        delisted_candidates=pd.DataFrame(),
        outcome_contract=outcome_contract(),
        sample_size=10,
        delisted_count=2,
        min_adr=2,
        seed="fixed-seed",
    )
    assert summary["status"] == "READY_ZERO_COST_SCHEMA_REQUEST_WITH_PROVIDER_DELISTED_QUERY"
    assert summary["provider_delisted_query_slots"] == 2
    slots = sample[sample["sample_role"].eq("historical_delisted_provider_query")]
    assert len(slots) == 2
    assert slots["security_id"].eq("").all()
    assert slots["provider_action"].str.contains("sort_sha256", regex=False).all()
    assert summary["purchase_authorized"] is False


def test_missing_long_horizon_blocks_request_contract() -> None:
    contract = outcome_contract()
    contract["horizons"] = [row for row in contract["horizons"] if row["trading_days"] != 504]
    summary, _, _ = build_request(
        current_universe=current_universe(),
        delisted_candidates=delisted_candidates(),
        outcome_contract=contract,
        sample_size=10,
        delisted_count=2,
        min_adr=2,
    )
    assert summary["status"] == "BLOCKED_REQUEST_CONTRACT"
    assert "outcome_contract_missing_required_horizons" in summary["blockers"]


def main() -> None:
    test_complete_request_is_deterministic_and_long_horizon_ready()
    test_missing_delisted_source_emits_deterministic_provider_slots()
    test_missing_long_horizon_blocks_request_contract()
    print("pit_estimate_guidance_sample_request_smoke: PASS")


if __name__ == "__main__":
    main()
