#!/usr/bin/env python3
"""Train a PIT-purged, proposal-only Run287 expected-return challenger.

The real historical path is fail-closed behind the U0-v2 experiment census.
This program never writes target books, creates orders, changes cash, mutates an
operating ledger, promotes a challenger, or runs a full rebuild.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-expected-return-challenger-v1"
READY_STATUS = "READY_EXPECTED_RETURN_FORWARD_REVIEW_ONLY"
BLOCKED_STATUS = "BLOCKED_EXPECTED_RETURN_CHALLENGER"
TARGET_KINDS = ("absolute", "benchmark_excess", "sector_neutral")
HORIZONS = (21, 63, 126)
EXPECTED_CONTRACT_SHA256 = (
    "3c7e2cffe20674c9e4fcd616f4b3764e0fad6487acf6129717b5c17e93dd73f7"
)
FORBIDDEN_FEATURE_RE = re.compile(
    r"(^|_)(future|forward|label|target|outcome)(_|$)|"
    r"^r_(1m|3m|6m|12m|24m|36m)$|^bench_(r|ret)_",
    re.IGNORECASE,
)
NYSE = mcal.get_calendar("NYSE")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = "wscha231/r1000-quant-engine"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key:{key}")
        out[key] = value
    return out


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()) if path.exists() else str(path),
        "exists": path.is_file(),
        "bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            timeout=10,
        ).strip()
    except Exception:
        return ""


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    if not FULL_SHA_RE.fullmatch(ancestor) or not FULL_SHA_RE.fullmatch(descendant):
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=REPO_ROOT,
            timeout=10,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def json_clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_clean(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_clean(nested) for nested in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).isoformat()
    if value is pd.NaT:
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            json_clean(value), indent=2, sort_keys=True, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("expected-return contract must be an object")
    if contract.get("schema_version") != (
        "run287-expected-return-challenger-contract-v1"
    ):
        raise ValueError("expected-return contract schema mismatch")
    if contract.get("family_id") != (
        "future_expected_excess_return_multihorizon_v1"
    ):
        raise ValueError("expected-return family identity mismatch")
    horizons = contract.get("horizons")
    features = contract.get("features")
    if not isinstance(horizons, dict) or set(horizons) != {
        "21",
        "63",
        "126",
    }:
        raise ValueError("expected-return horizons must be exactly 21/63/126")
    if not isinstance(features, dict) or set(features) != set(horizons):
        raise ValueError("expected-return feature groups mismatch")
    score_weight = 0.0
    for horizon in HORIZONS:
        spec = horizons[str(horizon)]
        names = features[str(horizon)]
        if not isinstance(spec, dict) or not isinstance(names, list) or not names:
            raise ValueError(f"invalid horizon contract:{horizon}")
        if len(names) != len(set(names)) or any(
            not isinstance(name, str) or not name for name in names
        ):
            raise ValueError(f"invalid feature whitelist:{horizon}")
        forbidden = sorted(name for name in names if FORBIDDEN_FEATURE_RE.search(name))
        if forbidden:
            raise ValueError("future/label columns in feature whitelist:" + ",".join(forbidden))
        for key in (
            "stock_return",
            "benchmark_return",
            "stock_label_end",
            "benchmark_label_end",
        ):
            if not isinstance(spec.get(key), str) or not spec[key]:
                raise ValueError(f"missing horizon label contract:{horizon}:{key}")
        score_weight += float(spec.get("score_weight") or 0.0)
    if abs(score_weight - 1.0) > 1e-12:
        raise ValueError("horizon score weights must sum to one")
    fixed_score_weights = {"21": 0.0, "63": 0.65, "126": 0.35}
    for horizon, expected_weight in fixed_score_weights.items():
        actual_weight = float(horizons[horizon].get("score_weight") or 0.0)
        if not math.isclose(actual_weight, expected_weight, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"fixed horizon score weight mismatch:{horizon}:"
                f"expected={expected_weight}:actual={actual_weight}"
            )
    purge_and_windows = contract.get("purge_and_windows") or {}
    embargo_sessions = purge_and_windows.get("embargo_nyse_sessions")
    if type(embargo_sessions) is not int or embargo_sessions != 126:
        raise ValueError("fixed NYSE-session embargo must equal 126")
    alpha_mix = (contract.get("target_contract") or {}).get(
        "benchmark_sector_mix"
    ) or {}
    for key, expected_weight in {
        "benchmark_excess": 0.7,
        "sector_neutral": 0.3,
    }.items():
        actual_weight = float(alpha_mix.get(key) or 0.0)
        if not math.isclose(actual_weight, expected_weight, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(
                f"fixed alpha target mix mismatch:{key}:"
                f"expected={expected_weight}:actual={actual_weight}"
            )
    model = contract.get("model") or {}
    if (
        model.get("parameter_tuning_allowed") is not False
        or float(model.get("long_history_weight") or 0.0)
        + float(model.get("recent_history_weight") or 0.0)
        != 1.0
    ):
        raise ValueError("fixed model blend contract mismatch")
    safety = contract.get("safety") or {}
    if safety.get("research_only") is not True or any(
        safety.get(key) is not False
        for key in (
            "automatic_promotion_allowed",
            "champion_change_allowed",
            "portfolio_mutation_allowed",
            "target_books_written",
            "orders_generated",
            "operating_ledger_mutated",
            "production_or_live_trading_enabled",
        )
    ):
        raise ValueError("expected-return safety contract mismatch")
    actual_contract_sha256 = canonical_sha256(contract)
    if actual_contract_sha256 != EXPECTED_CONTRACT_SHA256:
        raise ValueError(
            "expected-return contract hash mismatch:"
            f"expected={EXPECTED_CONTRACT_SHA256}:actual={actual_contract_sha256}"
        )
    return contract


def u0_gate(census: Any, contract: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    gate = contract["historical_gate"]
    if not isinstance(census, dict):
        return ["u0_census_not_an_object"]
    if census.get("schema_version") != gate["u0_schema_version"]:
        blockers.append("u0_census_schema_mismatch")
    if census.get("repository") != REPOSITORY:
        blockers.append("u0_census_repository_mismatch")
    if census.get("audit_default_branch") != "master":
        blockers.append("u0_census_default_branch_mismatch")
    audit_sha = str(census.get("audit_default_branch_sha") or "").lower()
    current_sha = git_head().lower()
    if not FULL_SHA_RE.fullmatch(audit_sha):
        blockers.append("u0_census_audit_sha_invalid")
    elif not git_is_ancestor(audit_sha, current_sha):
        blockers.append("u0_census_audit_sha_not_ancestor_of_runner")
    source = census.get("source_contract")
    if not isinstance(source, dict):
        source = {}
        blockers.append("u0_census_source_contract_missing")
    for key in ("branch_payload_sha256", "pull_request_payload_sha256"):
        if not SHA256_RE.fullmatch(str(source.get(key) or "").lower()):
            blockers.append(f"u0_census_source_hash_invalid:{key}")
    if (
        source.get("metadata_only") is not True
        or source.get("fullrun_executed") is not False
        or source.get("production_or_live_mutated") is not False
        or source.get("champion_changed") is not False
    ):
        blockers.append("u0_census_source_safety_mismatch")
    summary = census.get("summary")
    if not isinstance(summary, dict):
        summary = {}
        blockers.append("u0_census_summary_missing")
    if summary.get("historical_experiment_census_complete") is not True:
        blockers.append("u0_historical_experiment_census_incomplete")
    if summary.get("historical_challenger_allowed") is not True:
        blockers.append("u0_historical_challenger_not_allowed")
    promotion_blockers = census.get("promotion_blockers")
    if not isinstance(promotion_blockers, list) or promotion_blockers:
        blockers.append("u0_promotion_blockers_not_empty")
    return sorted(set(blockers))


def required_columns(contract: Mapping[str, Any]) -> list[str]:
    required = set(contract["data_policy"]["required_identity_columns"])
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        required.update(contract["features"][str(horizon)])
        if float(spec["score_weight"]) > 0.0:
            required.update(
                spec[key]
                for key in (
                    "stock_return",
                    "benchmark_return",
                    "stock_label_end",
                    "benchmark_label_end",
                )
            )
    return sorted(required)


def input_readiness(frame: pd.DataFrame, contract: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    missing = sorted(set(required_columns(contract)) - set(frame.columns))
    if missing:
        blockers.append("feature_store_missing_required_columns:" + ",".join(missing))
    if frame.empty:
        return ["feature_store_empty"]
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        if float(spec["score_weight"]) <= 0.0:
            continue
        for key in (
            "stock_return",
            "benchmark_return",
            "stock_label_end",
            "benchmark_label_end",
        ):
            column = spec[key]
            if column in frame.columns and frame[column].notna().sum() == 0:
                blockers.append(f"label_provenance_empty:{column}")
    return sorted(set(blockers))


def _rank_group(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() < 2 or numeric.nunique(dropna=True) < 2:
        return pd.Series(0.5, index=values.index, dtype=float)
    return numeric.rank(pct=True, method="average").fillna(0.5).clip(0.0, 1.0)


def prepare_frame(frame: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    blockers = input_readiness(frame, contract)
    if blockers:
        raise ValueError(";".join(blockers))
    out = frame.copy()
    out["feature_date"] = pd.to_datetime(out["feature_date"], errors="coerce").dt.normalize()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    if out[["feature_date", "rebalance_date"]].isna().any().any():
        raise ValueError("invalid feature or rebalance date")
    if not out["feature_date"].eq(out["rebalance_date"]).all():
        raise ValueError("feature_date and rebalance_date identity mismatch")
    if out["ticker"].isna().any():
        raise ValueError("null ticker in feature store")
    if out["sector"].isna().any():
        raise ValueError("null sector in feature store")
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper().str.replace(".", "-", regex=False)
    out["sector"] = out["sector"].astype(str).str.strip()
    if out["ticker"].eq("").any():
        raise ValueError("empty ticker in feature store")
    if out["sector"].eq("").any():
        raise ValueError("empty sector in feature store")
    benchmark_identity = out["benchmark_identity"].astype(str).str.strip().str.upper()
    benchmark_source = out["benchmark_source"].astype(str).str.strip().str.upper()
    expected_benchmark = str(contract["data_policy"]["canonical_benchmark"]).upper()
    expected_source = str(
        contract["data_policy"]["canonical_benchmark_source"]
    ).upper()
    if not benchmark_identity.eq(expected_benchmark).all():
        raise ValueError("benchmark identity provenance mismatch")
    if not benchmark_source.eq(expected_source).all():
        raise ValueError("benchmark source provenance mismatch")
    out["benchmark_identity"] = benchmark_identity
    out["benchmark_source"] = benchmark_source
    if out.duplicated(["feature_date", "ticker"]).any():
        raise ValueError("duplicate feature_date/ticker rows")

    all_features = sorted(
        {
            name
            for horizon in HORIZONS
            for name in contract["features"][str(horizon)]
        }
    )
    for name in all_features:
        out[f"xrank__{name}"] = out.groupby("feature_date", group_keys=False)[name].transform(_rank_group)
    for horizon in HORIZONS:
        spec = contract["horizons"][str(horizon)]
        if float(spec["score_weight"]) <= 0.0:
            for key in ("stock_return", "benchmark_return"):
                if spec[key] not in out.columns:
                    out[spec[key]] = np.nan
            for key in ("stock_label_end", "benchmark_label_end"):
                if spec[key] not in out.columns:
                    out[spec[key]] = pd.NaT
        stock = pd.to_numeric(out[spec["stock_return"]], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        benchmark = pd.to_numeric(
            out[spec["benchmark_return"]], errors="coerce"
        ).replace([np.inf, -np.inf], np.nan)
        stock_end = pd.to_datetime(out[spec["stock_label_end"]], errors="coerce").dt.normalize()
        benchmark_end = pd.to_datetime(out[spec["benchmark_label_end"]], errors="coerce").dt.normalize()
        if benchmark.groupby(out["feature_date"]).nunique(dropna=True).gt(1).any():
            raise ValueError(f"benchmark return is not unique by decision:{horizon}")
        if benchmark_end.groupby(out["feature_date"]).nunique(dropna=True).gt(1).any():
            raise ValueError(f"benchmark label end is not unique by decision:{horizon}")
        complete = stock.notna() & benchmark.notna() & stock_end.notna() & benchmark_end.notna()
        if stock_end.loc[complete].ne(benchmark_end.loc[complete]).any():
            raise ValueError(f"stock/benchmark label end mismatch:{horizon}")
        if (
            stock_end.where(complete)
            .groupby(out["feature_date"])
            .nunique(dropna=True)
            .gt(1)
            .any()
        ):
            raise ValueError(f"mixed cross-sectional label end dates:{horizon}")
        if (
            (stock_end.where(complete) <= out["feature_date"]).fillna(False).any()
            or (benchmark_end.where(complete) <= out["feature_date"]).fillna(False).any()
        ):
            raise ValueError(f"forward label does not end after decision:{horizon}")
        row_available = pd.concat([stock_end, benchmark_end], axis=1).max(axis=1).where(complete)
        # All cross-sectional targets for one decision mature together.
        available = row_available.groupby(out["feature_date"]).transform("max").where(complete)
        absolute = stock.where(complete)
        excess = (stock - benchmark).where(complete)
        sector_size = absolute.groupby(
            [out["feature_date"], out["sector"]]
        ).transform("count")
        sector_mean = absolute.groupby([out["feature_date"], out["sector"]]).transform("mean")
        sector_neutral = (absolute - sector_mean).where(
            complete
            & sector_size.ge(int(contract["target_contract"]["minimum_sector_cross_section"]))
        )
        out[f"label_available_at_{horizon}d"] = available
        out[f"y_absolute_{horizon}d"] = absolute
        out[f"y_benchmark_excess_{horizon}d"] = excess
        out[f"y_sector_neutral_{horizon}d"] = sector_neutral
        out[f"y_downside_{horizon}d"] = absolute.le(0.0).where(complete)
        feature_names = contract["features"][str(horizon)]
        out[f"feature_coverage_{horizon}d"] = out[feature_names].notna().mean(axis=1)
    return out.sort_values(["feature_date", "ticker"]).reset_index(drop=True)


def nyse_embargo_cutoffs(
    decision_dates: list[pd.Timestamp], embargo_sessions: int
) -> dict[pd.Timestamp, pd.Timestamp | None]:
    if not decision_dates:
        return {}
    start = min(decision_dates) - pd.Timedelta(days=max(730, embargo_sessions * 3))
    end = max(decision_dates) + pd.Timedelta(days=7)
    sessions = NYSE.valid_days(start_date=start, end_date=end).tz_localize(None).normalize()
    out: dict[pd.Timestamp, pd.Timestamp | None] = {}
    for raw_date in decision_dates:
        decision = pd.Timestamp(raw_date).normalize()
        prior = sessions[sessions < decision]
        out[decision] = (
            pd.Timestamp(prior[-embargo_sessions]).normalize()
            if len(prior) >= embargo_sessions
            else None
        )
    return out


def _standardize_fit(
    train_x: np.ndarray, test_x: np.ndarray
) -> tuple[np.ndarray, np.ndarray, StandardScaler]:
    scaler = StandardScaler()
    scaled_train = scaler.fit_transform(train_x)
    scaled_test = scaler.transform(test_x)
    return scaled_train, scaled_test, scaler


def fit_regression_pair(
    train: pd.DataFrame,
    recent: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    contract: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    minimum_rows = int(contract["model"]["minimum_training_rows"])
    minimum_dates = int(contract["model"]["minimum_training_decision_dates"])
    train = train.dropna(subset=[target_column])
    recent = recent.dropna(subset=[target_column])
    if (
        len(train) < minimum_rows
        or len(recent) < minimum_rows
        or train["feature_date"].nunique() < minimum_dates
        or recent["feature_date"].nunique() < minimum_dates
    ):
        return None

    def one_fit(source: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
        x = source[feature_columns].to_numpy(dtype=float)
        test_x = test[feature_columns].to_numpy(dtype=float)
        scaled_x, scaled_test, scaler = _standardize_fit(x, test_x)
        model = Ridge(
            alpha=float(contract["model"]["ridge_alpha"]),
            fit_intercept=True,
        )
        model.fit(scaled_x, source[target_column].to_numpy(dtype=float))
        return model.predict(scaled_test), {
            "intercept": float(model.intercept_),
            "coefficients": {
                feature_columns[index]: float(model.coef_[index])
                for index in range(len(feature_columns))
            },
            "scaler_mean": {
                feature_columns[index]: float(scaler.mean_[index])
                for index in range(len(feature_columns))
            },
            "scaler_scale": {
                feature_columns[index]: float(scaler.scale_[index])
                for index in range(len(feature_columns))
            },
            "training_rows": len(source),
            "training_dates": int(source["feature_date"].nunique()),
        }

    long_prediction, long_model = one_fit(train)
    recent_prediction, recent_model = one_fit(recent)
    long_weight = float(contract["model"]["long_history_weight"])
    recent_weight = float(contract["model"]["recent_history_weight"])
    blended = long_weight * long_prediction + recent_weight * recent_prediction
    return blended, np.abs(long_prediction - recent_prediction), {
        "long_history": long_model,
        "recent_36_month": recent_model,
    }


def fit_classifier_pair(
    train: pd.DataFrame,
    recent: pd.DataFrame,
    test: pd.DataFrame,
    feature_columns: list[str],
    target_column: str,
    contract: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    minimum_rows = int(contract["model"]["minimum_training_rows"])
    minimum_dates = int(contract["model"]["minimum_training_decision_dates"])
    train = train.dropna(subset=[target_column]).copy()
    recent = recent.dropna(subset=[target_column]).copy()
    if (
        len(train) < minimum_rows
        or len(recent) < minimum_rows
        or train["feature_date"].nunique() < minimum_dates
        or recent["feature_date"].nunique() < minimum_dates
        or train[target_column].nunique() != 2
        or recent[target_column].nunique() != 2
    ):
        return None

    def one_fit(source: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
        x = source[feature_columns].to_numpy(dtype=float)
        test_x = test[feature_columns].to_numpy(dtype=float)
        scaled_x, scaled_test, scaler = _standardize_fit(x, test_x)
        model = LogisticRegression(
            C=float(contract["model"]["logistic_c"]),
            class_weight="balanced",
            max_iter=1200,
            random_state=int(contract["model"]["random_seed"]),
        )
        model.fit(scaled_x, source[target_column].astype(int).to_numpy())
        return model.predict_proba(scaled_test)[:, 1], {
            "intercept": float(model.intercept_[0]),
            "coefficients": {
                feature_columns[index]: float(model.coef_[0, index])
                for index in range(len(feature_columns))
            },
            "scaler_mean": {
                feature_columns[index]: float(scaler.mean_[index])
                for index in range(len(feature_columns))
            },
            "scaler_scale": {
                feature_columns[index]: float(scaler.scale_[index])
                for index in range(len(feature_columns))
            },
            "training_rows": len(source),
            "training_dates": int(source["feature_date"].nunique()),
        }

    long_prediction, long_model = one_fit(train)
    recent_prediction, recent_model = one_fit(recent)
    long_weight = float(contract["model"]["long_history_weight"])
    recent_weight = float(contract["model"]["recent_history_weight"])
    blended = long_weight * long_prediction + recent_weight * recent_prediction
    return blended, np.abs(long_prediction - recent_prediction), {
        "long_history": long_model,
        "recent_36_month": recent_model,
    }


def walk_forward_predictions(
    prepared: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    full_start = pd.Timestamp(contract["purge_and_windows"]["full_start"])
    dates = [
        pd.Timestamp(value).normalize()
        for value in sorted(prepared["feature_date"].dropna().unique())
        if pd.Timestamp(value) >= full_start
    ]
    embargo_sessions = int(contract["purge_and_windows"]["embargo_nyse_sessions"])
    cutoffs = nyse_embargo_cutoffs(dates, embargo_sessions)
    prediction_parts: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    latest_models: dict[str, Any] = {}
    latest_date = max(dates) if dates else None

    for decision in dates:
        test = prepared[prepared["feature_date"].eq(decision)].copy()
        cutoff = cutoffs.get(decision)
        if cutoff is None:
            for horizon in HORIZONS:
                audit_rows.append(
                    {
                        "decision_date": decision,
                        "horizon": horizon,
                        "status": "BLOCKED_EMBARGO_HISTORY",
                        "embargo_cutoff": None,
                        "training_rows": 0,
                    }
                )
            continue
        date_output = test[["feature_date", "rebalance_date", "ticker", "sector"]].copy()
        selection_horizons_ready = True
        selection_candidate_eligible = pd.Series(True, index=test.index, dtype=bool)
        decision_models: dict[str, Any] = {}
        for horizon in HORIZONS:
            selection_required = float(
                contract["horizons"][str(horizon)]["score_weight"]
            ) > 0.0
            scoring_sector_eligible = test.groupby("sector")["ticker"].transform(
                "size"
            ).ge(int(contract["target_contract"]["minimum_sector_cross_section"]))
            if selection_required:
                selection_candidate_eligible &= scoring_sector_eligible
            feature_columns = [
                f"xrank__{name}" for name in contract["features"][str(horizon)]
            ]
            available_col = f"label_available_at_{horizon}d"
            eligible = prepared[
                prepared["feature_date"].le(cutoff)
                & prepared[available_col].notna()
                & prepared[available_col].lt(decision)
            ].copy()
            recent_start = decision - pd.DateOffset(
                months=int(contract["model"]["recent_history_months"])
            )
            recent = eligible[eligible["feature_date"].ge(recent_start)].copy()
            models: dict[str, Any] = {}
            target_results: dict[str, tuple[np.ndarray, np.ndarray, dict[str, Any]]] = {}
            horizon_ready = True
            for target_kind in TARGET_KINDS:
                target_column = f"y_{target_kind}_{horizon}d"
                fitted = fit_regression_pair(
                    eligible,
                    recent,
                    test,
                    feature_columns,
                    target_column,
                    contract,
                )
                if fitted is None:
                    horizon_ready = False
                    break
                target_results[target_kind] = fitted
                models[target_kind] = fitted[2]
            classifier = None
            if horizon_ready:
                classifier = fit_classifier_pair(
                    eligible,
                    recent,
                    test,
                    feature_columns,
                    f"y_downside_{horizon}d",
                    contract,
                )
                if classifier is None:
                    horizon_ready = False
            if not horizon_ready or classifier is None:
                audit_rows.append(
                    {
                        "decision_date": decision,
                        "horizon": horizon,
                        "status": (
                            "BLOCKED_INSUFFICIENT_TRAINING"
                            if selection_required
                            else "UNAVAILABLE_TIMING_ONLY_INSUFFICIENT_TRAINING"
                        ),
                        "embargo_cutoff": cutoff,
                        "training_rows": len(eligible),
                        "training_dates": int(eligible["feature_date"].nunique()),
                        "recent_training_rows": len(recent),
                        "max_training_feature_date": eligible["feature_date"].max() if not eligible.empty else None,
                        "max_label_available_at": eligible[available_col].max() if not eligible.empty else None,
                        "scoring_sector_eligible_rows": int(scoring_sector_eligible.sum()),
                        "scoring_sector_ineligible_rows": int((~scoring_sector_eligible).sum()),
                    }
                )
                if selection_required:
                    selection_horizons_ready = False
                    break
                for column in (
                    "expected_absolute",
                    "expected_benchmark_excess",
                    "expected_sector_neutral",
                    "expected_alpha",
                    "downside_probability",
                    "model_disagreement",
                ):
                    date_output[f"{column}_{horizon}d"] = np.nan
                date_output[f"feature_coverage_{horizon}d"] = test[
                    f"feature_coverage_{horizon}d"
                ].to_numpy()
                for target_kind in TARGET_KINDS:
                    date_output[f"realized_{target_kind}_{horizon}d"] = test[
                        f"y_{target_kind}_{horizon}d"
                    ].to_numpy()
                date_output[f"realized_downside_{horizon}d"] = test[
                    f"y_downside_{horizon}d"
                ].to_numpy()
                date_output[f"label_available_at_{horizon}d"] = test[
                    available_col
                ].to_numpy()
                decision_models[str(horizon)] = {
                    "status": "UNAVAILABLE_TIMING_ONLY_INSUFFICIENT_TRAINING",
                    "features": [
                        name.removeprefix("xrank__") for name in feature_columns
                    ],
                }
                continue
            benchmark_mix = float(
                contract["target_contract"]["benchmark_sector_mix"]["benchmark_excess"]
            )
            sector_mix = float(
                contract["target_contract"]["benchmark_sector_mix"]["sector_neutral"]
            )
            expected_alpha = (
                benchmark_mix * target_results["benchmark_excess"][0]
                + sector_mix * target_results["sector_neutral"][0]
            )
            disagreement = (
                benchmark_mix * target_results["benchmark_excess"][1]
                + sector_mix * target_results["sector_neutral"][1]
            )
            downside_probability = classifier[0]
            date_output[f"expected_absolute_{horizon}d"] = target_results["absolute"][0]
            date_output[f"expected_benchmark_excess_{horizon}d"] = target_results["benchmark_excess"][0]
            date_output[f"expected_sector_neutral_{horizon}d"] = target_results["sector_neutral"][0]
            date_output[f"expected_alpha_{horizon}d"] = expected_alpha
            date_output[f"downside_probability_{horizon}d"] = downside_probability
            date_output[f"model_disagreement_{horizon}d"] = disagreement
            date_output[f"feature_coverage_{horizon}d"] = test[f"feature_coverage_{horizon}d"].to_numpy()
            for target_kind in TARGET_KINDS:
                date_output[f"realized_{target_kind}_{horizon}d"] = test[f"y_{target_kind}_{horizon}d"].to_numpy()
            date_output[f"realized_downside_{horizon}d"] = test[f"y_downside_{horizon}d"].to_numpy()
            date_output[f"label_available_at_{horizon}d"] = test[available_col].to_numpy()
            models["downside"] = classifier[2]
            models["features"] = [
                name.removeprefix("xrank__") for name in feature_columns
            ]
            decision_models[str(horizon)] = models
            audit_rows.append(
                {
                    "decision_date": decision,
                    "horizon": horizon,
                    "status": "FIT_PIT_PURGED",
                    "embargo_cutoff": cutoff,
                    "training_rows": len(eligible),
                    "training_dates": int(eligible["feature_date"].nunique()),
                    "recent_training_rows": len(recent),
                    "recent_training_dates": int(recent["feature_date"].nunique()),
                    "max_training_feature_date": eligible["feature_date"].max(),
                    "max_label_available_at": eligible[available_col].max(),
                    "label_strictly_before_decision": bool(eligible[available_col].max() < decision),
                    "training_feature_on_or_before_embargo": bool(eligible["feature_date"].max() <= cutoff),
                    "feature_set_sha256": canonical_sha256(models["features"]),
                    "scoring_sector_eligible_rows": int(scoring_sector_eligible.sum()),
                    "scoring_sector_ineligible_rows": int((~scoring_sector_eligible).sum()),
                }
            )
        if not selection_horizons_ready:
            continue
        date_output = date_output.loc[selection_candidate_eligible].copy()
        if date_output.empty:
            audit_rows.append(
                {
                    "decision_date": decision,
                    "horizon": "selection",
                    "status": "BLOCKED_NO_SECTOR_NEUTRAL_ELIGIBLE_CANDIDATES",
                    "training_rows": 0,
                }
            )
            continue
        selection_horizons = [
            horizon
            for horizon in HORIZONS
            if float(contract["horizons"][str(horizon)]["score_weight"]) > 0.0
        ]
        horizon_alpha = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"expected_alpha_{horizon}d"]
            for horizon in selection_horizons
        )
        downside = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"downside_probability_{horizon}d"]
            for horizon in selection_horizons
        )
        disagreement = sum(
            float(contract["horizons"][str(horizon)]["score_weight"])
            * date_output[f"model_disagreement_{horizon}d"]
            for horizon in selection_horizons
        )
        date_output["expected_alpha_gross"] = horizon_alpha
        date_output["weighted_downside_probability"] = downside
        date_output["weighted_model_disagreement"] = disagreement
        date_output["entry_timing_score"] = (
            date_output["expected_alpha_21d"]
            - float(contract["score"]["downside_probability_penalty"])
            * date_output["downside_probability_21d"]
            - float(contract["score"]["long_recent_disagreement_penalty"])
            * date_output["model_disagreement_21d"]
        )
        date_output["expected_return_score"] = (
            horizon_alpha
            - float(contract["score"]["downside_probability_penalty"]) * downside
            - float(contract["score"]["long_recent_disagreement_penalty"]) * disagreement
        )
        date_output["expected_return_rank"] = date_output["expected_return_score"].rank(
            ascending=False, method="first"
        )
        date_output["research_only"] = True
        prediction_parts.append(date_output)
        if latest_date is not None and decision == latest_date:
            latest_models = {
                "decision_date": decision,
                "horizons": decision_models,
            }
    predictions = (
        pd.concat(prediction_parts, ignore_index=True)
        if prediction_parts
        else pd.DataFrame()
    )
    return predictions, pd.DataFrame(audit_rows), latest_models


def _metric_block(
    frame: pd.DataFrame,
    prediction_column: str,
    realized_column: str,
) -> dict[str, Any]:
    valid = frame.dropna(subset=[prediction_column, realized_column]).copy()
    if valid.empty:
        return {
            "rows": 0,
            "decision_dates": 0,
            "mean_monthly_spearman_ic": None,
            "positive_ic_share": None,
            "top_bottom_realized_spread": None,
            "rmse": None,
            "sign_hit_rate": None,
        }
    monthly_ic: list[float] = []
    spreads: list[float] = []
    for _, group in valid.groupby("feature_date"):
        if len(group) < 10 or group[prediction_column].nunique() < 2:
            continue
        ic = group[prediction_column].corr(group[realized_column], method="spearman")
        if pd.notna(ic):
            monthly_ic.append(float(ic))
        ranks = group[prediction_column].rank(pct=True, method="average")
        top = group.loc[ranks.ge(0.8), realized_column]
        bottom = group.loc[ranks.le(0.2), realized_column]
        if not top.empty and not bottom.empty:
            spreads.append(float(top.mean() - bottom.mean()))
    error = valid[prediction_column] - valid[realized_column]
    return {
        "rows": len(valid),
        "decision_dates": int(valid["feature_date"].nunique()),
        "mean_monthly_spearman_ic": float(np.mean(monthly_ic)) if monthly_ic else None,
        "positive_ic_share": float(np.mean(np.asarray(monthly_ic) > 0.0)) if monthly_ic else None,
        "top_bottom_realized_spread": float(np.mean(spreads)) if spreads else None,
        "rmse": float(np.sqrt(np.mean(np.square(error)))) if len(error) else None,
        "sign_hit_rate": float(
            np.mean(
                np.sign(valid[prediction_column].to_numpy())
                == np.sign(valid[realized_column].to_numpy())
            )
        ),
    }


def evaluate_predictions(
    predictions: pd.DataFrame, contract: Mapping[str, Any]
) -> dict[str, Any]:
    windows = {
        "full": (
            pd.Timestamp(contract["purge_and_windows"]["full_start"]),
            None,
        ),
        "oos2": (
            pd.Timestamp(contract["purge_and_windows"]["oos2_start"]),
            pd.Timestamp(contract["purge_and_windows"]["oos2_end"]),
        ),
        "oos": (
            pd.Timestamp(contract["purge_and_windows"]["oos_start"]),
            None,
        ),
    }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "metric_semantics": "cross_sectional_expected_return_diagnostics_not_portfolio_performance",
        "windows": {},
    }
    for name, (start, end) in windows.items():
        scoped = predictions[predictions["feature_date"].ge(start)].copy()
        if end is not None:
            scoped = scoped[scoped["feature_date"].le(end)].copy()
        horizon_rows: dict[str, Any] = {}
        for horizon in HORIZONS:
            horizon_rows[str(horizon)] = {
                target_kind: _metric_block(
                    scoped,
                    f"expected_{target_kind}_{horizon}d",
                    f"realized_{target_kind}_{horizon}d",
                )
                for target_kind in TARGET_KINDS
            }
            downside_valid = scoped.dropna(
                subset=[
                    f"downside_probability_{horizon}d",
                    f"realized_downside_{horizon}d",
                ]
            )
            horizon_rows[str(horizon)]["downside"] = {
                "rows": len(downside_valid),
                "brier_score": (
                    float(
                        np.mean(
                            np.square(
                                downside_valid[f"downside_probability_{horizon}d"].to_numpy(dtype=float)
                                - downside_valid[f"realized_downside_{horizon}d"].to_numpy(dtype=float)
                            )
                        )
                    )
                    if not downside_valid.empty
                    else None
                ),
            }
        result["windows"][name] = {
            "start": start,
            "end": end,
            "prediction_rows": len(scoped),
            "prediction_dates": int(scoped["feature_date"].nunique()),
            "horizons": horizon_rows,
            "composite_vs_realized_63d_benchmark_excess": _metric_block(
                scoped,
                "expected_return_score",
                "realized_benchmark_excess_63d",
            ),
        }
    return result


def public_latest_proposal(predictions: pd.DataFrame) -> pd.DataFrame:
    if predictions.empty:
        return pd.DataFrame(
            columns=[
                "feature_date",
                "ticker",
                "sector",
                "expected_return_score",
                "expected_return_rank",
                "expected_alpha_gross",
                "weighted_downside_probability",
                "weighted_model_disagreement",
                "research_only",
            ]
        )
    latest = predictions["feature_date"].max()
    forbidden = re.compile(r"^realized_|^label_available_at_|^y_")
    columns = [column for column in predictions.columns if not forbidden.search(column)]
    proposal = predictions.loc[predictions["feature_date"].eq(latest), columns].copy()
    return proposal.sort_values(
        ["expected_return_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def blocked_artifacts(
    output_dir: Path,
    *,
    blockers: list[str],
    contract: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    empty_predictions = pd.DataFrame()
    empty_predictions.to_csv(output_dir / "expected_return_predictions.csv", index=False)
    pd.DataFrame().to_csv(output_dir / "training_audit.csv", index=False)
    public_latest_proposal(empty_predictions).to_csv(
        output_dir / "latest_expected_return_proposal.csv", index=False
    )
    write_json(output_dir / "model_coefficients.json", {"status": BLOCKED_STATUS})
    write_json(
        output_dir / "expected_return_metrics.json",
        {
            "status": BLOCKED_STATUS,
            "metric_semantics": "not_computed",
            "blockers": blockers,
        },
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "family_id": contract["family_id"],
        "blockers": blockers,
        "historical_model_fit_executed": False,
        "historical_backtest_executed": False,
        "fullrun_executed": False,
        "target_books_written": False,
        "orders_generated": False,
        "portfolio_or_ledger_mutated": False,
        "automatic_promotion_allowed": False,
        "production_or_live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(
        "# Run287 expected-return challenger\n\n"
        f"Status: `{BLOCKED_STATUS}`\n\n"
        "Historical fit and backtest were not executed.\n\n"
        "## Blockers\n\n"
        + "\n".join(f"- `{item}`" for item in blockers)
        + "\n",
        encoding="utf-8",
    )
    write_json(
        output_dir / "source_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": git_head(),
            "contract_sha256": canonical_sha256(contract),
            "inputs": inputs,
            "status": BLOCKED_STATUS,
            "historical_fit_executed": False,
        },
    )
    return summary


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = repo_path(args.contract)
    census_path = repo_path(args.u0_census)
    feature_store_path = repo_path(args.feature_store)
    contract = validate_contract(read_json(contract_path))
    inputs = {
        "contract": fingerprint(contract_path),
        "u0_census": fingerprint(census_path),
        "feature_store": fingerprint(feature_store_path),
    }
    blockers: list[str] = []
    if not census_path.is_file():
        blockers.append("u0_census_missing")
    else:
        try:
            blockers.extend(u0_gate(read_json(census_path), contract))
        except Exception as exc:
            blockers.append(f"u0_census_unreadable:{type(exc).__name__}")
    frame = pd.DataFrame()
    if not feature_store_path.is_file():
        blockers.append("feature_store_missing")
    else:
        try:
            frame = pd.read_parquet(feature_store_path)
            blockers.extend(input_readiness(frame, contract))
        except Exception as exc:
            blockers.append(f"feature_store_unreadable:{type(exc).__name__}")
    blockers = sorted(set(blockers))
    if blockers:
        return blocked_artifacts(
            output_dir,
            blockers=blockers,
            contract=contract,
            inputs=inputs,
        )

    try:
        prepared = prepare_frame(frame, contract)
    except Exception as exc:
        detail = re.sub(r"[^A-Za-z0-9_.:,=-]+", "_", str(exc)).strip("_")
        return blocked_artifacts(
            output_dir,
            blockers=[
                f"feature_store_semantic_validation_failed:{type(exc).__name__}:"
                f"{detail[:240]}"
            ],
            contract=contract,
            inputs=inputs,
        )
    predictions, audit, latest_models = walk_forward_predictions(prepared, contract)
    if predictions.empty:
        return blocked_artifacts(
            output_dir,
            blockers=["no_pit_purged_walk_forward_predictions"],
            contract=contract,
            inputs=inputs,
        )
    latest_input_date = pd.Timestamp(prepared["feature_date"].max()).normalize()
    latest_scored_date = pd.Timestamp(predictions["feature_date"].max()).normalize()
    if latest_scored_date != latest_input_date:
        return blocked_artifacts(
            output_dir,
            blockers=[
                "latest_input_decision_not_scored:"
                f"input={latest_input_date.date()}:scored={latest_scored_date.date()}"
            ],
            contract=contract,
            inputs=inputs,
        )
    metrics = evaluate_predictions(predictions, contract)
    proposal = public_latest_proposal(predictions)
    predictions.to_csv(output_dir / "expected_return_predictions.csv", index=False)
    audit.to_csv(output_dir / "training_audit.csv", index=False)
    proposal.to_csv(output_dir / "latest_expected_return_proposal.csv", index=False)
    write_json(output_dir / "expected_return_metrics.json", metrics)
    write_json(output_dir / "model_coefficients.json", latest_models)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "family_id": contract["family_id"],
        "latest_decision_date": proposal["feature_date"].max() if not proposal.empty else None,
        "prediction_rows": len(predictions),
        "prediction_dates": int(predictions["feature_date"].nunique()),
        "latest_candidate_count": len(proposal),
        "historical_model_fit_executed": True,
        "historical_backtest_executed": False,
        "broker_ledger_metrics_available": False,
        "fullrun_executed": False,
        "target_books_written": False,
        "orders_generated": False,
        "portfolio_or_ledger_mutated": False,
        "automatic_promotion_allowed": False,
        "production_or_live_trading_enabled": False,
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(
        "# Run287 expected-return challenger\n\n"
        f"Status: `{READY_STATUS}`\n\n"
        f"Predictions: {len(predictions):,} rows across "
        f"{int(predictions['feature_date'].nunique())} decisions.\n\n"
        "These are cross-sectional research diagnostics, not after-cost portfolio performance. "
        "No target book, order, cash change, ledger mutation, fullrun, or promotion occurred.\n",
        encoding="utf-8",
    )
    output_fingerprints = {
        name: fingerprint(output_dir / name)
        for name in contract["outputs"]
        if name != "source_manifest.json" and (output_dir / name).is_file()
    }
    write_json(
        output_dir / "source_manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": git_head(),
            "contract_sha256": canonical_sha256(contract),
            "inputs": inputs,
            "outputs": output_fingerprints,
            "status": READY_STATUS,
            "historical_fit_executed": True,
            "historical_backtest_executed": False,
        },
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        default="docs/run287_expected_return_challenger_contract.json",
    )
    parser.add_argument("--u0-census", required=True)
    parser.add_argument("--feature-store", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps(json_clean(summary), sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
