#!/usr/bin/env python3
"""Materialize the three research-only scientific weighting input frames.

The builder is deliberately provenance-first.  It can consume a canonical PIT
component/price store, or adapt the repository's exact scored snapshot and
hash-pinned selector price archive as an explicitly unclean diagnostic.  It
never fits a model, selects securities, writes a target book, creates orders,
or mutates an operating ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import audit_run287_scientific_weighting_readiness as readiness


SCHEMA_VERSION = "run287-scientific-weighting-input-materialization-v1"
CONTRACT_SCHEMA = "run287-scientific-weighting-input-materialization-contract-v1"
DEFAULT_CONTRACT = (
    ROOT / "docs" / "run287_scientific_weighting_input_materialization_contract.json"
)
DEFAULT_READINESS_CONTRACT = (
    ROOT / "docs" / "run287_scientific_selection_allocation_contract.json"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NYSE = mcal.get_calendar("NYSE")

PILLARS: dict[str, dict[str, str]] = {
    "quality_moat": {
        "raw": "raw_quality_moat",
        "value": "pillar_quality_moat",
        "available": "pillar_quality_moat_available_from",
        "observed": "pillar_quality_moat_observed",
    },
    "valuation": {
        "raw": "raw_valuation",
        "value": "pillar_valuation",
        "available": "pillar_valuation_available_from",
        "observed": "pillar_valuation_observed",
    },
    "growth_revisions": {
        "raw": "raw_growth_revisions",
        "value": "pillar_growth_revisions",
        "available": "pillar_growth_revisions_available_from",
        "observed": "pillar_growth_revisions_observed",
    },
    "leadership_momentum": {
        "raw": "raw_leadership_momentum",
        "value": "pillar_leadership_momentum",
        "available": "pillar_leadership_momentum_available_from",
        "observed": "pillar_leadership_momentum_observed",
    },
    "event_actuals": {
        "raw": "raw_event_actuals",
        "value": "pillar_event_actuals",
        "available": "pillar_event_actuals_available_from",
        "observed": "pillar_event_actuals_observed",
    },
    "manager_13f_flow": {
        "raw": "raw_manager_13f_flow",
        "value": "pillar_13f_manager_flow",
        "available": "pillar_13f_manager_flow_available_from",
        "observed": "pillar_13f_manager_flow_observed",
    },
}

COMPONENT_IDENTITY_COLUMNS = [
    "feature_date",
    "rebalance_date",
    "decision_time_utc",
    "ticker",
    "sector",
    "stable_security_id",
    "pit_universe_label_clean",
]
COMPONENT_OUTPUT_COLUMNS = COMPONENT_IDENTITY_COLUMNS + [
    value
    for spec in PILLARS.values()
    for value in (spec["value"], spec["available"], spec["observed"])
] + [
    "realized_benchmark_excess_63d",
    "realized_benchmark_excess_126d",
    "label_available_at_63d",
    "label_available_at_126d",
]
PRICE_COLUMNS = [
    "date",
    "ticker",
    "stable_security_id",
    "adjusted_close",
    "available_from",
    "pit_lifecycle_state",
    "pit_universe_label_clean",
]
DAILY_RETURN_COLUMNS = [
    "date",
    "ticker",
    "stable_security_id",
    "return",
    "available_from",
    "pit_lifecycle_state",
    "pit_universe_label_clean",
]
PRIOR_OUTPUT_COLUMNS = [
    "rebalance_date",
    "ticker",
    "weight",
    "source_sha256",
    "portfolio_id",
    "weight_basis",
    "source_kind",
    "source_member_path",
    "source_accepted",
]


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key:{key}")
        output[key] = value
    return output


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "bytes": 0, "sha256": ""}
    return {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def load_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"unsupported table format:{path.suffix}")


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="coerce")
        return numeric.eq(1.0)
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes"})
    )


def utc_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def normalized_date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def stable_ticker(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.upper()
        .str.strip()
        .str.replace(".", "-", regex=False)
    )


def unique(values: Sequence[str]) -> list[str]:
    return sorted(set(str(value) for value in values if str(value)))


def nyse_schedule(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    schedule = NYSE.schedule(start_date=start.date(), end_date=end.date()).copy()
    schedule.index = pd.to_datetime(schedule.index).tz_localize(None).normalize()
    schedule["market_close"] = pd.to_datetime(schedule["market_close"], utc=True)
    return schedule


def validate_materialization_contract(contract: Any) -> list[str]:
    failures: list[str] = []
    if not isinstance(contract, dict):
        return ["materialization_contract_not_object"]
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        failures.append("materialization_contract_schema_mismatch")
    if set((contract.get("component_frame") or {}).get("canonical_raw_components") or {}) != set(PILLARS):
        failures.append("materialization_component_set_mismatch")
    archive = contract.get("archive") or {}
    if not SHA256_RE.fullmatch(str(archive.get("accepted_sha256") or "")):
        failures.append("materialization_archive_sha_invalid")
    safety = contract.get("safety") or {}
    required_false = [
        "model_fit_executed",
        "outer_test_opened",
        "portfolio_replay_executed",
        "stock_selection_produced",
        "portfolio_weights_produced",
        "target_books_written",
        "orders_generated",
        "operating_ledger_mutated",
        "production_or_live_trading_enabled",
        "automatic_promotion_allowed",
        "fullrun_executed",
    ]
    if safety.get("research_only") is not True:
        failures.append("materialization_not_research_only")
    for key in required_false:
        if safety.get(key) is not False:
            failures.append(f"materialization_safety_mismatch:{key}")
    return unique(failures)


def empty_component_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=COMPONENT_OUTPUT_COLUMNS)


def canonicalize_component_observations(
    source: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    blockers: list[str] = []
    required = set(COMPONENT_IDENTITY_COLUMNS)
    required.update(spec["raw"] for spec in PILLARS.values())
    required.update(spec["available"] for spec in PILLARS.values())
    required.update(spec["observed"] for spec in PILLARS.values())
    missing = sorted(required - set(source.columns))
    if missing:
        return empty_component_frame(), [
            "component_observations_missing_columns:" + ",".join(missing)
        ], {"source_rows": len(source), "output_rows": 0, "missing_columns": missing}
    if source.empty:
        return empty_component_frame(), ["component_observations_empty"], {
            "source_rows": 0,
            "output_rows": 0,
        }

    data = source.copy()
    data["feature_date"] = normalized_date_series(data["feature_date"])
    data["rebalance_date"] = normalized_date_series(data["rebalance_date"])
    data["decision_time_utc"] = utc_series(data["decision_time_utc"])
    data["ticker"] = stable_ticker(data["ticker"])
    data["sector"] = data["sector"].astype(str).str.strip()
    data["stable_security_id"] = data["stable_security_id"].astype(str).str.strip()
    data["pit_universe_label_clean"] = as_bool(data["pit_universe_label_clean"])

    invalid_identity = (
        data["feature_date"].isna()
        | data["rebalance_date"].isna()
        | data["decision_time_utc"].isna()
        | data["ticker"].eq("")
        | data["sector"].eq("")
        | data["stable_security_id"].eq("")
    )
    if invalid_identity.any():
        blockers.append(f"component_invalid_identity_rows:{int(invalid_identity.sum())}")
    if not data["feature_date"].eq(data["rebalance_date"]).all():
        blockers.append("component_feature_rebalance_date_mismatch")
    if data["decision_time_utc"].gt(as_of).any():
        blockers.append("component_decision_after_as_of")
    duplicate = data.duplicated(["feature_date", "ticker"], keep=False)
    if duplicate.any():
        blockers.append(f"component_duplicate_date_ticker_rows:{int(duplicate.sum())}")

    usable_identity = ~(invalid_identity | duplicate)
    data = data.loc[usable_identity].copy()
    output = data[COMPONENT_IDENTITY_COLUMNS].copy()
    coverage: dict[str, float] = {}
    for name, spec in PILLARS.items():
        raw = pd.to_numeric(data[spec["raw"]], errors="coerce")
        available = utc_series(data[spec["available"]])
        declared_observed = as_bool(data[spec["observed"]])
        invalid_observed = declared_observed & (raw.isna() | available.isna())
        after_decision = declared_observed & available.gt(data["decision_time_utc"])
        future_available = declared_observed & available.gt(as_of)
        if invalid_observed.any():
            blockers.append(
                f"component_observed_value_or_time_invalid:{name}:{int(invalid_observed.sum())}"
            )
        if after_decision.any():
            blockers.append(
                f"component_available_after_decision:{name}:{int(after_decision.sum())}"
            )
        if future_available.any():
            blockers.append(
                f"component_available_after_as_of:{name}:{int(future_available.sum())}"
            )
        observed = declared_observed & ~invalid_observed & ~after_decision & ~future_available
        ranked = raw.where(observed).groupby(data["feature_date"]).rank(
            pct=True, method="average"
        ) - 0.5
        output[spec["value"]] = ranked.where(observed)
        output[spec["available"]] = available.where(observed)
        output[spec["observed"]] = observed
        coverage[name] = float(observed.mean()) if len(observed) else 0.0

    for horizon in (63, 126):
        output[f"realized_benchmark_excess_{horizon}d"] = np.nan
        output[f"label_available_at_{horizon}d"] = pd.NaT
    output = output[COMPONENT_OUTPUT_COLUMNS].sort_values(
        ["feature_date", "ticker"]
    ).reset_index(drop=True)
    if not output["pit_universe_label_clean"].all():
        blockers.append("component_source_pit_universe_not_clean")
    return output, unique(blockers), {
        "source_rows": len(source),
        "output_rows": len(output),
        "decision_dates": int(output["feature_date"].nunique()),
        "tickers": int(output["ticker"].nunique()),
        "component_observation_coverage": coverage,
        "pit_clean_rows": int(output["pit_universe_label_clean"].sum()),
    }


def scored_snapshot_adapter(
    paths: Sequence[Path],
    *,
    as_of: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    frames: list[pd.DataFrame] = []
    source_fingerprints: list[dict[str, Any]] = []
    for path in paths:
        frames.append(load_table(path))
        source_fingerprints.append(fingerprint(path))
    source = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    raw_mapping = {
        "raw_quality_moat": ["moat_quality_blueprint_score"],
        "raw_valuation": ["valuation_blueprint_score"],
        "raw_growth_revisions": ["growth_blueprint_score", "revision_blueprint_score"],
        "raw_leadership_momentum": ["technical_blueprint_score"],
        "raw_event_actuals": ["actual_results_score"],
        "raw_manager_13f_flow": ["sec_13f_score"],
    }
    required = {
        "feature_date",
        "rebalance_date",
        "ticker",
        "sector",
        "score_available_from",
        "feature_available_from",
        "decision_feature_complete",
        "latest_only_inputs_neutralized",
        "current_technical_context_row_count",
        "actual_report_available",
        "institutional_actual_available",
    }
    required.update(column for columns in raw_mapping.values() for column in columns)
    missing = sorted(required - set(source.columns))
    if missing:
        return empty_component_frame(), [
            "scored_snapshot_missing_columns:" + ",".join(missing)
        ], {
            "source_rows": len(source),
            "output_rows": 0,
            "missing_columns": missing,
            "sources": source_fingerprints,
        }

    adapted = pd.DataFrame(index=source.index)
    for column in ("feature_date", "rebalance_date", "ticker", "sector"):
        adapted[column] = source[column]
    adapted["decision_time_utc"] = source["score_available_from"]

    explicit_stable = (
        source["stable_security_id"].astype(str).str.strip()
        if "stable_security_id" in source.columns
        else pd.Series("", index=source.index)
    )
    cik = (
        pd.to_numeric(source["identity_cik10"], errors="coerce")
        if "identity_cik10" in source.columns
        else pd.Series(np.nan, index=source.index)
    )
    ticker = stable_ticker(source["ticker"])
    fallback = pd.Series(
        [
            f"UNVERIFIED_SEC_CIK:{int(value):010d}:TICKER:{symbol}"
            if pd.notna(value)
            else f"UNVERIFIED_TICKER:{symbol}"
            for value, symbol in zip(cik, ticker)
        ],
        index=source.index,
    )
    fallback_used = explicit_stable.eq("")
    adapted["stable_security_id"] = explicit_stable.where(~fallback_used, fallback)
    source_pit = (
        as_bool(source["pit_universe_label_clean"])
        if "pit_universe_label_clean" in source.columns
        else pd.Series(False, index=source.index)
    )
    adapted["pit_universe_label_clean"] = source_pit & ~fallback_used

    for raw, columns in raw_mapping.items():
        numeric = pd.concat(
            [pd.to_numeric(source[column], errors="coerce") for column in columns],
            axis=1,
        )
        adapted[raw] = numeric.mean(axis=1).where(numeric.notna().all(axis=1))

    fundamental_gate = as_bool(source["decision_feature_complete"]) & ~as_bool(
        source["latest_only_inputs_neutralized"]
    )
    technical_gate = pd.to_numeric(
        source["current_technical_context_row_count"], errors="coerce"
    ).gt(0)
    event_gate = as_bool(source["actual_report_available"])
    manager_gate = as_bool(source["institutional_actual_available"])
    gates = {
        "quality_moat": fundamental_gate,
        "valuation": fundamental_gate,
        "growth_revisions": fundamental_gate,
        "leadership_momentum": technical_gate,
        "event_actuals": event_gate,
        "manager_13f_flow": manager_gate,
    }
    for name, spec in PILLARS.items():
        adapted[spec["observed"]] = gates[name]
        adapted[spec["available"]] = (
            source["score_available_from"]
            if name == "manager_13f_flow"
            else source["feature_available_from"]
        )

    output, blockers, diagnostics = canonicalize_component_observations(
        adapted, as_of=as_of
    )
    if fallback_used.any():
        blockers.append(
            f"scored_snapshot_unverified_stable_id_fallback:{int(fallback_used.sum())}"
        )
    if not fundamental_gate.all():
        blockers.append(
            f"scored_snapshot_fundamental_decision_incomplete:{int((~fundamental_gate).sum())}"
        )
    if not manager_gate.all():
        blockers.append(
            f"scored_snapshot_manager_13f_unobserved:{int((~manager_gate).sum())}"
        )
    diagnostics["adapter"] = "exact_scored_snapshot_diagnostic"
    diagnostics["sources"] = source_fingerprints
    diagnostics["fallback_stable_id_rows"] = int(fallback_used.sum())
    return output, unique(blockers), diagnostics


def load_archive_members(
    archive_path: Path | None,
    contract: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, Any]]:
    if archive_path is None:
        return {}, [], {"provided": False}
    blockers: list[str] = []
    expected = str(contract["archive"]["accepted_sha256"]).lower()
    actual = sha256_file(archive_path) if archive_path.is_file() else ""
    if actual != expected:
        blockers.append("static_archive_sha256_mismatch")
        return {}, blockers, {"provided": True, "archive": fingerprint(archive_path)}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            manifest_name = str(contract["archive"]["member_manifest"])
            manifest = json.loads(
                archive.read(manifest_name).decode("utf-8"),
                object_pairs_hook=reject_duplicate_json_keys,
            )
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        return {}, [f"static_archive_unreadable:{type(exc).__name__}:{exc}"], {
            "provided": True,
            "archive": fingerprint(archive_path),
        }
    if manifest.get("schema_version") != contract["archive"]["accepted_schema_version"]:
        blockers.append("static_archive_manifest_schema_mismatch")
    if manifest.get("status") != contract["archive"]["accepted_status"]:
        blockers.append("static_archive_manifest_status_mismatch")
    rows = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    members: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            blockers.append("static_archive_member_invalid")
            continue
        path = str(row.get("path") or "").replace("\\", "/")
        digest = str(row.get("sha256") or "").lower()
        if not path or path in members or not SHA256_RE.fullmatch(digest):
            blockers.append("static_archive_member_identity_invalid")
            continue
        members[path] = {"sha256": digest, "bytes": int(row.get("bytes") or 0)}
    if len(members) != int(manifest.get("file_count") or -1):
        blockers.append("static_archive_member_count_mismatch")
    return members, unique(blockers), {
        "provided": True,
        "archive": fingerprint(archive_path),
        "member_count": len(members),
        "manifest_status": manifest.get("status"),
    }


def canonical_price_observations(
    source: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    blockers: list[str] = []
    missing = sorted(set(PRICE_COLUMNS) - set(source.columns))
    if missing:
        return pd.DataFrame(columns=PRICE_COLUMNS), [
            "price_observations_missing_columns:" + ",".join(missing)
        ], {"source_rows": len(source), "output_rows": 0, "missing_columns": missing}
    data = source[PRICE_COLUMNS].copy()
    data["date"] = normalized_date_series(data["date"])
    data["ticker"] = stable_ticker(data["ticker"])
    data["stable_security_id"] = data["stable_security_id"].astype(str).str.strip()
    data["adjusted_close"] = pd.to_numeric(data["adjusted_close"], errors="coerce")
    data["available_from"] = utc_series(data["available_from"])
    data["pit_lifecycle_state"] = data["pit_lifecycle_state"].astype(str).str.strip()
    data["pit_universe_label_clean"] = as_bool(data["pit_universe_label_clean"])
    invalid = (
        data["date"].isna()
        | data["ticker"].eq("")
        | data["stable_security_id"].eq("")
        | ~np.isfinite(data["adjusted_close"])
        | data["adjusted_close"].le(0)
        | data["available_from"].isna()
        | data["pit_lifecycle_state"].eq("")
    )
    if invalid.any():
        blockers.append(f"price_invalid_rows:{int(invalid.sum())}")
    future = data["available_from"].gt(as_of)
    if future.any():
        blockers.append(f"price_available_after_as_of_rows:{int(future.sum())}")
    duplicate = data.duplicated(["date", "stable_security_id"], keep=False)
    if duplicate.any():
        blockers.append(f"price_duplicate_date_security_rows:{int(duplicate.sum())}")
    data = data.loc[~(invalid | future | duplicate)].copy()
    if not data.empty:
        schedule = nyse_schedule(data["date"].min(), data["date"].max())
        close_map = schedule["market_close"]
        scheduled = data["date"].map(close_map)
        invalid_session = scheduled.isna()
        before_close = data["available_from"].lt(scheduled)
        if invalid_session.any():
            blockers.append(f"price_non_nyse_session_rows:{int(invalid_session.sum())}")
        if before_close.any():
            blockers.append(f"price_available_before_close_rows:{int(before_close.sum())}")
        data = data.loc[~(invalid_session | before_close)].copy()
    data = data.sort_values(["stable_security_id", "date"]).reset_index(drop=True)
    return data, unique(blockers), {
        "source_rows": len(source),
        "output_rows": len(data),
        "tickers": int(data["ticker"].nunique()) if not data.empty else 0,
        "stable_security_ids": int(data["stable_security_id"].nunique()) if not data.empty else 0,
        "sessions": int(data["date"].nunique()) if not data.empty else 0,
        "pit_clean_rows": int(data["pit_universe_label_clean"].sum()) if not data.empty else 0,
    }


def selector_price_map_adapter(
    *,
    price_map_path: Path,
    price_manifest_path: Path,
    price_search_root: Path,
    component_frame: pd.DataFrame,
    as_of: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    blockers: list[str] = []
    price_map = pd.read_csv(price_map_path)
    manifest = read_json(price_manifest_path)
    expected_output = ((manifest.get("outputs") or {}).get("selector_price_map") or {})
    if manifest.get("status") != "READY_CURRENT_SELECTOR_PRICE_MAP_NONSELECTING":
        blockers.append("price_map_manifest_status_invalid")
    if sha256_file(price_map_path) != str(expected_output.get("sha256") or "").lower():
        blockers.append("price_map_manifest_output_sha_mismatch")
    generated_at = pd.to_datetime(manifest.get("generated_at_utc"), errors="coerce", utc=True)
    if pd.isna(generated_at):
        blockers.append("price_map_manifest_generated_at_invalid")
        generated_at = pd.NaT
    elif generated_at > as_of:
        blockers.append("price_map_manifest_generated_after_as_of")

    required = {"ticker", "status", "path", "sha256", "expected_sha256"}
    missing = sorted(required - set(price_map.columns))
    if missing:
        return pd.DataFrame(columns=PRICE_COLUMNS), unique(
            blockers + ["price_map_missing_columns:" + ",".join(missing)]
        ), {"source_rows": len(price_map), "output_rows": 0}

    component_identity = (
        component_frame.sort_values("decision_time_utc")
        .drop_duplicates("ticker", keep="last")
        .set_index("ticker")[["stable_security_id", "pit_universe_label_clean"]]
        if not component_frame.empty
        else pd.DataFrame(columns=["stable_security_id", "pit_universe_label_clean"])
    )
    file_index: dict[str, list[Path]] = {}
    for path in price_search_root.rglob("*.parquet"):
        file_index.setdefault(path.name.lower(), []).append(path)

    frames: list[pd.DataFrame] = []
    missing_file_tickers: list[str] = []
    hash_mismatch_tickers: list[str] = []
    identity_fallback_tickers: list[str] = []
    for row in price_map.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "").upper().strip().replace(".", "-")
        expected_hash = str(row.get("expected_sha256") or row.get("sha256") or "").lower()
        basename = PureWindowsPath(str(row.get("path") or "")).name.lower()
        if str(row.get("status") or "").lower() != "ready" or not SHA256_RE.fullmatch(expected_hash):
            blockers.append(f"price_map_row_not_ready:{ticker}")
            continue
        candidates = file_index.get(basename, [])
        matching = [path for path in candidates if sha256_file(path) == expected_hash]
        if not candidates:
            missing_file_tickers.append(ticker)
            continue
        if len(matching) != 1:
            hash_mismatch_tickers.append(ticker)
            continue
        raw = pd.read_parquet(matching[0])
        if "Adj Close" not in raw.columns:
            blockers.append(f"price_file_adjusted_close_missing:{ticker}")
            continue
        dates = pd.to_datetime(raw.index, errors="coerce").tz_localize(None).normalize()
        if ticker == "SPY":
            stable_id = "BENCHMARK:SPY"
        elif ticker in component_identity.index:
            stable_id = str(component_identity.at[ticker, "stable_security_id"])
        else:
            stable_id = f"UNVERIFIED_TICKER:{ticker}"
            identity_fallback_tickers.append(ticker)
        frame = pd.DataFrame(
            {
                "date": dates,
                "ticker": ticker,
                "stable_security_id": stable_id,
                "adjusted_close": pd.to_numeric(raw["Adj Close"], errors="coerce").to_numpy(),
                "available_from": generated_at,
                "pit_lifecycle_state": "UNVERIFIED_CURRENT_VINTAGE",
                "pit_universe_label_clean": False,
            }
        )
        frames.append(frame)
    if missing_file_tickers:
        blockers.append(f"price_map_files_missing:{len(missing_file_tickers)}")
    if hash_mismatch_tickers:
        blockers.append(f"price_map_files_hash_ambiguous_or_mismatch:{len(hash_mismatch_tickers)}")
    if identity_fallback_tickers:
        blockers.append(f"price_map_identity_fallback:{len(identity_fallback_tickers)}")
    source = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)
    output, canonical_blockers, diagnostics = canonical_price_observations(
        source, as_of=as_of
    )
    blockers.extend(canonical_blockers)
    blockers.extend(
        [
            "selector_price_map_adapter_pit_universe_not_clean",
            "selector_price_map_adapter_lifecycle_unverified",
        ]
    )
    diagnostics.update(
        {
            "adapter": "hash_pinned_selector_price_map_diagnostic",
            "price_map": fingerprint(price_map_path),
            "price_manifest": fingerprint(price_manifest_path),
            "resolved_price_files": len(frames),
            "missing_file_tickers": missing_file_tickers[:25],
            "hash_mismatch_tickers": hash_mismatch_tickers[:25],
            "identity_fallback_tickers": identity_fallback_tickers[:25],
            "source_available_from_utc": generated_at.isoformat() if pd.notna(generated_at) else None,
        }
    )
    return output, unique(blockers), diagnostics


def build_daily_returns(
    prices: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    if prices.empty:
        return pd.DataFrame(columns=DAILY_RETURN_COLUMNS), ["daily_returns_no_price_rows"], {
            "rows": 0
        }
    blockers: list[str] = []
    data = prices.copy().sort_values(["stable_security_id", "date"])
    schedule = nyse_schedule(data["date"].min(), data["date"].max())
    session_number = pd.Series(np.arange(len(schedule)), index=schedule.index)
    data["_session_number"] = data["date"].map(session_number)
    grouped = data.groupby("stable_security_id", sort=False)
    data["_prior_session_number"] = grouped["_session_number"].shift(1)
    data["_prior_close"] = grouped["adjusted_close"].shift(1)
    data["_prior_available"] = grouped["available_from"].shift(1)
    data["_prior_clean"] = grouped["pit_universe_label_clean"].shift(1)
    consecutive = data["_session_number"].sub(data["_prior_session_number"]).eq(1)
    valid = consecutive & data["_prior_close"].gt(0) & data["_prior_available"].notna()
    skipped_gaps = int((data["_prior_close"].notna() & ~consecutive).sum())
    if skipped_gaps:
        blockers.append(f"daily_returns_nonconsecutive_price_pairs_skipped:{skipped_gaps}")
    current = data.loc[valid].copy()
    result = current[
        ["date", "ticker", "stable_security_id", "pit_lifecycle_state"]
    ].copy()
    result["return"] = current["adjusted_close"].div(current["_prior_close"]).sub(1.0)
    result["available_from"] = current["available_from"].where(
        current["available_from"].ge(current["_prior_available"]),
        current["_prior_available"],
    )
    result["pit_universe_label_clean"] = (
        current["pit_universe_label_clean"].astype(bool)
        & current["_prior_clean"].eq(True)
    )
    result = result[DAILY_RETURN_COLUMNS].sort_values(
        ["date", "stable_security_id"]
    ).reset_index(drop=True)
    return result, unique(blockers), {
        "rows": len(result),
        "tickers": int(result["ticker"].nunique()),
        "stable_security_ids": int(result["stable_security_id"].nunique()),
        "sessions": int(result["date"].nunique()),
        "nonconsecutive_pairs_skipped": skipped_gaps,
        "pit_clean_rows": int(result["pit_universe_label_clean"].sum()),
    }


def attach_labels(
    component_frame: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    benchmark_ticker: str,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    if component_frame.empty or prices.empty:
        return component_frame, [], {"63": 0, "126": 0}
    output = component_frame.copy()
    min_date = min(output["feature_date"].min(), prices["date"].min())
    max_date = max(output["feature_date"].max(), prices["date"].max()) + pd.Timedelta(days=400)
    sessions = nyse_schedule(min_date, max_date).index
    price_lookup = {
        (str(row.stable_security_id), pd.Timestamp(row.date).normalize()): (
            float(row.adjusted_close),
            pd.Timestamp(row.available_from),
        )
        for row in prices.itertuples(index=False)
    }
    benchmark_rows = prices.loc[prices["ticker"].eq(benchmark_ticker)].copy()
    benchmark_lookup = {
        pd.Timestamp(row.date).normalize(): (
            float(row.adjusted_close),
            pd.Timestamp(row.available_from),
        )
        for row in benchmark_rows.itertuples(index=False)
    }
    blockers: list[str] = []
    label_counts: dict[str, int] = {}
    for horizon in (63, 126):
        values: list[float] = []
        available_values: list[pd.Timestamp | pd.NaT] = []
        for row in output.itertuples(index=False):
            decision_date = pd.Timestamp(row.feature_date).normalize()
            future = sessions[sessions > decision_date]
            if len(future) <= horizon:
                values.append(np.nan)
                available_values.append(pd.NaT)
                continue
            entry_date = pd.Timestamp(future[0]).normalize()
            exit_date = pd.Timestamp(future[horizon]).normalize()
            stock_entry = price_lookup.get((str(row.stable_security_id), entry_date))
            stock_exit = price_lookup.get((str(row.stable_security_id), exit_date))
            benchmark_entry = benchmark_lookup.get(entry_date)
            benchmark_exit = benchmark_lookup.get(exit_date)
            endpoints = (stock_entry, stock_exit, benchmark_entry, benchmark_exit)
            if any(value is None for value in endpoints):
                values.append(np.nan)
                available_values.append(pd.NaT)
                continue
            assert stock_entry and stock_exit and benchmark_entry and benchmark_exit
            label_available = max(
                stock_entry[1],
                stock_exit[1],
                benchmark_entry[1],
                benchmark_exit[1],
            )
            if label_available > as_of:
                values.append(np.nan)
                available_values.append(pd.NaT)
                continue
            stock_return = stock_exit[0] / stock_entry[0] - 1.0
            benchmark_return = benchmark_exit[0] / benchmark_entry[0] - 1.0
            values.append(stock_return - benchmark_return)
            available_values.append(label_available)
        output[f"realized_benchmark_excess_{horizon}d"] = values
        output[f"label_available_at_{horizon}d"] = pd.to_datetime(
            available_values, errors="coerce", utc=True
        )
        label_counts[str(horizon)] = int(
            output[f"realized_benchmark_excess_{horizon}d"].notna().sum()
        )
    if benchmark_rows.empty:
        blockers.append(f"benchmark_price_missing:{benchmark_ticker}")
    return output, unique(blockers), label_counts


def validate_prior_attestation(
    path: Path | None,
    source_sha256: str,
    weight_column: str,
) -> tuple[bool, dict[str, Any], list[str]]:
    if path is None:
        return False, {}, []
    try:
        value = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, {}, [f"prior_attestation_unreadable:{type(exc).__name__}:{exc}"]
    accepted = (
        isinstance(value, dict)
        and value.get("schema_version") == "run287-scientific-prior-weights-attestation-v1"
        and value.get("status") == "ACCEPTED_RESEARCH_PRIOR_WEIGHTS"
        and str(value.get("source_sha256") or "").lower() == source_sha256
        and value.get("weight_column") == weight_column
        and value.get("research_only") is True
    )
    return accepted, value if isinstance(value, dict) else {}, ([] if accepted else ["prior_attestation_invalid"])


def build_prior_weights(
    *,
    source_path: Path,
    weight_column: str,
    portfolio_id: str,
    weight_basis: str,
    archive_members: Mapping[str, Mapping[str, Any]],
    archive_restore_root: Path | None,
    attestation_path: Path | None,
) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    blockers: list[str] = []
    source = load_table(source_path)
    required = {"rebalance_date", "ticker", weight_column}
    missing = sorted(required - set(source.columns))
    source_hash = sha256_file(source_path)
    if missing:
        return pd.DataFrame(columns=PRIOR_OUTPUT_COLUMNS), [
            "prior_weights_source_missing_columns:" + ",".join(missing)
        ], {"source_rows": len(source), "output_rows": 0, "source": fingerprint(source_path)}

    data = pd.DataFrame(
        {
            "rebalance_date": normalized_date_series(source["rebalance_date"]),
            "ticker": stable_ticker(source["ticker"]),
            "weight": pd.to_numeric(source[weight_column], errors="coerce"),
        }
    )
    invalid = (
        data["rebalance_date"].isna()
        | data["ticker"].eq("")
        | ~np.isfinite(data["weight"])
        | data["weight"].lt(0)
    )
    if invalid.any():
        blockers.append(f"prior_weights_invalid_rows:{int(invalid.sum())}")
    duplicate = data.duplicated(["rebalance_date", "ticker"], keep=False)
    if duplicate.any():
        blockers.append(f"prior_weights_duplicate_rows:{int(duplicate.sum())}")
    data = data.loc[~(invalid | duplicate)].copy()
    sums = data.groupby("rebalance_date")["weight"].sum()
    bad_sums = sums[~np.isclose(sums, 1.0, rtol=0.0, atol=1e-9)]
    if len(bad_sums):
        blockers.append(f"prior_weights_dates_not_sum_one:{len(bad_sums)}")

    source_member_path = ""
    archive_accepted = False
    if archive_restore_root is not None and archive_members:
        try:
            source_member_path = source_path.resolve().relative_to(
                archive_restore_root.resolve()
            ).as_posix()
        except ValueError:
            source_member_path = ""
        member = archive_members.get(source_member_path) if source_member_path else None
        archive_accepted = bool(member and member.get("sha256") == source_hash)
    attested, attestation, attestation_blockers = validate_prior_attestation(
        attestation_path, source_hash, weight_column
    )
    blockers.extend(attestation_blockers)
    source_accepted = archive_accepted or attested
    if not source_accepted:
        blockers.append("prior_weights_source_not_accepted")
    source_kind = (
        "HASH_PINNED_RUN287_RESEARCH_STATIC_ARCHIVE"
        if archive_accepted
        else "ACCEPTED_RESEARCH_PRIOR_ATTESTATION"
        if attested
        else "UNATTESTED_RESEARCH_SOURCE"
    )
    data["source_sha256"] = source_hash
    data["portfolio_id"] = portfolio_id
    data["weight_basis"] = weight_basis
    data["source_kind"] = source_kind
    data["source_member_path"] = source_member_path
    data["source_accepted"] = source_accepted
    data = data[PRIOR_OUTPUT_COLUMNS].sort_values(
        ["rebalance_date", "ticker"]
    ).reset_index(drop=True)
    latest = data["rebalance_date"].max() if not data.empty else pd.NaT
    latest_rows = data.loc[data["rebalance_date"].eq(latest)] if pd.notna(latest) else data
    return data, unique(blockers), {
        "source_rows": len(source),
        "output_rows": len(data),
        "decision_dates": int(data["rebalance_date"].nunique()),
        "latest_rebalance_date": latest.date().isoformat() if pd.notna(latest) else None,
        "latest_rows": len(latest_rows),
        "latest_weight_sum": float(latest_rows["weight"].sum()) if len(latest_rows) else 0.0,
        "source": fingerprint(source_path),
        "source_member_path": source_member_path,
        "source_accepted": source_accepted,
        "attestation": fingerprint(attestation_path) if attestation_path else None,
        "attestation_payload": attestation if attestation else None,
    }


def render_report(summary: Mapping[str, Any]) -> str:
    blockers = summary.get("materialization_blockers") or []
    readiness_blockers = summary.get("readiness_data_blockers") or []
    lines = [
        "# Run287 scientific weighting input materialization",
        "",
        f"- status: `{summary['status']}`",
        f"- readiness status: `{summary['readiness_status']}`",
        f"- component rows: `{summary['row_counts']['component_frame']}`",
        f"- daily return rows: `{summary['row_counts']['daily_returns']}`",
        f"- prior weight rows: `{summary['row_counts']['prior_weights']}`",
        "- model fit executed: `false`",
        "- portfolio weights produced: `false`",
        "",
        "## Materialization blockers",
        "",
    ]
    lines.extend([f"- `{item}`" for item in blockers] or ["- none"])
    lines.extend(["", "## Readiness blockers", ""])
    lines.extend([f"- `{item}`" for item in readiness_blockers] or ["- none"])
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "These files are research inputs only. A materialized file is not proof that its historical membership, lifecycle, component availability, or prior-book authority is clean. The readiness audit remains the controlling fail-closed gate.",
            "",
        ]
    )
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of = pd.to_datetime(args.as_of_time, errors="coerce", utc=True)
    if pd.isna(as_of):
        raise ValueError("invalid --as-of-time")

    materialization_contract_path = Path(args.contract).resolve()
    contract = read_json(materialization_contract_path)
    contract_failures = validate_materialization_contract(contract)
    archive_path = Path(args.static_archive).resolve() if args.static_archive else None
    archive_members, archive_blockers, archive_diagnostics = load_archive_members(
        archive_path, contract
    )

    if args.component_observations:
        component_sources = [Path(value).resolve() for value in args.component_observations]
        raw = pd.concat([load_table(path) for path in component_sources], ignore_index=True)
        component_frame, component_blockers, component_diagnostics = (
            canonicalize_component_observations(raw, as_of=as_of)
        )
        component_diagnostics["adapter"] = "canonical_component_observations"
        component_diagnostics["sources"] = [fingerprint(path) for path in component_sources]
    elif args.scored_snapshot:
        component_sources = [Path(value).resolve() for value in args.scored_snapshot]
        component_frame, component_blockers, component_diagnostics = scored_snapshot_adapter(
            component_sources, as_of=as_of
        )
    else:
        component_sources = []
        component_frame, component_blockers, component_diagnostics = (
            empty_component_frame(),
            ["component_source_missing"],
            {"source_rows": 0, "output_rows": 0},
        )

    if args.price_observations:
        price_source_path = Path(args.price_observations).resolve()
        prices, price_blockers, price_diagnostics = canonical_price_observations(
            load_table(price_source_path), as_of=as_of
        )
        price_diagnostics["adapter"] = "canonical_price_observations"
        price_diagnostics["source"] = fingerprint(price_source_path)
    elif args.price_map:
        prices, price_blockers, price_diagnostics = selector_price_map_adapter(
            price_map_path=Path(args.price_map).resolve(),
            price_manifest_path=Path(args.price_manifest).resolve(),
            price_search_root=Path(args.price_search_root).resolve(),
            component_frame=component_frame,
            as_of=as_of,
        )
    else:
        prices, price_blockers, price_diagnostics = (
            pd.DataFrame(columns=PRICE_COLUMNS),
            ["price_source_missing"],
            {"source_rows": 0, "output_rows": 0},
        )

    component_frame, label_blockers, label_diagnostics = attach_labels(
        component_frame,
        prices,
        as_of=as_of,
        benchmark_ticker=str(args.benchmark_ticker).upper(),
    )
    daily_returns, return_blockers, return_diagnostics = build_daily_returns(prices)

    prior_path = Path(args.prior_weights_source).resolve()
    prior_weights, prior_blockers, prior_diagnostics = build_prior_weights(
        source_path=prior_path,
        weight_column=str(args.prior_weight_column),
        portfolio_id=str(args.portfolio_id),
        weight_basis=str(args.weight_basis),
        archive_members=archive_members,
        archive_restore_root=(
            Path(args.archive_restore_root).resolve()
            if args.archive_restore_root
            else None
        ),
        attestation_path=(
            Path(args.prior_attestation).resolve() if args.prior_attestation else None
        ),
    )

    component_path = output_dir / "component_frame.parquet"
    returns_path = output_dir / "daily_returns.parquet"
    prior_path_out = output_dir / "prior_weights.csv"
    component_frame.to_parquet(component_path, index=False)
    daily_returns.to_parquet(returns_path, index=False)
    prior_weights.to_csv(prior_path_out, index=False)

    readiness_payload = readiness.audit(
        contract_path=Path(args.readiness_contract).resolve(),
        component_frame_path=component_path,
        daily_returns_path=returns_path,
        prior_weights_path=prior_path_out,
        output_dir=output_dir / "readiness",
        as_of_time=as_of.isoformat(),
    )
    materialization_blockers = unique(
        contract_failures
        + archive_blockers
        + component_blockers
        + price_blockers
        + label_blockers
        + return_blockers
        + prior_blockers
    )
    status = (
        "MATERIALIZED_READY_FOR_PREREGISTRATION"
        if readiness_payload["data_ready"] and not materialization_blockers
        else "MATERIALIZED_RESEARCH_INPUTS_WITH_BLOCKERS"
    )
    safety = dict(contract["safety"])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "as_of_time_utc": as_of.isoformat(),
        "contract_valid": not contract_failures,
        "materialization_blockers": materialization_blockers,
        "readiness_status": readiness_payload["status"],
        "readiness_data_ready": readiness_payload["data_ready"],
        "readiness_data_blockers": readiness_payload["data_blockers"],
        "row_counts": {
            "component_frame": len(component_frame),
            "daily_returns": len(daily_returns),
            "prior_weights": len(prior_weights),
        },
        "diagnostics": {
            "component_frame": component_diagnostics,
            "labels": label_diagnostics,
            "prices": price_diagnostics,
            "daily_returns": return_diagnostics,
            "prior_weights": prior_diagnostics,
            "archive": archive_diagnostics,
        },
        "inputs": {
            "materialization_contract": fingerprint(materialization_contract_path),
            "readiness_contract": fingerprint(Path(args.readiness_contract).resolve()),
            "component_sources": [fingerprint(path) for path in component_sources],
            "static_archive": fingerprint(archive_path) if archive_path else None,
        },
        "outputs": {
            "component_frame": fingerprint(component_path),
            "daily_returns": fingerprint(returns_path),
            "prior_weights": fingerprint(prior_path_out),
            "readiness": fingerprint(output_dir / "readiness" / "data_readiness.json"),
        },
        "safety": safety,
    }
    write_json(output_dir / "materialization_summary.json", summary)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "as_of_time_utc": as_of.isoformat(),
        "inputs": summary["inputs"],
        "outputs": {
            **summary["outputs"],
            "materialization_summary": fingerprint(
                output_dir / "materialization_summary.json"
            ),
        },
        "source_provenance": {
            "component": component_diagnostics.get("sources") or component_diagnostics.get("source"),
            "prices": price_diagnostics,
            "prior_weights": prior_diagnostics.get("source"),
            "prior_weights_source_accepted": prior_diagnostics.get("source_accepted"),
        },
        "materialization_blockers": materialization_blockers,
        "readiness_status": readiness_payload["status"],
        "safety": safety,
    }
    write_json(output_dir / "input_manifest.json", manifest)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--readiness-contract", default=str(DEFAULT_READINESS_CONTRACT))
    component = parser.add_mutually_exclusive_group(required=True)
    component.add_argument("--component-observations", action="append")
    component.add_argument("--scored-snapshot", action="append")
    price = parser.add_mutually_exclusive_group(required=True)
    price.add_argument("--price-observations")
    price.add_argument("--price-map")
    parser.add_argument("--price-manifest", default="")
    parser.add_argument("--price-search-root", default="")
    parser.add_argument("--static-archive", default="")
    parser.add_argument("--archive-restore-root", default="")
    parser.add_argument("--prior-weights-source", required=True)
    parser.add_argument("--prior-weight-column", required=True)
    parser.add_argument("--prior-attestation", default="")
    parser.add_argument("--portfolio-id", default="run287_main_research_anchor")
    parser.add_argument("--weight-basis", default="total_portfolio_including_cash")
    parser.add_argument("--benchmark-ticker", default="SPY")
    parser.add_argument("--as-of-time", required=True)
    parser.add_argument(
        "--output-dir", default="outputs/run287_scientific_weighting_inputs"
    )
    args = parser.parse_args()
    if args.price_map and (not args.price_manifest or not args.price_search_root):
        parser.error("--price-map requires --price-manifest and --price-search-root")
    return args


def main() -> int:
    args = parse_args()
    summary = build(args)
    print(
        json.dumps(
            {
                "status": summary["status"],
                "readiness_status": summary["readiness_status"],
                "row_counts": summary["row_counts"],
                "materialization_blockers": summary["materialization_blockers"],
                "readiness_data_blockers": summary["readiness_data_blockers"],
                "model_fit_executed": False,
                "portfolio_weights_produced": False,
                "output_dir": str(Path(args.output_dir).resolve()),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
