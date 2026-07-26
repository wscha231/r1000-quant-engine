#!/usr/bin/env python3
"""Synthetic, network-free checks for the Run287 sector leadership challenger."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "run_run287_sector_leadership_challenger.py"
SOURCE_COMMIT = "1" * 40
SOURCE_WORKFLOW = "Synthetic accepted paper close"
EXPECTED_OUTPUTS = {
    "source_manifest.json",
    "feature_manifest.json",
    "experiment_ledger.json",
    "sector_leadership.csv",
    "subsector_leadership.csv",
    "leadership_transitions.csv",
    "candidate_ranking.csv",
    "operation_health.json",
    "summary.json",
    "report.md",
}
HORIZONS = ("1d", "5d", "1m", "3m", "6m", "12m")
BENCHMARKS = ("SPY", "QQQ", "SMH")
TAXONOMY: dict[str, tuple[str, str]] = {
    "Communication Services": ("Interactive Media", "Entertainment"),
    "Consumer Discretionary": ("Specialty Retail", "Automobiles"),
    "Consumer Staples": ("Food Products", "Household Products"),
    "Energy": ("Oil & Gas", "Energy Equipment"),
    "Financials": ("Banks", "Capital Markets"),
    "Health Care": ("Biotechnology", "Health Care Equipment"),
    "Industrials": ("Electrical Equipment", "Aerospace & Defense"),
    "Information Technology": ("Semiconductors", "Software"),
    "Materials": ("Chemicals", "Metals & Mining"),
    "Real Estate": ("Equity REITs", "Real Estate Management"),
    "Utilities": ("Electric Utilities", "Multi-Utilities"),
}
SECTOR_PREFIX = {
    "Communication Services": "COM",
    "Consumer Discretionary": "CD",
    "Consumer Staples": "CS",
    "Energy": "EN",
    "Financials": "FN",
    "Health Care": "HC",
    "Industrials": "IN",
    "Information Technology": "IT",
    "Materials": "MA",
    "Real Estate": "RE",
    "Utilities": "UT",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact_record(
    path: Path, *, declared_path: str | None = None
) -> dict[str, Any]:
    return {
        "path": declared_path or path.name,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _ticker_rows(
    session: str,
    *,
    semiconductor_mode: str,
    utility_mode: str,
    leadership_regime: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    session_ts = pd.Timestamp(session)
    dates = pd.bdate_range(end=session_ts, periods=6)
    scored: list[dict[str, Any]] = []
    bars: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    sector_alpha = {
        "Communication Services": 0.01,
        "Consumer Discretionary": -0.01,
        "Consumer Staples": -0.03,
        "Energy": -0.04,
        "Financials": 0.00,
        "Health Care": -0.02,
        "Industrials": 0.05,
        "Information Technology": 0.00,
        "Materials": -0.01,
        "Real Estate": -0.035,
        "Utilities": 0.17 if utility_mode == "emerging" else 0.25,
    }
    if leadership_regime == "industrials":
        sector_alpha["Industrials"] = 0.25
        sector_alpha["Utilities"] = -0.03
    elif leadership_regime != "utilities":
        raise AssertionError(f"unknown synthetic leadership regime: {leadership_regime}")
    benchmark_momentum = {
        "1m": 0.02,
        "3m": 0.06,
        "6m": 0.10,
        "12m": 0.16,
    }
    for sector, subsectors in TAXONOMY.items():
        prefix = SECTOR_PREFIX[sector]
        for sub_index, subsector in enumerate(subsectors):
            for member in range(3):
                ticker = f"{prefix}{sub_index + 1}{member + 1}"
                alpha = sector_alpha[sector]
                five_day_return = 0.015 + alpha * 0.20
                if sector == "Information Technology" and subsector == "Semiconductors":
                    if semiconductor_mode == "breakdown":
                        alpha = -0.35
                        five_day_return = -0.22
                    elif semiconductor_mode == "reentry":
                        alpha = 0.11
                        five_day_return = 0.07
                # A single biotech crash must remain idiosyncratic: the other five
                # Health Care constituents stay positive.
                if (
                    sector == "Health Care"
                    and subsector == "Biotechnology"
                    and member == 0
                ):
                    alpha = -0.42
                    five_day_return = -0.35

                row: dict[str, Any] = {
                    "ticker": ticker,
                    "Name": ticker,
                    "sector": sector,
                    "industry_group": subsector,
                    "subindustry": subsector,
                    "score": 50.0 + alpha * 100.0,
                    "valuation_price_cutoff_date": session,
                    # Keep one noneligible name in the provider/audit universe.
                    # Future/stale poison cases target this first row, proving
                    # exact-close validation happens before eligibility filtering.
                    "research_eligible_after_quarantine": ticker != "COM11",
                }
                for horizon, market_return in benchmark_momentum.items():
                    row[f"mom_{horizon}"] = market_return + alpha
                scored.append(row)

                start = 100.0 + member
                end = start * (1.0 + five_day_return)
                closes = np.linspace(start, end, len(dates))
                for when, close in zip(dates, closes):
                    bars.append(
                        {
                            "ticker": ticker,
                            "Date": when,
                            "Close": float(close),
                            "Volume": 1_000_000 + member * 100_000,
                        }
                    )
                audit.append(
                    {
                        "ticker": ticker,
                        "status": "PASS",
                        "exact_session_close": True,
                        "session_date": session,
                    }
                )
    return pd.DataFrame(scored), pd.DataFrame(bars), pd.DataFrame(audit)


def _benchmark_frame(session: str, ticker: str) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp(session), periods=253)
    annual_return = {"SPY": 0.16, "QQQ": 0.22, "SMH": 0.30}[ticker]
    daily = (1.0 + annual_return) ** (1.0 / 252.0)
    values = 100.0 * np.power(daily, np.arange(len(dates)))
    return pd.DataFrame(
        {
            "Open": values,
            "Close": values,
            "Adj Close": values,
            "Volume": np.full(len(dates), 10_000_000),
        },
        index=dates,
    )


def _build_fixture(
    root: Path,
    session: str,
    *,
    semiconductor_mode: str = "breakdown",
    utility_mode: str = "emerging",
    leadership_regime: str = "utilities",
    shuffle_seed: int | None = None,
    bad_taxonomy: bool = False,
    single_unknown_taxonomy: bool = False,
    missing_eligibility: bool = False,
    missing_scored_date: bool = False,
    future_provider_row: bool = False,
    stale_ticker: bool = False,
    stale_audit_session: bool = False,
    stale_benchmark: bool = False,
    run_id: str = "88001",
) -> dict[str, Any]:
    inputs = root / "inputs"
    scored_root = (
        inputs
        / "restored_artifact"
        / "outputs"
        / "run287_scored_latest_refresh"
    )
    cache = root / "benchmark_cache"
    output = root / "output"
    scored_root.mkdir(parents=True)
    cache.mkdir()

    scored, provider, audit = _ticker_rows(
        session,
        semiconductor_mode=semiconductor_mode,
        utility_mode=utility_mode,
        leadership_regime=leadership_regime,
    )
    if bad_taxonomy:
        scored.loc[scored["sector"].eq("Utilities"), "sector"] = "Mystery Sector"
    if single_unknown_taxonomy:
        scored.loc[scored["ticker"].eq("CD11"), "sector"] = "Mystery Sector"
    if missing_eligibility:
        scored = scored.drop(columns=["research_eligible_after_quarantine"])
    if missing_scored_date:
        scored = scored.drop(columns=["valuation_price_cutoff_date"])
    if future_provider_row:
        poison = provider.iloc[[0]].copy()
        poison["Date"] = pd.Timestamp(session) + pd.offsets.BDay(1)
        poison["Close"] = 1_000_000.0
        provider = pd.concat([provider, poison], ignore_index=True)
    if stale_ticker:
        ticker = str(scored.iloc[0]["ticker"])
        provider = provider.loc[
            ~(
                provider["ticker"].eq(ticker)
                & provider["Date"].eq(pd.Timestamp(session))
            )
        ].copy()
    if stale_audit_session:
        audit.loc[audit.index[0], "session_date"] = (
            pd.Timestamp(session) - pd.offsets.BDay(1)
        ).date().isoformat()
    if shuffle_seed is not None:
        scored = scored.sample(frac=1.0, random_state=shuffle_seed).reset_index(
            drop=True
        )
        provider = provider.sample(
            frac=1.0, random_state=shuffle_seed + 1
        ).reset_index(drop=True)
        audit = audit.sample(
            frac=1.0, random_state=shuffle_seed + 2
        ).reset_index(drop=True)

    scored_path = scored_root / "scored_latest.csv"
    provider_path = scored_root / "provider_price_overlap.parquet"
    audit_path = scored_root / "ticker_refresh_audit.csv"
    scored.to_csv(scored_path, index=False)
    provider.to_parquet(provider_path, index=False)
    audit.to_csv(audit_path, index=False)

    accepted = {
        "schema_version": "run287-accepted-publication-manifest-v1",
        "status": "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY",
        "as_of_date": session,
        "source_identity": {
            "commit_sha": SOURCE_COMMIT,
            "run_id": run_id,
            "run_attempt": 1,
            "workflow": SOURCE_WORKFLOW,
        },
        "review_only": True,
        "automatic_champion_replacement_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
    }
    accepted_path = inputs / "accepted_publication_manifest.json"
    _write_json(accepted_path, accepted)

    scored_manifest = {
        "schema_version": "run287-scored-latest-refresh-v4",
        "status": "READY_RESEARCH_SCORED_LATEST",
        "session_date": session,
        "research_only": True,
        "fullrun_executed": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "outputs": {
            "scored_latest.csv": _artifact_record(
                scored_path,
                declared_path=(
                    "/home/runner/work/r1000-quant-engine/"
                    "r1000-quant-engine/outputs/"
                    "run287_scored_latest_refresh/scored_latest.csv"
                ),
            ),
            "provider_price_overlap.parquet": _artifact_record(
                provider_path,
                declared_path=(
                    "/home/runner/work/r1000-quant-engine/"
                    "r1000-quant-engine/outputs/"
                    "run287_scored_latest_refresh/"
                    "provider_price_overlap.parquet"
                ),
            ),
            "ticker_refresh_audit.csv": _artifact_record(
                audit_path,
                declared_path=(
                    "/home/runner/work/r1000-quant-engine/"
                    "r1000-quant-engine/outputs/"
                    "run287_scored_latest_refresh/"
                    "ticker_refresh_audit.csv"
                ),
            ),
        },
    }
    scored_manifest_path = scored_root / "manifest.json"
    _write_json(scored_manifest_path, scored_manifest)

    cache_files: dict[str, Any] = {}
    for ticker in BENCHMARKS:
        frame = _benchmark_frame(session, ticker)
        if stale_benchmark and ticker == "QQQ":
            frame = frame.iloc[:-1]
        cache_name = (
            hashlib.sha1(ticker.upper().encode("utf-8")).hexdigest()[:16]
            + ".parquet"
        )
        path = cache / cache_name
        frame.to_parquet(path)
        cache_files[ticker] = {
            "file": path.name,
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
    cache_manifest = {
        "schema_version": "run287-replay-price-cache-manifest-v2",
        "status": "completed",
        "refresh_through_date": session,
        "common_coverage_end": session,
        "refresh_through_exact_coverage": True,
        "refresh_through_missing_tickers": [],
        "ticker_count": 3,
        "refresh_through_ticker_count": 3,
        "refresh_through_exact_ticker_count": 3,
        "review_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "cache_files": cache_files,
    }
    cache_manifest_path = cache / "replay_price_cache_manifest.json"
    _write_json(cache_manifest_path, cache_manifest)

    return {
        "output": output,
        "accepted": accepted_path,
        "scored_manifest": scored_manifest_path,
        "scored": scored_path,
        "provider": provider_path,
        "audit": audit_path,
        "cache": cache,
        "cache_manifest": cache_manifest_path,
        "session": session,
        "run_id": run_id,
    }


def _run(
    fixture: dict[str, Any],
    *,
    prior: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(TOOL),
        "--accepted-publication-manifest",
        str(fixture["accepted"]),
        "--expected-accepted-publication-sha256",
        _sha256(fixture["accepted"]),
        "--scored-latest-manifest",
        str(fixture["scored_manifest"]),
        "--expected-scored-latest-manifest-sha256",
        _sha256(fixture["scored_manifest"]),
        "--scored-latest-csv",
        str(fixture["scored"]),
        "--expected-scored-latest-csv-sha256",
        _sha256(fixture["scored"]),
        "--provider-price-overlap",
        str(fixture["provider"]),
        "--expected-provider-price-overlap-sha256",
        _sha256(fixture["provider"]),
        "--ticker-refresh-audit",
        str(fixture["audit"]),
        "--expected-ticker-refresh-audit-sha256",
        _sha256(fixture["audit"]),
        "--benchmark-cache-dir",
        str(fixture["cache"]),
        "--benchmark-cache-manifest",
        str(fixture["cache_manifest"]),
        "--expected-benchmark-cache-manifest-sha256",
        _sha256(fixture["cache_manifest"]),
        "--source-run-id",
        fixture["run_id"],
        "--source-run-attempt",
        "1",
        "--source-commit-sha",
        SOURCE_COMMIT,
        "--source-session-date",
        fixture["session"],
        "--source-workflow",
        SOURCE_WORKFLOW,
        "--output-dir",
        str(fixture["output"]),
    ]
    if prior is not None:
        cmd.extend(
            [
                "--prior-challenger-artifact",
                str(prior),
                "--expected-prior-challenger-sha256",
                _sha256(prior),
            ]
        )
    env = os.environ.copy()
    env["RUN287_NETWORK_DISABLED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _state_row(summary: dict[str, Any], entity_type: str, key: str) -> dict[str, Any]:
    matches = [
        row
        for row in summary["state_memory"]
        if row["entity_type"] == entity_type and row["entity_key"] == key
    ]
    assert len(matches) == 1, (entity_type, key, matches)
    return matches[0]


def _assert_safety(payload: dict[str, Any]) -> None:
    assert payload["review_only"] is True
    assert payload["research_only"] is True
    for field in (
        "production_activation_allowed",
        "live_trading_enabled",
        "target_books_mutated",
        "weights_mutated",
        "orders_generated",
        "account_state_mutated",
        "operating_ledger_mutated",
        "automatic_promotion_allowed",
        "automatic_champion_replacement_allowed",
        "production_mutation_allowed",
        "portfolio_weights_written",
        "cash_allocator_written",
        "accounts_written",
        "operating_ledgers_written",
        "backtest_executed",
        "fullrun_executed",
    ):
        assert payload[field] is False, field


def _assert_completed_contract(output: Path, session: str) -> dict[str, Any]:
    assert {path.name for path in output.iterdir() if path.is_file()} == EXPECTED_OUTPUTS
    summary = _json(output / "summary.json")
    assert summary["status"] == "READY_SECTOR_LEADERSHIP_RESEARCH_ONLY"
    assert summary["source_identity"]["session_date"] == session
    for name in (
        "source_manifest.json",
        "feature_manifest.json",
        "experiment_ledger.json",
        "operation_health.json",
        "summary.json",
    ):
        _assert_safety(_json(output / name))
    forbidden = (
        "main_target",
        "concentrated_target",
        "order",
        "fill",
        "account",
        "paper_ledger",
    )
    assert not any(
        token in path.name.lower()
        for path in output.rglob("*")
        for token in forbidden
    )
    source = _json(output / "source_manifest.json")
    feature = _json(output / "feature_manifest.json")
    health = _json(output / "operation_health.json")
    assert len(source["input_set_sha256"]) == 64
    assert source["input_set_sha256"] == summary["input_set_sha256"]
    assert feature["input_set_sha256"] == summary["input_set_sha256"]
    assert health["input_set_sha256"] == summary["input_set_sha256"]
    assert health["status"] == "READY"
    assert health["challenger_status"] == summary["status"]
    assert all(health["gates"].values())
    for label in (
        "scored_manifest_output_csv",
        "scored_manifest_output_provider",
        "scored_manifest_output_ticker_audit",
    ):
        relocation = source["source_inputs"][label]
        assert relocation["portable_outputs_relocation_verified"] is True
        assert relocation["hash_matches"] is True
    for name, record in feature["table_outputs"].items():
        artifact = output / name
        assert artifact.is_file()
        assert record["sha256"] == _sha256(artifact)
        assert int(record["bytes"]) == artifact.stat().st_size
    for name, record in summary["artifact_hashes"].items():
        artifact = output / name
        assert artifact.is_file()
        assert record["sha256"] == _sha256(artifact)
        assert int(record["bytes"]) == artifact.stat().st_size
    return summary


def test_rotation_breakdown_rs_determinism_and_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        industrial_regime = _build_fixture(
            root / "industrial_regime",
            "2026-07-23",
            leadership_regime="industrials",
            run_id="87999",
        )
        industrial_proc = _run(industrial_regime)
        assert industrial_proc.returncode == 0, (
            industrial_proc.stdout + industrial_proc.stderr
        )
        _assert_completed_contract(
            industrial_regime["output"], industrial_regime["session"]
        )
        prior_sectors = pd.read_csv(
            industrial_regime["output"] / "sector_leadership.csv"
        )
        assert prior_sectors.iloc[0]["sector"] == "Industrials"

        fixture = _build_fixture(root / "ordered", "2026-07-24")
        proc = _run(fixture)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        summary = _assert_completed_contract(
            fixture["output"], fixture["session"]
        )
        sectors = pd.read_csv(fixture["output"] / "sector_leadership.csv")
        subsectors = pd.read_csv(
            fixture["output"] / "subsector_leadership.csv"
        )
        candidates = pd.read_csv(fixture["output"] / "candidate_ranking.csv")
        assert set(sectors["sector"]) == set(TAXONOMY)
        assert len(sectors) == 11
        assert sectors.iloc[0]["sector"] == "Utilities"

        semis = subsectors.loc[
            subsectors["entity_key"].eq(
                "subindustry|Information Technology|Semiconductors|Semiconductors"
            )
        ].iloc[0]
        assert semis["raw_signal"] == "BREAKDOWN"
        assert semis["leadership_state"] == "BREAKDOWN"
        biotech = subsectors.loc[
            subsectors["entity_key"].eq(
                "subindustry|Health Care|Biotechnology|Biotechnology"
            )
        ].iloc[0]
        assert biotech["raw_signal"] != "BREAKDOWN"
        health = sectors.loc[sectors["sector"].eq("Health Care")].iloc[0]
        assert health["raw_signal"] != "BREAKDOWN"
        assert pd.api.types.is_bool_dtype(candidates["idiosyncratic_decline"])
        idiosyncratic = candidates.loc[candidates["ticker"].eq("HC11")].iloc[0]
        assert idiosyncratic["idiosyncratic_decline"] is True or bool(
            idiosyncratic["idiosyncratic_decline"]
        )

        expected_rs = {
            f"rs_{benchmark.lower()}_{horizon}"
            for benchmark in BENCHMARKS
            for horizon in HORIZONS
        }
        assert expected_rs.issubset(candidates.columns)
        assert candidates[list(expected_rs)].notna().all().all()
        assert summary["coverage"]["canonical_sector_count"] == 11
        coverage = summary["coverage"]
        assert int(coverage["full_source_ticker_count"]) == 66
        assert int(coverage["eligible_ticker_count"]) == 65
        assert int(coverage["analyzed_ticker_count"]) == 65
        assert int(coverage["provider_full_scored_exact_close_count"]) == 66
        assert float(coverage["full_source_exact_close_ratio"]) == 1.0
        assert float(coverage["eligible_exact_close_ratio"]) == 1.0
        assert float(coverage["analyzed_exact_close_ratio"]) == 1.0
        assert coverage["leadership_scope"] == "eligible_candidate_leadership"
        assert coverage["full_universe_market_breadth_claimed"] is False

        shuffled = _build_fixture(
            root / "shuffled",
            "2026-07-24",
            shuffle_seed=97,
        )
        shuffled_proc = _run(shuffled)
        assert shuffled_proc.returncode == 0, (
            shuffled_proc.stdout + shuffled_proc.stderr
        )
        _assert_completed_contract(shuffled["output"], shuffled["session"])
        assert (
            _json(fixture["output"] / "feature_manifest.json")[
                "table_outputs"
            ]
            == _json(shuffled["output"] / "feature_manifest.json")[
                "table_outputs"
            ]
        )
        for name in (
            "sector_leadership.csv",
            "subsector_leadership.csv",
            "candidate_ranking.csv",
            "leadership_transitions.csv",
        ):
            left = pd.read_csv(fixture["output"] / name)
            right = pd.read_csv(shuffled["output"] / name)
            pd.testing.assert_frame_equal(left, right, check_like=False)


def test_distinct_session_confirmation_reentry_and_same_date_idempotency() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = _build_fixture(
            root / "first",
            "2026-07-23",
            semiconductor_mode="breakdown",
            utility_mode="emerging",
            run_id="88011",
        )
        first_proc = _run(first)
        assert first_proc.returncode == 0, first_proc.stdout + first_proc.stderr
        first_summary = _assert_completed_contract(
            first["output"], first["session"]
        )
        assert _state_row(
            first_summary,
            "subindustry",
            (
                "subindustry|Information Technology|Semiconductors|"
                "Semiconductors"
            ),
        )["state"] == "BREAKDOWN"
        semi_entity_key = (
            "subindustry|Information Technology|Semiconductors|"
            "Semiconductors"
        )
        first_transitions = pd.read_csv(
            first["output"] / "leadership_transitions.csv"
        )
        first_semi_transition = first_transitions.loc[
            (first_transitions["entity_type"] == "subindustry")
            & (first_transitions["entity_key"] == semi_entity_key)
        ].iloc[0]
        assert bool(first_semi_transition["state_changed"]) is True
        assert (
            bool(first_semi_transition["immediate_negative_transition"])
            is True
        )
        utility_first = _state_row(
            first_summary, "sector", "sector|Utilities"
        )
        assert utility_first["state"] == "EMERGING_WATCH"
        assert utility_first["pending_confirmation"] == "EMERGING"
        assert int(utility_first["pending_streak"]) == 1

        persistent_breakdown = _build_fixture(
            root / "persistent_breakdown",
            "2026-07-24",
            semiconductor_mode="breakdown",
            utility_mode="emerging",
            run_id="88015",
        )
        persistent_proc = _run(
            persistent_breakdown,
            prior=first["output"] / "summary.json",
        )
        assert persistent_proc.returncode == 0, (
            persistent_proc.stdout + persistent_proc.stderr
        )
        _assert_completed_contract(
            persistent_breakdown["output"],
            persistent_breakdown["session"],
        )
        persistent_transitions = pd.read_csv(
            persistent_breakdown["output"] / "leadership_transitions.csv"
        )
        persistent_semi_transition = persistent_transitions.loc[
            (persistent_transitions["entity_type"] == "subindustry")
            & (persistent_transitions["entity_key"] == semi_entity_key)
        ].iloc[0]
        assert persistent_semi_transition["current_state"] == "BREAKDOWN"
        assert bool(persistent_semi_transition["state_changed"]) is False
        assert (
            bool(
                persistent_semi_transition[
                    "immediate_negative_transition"
                ]
            )
            is False
        )

        gap = _build_fixture(
            root / "stale_prior_gap",
            "2026-07-27",
            semiconductor_mode="reentry",
            utility_mode="emerging",
            run_id="88014",
        )
        gap_proc = _run(gap, prior=first["output"] / "summary.json")
        assert gap_proc.returncode == 0, gap_proc.stdout + gap_proc.stderr
        gap_summary = _assert_completed_contract(
            gap["output"], gap["session"]
        )
        gap_source = _json(gap["output"] / "source_manifest.json")
        assert gap_source["prior_artifact"]["ignored"] is True
        assert (
            gap_source["prior_artifact"]["ignored_reason"]
            == "not_immediately_preceding_nyse_session"
        )
        assert (
            _state_row(gap_summary, "sector", "sector|Utilities")["state"]
            == "EMERGING_WATCH"
        )

        second = _build_fixture(
            root / "second",
            "2026-07-24",
            semiconductor_mode="reentry",
            utility_mode="emerging",
            run_id="88012",
        )
        second_proc = _run(
            second, prior=first["output"] / "summary.json"
        )
        assert second_proc.returncode == 0, (
            second_proc.stdout + second_proc.stderr
        )
        second_summary = _assert_completed_contract(
            second["output"], second["session"]
        )
        semi_second = _state_row(
            second_summary,
            "subindustry",
            semi_entity_key,
        )
        assert semi_second["state"] == "EMERGING_WATCH"
        assert semi_second["pending_confirmation"] == "REENTRY"
        assert int(semi_second["pending_streak"]) == 1
        utility_second = _state_row(
            second_summary, "sector", "sector|Utilities"
        )
        assert utility_second["state"] == "LEADING"
        assert utility_second["pending_confirmation"] == ""
        assert int(utility_second["pending_streak"]) == 0

        third = _build_fixture(
            root / "third",
            "2026-07-27",
            semiconductor_mode="reentry",
            utility_mode="emerging",
            run_id="88013",
        )
        third_proc = _run(
            third, prior=second["output"] / "summary.json"
        )
        assert third_proc.returncode == 0, third_proc.stdout + third_proc.stderr
        third_summary = _assert_completed_contract(
            third["output"], third["session"]
        )
        semi_third = _state_row(
            third_summary,
            "subindustry",
            semi_entity_key,
        )
        assert semi_third["state"] == "REENTRY"
        assert int(semi_third["pending_streak"]) == 0

        idempotent = {
            **third,
            "output": root / "idempotent_output",
        }
        idem_proc = _run(
            idempotent, prior=third["output"] / "summary.json"
        )
        assert idem_proc.returncode == 0, idem_proc.stdout + idem_proc.stderr
        idem_summary = _assert_completed_contract(
            idempotent["output"], idempotent["session"]
        )
        assert _state_row(
            idem_summary,
            "subindustry",
            semi_entity_key,
        ) == semi_third

        changed = _build_fixture(
            root / "same_date_changed",
            "2026-07-27",
            semiconductor_mode="breakdown",
            utility_mode="emerging",
            run_id="88013",
        )
        changed_proc = _run(
            changed, prior=third["output"] / "summary.json"
        )
        assert changed_proc.returncode == 2
        changed_summary = _json(changed["output"] / "summary.json")
        assert (
            changed_summary["status"]
            == "BLOCKED_SECTOR_LEADERSHIP_CHALLENGER"
        )
        assert "same_date" in " ".join(
            changed_summary["contract_failures"]
        ).lower()


def test_prior_state_memory_is_bound_and_coherent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prior_fixture = _build_fixture(
            root / "prior",
            "2026-07-23",
            run_id="88090",
        )
        prior_proc = _run(prior_fixture)
        assert prior_proc.returncode == 0, (
            prior_proc.stdout + prior_proc.stderr
        )
        prior_payload = _json(
            prior_fixture["output"] / "summary.json"
        )

        def forged_future_and_signal(row: dict[str, Any]) -> None:
            row["last_session"] = "2026-07-24"
            row["state"] = "BREAKDOWN"
            row["signal"] = "LEADING"

        def forged_nonwatch_pending(row: dict[str, Any]) -> None:
            row["state"] = "LEADING"
            row["signal"] = "LEADING"
            row["pending_confirmation"] = "EMERGING"
            row["pending_streak"] = 1
            row["last_evidence_session"] = "2026-07-23"

        def forged_watch_without_evidence(row: dict[str, Any]) -> None:
            row["state"] = "EMERGING_WATCH"
            row["signal"] = "EMERGING"
            row["pending_confirmation"] = ""
            row["pending_streak"] = 0
            row["last_evidence_session"] = ""

        def forged_fractional_streak(row: dict[str, Any]) -> None:
            row["state"] = "EMERGING_WATCH"
            row["signal"] = "EMERGING"
            row["pending_confirmation"] = "EMERGING"
            row["pending_streak"] = 1.0
            row["last_evidence_session"] = "2026-07-23"

        cases = (
            ("future_signal", forged_future_and_signal),
            ("nonwatch_pending", forged_nonwatch_pending),
            ("watch_without_evidence", forged_watch_without_evidence),
            ("fractional_streak", forged_fractional_streak),
        )
        for index, (name, mutate) in enumerate(cases):
            payload = json.loads(json.dumps(prior_payload))
            assert payload["state_memory"]
            mutate(payload["state_memory"][0])
            forged_prior = root / f"forged_{name}.json"
            _write_json(forged_prior, payload)
            current = _build_fixture(
                root / f"current_{name}",
                "2026-07-24",
                run_id=str(88091 + index),
            )
            proc = _run(current, prior=forged_prior)
            assert proc.returncode == 2, (
                name,
                proc.stdout,
                proc.stderr,
            )
            summary = _json(current["output"] / "summary.json")
            assert (
                summary["status"]
                == "BLOCKED_SECTOR_LEADERSHIP_CHALLENGER"
            )
            failures = " ".join(
                summary["contract_failures"]
            ).lower()
            assert "prior_state_memory" in failures, (
                name,
                failures,
            )
            _assert_safety(summary)


def test_prior_source_identity_is_strict_and_workflow_bound() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prior_fixture = _build_fixture(
            root / "prior_identity",
            "2026-07-23",
            run_id="88120",
        )
        prior_proc = _run(prior_fixture)
        assert prior_proc.returncode == 0, (
            prior_proc.stdout + prior_proc.stderr
        )
        prior_payload = _json(
            prior_fixture["output"] / "summary.json"
        )
        cases = (
            (
                "foreign_workflow",
                "source_identity",
                "workflow",
                (
                    "other/repository/.github/workflows/"
                    "foreign.yml@refs/heads/master"
                ),
                "prior_source_workflow_mismatch",
            ),
            (
                "invalid_run_id",
                "source_identity",
                "run_id",
                "0",
                "prior_source_identity_invalid",
            ),
            (
                "invalid_run_attempt",
                "source_identity",
                "run_attempt",
                "attempt-one",
                "prior_source_identity_invalid",
            ),
            (
                "invalid_commit",
                "source_identity",
                "commit_sha",
                "not-a-commit",
                "prior_source_identity_invalid",
            ),
            (
                "invalid_input_hash",
                "",
                "input_set_sha256",
                "not-a-sha256",
                "prior_source_identity_invalid",
            ),
        )
        for index, (
            name,
            parent,
            field,
            value,
            expected,
        ) in enumerate(cases):
            payload = json.loads(json.dumps(prior_payload))
            target = payload[parent] if parent else payload
            target[field] = value
            forged_prior = root / f"forged_identity_{name}.json"
            _write_json(forged_prior, payload)
            current = _build_fixture(
                root / f"current_identity_{name}",
                "2026-07-24",
                run_id=str(88121 + index),
            )
            proc = _run(current, prior=forged_prior)
            assert proc.returncode == 2, (
                name,
                proc.stdout,
                proc.stderr,
            )
            summary = _json(current["output"] / "summary.json")
            assert (
                summary["status"]
                == "BLOCKED_SECTOR_LEADERSHIP_CHALLENGER"
            )
            failures = " ".join(
                summary["contract_failures"]
            ).lower()
            assert expected in failures, (name, failures)
            _assert_safety(summary)


def test_taxonomy_exact_close_future_and_stale_rows_fail_closed() -> None:
    cases = (
        ("bad_taxonomy", {"bad_taxonomy": True}, "taxonomy"),
        (
            "missing_eligibility",
            {"missing_eligibility": True},
            "eligibility_field_missing",
        ),
        (
            "missing_scored_date",
            {"missing_scored_date": True},
            "row_date_column_missing",
        ),
        ("future_provider", {"future_provider_row": True}, "future"),
        ("stale_ticker", {"stale_ticker": True}, "exact"),
        (
            "stale_audit_session",
            {"stale_audit_session": True},
            "audit_session_date_mismatch",
        ),
        ("stale_benchmark", {"stale_benchmark": True}, "exact"),
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for index, (name, kwargs, expected) in enumerate(cases):
            fixture = _build_fixture(
                root / name,
                "2026-07-24",
                run_id=str(88100 + index),
                **kwargs,
            )
            proc = _run(fixture)
            assert proc.returncode == 2, name
            combined = (proc.stdout + proc.stderr).lower()
            summary = _json(fixture["output"] / "summary.json")
            health = _json(fixture["output"] / "operation_health.json")
            assert (
                summary["status"]
                == "BLOCKED_SECTOR_LEADERSHIP_CHALLENGER"
            )
            assert health["status"] == "BLOCKED"
            assert health["challenger_status"] == summary["status"]
            _assert_safety(summary)
            _assert_safety(health)
            failures = " ".join(summary["contract_failures"]).lower()
            assert expected in failures, (name, combined, failures)
            assert {
                path.name
                for path in fixture["output"].iterdir()
                if path.is_file()
            } == EXPECTED_OUTPUTS
            for csv_name in (
                "sector_leadership.csv",
                "subsector_leadership.csv",
                "leadership_transitions.csv",
                "candidate_ranking.csv",
            ):
                assert pd.read_csv(fixture["output"] / csv_name).empty


def test_sub_two_percent_unknown_taxonomy_is_excluded() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fixture = _build_fixture(
            Path(tmp) / "single_unknown",
            "2026-07-24",
            single_unknown_taxonomy=True,
            run_id="88801",
        )
        proc = _run(fixture)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        summary = _assert_completed_contract(
            fixture["output"], fixture["session"]
        )
        coverage = summary["coverage"]
        assert int(coverage["eligible_ticker_count"]) == 65
        assert int(coverage["taxonomy_excluded_count"]) == 1
        assert coverage["taxonomy_excluded_tickers"] == ["CD11"]
        assert int(coverage["analyzed_ticker_count"]) == 64
        candidates = pd.read_csv(
            fixture["output"] / "candidate_ranking.csv"
        )
        sectors = pd.read_csv(
            fixture["output"] / "sector_leadership.csv"
        )
        assert "CD11" not in set(candidates["ticker"])
        assert not sectors["sector"].fillna("").eq("").any()


def test_observable_catchup_skip_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "catchup_skip"
        cmd = [
            sys.executable,
            str(TOOL),
            "--emit-catchup-skip",
            "--source-run-id",
            "88901",
            "--source-run-attempt",
            "1",
            "--source-commit-sha",
            SOURCE_COMMIT,
            "--source-session-date",
            "2026-07-24",
            "--source-workflow",
            SOURCE_WORKFLOW,
            "--output-dir",
            str(output),
        ]
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert {
            path.name for path in output.iterdir() if path.is_file()
        } == EXPECTED_OUTPUTS
        summary = _json(output / "summary.json")
        health = _json(output / "operation_health.json")
        assert summary["status"] == "SKIPPED_CATCHUP_NO_PIT_SCORE_SNAPSHOT"
        assert health["status"] == "SKIPPED"
        assert health["challenger_status"] == summary["status"]
        assert summary["contract_failures"] == [
            "catchup_has_no_pit_score_snapshot"
        ]
        _assert_safety(summary)
        _assert_safety(health)
        for csv_name in (
            "sector_leadership.csv",
            "subsector_leadership.csv",
            "leadership_transitions.csv",
            "candidate_ranking.csv",
        ):
            assert pd.read_csv(output / csv_name).empty


def main() -> int:
    assert TOOL.is_file(), f"missing tool: {TOOL}"
    test_rotation_breakdown_rs_determinism_and_contract()
    test_distinct_session_confirmation_reentry_and_same_date_idempotency()
    test_prior_state_memory_is_bound_and_coherent()
    test_prior_source_identity_is_strict_and_workflow_bound()
    test_taxonomy_exact_close_future_and_stale_rows_fail_closed()
    test_sub_two_percent_unknown_taxonomy_is_excluded()
    test_observable_catchup_skip_contract()
    print("run287_sector_leadership_challenger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
