#!/usr/bin/env python3
"""Smoke tests for guarded ADR universe manifest application."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.apply_adr_universe_update import APPROVAL_TOKEN, run  # noqa: E402


def write_universe(path: Path) -> None:
    path.write_text(
        """adr_universe:
  - ticker: TSM
    name: "Taiwan Semiconductor Manufacturing"
    country: TW
    sector: Semiconductors
    sub_sector: Foundry
    mcap_usd_b: 800
    listed_since: "1997-10"
    themes: [semi_design_memory, ai_compute]
""",
        encoding="utf-8",
    )


def reviewed_manifest(path: Path, *, ticker: str = "ARM") -> None:
    payload = {
        "schema_version": "adr-universe-update-manifest-v1",
        "production_mutation_allowed": False,
        "manual_review_required": True,
        "proposed_additions": [
            {
                "ticker": ticker,
                "candidate_status": "review_add",
                "exchange": "NASDAQ",
                "alpaca_tradable": True,
                "proposed_entry": {
                    "ticker": ticker,
                    "name": "Arm Holdings",
                    "country": "UK",
                    "sector": "Semiconductors",
                    "sub_sector": "IP",
                    "mcap_usd_b": 120.0,
                    "listed_since": "2023-09",
                    "themes": ["semi_design_memory", "ai_compute"],
                    "notes": "Reviewed ADR/ADS listing with sufficient liquidity.",
                },
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def placeholder_manifest(path: Path) -> None:
    payload = {
        "schema_version": "adr-universe-update-manifest-v1",
        "production_mutation_allowed": False,
        "manual_review_required": True,
        "proposed_additions": [
            {
                "ticker": "XYZ",
                "candidate_status": "review_add",
                "exchange": "NYSE",
                "alpaca_tradable": True,
                "proposed_entry": {
                    "ticker": "XYZ",
                    "name": "",
                    "country": "",
                    "sector": "ADR_REVIEW_REQUIRED",
                    "sub_sector": "",
                    "mcap_usd_b": None,
                    "listed_since": "",
                    "themes": [],
                },
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def args(manifest: Path, target: Path, out: Path, **overrides) -> Namespace:
    values = {
        "manifest": str(manifest),
        "target_file": str(target),
        "output_dir": str(out),
        "execute": False,
        "approval_token": "",
        "review_complete": False,
        "reviewed_by": "",
    }
    values.update(overrides)
    return Namespace(**values)


def test_reviewed_manifest_dry_run_writes_patch_without_mutating_target() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "adr_universe.yaml"
        manifest = root / "manifest.json"
        out = root / "out"
        write_universe(target)
        reviewed_manifest(manifest)
        before = target.read_text(encoding="utf-8")
        summary = run(args(manifest, target, out))
        assert summary["status"] == "dry_run_ready"
        assert summary["accepted_count"] == 1
        assert summary["blocked_count"] == 0
        assert target.read_text(encoding="utf-8") == before
        preview = (out / "adr_universe_patch_preview.yaml").read_text(encoding="utf-8")
        assert "ticker: ARM" in preview
        assert "semi_design_memory" in preview


def test_execute_requires_approval_and_review_complete() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "adr_universe.yaml"
        manifest = root / "manifest.json"
        write_universe(target)
        reviewed_manifest(manifest)
        summary = run(args(manifest, target, root / "out", execute=True, approval_token=APPROVAL_TOKEN, reviewed_by="codex"))
        assert summary["status"] == "refused"
        assert summary["refusal_reason"] == "review_complete_flag_missing"
        assert "ticker: ARM" not in target.read_text(encoding="utf-8")


def test_execute_appends_reviewed_entry() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "adr_universe.yaml"
        manifest = root / "manifest.json"
        write_universe(target)
        reviewed_manifest(manifest)
        summary = run(
            args(
                manifest,
                target,
                root / "out",
                execute=True,
                approval_token=APPROVAL_TOKEN,
                review_complete=True,
                reviewed_by="codex-smoke",
            )
        )
        assert summary["status"] == "applied"
        text = target.read_text(encoding="utf-8")
        assert "Reviewed ADR additions" in text
        assert "ticker: ARM" in text
        assert "Arm Holdings" in text


def test_placeholder_manifest_is_blocked() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "adr_universe.yaml"
        manifest = root / "manifest.json"
        write_universe(target)
        placeholder_manifest(manifest)
        summary = run(args(manifest, target, root / "out"))
        assert summary["status"] == "dry_run_blocked"
        assert summary["accepted_count"] == 0
        assert summary["blocked_count"] == 1
        errors = summary["rows"][0]["errors"]
        assert "placeholder_sector_not_reviewed" in errors
        assert "mcap_usd_b_missing_or_invalid" in errors


if __name__ == "__main__":
    test_reviewed_manifest_dry_run_writes_patch_without_mutating_target()
    test_execute_requires_approval_and_review_complete()
    test_execute_appends_reviewed_entry()
    test_placeholder_manifest_is_blocked()
    print("adr_universe_apply_smoke: PASS")
