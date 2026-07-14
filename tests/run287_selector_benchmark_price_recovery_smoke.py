#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import recover_run287_selector_benchmark_price as recovery


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path, *, allow_network: bool = True) -> argparse.Namespace:
    crisis = root / "crisis.json"
    crisis.write_text(
        json.dumps(
            {
                "status": "READY_CURRENT_CRISIS_STATE_NONSELECTING",
                "valuation_price_cutoff_date": "2026-07-10",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    source = root / "source"
    source.mkdir()
    return argparse.Namespace(
        crisis_manifest=str(crisis),
        expected_crisis_sha256=sha(crisis),
        ticker="SOXX",
        source_cache=str(source),
        valuation_date="2026-07-10",
        start_date="2025-01-02",
        minimum_rows=252,
        allow_network=allow_network,
        output_dir=str(root / "output"),
    )


def fake_downloader(
    tickers: list[str], *, start: str, end: str, interval: str
) -> dict[str, pd.DataFrame]:
    del start, end, interval
    dates = pd.bdate_range("2025-01-02", "2026-07-10")
    values = 200.0 * np.cumprod(np.full(len(dates), 1.0004))
    return {
        tickers[0]: pd.DataFrame(
            {"Date": dates, "Close": values, "Volume": 1_000_000}
        )
    }


def test_bounded_recovery_spends_one_request_and_never_selects() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = recovery.build(fixture(root), downloader=fake_downloader)
        assert payload["status"] == "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING"
        assert payload["price_recovery_passed"] is True
        assert payload["ticker"] == "SOXX"
        assert payload["network_requests_executed"] == 1
        assert payload["coverage"]["date_max"] == "2026-07-10"
        assert payload["selector_executed"] is False
        assert payload["target_books_mutated"] is False


def test_no_network_blocks_when_source_is_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = recovery.build(fixture(root, allow_network=False))
        assert payload["status"] == "BLOCKED_SELECTOR_BENCHMARK_PRICE_RECOVERY"
        assert "network_required_but_not_allowed" in payload["contract_failures"]
        assert payload["network_requests_executed"] == 0
        assert payload["selector_executed"] is False


def main() -> int:
    test_bounded_recovery_spends_one_request_and_never_selects()
    test_no_network_blocks_when_source_is_missing()
    print("run287_selector_benchmark_price_recovery_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
