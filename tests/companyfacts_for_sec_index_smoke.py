#!/usr/bin/env python3
"""Smoke tests for the bounded Companyfacts history collector."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.fetch_companyfacts_for_sec_index import build  # noqa: E402


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        pd.DataFrame(
            [
                {"ticker": "AAA", "cik10": "0000000001"},
                {"ticker": "AAA.A", "cik10": "0000000001"},
                {"ticker": "BBB", "cik10": "0000000002"},
            ]
        ).to_parquet(root / "sec.parquet", index=False)

        def fetcher(url: str, _user_agent: str) -> bytes:
            cik = url.rsplit("CIK", 1)[1].split(".", 1)[0]
            return json.dumps({"cik": int(cik), "facts": {}}).encode("utf-8")

        args = argparse.Namespace(
            sec_index=str(root / "sec.parquet"),
            user_agent="Researcher test@example.com",
            max_network_requests=2,
            output_dir=str(root / "out"),
        )
        manifest = build(args, fetcher=fetcher)
        assert manifest["status"] == "READY_RESEARCH_ONLY_COMPANYFACTS_HISTORY", manifest
        assert manifest["network_requests_executed"] == 2, manifest
        assert manifest["issuer_level_not_listing_specific"] is True, manifest
        assert manifest["fullrun_executed"] is False, manifest
        assert manifest["portfolio_weights_mutated"] is False, manifest
        for record in manifest["companyfacts_files"]:
            assert Path(record["path"]).is_file(), record

    print("companyfacts for SEC index smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
