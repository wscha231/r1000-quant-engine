#!/usr/bin/env python3
"""Smoke test for concentrated cap/replacement audit."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_concentrated_cap_replacement_audit import run  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        stock = root / "stock_selection_quality"
        out = root / "out"
        rows = [
            {
                "portfolio": "concentrated",
                "ticker": "WIN",
                "rebalance_date": "2026-01-31",
                "theme": "Semiconductors",
                "sector": "Information Technology",
                "subindustry": "Semiconductors",
                "rejection_reason": "cap_or_replacement",
                "leader_rank_ex_ante": 2,
                "rs_spy_3m": 0.35,
                "rs_spy_6m": 0.60,
                "revenue_growth": 0.22,
                "liquidity_score": 600_000_000,
                "forward_21d_excess": 0.10,
                "forward_63d_excess": 0.30,
                "forward_126d_excess": 0.80,
                "used_forward_return_in_ranking": False,
            },
            {
                "portfolio": "concentrated",
                "ticker": "OK",
                "rebalance_date": "2026-01-31",
                "theme": "Software",
                "sector": "Information Technology",
                "rejection_reason": "cap_or_replacement",
                "leader_rank_ex_ante": 12,
                "rs_spy_3m": 0.22,
                "rs_spy_6m": 0.25,
                "revenue_growth": 0.05,
                "liquidity_score": 100_000_000,
                "forward_126d_excess": 0.12,
                "used_forward_return_in_ranking": False,
            },
            {
                "portfolio": "concentrated",
                "ticker": "WIN2",
                "rebalance_date": "2026-02-28",
                "theme": "Semiconductors",
                "sector": "Information Technology",
                "rejection_reason": "cap_or_replacement",
                "leader_rank_ex_ante": 5,
                "rs_spy_3m": 0.28,
                "rs_spy_6m": 0.40,
                "revenue_growth": 0.18,
                "liquidity_score": 700_000_000,
                "forward_126d_excess": 0.50,
                "used_forward_return_in_ranking": False,
            },
            {
                "portfolio": "concentrated",
                "ticker": "WIN3",
                "rebalance_date": "2026-03-31",
                "theme": "Semiconductors",
                "sector": "Information Technology",
                "rejection_reason": "cap_or_replacement",
                "leader_rank_ex_ante": 8,
                "rs_spy_3m": 0.24,
                "rs_spy_6m": 0.35,
                "revenue_growth": 0.15,
                "liquidity_score": 800_000_000,
                "forward_126d_excess": 0.40,
                "used_forward_return_in_ranking": False,
            },
            {
                "portfolio": "concentrated",
                "ticker": "BAD",
                "rebalance_date": "2026-01-31",
                "theme": "Retail",
                "sector": "Consumer Discretionary",
                "rejection_reason": "cap_or_replacement",
                "leader_rank_ex_ante": 18,
                "rs_spy_3m": -0.05,
                "rs_spy_6m": 0.01,
                "revenue_growth": -0.05,
                "liquidity_score": 50_000_000,
                "forward_126d_excess": -0.30,
                "used_forward_return_in_ranking": False,
            },
            {
                "portfolio": "main",
                "ticker": "MAIN",
                "rebalance_date": "2026-01-31",
                "rejection_reason": "cap_or_replacement",
                "leader_rank_ex_ante": 1,
                "forward_126d_excess": 1.00,
                "used_forward_return_in_ranking": False,
            },
        ]
        write_csv(stock / "missed_leaders_audit.csv", rows)

        payload = run(stock, out)
        assert payload["status"] == "completed", payload
        assert payload["production_activation_allowed"] is False
        assert payload["policy_mutation_allowed"] is False
        assert payload["forward_labels_used_for_ranking"] is False
        assert payload["cap_or_replacement_rows"] == 5
        assert payload["best_rule"]["rule"] != "all_cap_or_replacement"
        assert payload["best_rule"]["labelled_count"] >= 3
        assert payload["best_rule"]["sum_126d_excess"] > 0.0
        rules = pd.read_csv(out / "rule_scan.csv")
        top = pd.read_csv(out / "top_missed_cap_replacement.csv")
        assert "rank_top_10_and_rs3_ge_20pct" in set(rules["rule"])
        assert top.iloc[0]["ticker"] == "WIN"
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["live_trading_enabled"] is False
        assert "Forward returns are audit labels only" in (out / "report.md").read_text(encoding="utf-8")

        contaminated = root / "contaminated"
        contaminated_rows = [dict(rows[0], used_forward_return_in_ranking=True)]
        write_csv(contaminated / "missed_leaders_audit.csv", contaminated_rows)
        contaminated_payload = run(contaminated, root / "contaminated_out")
        assert contaminated_payload["status"] == "blocked_forward_labels_used_for_ranking"
        assert contaminated_payload["production_activation_allowed"] is False
    print("concentrated_cap_replacement_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
