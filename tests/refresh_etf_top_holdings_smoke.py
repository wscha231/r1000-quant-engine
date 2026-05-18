#!/usr/bin/env python3
"""Smoke test for tools/refresh_etf_top_holdings.py.

Verifies:
  1. Module imports cleanly.
  2. matches_exclude_pattern rejects 3X/inverse/bond patterns.
  3. refresh() handles missing yaml gracefully.
  4. refresh() with monkeypatched fetch returns the synthetic holdings.
  5. silent-rollback: when all fetches fail, the existing yaml is NOT
     overwritten (apply=True is a no-op if etfs_fetched_ok == 0).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.refresh_etf_top_holdings import refresh, matches_exclude_pattern  # noqa: E402


def test_exclude_patterns() -> None:
    patterns = [r"(3X|2X|Ultra|Pro|Bull|Bear|Inverse|Short)", r"(Bond|Treasury|TIPS)"]
    assert matches_exclude_pattern("SOXL", "Direxion 3X Bull Semiconductor", patterns) is True
    assert matches_exclude_pattern("TLT", "iShares 20+ Year Treasury Bond ETF", patterns) is True
    assert matches_exclude_pattern("AAPL", "Apple Inc", patterns) is False


def test_missing_yaml() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        s = refresh(
            yaml_path=root / "no_such.yaml",
            output_dir=root / "out",
            top_n=5,
            apply=False,
        )
        assert s["status"] == "blocked"
        assert "yaml load failed" in s["reason"]


def test_refresh_with_monkeypatched_fetch(monkeypatch=None) -> None:
    """Build a minimal yaml, monkey-patch the fetch fn to return synthetic
    holdings, and verify the refresh produces a snapshot + correct counts.
    """
    import yaml
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        yaml_path = root / "thematic.yaml"
        yaml_path.write_text(yaml.safe_dump({
            "thematic_etf_universe": [
                {"ticker": "OLDTKR", "name": "old holding", "theme": "quantum_computing", "source_etf": "QTUM", "domicile": "US"},
            ],
            "etf_sources": [
                {"ticker": "QTUM", "issuer": "Defiance", "theme": "quantum_computing"},
                {"ticker": "ARKQ", "issuer": "ARK", "theme": "autonomous_robotics"},
            ],
            "exclude_patterns": [r"(3X|2X|Bond)"],
        }), encoding="utf-8")

        # Monkey-patch fetch fn to deterministic synthetic data
        import tools.refresh_etf_top_holdings as mod
        original_fetch = mod.fetch_etf_top_holdings

        def fake_fetch(etf, top_n=5):
            if etf == "QTUM":
                return [
                    {"ticker": "IONQ", "name": "IonQ Inc", "weight": 0.05},
                    {"ticker": "RGTI", "name": "Rigetti Computing", "weight": 0.04},
                ]
            if etf == "ARKQ":
                return [
                    {"ticker": "JOBY", "name": "Joby Aviation", "weight": 0.06},
                ]
            return []

        mod.fetch_etf_top_holdings = fake_fetch
        try:
            s = refresh(
                yaml_path=yaml_path,
                output_dir=root / "out",
                top_n=5,
                apply=True,
            )
        finally:
            mod.fetch_etf_top_holdings = original_fetch

        assert s["status"] == "completed", s
        assert s["etfs_fetched_ok"] == 2, s
        assert s["etfs_fetch_failed"] == 0, s
        assert s["fresh_holdings_count"] == 3, s
        assert s["yaml_rewritten"] is True, s
        # Verify yaml was rewritten with the synthetic data.
        out = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        tkrs = {e["ticker"] for e in out["thematic_etf_universe"]}
        assert tkrs == {"IONQ", "RGTI", "JOBY"}, tkrs


def test_silent_rollback_when_all_fetches_fail() -> None:
    """If every ETF fetch fails, yaml MUST NOT be overwritten."""
    import yaml
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        yaml_path = root / "thematic.yaml"
        original = {
            "thematic_etf_universe": [
                {"ticker": "OLDTKR", "name": "old", "theme": "x", "source_etf": "Y", "domicile": "US"},
            ],
            "etf_sources": [
                {"ticker": "QTUM", "issuer": "Defiance", "theme": "quantum_computing"},
            ],
            "exclude_patterns": [],
        }
        yaml_path.write_text(yaml.safe_dump(original), encoding="utf-8")

        import tools.refresh_etf_top_holdings as mod
        original_fetch = mod.fetch_etf_top_holdings
        mod.fetch_etf_top_holdings = lambda etf, top_n=5: []
        try:
            s = refresh(
                yaml_path=yaml_path,
                output_dir=root / "out",
                top_n=5,
                apply=True,
            )
        finally:
            mod.fetch_etf_top_holdings = original_fetch

        assert s["status"] == "completed", s
        assert s["etfs_fetched_ok"] == 0, s
        assert s["yaml_rewritten"] is False, "yaml must NOT be rewritten when all fetches fail"
        # Original yaml content preserved.
        roundtrip = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        tkrs = {e["ticker"] for e in roundtrip["thematic_etf_universe"]}
        assert tkrs == {"OLDTKR"}, tkrs


def main() -> int:
    test_exclude_patterns()
    test_missing_yaml()
    test_refresh_with_monkeypatched_fetch()
    test_silent_rollback_when_all_fetches_fail()
    print("refresh_etf_top_holdings_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
