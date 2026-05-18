#!/usr/bin/env python3
"""Smoke test research handoff bundle packaging."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.package_research_handoff import run  # noqa: E402


def test_research_handoff_package_writes_manifest_and_zip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "sample.json"
        source.write_text('{"ok": true}\n', encoding="utf-8")
        output = root / "out"
        payload = run(
            argparse.Namespace(
                output_dir=str(output),
                bundle_name="sample_handoff.zip",
                label="smoke",
                include=[str(source)],
                include_heavy=False,
            )
        )
        bundle = Path(payload["bundle"])
        manifest = Path(payload["manifest"])
        assert bundle.exists()
        assert manifest.exists()
        assert payload["file_count"] >= 1
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert data["research_only"] is True
        assert data["production_activation_allowed"] is False
        assert data["bundle_sha256"]
        with zipfile.ZipFile(bundle) as zf:
            names = set(zf.namelist())
            assert "sample_handoff.manifest.json" in names
            assert "sample_handoff.README.md" in names
            assert any(name.endswith("sample.json") for name in names)


if __name__ == "__main__":
    test_research_handoff_package_writes_manifest_and_zip()
    print("research_handoff_package_smoke: PASS")
