"""Reproduce audited legacy defects with synthetic data, without importing the engine.

Success means the failures are reproduced, not fixed. No network, collection,
portfolio execution or output-file mutation occurs. Source changes require a
new audit; never silently weaken the expected source hash to make this pass.
"""

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


EXPECTED_SOURCE_SHA256 = (
    "736f98c5668f2012f9ae3ce309c24f01d465960a50a45bb74f1165b3da6a258f"
)


def main():
    source = Path(__file__).resolve().parents[2] / "r1000_pipeline.py"
    source_bytes = source.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SystemExit("AUDIT_SOURCE_CHANGED: rerun an audit of the new implementation")

    names = {
        "infer_fiscal_year_end_month",
        "infer_quarter_from_period",
        "companyfacts_quarter_index",
        "companyfacts_quarterly_flows",
        "prep_num",
    }
    nodes = [
        node for node in ast.parse(source_bytes.decode("utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    if len(nodes) != len(names):
        raise SystemExit("AUDIT_FUNCTION_SET_CHANGED")
    scope = {
        "pd": pd, "np": np, "re": re, "Any": Any, "Optional": Optional,
        "safe_float": lambda x: float(x) if x is not None else np.nan,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)

    rows = []
    for fp, period, accepted, duration, value in [
        ("Q1", "2024-03-31", "2024-05-01", 91, 100),
        ("Q2", "2024-06-30", "2024-08-01", 182, 250),
        ("Q1", "2024-03-31", "2025-05-01", 91, 120),
    ]:
        rows.append({
            "cik": "0000000001", "field_name": "revenues", "fy": 2024,
            "fp": fp, "frame": None, "period": pd.Timestamp(period),
            "accepted": pd.Timestamp(accepted), "duration_days": duration,
            "value": value,
        })
    decision = pd.Timestamp("2024-08-02")
    all_rows = pd.DataFrame(rows)
    flows = scope["companyfacts_quarterly_flows"]
    past = flows(all_rows[all_rows.accepted <= decision])
    whole = flows(all_rows)
    first = float(past.loc[past.q_idx == 2, "flow"].iloc[0])
    second = float(whole.loc[whole.q_idx == 2, "flow"].iloc[0])
    availability = whole.loc[whole.q_idx == 2, "accepted"].iloc[0]
    if not (first == 150 and second == 130 and availability < decision):
        raise SystemExit("QUARTER_FLOW_COUNTEREXAMPLE_NOT_REPRODUCED")

    num = pd.DataFrame([{
        "adsh": "0000000001-24-000001", "tag": "Assets", "ddate": 20240331,
        "qtrs": 0, "uom": "USD", "value": 100, "version": "us-gaap/2024",
        "segments": "example-axis=example-member", "coreg": "",
    }])
    parsed = scope["prep_num"](num)
    observed_date = parsed.ddate.iloc[0].isoformat()
    dropped = sorted(set(num.columns) - set(parsed.columns))
    if observed_date != "1970-01-01T00:00:00.020240331":
        raise SystemExit("FSDS_DATE_COUNTEREXAMPLE_NOT_REPRODUCED")
    if dropped != ["coreg", "segments", "version"]:
        raise SystemExit("FSDS_CONTEXT_COUNTEREXAMPLE_NOT_REPRODUCED")

    print(json.dumps({
        "status": "FAILURE_REPRODUCTION_SUCCESS",
        "case": "legacy_quarter_flow_uses_future_q1_revision",
        "data_kind": "SYNTHETIC_COUNTEREXAMPLE_NOT_PERFORMANCE",
        "source_sha256": source_hash,
        "decision_date": str(decision.date()),
        "future_revision_date": "2025-05-01",
        "correct_then_known_q2": first,
        "legacy_q2_after_future_row_added": second,
        "legacy_q2_available_at": str(availability.date()),
        "reproduced": True,
        "fsds_integer_date_case": {
            "input_ddate": 20240331, "expected_date": "2024-03-31",
            "observed_date": observed_date,
            "context_columns_dropped": dropped, "reproduced": True,
        },
    }, indent=2))


if __name__ == "__main__":
    main()
