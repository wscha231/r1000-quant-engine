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

from tools.run_late_cycle_ai_regime_audit import audit, main  # noqa: E402


def test_regime_audit_flags_late_cycle_ai_without_forcing_trades() -> None:
    revisions = pd.DataFrame(
        [
            {"ticker": "AAA", "sector": "Information Technology", "eps_revision_13w": 0.10, "positive_guidance_flag": 1},
            {"ticker": "BBB", "sector": "Information Technology", "eps_revision_13w": 0.08, "positive_guidance_flag": 1},
        ]
    )
    candidates = pd.DataFrame(
        [
            {"ticker": "AAA", "eps_revision_13w": 0.10, "ai_capex_bottleneck_score": 0.8, "rs_benchmark_3m": 0.2},
            {"ticker": "BBB", "eps_revision_13w": 0.05, "ai_capex_bottleneck_score": 0.7, "rs_benchmark_3m": 0.1},
        ]
    )
    market = pd.DataFrame([{"breadth_above_ma200": 0.55, "forward_pe_vs_10y_avg": 0.25}])
    payload = audit(revisions=revisions, candidates=candidates, market=market)
    assert payload["late_cycle_ai_capex_regime"] is True
    assert payload["bubble_precondition_score"] > 0.55


def test_cli_writes_regime_report() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        revisions = root / "revisions.csv"
        candidates = root / "candidates.csv"
        market = root / "market.csv"
        out = root / "out"
        pd.DataFrame(
            [{"ticker": "AAA", "sector": "Information Technology", "eps_revision_13w": 0.10, "positive_guidance_flag": 1}]
        ).to_csv(revisions, index=False)
        pd.DataFrame([{"ticker": "AAA", "eps_revision_13w": 0.10, "ai_capex_bottleneck_score": 0.8, "rs_benchmark_3m": 0.2}]).to_csv(
            candidates, index=False
        )
        pd.DataFrame([{"breadth_above_ma200": 0.55, "forward_pe_vs_10y_avg": 0.25}]).to_csv(market, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "run_late_cycle_ai_regime_audit.py",
                "--revisions",
                str(revisions),
                "--candidates",
                str(candidates),
                "--market",
                str(market),
                "--output-dir",
                str(out),
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert payload["force_trades"] is False
        assert payload["production_activation_allowed"] is False


if __name__ == "__main__":
    test_regime_audit_flags_late_cycle_ai_without_forcing_trades()
    test_cli_writes_regime_report()
    print("late_cycle_ai_regime_audit_smoke: PASS")
