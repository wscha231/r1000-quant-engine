#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ai_capex_taxonomy import classify_row, enrich_frame, taxonomy_table  # noqa: E402


def test_taxonomy_classifies_bottleneck_rows_without_buy_list_semantics() -> None:
    memory = classify_row(
        {
            "ticker": "MU",
            "industry": "Semiconductor Memory",
            "rationale": "HBM tight supply and DRAM ASP up with datacenter backlog",
        }
    )
    assert memory["ai_capex_value_chain_bucket"] == "AI_MEMORY"
    assert memory["ai_capex_bottleneck_score"] > 0.4
    assert memory["ai_capex_source_confidence"] != "unclassified"

    health = classify_row({"ticker": "ABC", "sector": "Health Care", "industry": "Managed Care"})
    assert health["ai_capex_value_chain_bucket"] == "AI_OTHER"


def test_enrich_frame_adds_expected_columns() -> None:
    frame = pd.DataFrame(
        [
            {"ticker": "CRDO", "industry": "Networking", "theme": "AEC ethernet retimer 1.6T"},
            {"ticker": "ZZZ", "industry": "Retail"},
        ]
    )
    out = enrich_frame(frame)
    assert "ai_capex_value_chain_bucket" in out.columns
    assert out.loc[0, "ai_capex_value_chain_bucket"] == "AI_CONNECT"
    assert out.loc[1, "ai_capex_value_chain_bucket"] == "AI_OTHER"
    assert "AI_MEMORY" in set(taxonomy_table()["bucket"])


if __name__ == "__main__":
    test_taxonomy_classifies_bottleneck_rows_without_buy_list_semantics()
    test_enrich_frame_adds_expected_columns()
    print("ai_capex_taxonomy_smoke: PASS")
