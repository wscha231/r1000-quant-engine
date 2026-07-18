#!/usr/bin/env python3
"""Smoke test for the non-ranking outside-candidate shadow context."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_candidate_shadow_context import build  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def fp(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        price_root = root / "prices"
        price_root.mkdir()
        dates = pd.bdate_range(end="2026-07-14", periods=100)
        close = np.linspace(10.0, 20.0, len(dates))
        pd.DataFrame(
            {
                "Open": close * 0.99,
                "High": close * 1.01,
                "Low": close * 0.98,
                "Close": close,
                "Adj Close": close,
                "Volume": np.arange(len(dates)) + 1000,
            },
            index=dates,
        ).to_parquet(price_root / px_cache_name("AAA"))
        (price_root / "replay_price_cache_manifest.json").write_text(
            json.dumps({"status": "completed", "failed_count": 0, "end": "2026-07-14"}),
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "issuer_key": "AAA",
                    "in_frozen_universe": False,
                    "operating_universe_append_allowed": False,
                    "identity_cik10": "",
                    "universe_cik10": "",
                    "issuer_sec_proxy_ticker": "",
                    "canonical_7y_price_eligible": False,
                }
            ]
        ).to_csv(root / "queue.csv", index=False)
        model = {
            "model_features": ["mom_1m", "assets", "macro_x"],
            "scaler": {
                key: {"lo": -10.0, "hi": 10.0, "med": 0.0, "mad": 1.0}
                for key in ("mom_1m", "assets", "macro_x")
            },
        }
        (root / "model.json").write_text(json.dumps(model), encoding="utf-8")
        decision = {
            "status": "READY_COMPLETE_CURRENT_DECISION_FRAME",
            "source_inputs": {"model_meta": fp(root / "model.json")},
        }
        (root / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
        macro = {
            "status": "BLOCKED_MACRO_CONTRACT",
            "blockers": ["macro_row_not_exact_close"],
            "macro_merge_allowed": False,
            "valuation_close_date": "2026-07-14",
            "macro_available_from": "2026-07-14T23:59:59Z",
        }
        (root / "macro.json").write_text(json.dumps(macro), encoding="utf-8")
        pd.DataFrame(
            columns=[
                "ticker",
                "cik10",
                "accession_number",
                "form_type",
                "accepted_at",
                "available_from",
                "period_of_report",
            ]
        ).to_parquet(root / "sec.parquet", index=False)
        (root / "cf.json").write_text(
            json.dumps(
                {
                    "status": "READY_RESEARCH_ONLY_COMPANYFACTS_HISTORY",
                    "companyfacts_files": [],
                }
            ),
            encoding="utf-8",
        )
        args = argparse.Namespace(
            research_context_queue=str(root / "queue.csv"),
            price_root=str(price_root),
            current_decision_manifest=str(root / "decision.json"),
            macro_manifest=str(root / "macro.json"),
            sec_index=[str(root / "sec.parquet")],
            companyfacts_manifest=[str(root / "cf.json")],
            valuation_close_date="2026-07-14",
            observed_at_utc="2026-07-15T04:00:00Z",
            expected_ticker_count=1,
            expected_model_feature_count=3,
            missing_neutral_tolerance=1e-12,
            output_dir=str(root / "out"),
        )
        manifest = build(args)
        assert manifest["status"] == "READY_PARTIAL_CANDIDATE_SHADOW_CONTEXT_NONRANKING", manifest
        assert manifest["coverage"]["technical_exact_close_count"] == 1, manifest
        assert manifest["coverage"]["fundamental_panel_ready_count"] == 0, manifest
        assert manifest["coverage"]["macro_model_feature_count"] == 0, manifest
        assert manifest["coverage"]["scaled_model_feature_finite_ratio"] == 1.0, manifest
        assert manifest["coverage"]["scaled_missing_neutral_violation_count"] == 0, manifest
        assert manifest["decision_ranking_allowed"] is False, manifest
        assert manifest["operating_universe_mutated"] is False, manifest
        assert manifest["fullrun_executed"] is False, manifest
        scaled = pd.read_parquet(root / "out" / "shadow_scaled_model_input.parquet")
        assert float(scaled.iloc[0]["assets"]) == 0.0, scaled
        assert float(scaled.iloc[0]["macro_x"]) == 0.0, scaled

        try:
            build(args)
            raise AssertionError("append-only output reuse should fail")
        except FileExistsError:
            pass

    print("run287 candidate shadow-context smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
