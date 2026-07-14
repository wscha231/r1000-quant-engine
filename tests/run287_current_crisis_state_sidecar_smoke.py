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

from tools import build_run287_current_crisis_state_sidecar as sidecar


PINNED_COMMIT = "15176b588d5bb0792bce1df6367758d795a8a33a"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path), "exists": True}


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def price_name(ticker: str) -> str:
    return hashlib.sha1(ticker.upper().encode("utf-8")).hexdigest()[:16] + ".parquet"


def fixture(root: Path, *, bad_threshold_hash: bool = False) -> argparse.Namespace:
    valuation = pd.Timestamp("2026-07-10")
    dates = pd.bdate_range("2024-12-02", valuation)
    cache_prices = root / "cache_prices"
    cache_macro = root / "cache_macro"
    cache_prices.mkdir()
    cache_macro.mkdir()
    for ticker, start in (("SPY", 500.0), ("QQQ", 450.0)):
        values = start * np.cumprod(np.full(len(dates), 1.0005))
        pd.DataFrame({"Date": dates, "close": values}).to_parquet(
            cache_prices / price_name(ticker), index=False
        )

    def fred(name: str, series_id: str, values: np.ndarray) -> None:
        pd.DataFrame({"date": dates, "value": values}).to_parquet(
            cache_macro / f"fred_{name}_{series_id}.parquet", index=False
        )

    fred("vix", "VIXCLS", np.full(len(dates), 16.0))
    fred("dgs10", "DGS10", np.full(len(dates), 4.0))
    fred("hy_oas", "BAMLH0A0HYM2", np.full(len(dates), 3.0))
    fred("dxy", "DTWEXBGS", np.full(len(dates), 100.0))
    fred("m2", "M2SL", np.linspace(21000.0, 22000.0, len(dates)))
    fred("fed_assets", "WALCL", np.full(len(dates), 7000.0))
    fred("reverse_repo", "RRPTSYD", np.full(len(dates), 10.0))
    fred("tga", "WDTGAL", np.full(len(dates), 700.0))

    selector_manifest = root / "selector_contract.json"
    write_json(
        selector_manifest,
        {"status": "READY_CURRENT_SELECTOR_CONTRACT_AUDIT_NONSELECTING"},
    )
    pinned_manifest = root / "pinned_import.json"
    write_json(
        pinned_manifest,
        {
            "status": "READY_PINNED_POLICY_IMPORT_NONSELECTING",
            "pinned_source_commit": PINNED_COMMIT,
        },
    )
    macro_current = root / "macro_current.csv"
    pd.DataFrame({"macro_date": [valuation.date().isoformat()]}).to_csv(
        macro_current, index=False
    )
    macro_manifest = root / "macro_manifest.json"
    write_json(
        macro_manifest,
        {
            "status": "READY_CONSERVATIVE_MACRO_SIDECAR",
            "fred_vintage_clean": False,
            "decision_time_utc": "2026-07-11T00:00:00+00:00",
            "macro_available_from": "2026-07-10T23:59:59+00:00",
            "outputs": {"macro_current": record(macro_current)},
        },
    )
    official = root / "official_daily_crisis.csv"
    official_dates = pd.bdate_range("2026-06-24", "2026-06-30")
    pd.DataFrame(
        {
            "date": official_dates,
            "raw_state": ["GREEN"] * len(official_dates),
            "crisis_state": ["GREEN"] * len(official_dates),
        }
    ).to_csv(official, index=False)
    thresholds = root / "thresholds.json"
    write_json(
        thresholds,
        {
            "governor_thresholds": {"low": 0.2, "mid": 0.35, "high": 0.55},
            "cash_hard_gate": {
                "liquidity_gate": 0.5,
                "trend_gate": 0.35,
                "credit_gate": 0.55,
            },
        },
    )
    return argparse.Namespace(
        selector_contract_manifest=str(selector_manifest),
        expected_selector_contract_sha256=sha(selector_manifest),
        pinned_import_manifest=str(pinned_manifest),
        expected_pinned_import_sha256=sha(pinned_manifest),
        macro_manifest=str(macro_manifest),
        expected_macro_sha256=sha(macro_manifest),
        official_daily_crisis_state=str(official),
        expected_daily_crisis_sha256=sha(official),
        official_thresholds=str(thresholds),
        expected_thresholds_sha256=(
            "0" * 64 if bad_threshold_hash else sha(thresholds)
        ),
        cache_prices=str(cache_prices),
        cache_macro=str(cache_macro),
        expected_price_file_count=2,
        expected_macro_file_count=8,
        expected_policy_commit=PINNED_COMMIT,
        valuation_date=valuation.date().isoformat(),
        output_dir=str(root / "output"),
    )


def test_current_crisis_extension_is_deterministic_and_nonselecting() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = sidecar.build(fixture(root))
        assert payload["status"] == "READY_CURRENT_CRISIS_STATE_NONSELECTING"
        assert payload["crisis_state_sidecar_passed"] is True
        assert payload["current_state"]["date"] == "2026-07-10"
        assert payload["current_state"]["crisis_state"] == "GREEN"
        assert payload["feature_contract"]["future_labels_used_for_state"] is False
        assert payload["extension"]["extension_deterministic"] is True
        assert payload["pinned_runtime"]["all_modules_from_pinned_git_objects"] is True
        assert payload["selector_executed"] is False
        assert payload["target_books_mutated"] is False


def test_input_hash_failure_blocks_before_crisis_runtime() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = sidecar.build(fixture(root, bad_threshold_hash=True))
        assert payload["status"] == "BLOCKED_CURRENT_CRISIS_STATE_SIDECAR"
        assert payload["crisis_state_function_executed"] is False
        assert payload["selector_executed"] is False


def main() -> int:
    test_current_crisis_extension_is_deterministic_and_nonselecting()
    test_input_hash_failure_blocks_before_crisis_runtime()
    print("run287_current_crisis_state_sidecar_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
