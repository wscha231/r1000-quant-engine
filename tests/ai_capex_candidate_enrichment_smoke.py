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

from tools.run_ai_capex_candidate_enrichment import main  # noqa: E402


def test_candidate_enrichment_cli_preserves_score_total() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        out = root / "out"
        pd.DataFrame(
            [
                {
                    "ticker": "MU",
                    "industry": "Semiconductor Memory",
                    "theme": "HBM tight supply price increase",
                    "score_total": 1.23,
                },
                {"ticker": "ABC", "industry": "Retail", "score_total": 0.42},
            ]
        ).to_csv(candidate, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "run_ai_capex_candidate_enrichment.py",
                "--candidate-book",
                str(candidate),
                "--output-dir",
                str(out),
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        enriched = pd.read_csv(out / "candidate_replay_book_ai_capex_enriched.csv")
        assert payload["score_total_mutated"] is False
        assert list(enriched["score_total"]) == [1.23, 0.42]
        assert enriched.loc[0, "ai_capex_value_chain_bucket"] == "AI_MEMORY"
        assert payload["production_activation_allowed"] is False


if __name__ == "__main__":
    test_candidate_enrichment_cli_preserves_score_total()
    print("ai_capex_candidate_enrichment_smoke: PASS")
