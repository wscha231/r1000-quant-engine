#!/usr/bin/env python3
"""Smoke checks for the Evidence Readiness C0.2 preflight."""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT))

from tools.audit_evidence_readiness import build_payload, repo_path, write_outputs  # noqa: E402


def _write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def _args(root: Path, *, strict_etf: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        latest_run=str(root / "outputs"),
        output_dir=str(root / "outputs" / "evidence_readiness"),
        form4_transactions=str(root / "data_pit" / "sec" / "form4_transactions.parquet"),
        institutional_13f=str(root / "data_pit" / "sec" / "institutional_13f_holdings.parquet"),
        etf_holdings=str(root / "data_pit" / "etf_holdings" / "etf_holdings.parquet"),
        min_form4_signal_tickers=2,
        min_13f_signal_tickers=2,
        min_etf_signal_tickers=2,
        require_form4=True,
        require_13f=True,
        require_etf=strict_etf,
        require_etf_for_c4=strict_etf,
        strict=False,
    )


def _populate_ready_fixture(root: Path) -> None:
    _write(
        root / "data_pit" / "sec" / "form4_transactions.parquet",
        pd.DataFrame(
            [
                {"issuer_ticker": "AAPL", "accepted_at": "2026-05-13T00:00:00Z", "available_from": "2026-05-13T00:00:00Z"},
                {"issuer_ticker": "MSFT", "accepted_at": "2026-05-14T00:00:00Z", "available_from": "2026-05-14T00:00:00Z"},
            ]
        ),
    )
    _write(
        root / "outputs" / "sec_ownership_signals" / "form4_latest.csv",
        pd.DataFrame({"ticker": ["AAPL", "MSFT"], "latest_available_from": ["2026-05-14T00:00:00Z", "2026-05-14T00:00:00Z"]}),
    )
    _write(
        root / "data_pit" / "sec" / "institutional_13f_holdings.parquet",
        pd.DataFrame(
            [
                {"ticker_mapped": "AAPL", "accepted_at": "2026-05-15T18:00:00Z", "available_from": "2026-05-15T18:00:00Z"},
                {"ticker_mapped": "MSFT", "accepted_at": "2026-05-15T18:30:00Z", "available_from": "2026-05-15T18:30:00Z"},
            ]
        ),
    )
    _write(
        root / "outputs" / "sec_institutional_signals" / "13f_latest.csv",
        pd.DataFrame({"ticker": ["AAPL", "MSFT"], "latest_available_from": ["2026-05-15T18:30:00Z", "2026-05-15T18:30:00Z"]}),
    )
    _write(
        root / "data_pit" / "etf_holdings" / "etf_holdings.parquet",
        pd.DataFrame({"holding_ticker": ["AAPL", "MSFT"], "available_from": ["2026-05-16T00:00:00Z", "2026-05-16T00:00:00Z"]}),
    )
    _write(
        root / "outputs" / "etf_thematic_signals" / "signals_latest.csv",
        pd.DataFrame({"ticker": ["AAPL", "MSFT"], "latest_available_from": ["2026-05-16T00:00:00Z", "2026-05-16T00:00:00Z"]}),
    )
    manifest = root / "outputs" / "full_rebuild_logs" / "sec_evidence_restore_manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"status": "restored"}) + "\n", encoding="utf-8")


def test_ready_fixture_passes() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="evidence_readiness_"))
    try:
        _populate_ready_fixture(tmp)
        payload = build_payload(_args(tmp, strict_etf=True))
        assert payload["status"] == "ready"
        assert payload["ready_for_d1_13f_events"] is True
        assert payload["ready_for_d5_form4_event_study"] is True
        assert payload["ready_for_c5_etf_pit"] is True
        assert payload["ready_for_c4_broker_challenger"] is True
        assert payload["production_activation_allowed"] is False
        write_outputs(payload, repo_path(tmp / "outputs" / "evidence_readiness"))
        assert (tmp / "outputs" / "evidence_readiness" / "evidence_health.json").exists()
        assert (tmp / "outputs" / "evidence_readiness" / "report.md").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pit_and_mapping_blockers_are_reported() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="evidence_readiness_bad_"))
    try:
        _populate_ready_fixture(tmp)
        _write(
            tmp / "data_pit" / "sec" / "institutional_13f_holdings.parquet",
            pd.DataFrame(
                [
                    {"ticker_mapped": "", "accepted_at": "2026-05-15T18:00:00Z", "available_from": "2026-05-15T17:00:00Z"},
                ]
            ),
        )
        payload = build_payload(_args(tmp))
        assert payload["status"] == "blocked"
        assert any("13F evidence is not ready" in item for item in payload["blockers"])
        assert any("13f_raw has available_from before accepted_at" in item for item in payload["blockers"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_ready_fixture_passes()
    test_pit_and_mapping_blockers_are_reported()
    print("evidence_readiness_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
