#!/usr/bin/env python3
"""Refresh Run287 current prices and scored_latest without running fullrun.

The lane is deliberately bounded to one completed market session.  It downloads
only a short provider overlap for names with an existing cache, keeps the source
cache immutable, recomputes the registered daily technical table, applies the
frozen 238-feature scaler and model heads, and writes a research-only ranked
snapshot.  It never selects, sizes, backtests, writes target books, or trades.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_config import EngineConfig  # noqa: E402
from r1000_pipeline import (  # noqa: E402
    apply_scaler,
    compute_adaptive_ensemble_state,
    compute_daily_tech_table,
    logreg_predict_proba_from_meta,
    ridge_predict_from_meta,
)
from tools.build_replay_price_cache import (  # noqa: E402
    normalize_download_frame,
    yfinance_symbol,
)
from tools.build_run287_feature_frame_pilot import (  # noqa: E402
    recompute_long_momentum_columns,
    transform_feature_context,
)
from tools.run_run287_current_model_score_dryrun import HEADS  # noqa: E402
from tools.run_run287_current_score_stack_audit import (  # noqa: E402
    PREDICTION_COLUMNS,
    execute_stack,
)
from tools.run_data_freshness_contract import (  # noqa: E402
    core_candidate_coverage_for_path,
    core_candidate_ticker_set_sha256,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools import stage_run287_price_batch as checkpoint  # noqa: E402
from tools.security_lifecycle import (  # noqa: E402
    filter_terminal_tickers,
    resolve_security_lifecycle,
)


SCHEMA_VERSION = "run287-scored-latest-refresh-v4"
REQUIRED_PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Adj Close", "Volume")
PREFLIGHT_INPUT_LABELS = (
    "universe",
    "base_selection_context",
    "base_score_stack",
    "model_classification",
    "model_regression",
    "model_bundle",
    "model_meta",
    "scored_oos",
    "security_lifecycle_events",
)
DEFAULT_CANONICAL = (
    "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"
)
DownloadFn = Callable[[list[str], str, str], tuple[dict[str, pd.DataFrame], dict[str, Any]]]
PROVIDER_SYMBOL_OVERRIDES: dict[str, str] = {}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    return "" if ticker in {"", "NAN", "NONE", "CASH", "__CASH__"} else ticker


def parse_provider_symbol_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in values:
        if "=" not in str(raw):
            raise ValueError(f"invalid provider symbol override: {raw}")
        logical, provider = str(raw).split("=", 1)
        logical = normalize_ticker(logical)
        provider = normalize_ticker(provider)
        if not logical or not provider:
            raise ValueError(f"invalid provider symbol override: {raw}")
        overrides[logical] = provider
    return overrides


def parse_expected_input_sha256(values: list[str]) -> dict[str, str]:
    """Parse the exact upstream-preflight hash contract for scorer inputs."""

    expected: dict[str, str] = {}
    for raw in values:
        if "=" not in str(raw):
            raise ValueError(f"invalid expected input sha256: {raw}")
        label, digest = str(raw).split("=", 1)
        label = label.strip()
        digest = digest.strip().lower()
        if (
            label not in PREFLIGHT_INPUT_LABELS
            or label in expected
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"invalid expected input sha256: {raw}")
        expected[label] = digest
    missing = sorted(set(PREFLIGHT_INPUT_LABELS).difference(expected))
    extra = sorted(set(expected).difference(PREFLIGHT_INPUT_LABELS))
    if missing or extra:
        raise ValueError(
            "expected_input_sha256_contract_failed:"
            f"missing={','.join(missing)}:extra={','.join(extra)}"
        )
    return expected


def validate_preflight_input_hashes(
    input_paths: Mapping[str, Path],
    expected_sha256: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    """Hash every fixed scorer input before any of those inputs is parsed."""

    if set(input_paths) != set(PREFLIGHT_INPUT_LABELS):
        raise ValueError("preflight_input_path_contract_failed")
    audits: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for label in PREFLIGHT_INPUT_LABELS:
        path = input_paths[label]
        audit = checkpoint.fingerprint(path)
        expected = str(expected_sha256.get(label) or "").lower()
        audit["expected_sha256"] = expected
        audit["hash_matches"] = bool(
            audit.get("exists") is True
            and len(expected) == 64
            and audit.get("sha256") == expected
        )
        audits[label] = audit
        if audit["hash_matches"] is not True:
            failures.append(label)
    if failures:
        raise ValueError(
            "preflight_input_hash_contract_failed:" + ",".join(sorted(failures))
        )
    return audits


def changed_preflight_inputs(
    initial_audit: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Rehash fixed inputs immediately before READY publication."""

    failures: list[str] = []
    for label in PREFLIGHT_INPUT_LABELS:
        prior = initial_audit.get(label) or {}
        current = checkpoint.fingerprint(Path(str(prior.get("path") or "")))
        if any(
            current.get(field) != prior.get(field)
            for field in ("exists", "bytes", "sha256")
        ):
            failures.append(f"input_changed_before_scorer_ready:{label}")
    return failures


def validate_ticker_identity(
    *,
    label: str,
    tickers: list[str],
    expected_count: int,
    expected_ticker_set_sha256: str,
) -> dict[str, Any]:
    """Validate count and membership against the upstream-preflight identity."""

    expected_sha = str(expected_ticker_set_sha256 or "").strip().lower()
    actual_sha = core_candidate_ticker_set_sha256(tickers)
    valid_expected_sha = bool(
        len(expected_sha) == 64
        and all(character in "0123456789abcdef" for character in expected_sha)
    )
    unique_count = len(
        {
            normalize_ticker(value)
            for value in tickers
            if normalize_ticker(value)
        }
    )
    matches = bool(
        valid_expected_sha
        and int(expected_count) == len(tickers)
        and unique_count == len(tickers)
        and actual_sha == expected_sha
    )
    audit = {
        "label": label,
        "expected_count": int(expected_count),
        "actual_count": len(tickers),
        "unique_count": unique_count,
        "expected_ticker_set_sha256": expected_sha,
        "actual_ticker_set_sha256": actual_sha,
        "matches": matches,
    }
    if not matches:
        raise ValueError(f"{label}_ticker_identity_contract_failed")
    return audit


def build_price_cache_input_audit(
    tickers: list[str],
    price_cache: Path,
) -> dict[str, Any]:
    """Fingerprint the exact historical cache files the scorer may consume."""

    inputs = {
        ticker: checkpoint.fingerprint(price_cache / px_cache_name(ticker))
        for ticker in tickers
    }
    semantic = [
        {
            "ticker": ticker,
            "exists": record.get("exists") is True,
            "bytes": int(record.get("bytes") or 0),
            "sha256": str(record.get("sha256") or ""),
        }
        for ticker, record in sorted(inputs.items())
    ]
    contract_sha256 = hashlib.sha256(
        json.dumps(
            semantic, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "run287-price-cache-input-audit-v1",
        "ticker_count": len(tickers),
        "ticker_set_sha256": core_candidate_ticker_set_sha256(tickers),
        "contract_sha256": contract_sha256,
        "inputs": inputs,
    }


def changed_price_cache_inputs(
    initial_audit: Mapping[str, Any],
    *,
    failure_prefix: str = "price_cache_changed_before_scorer_ready",
) -> list[str]:
    failures: list[str] = []
    for ticker, prior in (initial_audit.get("inputs") or {}).items():
        current = checkpoint.fingerprint(Path(str((prior or {}).get("path") or "")))
        if any(
            current.get(field) != (prior or {}).get(field)
            for field in ("exists", "bytes", "sha256")
        ):
            failures.append(f"{failure_prefix}:{ticker}")
    return failures


def drop_stale_prediction_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Prevent pandas merge suffixes from hiding newly computed predictions."""

    return frame.drop(columns=PREDICTION_COLUMNS, errors="ignore")


def normalize_price(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    out.index = pd.to_datetime(out.index, errors="coerce", utc=True).tz_localize(None)
    out = out.loc[out.index.notna()].sort_index()
    return out.loc[~out.index.duplicated(keep="last")]


def advance_feature_available_from(
    frame: pd.DataFrame,
    *,
    refreshed_feature_available_at: pd.Timestamp,
) -> pd.DataFrame:
    """Advance refreshed rows to the public availability of the exact close."""

    out = frame.copy()
    available_at = pd.Timestamp(refreshed_feature_available_at)
    if available_at.tzinfo is None:
        available_at = available_at.tz_localize("UTC")
    else:
        available_at = available_at.tz_convert("UTC")
    if "feature_available_from" in out:
        inherited = pd.to_datetime(
            out["feature_available_from"], errors="coerce", utc=True
        )
        effective = inherited.where(inherited > available_at, available_at)
    else:
        effective = pd.Series(available_at, index=out.index, dtype="datetime64[ns, UTC]")
    out["feature_available_from"] = effective.map(
        lambda value: pd.Timestamp(value).isoformat()
    )
    return out


def nyse_session_close_utc(session: pd.Timestamp) -> pd.Timestamp:
    """Return the actual scheduled NYSE close, including half-day sessions."""

    session_date = pd.Timestamp(session).date()
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=session_date,
        end_date=session_date,
    )
    if len(schedule) != 1:
        raise ValueError(f"session_date_is_not_one_nyse_session:{session_date}")
    close = pd.Timestamp(schedule.iloc[0]["market_close"])
    if close.tzinfo is None:
        close = close.tz_localize("UTC")
    else:
        close = close.tz_convert("UTC")
    return close


def max_price_date_from_metadata(path: Path) -> pd.Timestamp | None:
    if not path.is_file():
        return None
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        date_name = "Date" if "Date" in parquet.schema.names else parquet.schema.names[-1]
        column_index = parquet.schema.names.index(date_name)
        maxima: list[pd.Timestamp] = []
        for group in range(parquet.metadata.num_row_groups):
            stats = parquet.metadata.row_group(group).column(column_index).statistics
            if stats is not None and stats.has_min_max:
                maxima.append(pd.Timestamp(stats.max).tz_localize(None).normalize())
        return max(maxima) if maxima else None
    except Exception:
        return None


def download_yfinance(
    tickers: list[str], start_date: str, end_date_exclusive: str
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    import yfinance as yf

    symbols = {
        yfinance_symbol(PROVIDER_SYMBOL_OVERRIDES.get(ticker, ticker)): ticker
        for ticker in tickers
    }
    started = time.perf_counter()
    try:
        raw = yf.download(
            list(symbols),
            start=start_date,
            end=end_date_exclusive,
            actions=False,
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
            timeout=30,
            multi_level_index=True,
        )
        error = ""
    except Exception as exc:
        raw = pd.DataFrame()
        error = f"{type(exc).__name__}:{exc}"
    frames = {
        ticker: normalize_download_frame(raw, ticker, symbol)
        for symbol, ticker in symbols.items()
    }
    return frames, {
        "provider": "yfinance",
        "version": str(getattr(yf, "__version__", "")),
        "ticker_count": len(tickers),
        "start_date": start_date,
        "end_date_exclusive": end_date_exclusive,
        "elapsed_seconds": time.perf_counter() - started,
        "error": error,
    }


def merge_current_vintage(
    source: pd.DataFrame,
    provider: pd.DataFrame,
    *,
    session_date: pd.Timestamp,
    provider_symbol_link: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Overlay current provider rows and adjust only the older source prefix."""

    provider_norm = normalize_price(provider)
    provider_norm = provider_norm.loc[provider_norm.index <= session_date]
    missing_columns = [c for c in REQUIRED_PRICE_COLUMNS if c not in provider_norm]
    if provider_norm.empty or missing_columns:
        raise ValueError(f"provider_price_columns_missing:{','.join(missing_columns)}")
    if session_date not in provider_norm.index:
        raise ValueError("provider_exact_session_close_missing")

    source_norm = normalize_price(source) if source is not None and not source.empty else pd.DataFrame()
    if provider_symbol_link:
        last_trade = pd.to_datetime(
            provider_symbol_link.get("last_trading_date"), errors="coerce"
        )
        effective = pd.to_datetime(
            provider_symbol_link.get("effective_date"), errors="coerce"
        )
        if pd.isna(last_trade) or pd.isna(effective) or last_trade >= effective:
            raise ValueError("provider_symbol_link_cutover_invalid")
        if source_norm.empty or pd.Timestamp(last_trade).normalize() not in source_norm.index:
            raise ValueError("predecessor_last_trading_close_missing")
        successor = provider_norm.loc[
            provider_norm.index >= pd.Timestamp(effective).normalize()
        ].copy()
        if successor.empty or session_date not in successor.index:
            raise ValueError("successor_exact_session_close_missing")
        if successor.index.min() > pd.Timestamp(effective).normalize() + pd.Timedelta(days=7):
            raise ValueError("successor_history_gap_after_cutover")
        predecessor = source_norm.loc[
            source_norm.index <= pd.Timestamp(last_trade).normalize()
        ].copy()
        merged = pd.concat([predecessor, successor], axis=0).sort_index()
        merged = merged.loc[~merged.index.duplicated(keep="last")]
        return merged, {
            "source_present": True,
            "source_latest_date": source_norm.index.max().date().isoformat(),
            "provider_start_date": successor.index.min().date().isoformat(),
            "provider_overlap_row_count": 0,
            "prefix_adjustment_factor": 1.0,
            "merged_row_count": len(merged),
            "lifecycle_cutover_applied": True,
            "predecessor_last_trading_date": pd.Timestamp(last_trade).date().isoformat(),
            "successor_effective_date": pd.Timestamp(effective).date().isoformat(),
        }
    if source_norm.empty:
        if len(provider_norm) < 756:
            raise ValueError(f"provider_history_under_756_sessions:{len(provider_norm)}")
        return provider_norm, {
            "source_present": False,
            "source_latest_date": "",
            "provider_start_date": provider_norm.index.min().date().isoformat(),
            "provider_overlap_row_count": 0,
            "prefix_adjustment_factor": 1.0,
            "merged_row_count": len(provider_norm),
        }

    common = source_norm.index.intersection(provider_norm.index)
    if len(common) < 5:
        raise ValueError(f"provider_overlap_under_5:{len(common)}")
    source_adj = pd.to_numeric(source_norm.loc[common, "Adj Close"], errors="coerce")
    provider_adj = pd.to_numeric(provider_norm.loc[common, "Adj Close"], errors="coerce")
    ratios = (provider_adj / source_adj.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(ratios) < 5:
        raise ValueError(f"provider_adjustment_overlap_under_5:{len(ratios)}")
    first_ratio = float(ratios.iloc[0])
    break_positions = np.flatnonzero((ratios - first_ratio).abs().gt(1e-5).to_numpy())
    initial_end = int(break_positions[0]) if len(break_positions) else len(ratios)
    initial = ratios.iloc[:initial_end]
    if len(initial) < 3:
        raise ValueError(f"provider_initial_adjustment_regime_under_3:{len(initial)}")
    factor = float(initial.median())
    dispersion = float((initial - factor).abs().max())
    if not math.isfinite(factor) or factor <= 0 or dispersion > 1e-5:
        raise ValueError(f"provider_prefix_adjustment_unstable:{factor}:{dispersion}")

    provider_start = provider_norm.index.min()
    prefix = source_norm.loc[source_norm.index < provider_start].copy()
    prefix["Adj Close"] = pd.to_numeric(prefix["Adj Close"], errors="coerce") * factor
    merged = pd.concat([prefix, provider_norm], axis=0).sort_index()
    merged = merged.loc[~merged.index.duplicated(keep="last")]
    return merged, {
        "source_present": True,
        "source_latest_date": source_norm.index.max().date().isoformat(),
        "provider_start_date": provider_start.date().isoformat(),
        "provider_overlap_row_count": len(common),
        "prefix_adjustment_factor": factor,
        "prefix_adjustment_dispersion": dispersion,
        "merged_row_count": len(merged),
    }


def lifecycle_download_start(
    overlap_start: str,
    tickers: list[str],
    provider_symbol_links: Mapping[str, Mapping[str, Any]],
) -> str:
    """Start linked-symbol downloads at the earliest verified cutover."""
    starts = [pd.Timestamp(overlap_start).normalize()]
    for ticker in tickers:
        link = provider_symbol_links.get(ticker) or {}
        effective = pd.to_datetime(link.get("effective_date"), errors="coerce")
        if not pd.isna(effective):
            starts.append(pd.Timestamp(effective).normalize())
    return min(starts).date().isoformat()


def run_download_batches(
    tickers: list[str],
    *,
    start_date: str,
    end_date_exclusive: str,
    batch_size: int,
    download_fn: DownloadFn,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    frames: dict[str, pd.DataFrame] = {}
    audits: list[dict[str, Any]] = []
    for start in range(0, len(tickers), max(int(batch_size), 1)):
        batch = tickers[start : start + max(int(batch_size), 1)]
        downloaded, audit = download_fn(batch, start_date, end_date_exclusive)
        audit = {**audit, "batch_index": start // max(int(batch_size), 1) + 1}
        audits.append(audit)
        frames.update(downloaded)
    return frames, audits


def score_current_context(
    context: pd.DataFrame,
    *,
    model_meta: Mapping[str, Any],
    cat_reg_path: Path,
    cat_cls_path: Path,
    model_bundle: Mapping[str, Any],
    scored_oos: pd.DataFrame,
    session_date: pd.Timestamp,
    quarantine_tickers: set[str],
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    from catboost import CatBoostClassifier, CatBoostRegressor

    model_features = [str(value) for value in model_meta.get("model_features") or []]
    if len(model_features) != 238:
        raise ValueError(f"frozen_model_feature_count:{len(model_features)}!=238")
    raw_model = context.reindex(columns=model_features).apply(pd.to_numeric, errors="coerce")
    matrix = apply_scaler(raw_model, model_meta.get("scaler") or {}, model_features)
    if matrix.shape != (len(context), len(model_features)) or not np.isfinite(matrix).all():
        raise ValueError("scaled_model_matrix_contract_failed")
    scaled = pd.DataFrame(matrix, columns=model_features)
    scaled.insert(0, "ticker", context["ticker"].astype(str).str.upper().str.strip())

    predictions = pd.DataFrame({"ticker": scaled["ticker"]})
    for output_name, (meta_key, kind) in HEADS.items():
        predictions[output_name] = (
            ridge_predict_from_meta(matrix, dict(model_meta), key=meta_key)
            if kind == "ridge"
            else logreg_predict_proba_from_meta(matrix, dict(model_meta), key=meta_key)
        )

    regressor = CatBoostRegressor()
    classifier = CatBoostClassifier()
    regressor.load_model(str(cat_reg_path))
    classifier.load_model(str(cat_cls_path))
    predictions["pred_cat_ret"] = np.asarray(regressor.predict(matrix), dtype=float)
    predictions["pred_cat_p"] = np.asarray(classifier.predict_proba(matrix)[:, 1], dtype=float)
    predictions["pred_rank"] = 0.0
    if not np.isfinite(predictions.drop(columns="ticker").to_numpy(dtype=float)).all():
        raise ValueError("nonfinite_model_prediction")

    cfg = EngineConfig()
    adaptive = compute_adaptive_ensemble_state(
        scored_oos, cfg, as_of_date=session_date
    )
    fallback_used = False
    if not adaptive.get("active"):
        diagnostics = model_bundle.get("adaptive_ensemble_diagnostics") or {}
        adaptive = {
            "weights": model_bundle.get("adaptive_ensemble_weights") or {},
            "quality": diagnostics.get("quality") or {},
            "history_months": int(diagnostics.get("history_months") or 0),
            "active": bool(diagnostics.get("active")),
        }
        fallback_used = True
    if not adaptive.get("active"):
        raise ValueError("adaptive_ensemble_inactive")

    # The historical audit context already contains stale pred_* columns.  Drop
    # them before merge so pandas suffixing cannot silently turn new predictions
    # into engine-default zeros.
    stack_input = drop_stale_prediction_columns(context)
    scored, logs = execute_stack(
        stack_input,
        predictions,
        cfg,
        adaptive,
        model_bundle.get("regime_ensemble_weights") or {},
    )
    scored["registered_ranking_eligible"] = scored["ranking_eligible"].map(
        checkpoint.boolish
    )
    scored["corporate_action_quarantine"] = scored["ticker"].isin(quarantine_tickers)
    scored["research_eligible_after_quarantine"] = (
        scored["registered_ranking_eligible"] & ~scored["corporate_action_quarantine"]
    )
    scored["research_score_rank"] = np.nan
    eligible = scored["research_eligible_after_quarantine"]
    scored.loc[eligible, "research_score_rank"] = (
        pd.to_numeric(scored.loc[eligible, "score"], errors="coerce")
        .rank(method="first", ascending=False)
        .astype(float)
    )
    scored["score_rank"] = scored["research_score_rank"]
    scored["decision_ranking_allowed"] = False
    scored["production_activation_allowed"] = False
    scored["pit_universe_label_clean"] = False
    scored["scored_latest_schema_version"] = SCHEMA_VERSION
    scored["score_available_from"] = utc_now()
    scored = scored.sort_values(
        ["research_eligible_after_quarantine", "score"],
        ascending=[False, False],
        kind="stable",
    ).reset_index(drop=True)
    diagnostics = {
        "model_feature_count": len(model_features),
        "scaled_finite_ratio": float(np.isfinite(matrix).mean()),
        "adaptive_state": adaptive,
        "adaptive_bundle_fallback_used": fallback_used,
        "engine_log_lines": logs,
        "registered_eligible_count": int(scored["registered_ranking_eligible"].sum()),
        "research_eligible_count": int(scored["research_eligible_after_quarantine"].sum()),
        "prediction_nonzero_counts": {
            column: int(pd.to_numeric(predictions[column], errors="coerce").ne(0).sum())
            for column in predictions.columns
            if column != "ticker"
        },
    }
    return scored, diagnostics, scaled


def read_git_csv(path: str) -> pd.DataFrame:
    try:
        raw = subprocess.check_output(["git", "show", f"HEAD:{path}"], cwd=ROOT)
        return pd.read_csv(io.BytesIO(raw), low_memory=False)
    except Exception:
        return pd.DataFrame()


def build(
    args: argparse.Namespace,
    *,
    download_fn: DownloadFn | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    session = pd.Timestamp(args.session_date).normalize()
    if pd.isna(session):
        raise ValueError("--session-date must be YYYY-MM-DD")
    decision_time = pd.to_datetime(args.decision_time_utc, errors="coerce", utc=True)
    if pd.isna(decision_time):
        raise ValueError(
            "--decision-time-utc is required and must include a valid timestamp"
        )
    exact_close_available_at = nyse_session_close_utc(session)
    if pd.Timestamp(decision_time) < exact_close_available_at:
        raise ValueError("decision_time_precedes_exact_nyse_close")
    if not args.allow_network_refresh and download_fn is None:
        raise ValueError("--allow-network-refresh is required")
    PROVIDER_SYMBOL_OVERRIDES.clear()
    manual_provider_overrides = parse_provider_symbol_overrides(
        args.provider_symbol_override
    )

    universe_path = repo_path(args.universe)
    context_path = repo_path(args.base_selection_context)
    prior_stack_path = repo_path(args.base_score_stack)
    price_cache = repo_path(args.price_cache)
    model_root = repo_path(args.model_root)
    scored_oos_path = repo_path(args.scored_oos)
    model_meta_path = repo_path(args.model_meta)
    cat_reg_path = repo_path(args.model_regression)
    cat_cls_path = repo_path(args.model_classification)
    model_bundle_path = repo_path(args.model_bundle)
    lifecycle_path = repo_path(args.security_lifecycle_events)
    input_paths = {
        "universe": universe_path,
        "base_selection_context": context_path,
        "base_score_stack": prior_stack_path,
        "model_classification": cat_cls_path,
        "model_regression": cat_reg_path,
        "model_bundle": model_bundle_path,
        "model_meta": model_meta_path,
        "scored_oos": scored_oos_path,
        "security_lifecycle_events": lifecycle_path,
    }
    expected_input_sha256 = parse_expected_input_sha256(
        args.expected_input_sha256
    )
    input_audit = validate_preflight_input_hashes(
        input_paths, expected_input_sha256
    )
    if not price_cache.is_dir() or not model_root.is_dir():
        raise FileNotFoundError("required_input_directory_missing")

    universe = pd.read_csv(universe_path, dtype={"ticker": str}, low_memory=False)
    base = pd.read_parquet(context_path)
    base["ticker"] = base["ticker"].map(normalize_ticker)
    prior_stack = pd.read_csv(prior_stack_path, low_memory=False)
    prior_stack["ticker"] = prior_stack["ticker"].map(normalize_ticker)
    universe_ticker_list = [
        normalize_ticker(value) for value in universe["ticker"].tolist()
    ]
    universe_ticker_identity = validate_ticker_identity(
        label="universe",
        tickers=universe_ticker_list,
        expected_count=int(args.expected_universe_count),
        expected_ticker_set_sha256=args.expected_universe_ticker_set_sha256,
    )
    base_ticker_list = base["ticker"].tolist()
    if base.empty or base["ticker"].duplicated().any() or not all(base_ticker_list):
        raise ValueError("base_context_dynamic_unique_ticker_contract_failed")
    pre_lifecycle_context_count = len(base_ticker_list)
    expected_pre_lifecycle_context_count = int(args.expected_pre_lifecycle_context_count)
    if (
        expected_pre_lifecycle_context_count <= 0
        or pre_lifecycle_context_count != expected_pre_lifecycle_context_count
    ):
        raise ValueError(
            "base_context_external_count_contract_failed:"
            f"{pre_lifecycle_context_count}!={expected_pre_lifecycle_context_count}"
        )
    pre_lifecycle_ticker_identity = validate_ticker_identity(
        label="pre_lifecycle_context",
        tickers=base_ticker_list,
        expected_count=expected_pre_lifecycle_context_count,
        expected_ticker_set_sha256=args.expected_pre_lifecycle_ticker_set_sha256,
    )
    lifecycle = resolve_security_lifecycle(
        lifecycle_path,
        session_date=session,
        decision_time_utc=decision_time,
        active_tickers=set(base_ticker_list),
    )
    for logical, provider in lifecycle.provider_symbol_overrides.items():
        manual = manual_provider_overrides.get(logical)
        if manual is not None and manual != provider:
            raise ValueError(f"provider_symbol_override_conflicts_with_lifecycle:{logical}")
    PROVIDER_SYMBOL_OVERRIDES.update(lifecycle.provider_symbol_overrides)
    PROVIDER_SYMBOL_OVERRIDES.update(manual_provider_overrides)
    terminal_exclusions = lifecycle.terminal_events.copy()
    terminal_tickers = set(lifecycle.terminal_tickers)
    base = filter_terminal_tickers(base, lifecycle)
    tickers = base["ticker"].tolist()
    if not tickers:
        raise ValueError("security_lifecycle_excluded_entire_context")
    lifecycle_excluded_tickers = sorted(set(base_ticker_list) - set(tickers))
    post_lifecycle_context_count = len(tickers)
    if (
        pre_lifecycle_context_count
        != len(lifecycle_excluded_tickers) + post_lifecycle_context_count
    ):
        raise ValueError("security_lifecycle_dynamic_count_contract_failed")
    post_lifecycle_ticker_identity = validate_ticker_identity(
        label="post_lifecycle_context",
        tickers=tickers,
        expected_count=int(args.expected_post_lifecycle_context_count),
        expected_ticker_set_sha256=args.expected_post_lifecycle_ticker_set_sha256,
    )
    price_cache_input_audit = build_price_cache_input_audit(
        tickers, price_cache
    )
    expected_price_cache_contract_sha256 = str(
        args.expected_price_cache_contract_sha256 or ""
    ).strip().lower()
    if (
        len(expected_price_cache_contract_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in expected_price_cache_contract_sha256
        )
        or price_cache_input_audit.get("contract_sha256")
        != expected_price_cache_contract_sha256
    ):
        raise ValueError("price_cache_preflight_contract_failed")
    universe_tickers = {normalize_ticker(value) for value in universe["ticker"]}
    excluded = sorted((universe_tickers - set(tickers)) - {""})

    source_dates: dict[str, str] = {}
    existing: list[str] = []
    missing_source: list[str] = []
    for ticker in tickers:
        path = price_cache / px_cache_name(ticker)
        latest = max_price_date_from_metadata(path)
        if latest is None:
            missing_source.append(ticker)
            source_dates[ticker] = ""
        else:
            existing.append(ticker)
            source_dates[ticker] = latest.date().isoformat()

    end_exclusive = (session + pd.Timedelta(days=1)).date().isoformat()
    downloader = download_fn or download_yfinance
    provider_frames: dict[str, pd.DataFrame] = {}
    batch_audits: list[dict[str, Any]] = []
    linked_existing = [
        ticker for ticker in existing if ticker in lifecycle.provider_symbol_links
    ]
    regular_existing = [ticker for ticker in existing if ticker not in linked_existing]
    if regular_existing:
        current_frames, audits = run_download_batches(
            regular_existing,
            start_date=args.overlap_start,
            end_date_exclusive=end_exclusive,
            batch_size=args.batch_size,
            download_fn=downloader,
        )
        provider_frames.update(current_frames)
        batch_audits.extend(audits)
    if linked_existing:
        linked_frames, audits = run_download_batches(
            linked_existing,
            start_date=lifecycle_download_start(
                args.overlap_start,
                linked_existing,
                lifecycle.provider_symbol_links,
            ),
            end_date_exclusive=end_exclusive,
            batch_size=args.batch_size,
            download_fn=downloader,
        )
        provider_frames.update(linked_frames)
        batch_audits.extend(audits)
    if missing_source:
        history_frames, audits = run_download_batches(
            missing_source,
            start_date=args.missing_history_start,
            end_date_exclusive=end_exclusive,
            batch_size=args.batch_size,
            download_fn=downloader,
        )
        provider_frames.update(history_frames)
        batch_audits.extend(audits)

    exact = {
        ticker
        for ticker, frame in provider_frames.items()
        if not frame.empty and session in normalize_price(frame).index
    }
    failed = sorted(set(tickers) - exact)
    if failed and download_fn is None:
        retry_frames, retry_audits = run_download_batches(
            failed,
            start_date=args.missing_history_start,
            end_date_exclusive=end_exclusive,
            batch_size=max(1, min(10, args.batch_size)),
            download_fn=downloader,
        )
        provider_frames.update(retry_frames)
        batch_audits.extend({**row, "retry": True} for row in retry_audits)
        exact = {
            ticker
            for ticker, frame in provider_frames.items()
            if not frame.empty and session in normalize_price(frame).index
        }
        failed = sorted(set(tickers) - exact)
    if failed:
        checkpoint.write_json(
            output_dir / "manifest.json",
            {
                "schema_version": SCHEMA_VERSION,
                "status": "BLOCKED_MISSING_EXACT_SESSION_CLOSE",
                "session_date": session.date().isoformat(),
                "missing_tickers": failed,
                "exact_ticker_count": len(exact),
                "required_ticker_count": len(tickers),
                "fullrun_executed": False,
                "target_books_mutated": False,
                "production_activation_allowed": False,
            },
        )
        raise RuntimeError(f"exact_session_close_missing:{','.join(failed)}")

    provider_rows: list[pd.DataFrame] = []
    technical_rows: list[dict[str, Any]] = []
    ticker_audits: list[dict[str, Any]] = []
    failures: list[str] = []
    for ticker in tickers:
        provider = normalize_price(provider_frames[ticker])
        archive = provider.reset_index().rename(columns={provider.index.name or "index": "Date"})
        archive.insert(0, "ticker", ticker)
        provider_rows.append(archive)
        source_path = price_cache / px_cache_name(ticker)
        try:
            source = pd.read_parquet(source_path) if source_path.is_file() else pd.DataFrame()
            merged, audit = merge_current_vintage(
                source,
                provider,
                session_date=session,
                provider_symbol_link=lifecycle.provider_symbol_links.get(ticker),
            )
            technical = compute_daily_tech_table(merged)
            technical.index = pd.to_datetime(technical.index).normalize()
            if session not in technical.index:
                raise ValueError("technical_exact_session_row_missing")
            row: dict[str, Any] = {"ticker": ticker}
            for column, value in technical.loc[session].items():
                row[f"technical_{column}"] = value
                row[f"delta_{column}"] = np.nan
            technical_rows.append(row)
            ticker_audits.append(
                {
                    "ticker": ticker,
                    "status": "PASS",
                    "source_cache_date": source_dates[ticker],
                    "exact_session_close": True,
                    **audit,
                }
            )
        except Exception as exc:
            failures.append(f"{ticker}:{type(exc).__name__}:{exc}")
            ticker_audits.append(
                {
                    "ticker": ticker,
                    "status": "BLOCKED_TECHNICAL_REFRESH",
                    "source_cache_date": source_dates[ticker],
                    "exact_session_close": True,
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
    pd.concat(provider_rows, ignore_index=True).to_parquet(
        output_dir / "provider_price_overlap.parquet", index=False
    )
    lifecycle.applicable_events.to_csv(
        output_dir / "security_lifecycle_applicable_events.csv", index=False
    )
    pd.DataFrame(batch_audits).to_csv(output_dir / "provider_batch_audit.csv", index=False)
    pd.DataFrame(ticker_audits).to_csv(output_dir / "ticker_refresh_audit.csv", index=False)
    if failures:
        checkpoint.write_json(
            output_dir / "manifest.json",
            {
                "schema_version": SCHEMA_VERSION,
                "status": "BLOCKED_TECHNICAL_REFRESH",
                "session_date": session.date().isoformat(),
                "contract_failures": failures,
                "fullrun_executed": False,
                "target_books_mutated": False,
                "production_activation_allowed": False,
            },
        )
        raise RuntimeError(f"technical_refresh_failed:{len(failures)}")

    technical_latest = pd.DataFrame(technical_rows)
    technical_latest.to_csv(output_dir / "latest_technical_features.csv", index=False)
    technical_index = technical_latest.set_index("ticker")
    context = base.copy()
    old_px = pd.to_numeric(context.get("px"), errors="coerce")
    for column in technical_latest.columns:
        if not column.startswith("technical_"):
            continue
        base_column = column[len("technical_") :]
        context[base_column] = context["ticker"].map(technical_index[column])
    new_px = pd.to_numeric(context.get("px"), errors="coerce")
    ratio = (new_px / old_px.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    for column in ("mktcap", "market_cap_live"):
        if column in context:
            context[column] = pd.to_numeric(context[column], errors="coerce") * ratio
    if "current_price_live" in context:
        context["current_price_live"] = new_px
    context["feature_date"] = session
    context["rebalance_date"] = session
    context["valuation_price_cutoff_date"] = session.date().isoformat()
    context["technical_available_after_close"] = session.date().isoformat()
    context = recompute_long_momentum_columns(context)
    context = transform_feature_context(context, EngineConfig())
    context = advance_feature_available_from(
        context,
        refreshed_feature_available_at=exact_close_available_at,
    )

    model_meta = json.loads(model_meta_path.read_text(encoding="utf-8"))
    model_bundle = json.loads(model_bundle_path.read_text(encoding="utf-8"))
    scored_oos = pd.read_parquet(scored_oos_path)
    quarantine = set(
        prior_stack.loc[
            prior_stack.get("corporate_action_quarantine", False).map(checkpoint.boolish),
            "ticker",
        ]
    )
    scored, score_diag, scaled = score_current_context(
        context,
        model_meta=model_meta,
        cat_reg_path=cat_reg_path,
        cat_cls_path=cat_cls_path,
        model_bundle=model_bundle,
        scored_oos=scored_oos,
        session_date=session,
        quarantine_tickers=quarantine,
    )
    context.to_parquet(output_dir / "selection_context.parquet", index=False)
    scaled.to_parquet(output_dir / "scaled_model_input.parquet", index=False)
    scored_path = output_dir / "scored_latest.csv"
    scored.to_csv(scored_path, index=False)
    core_candidate_coverage, core_coverage_failures = (
        core_candidate_coverage_for_path(
            scored_path,
            minimum_ratio=0.98,
            expected_row_count=post_lifecycle_context_count,
            expected_valuation_date=session.date().isoformat(),
            decision_time_utc=pd.Timestamp(decision_time).isoformat(),
            expected_ticker_set_sha256=(
                post_lifecycle_ticker_identity[
                    "expected_ticker_set_sha256"
                ]
            ),
        )
    )

    output_records = {
        name: checkpoint.fingerprint(output_dir / name)
        for name in (
            "provider_price_overlap.parquet",
            "provider_batch_audit.csv",
            "ticker_refresh_audit.csv",
            "security_lifecycle_applicable_events.csv",
            "latest_technical_features.csv",
            "selection_context.parquet",
            "scaled_model_input.parquet",
            "scored_latest.csv",
        )
    }
    ticker_identity = {
        "universe": universe_ticker_identity,
        "pre_lifecycle_context": pre_lifecycle_ticker_identity,
        "post_lifecycle_context": post_lifecycle_ticker_identity,
    }

    def block_changed_inputs(contract_failures: list[str]) -> dict[str, Any]:
        blocked_payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "BLOCKED_PREFLIGHT_INPUT_CHANGED",
            "session_date": session.date().isoformat(),
            "decision_time_utc": pd.Timestamp(decision_time).isoformat(),
            "score_available_from": utc_now(),
            "contract_failures": sorted(set(contract_failures)),
            "ticker_identity": ticker_identity,
            "research_only": True,
            "current_decision_only": True,
            "fullrun_executed": False,
            "selector_executed": False,
            "target_book_generation_executed": False,
            "target_books_mutated": False,
            "backtest_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "source_cache_mutated": False,
            "source_inputs": input_audit,
            "price_cache_inputs": price_cache_input_audit,
            "outputs": output_records,
            "performance": {"elapsed_seconds": time.perf_counter() - started},
        }
        checkpoint.write_json(output_dir / "manifest.json", blocked_payload)
        return blocked_payload

    input_change_failures = [
        *changed_preflight_inputs(input_audit),
        *changed_price_cache_inputs(price_cache_input_audit),
    ]
    if input_change_failures:
        return block_changed_inputs(input_change_failures)

    if core_coverage_failures:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "BLOCKED_CORE_CANDIDATE_COVERAGE",
            "session_date": session.date().isoformat(),
            "decision_time_utc": pd.Timestamp(decision_time).isoformat(),
            "score_available_from": utc_now(),
            "contract_failures": sorted(set(core_coverage_failures)),
            "core_candidate_coverage": core_candidate_coverage,
            "coverage": {
                "universe_count": len(universe),
                "pre_lifecycle_context_count": pre_lifecycle_context_count,
                "lifecycle_excluded_count": len(lifecycle_excluded_tickers),
                "post_lifecycle_context_count": post_lifecycle_context_count,
                "current_context_count": len(context),
                "core_candidate_coverage_ratio": core_candidate_coverage[
                    "coverage_ratio"
                ],
            },
            "ticker_identity": ticker_identity,
            "research_only": True,
            "current_decision_only": True,
            "fullrun_executed": False,
            "selector_executed": False,
            "target_book_generation_executed": False,
            "target_books_mutated": False,
            "backtest_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "source_cache_mutated": False,
            "source_inputs": input_audit,
            "price_cache_inputs": price_cache_input_audit,
            "outputs": output_records,
            "performance": {"elapsed_seconds": time.perf_counter() - started},
        }
        checkpoint.write_json(output_dir / "manifest.json", payload)
        return payload

    canonical_rel = str(args.canonical_output).replace("\\", "/")
    prior_canonical = read_git_csv(canonical_rel) if canonical_rel else pd.DataFrame()
    comparison: dict[str, Any] = {
        "prior_row_count": len(prior_canonical),
        "current_row_count": len(scored),
        "common_ticker_count": 0,
        "score_spearman": None,
    }
    if not prior_canonical.empty and "ticker" in prior_canonical and "score" in prior_canonical:
        left = prior_canonical[["ticker", "score"]].copy()
        right = scored[["ticker", "score"]].copy()
        both = left.merge(right, on="ticker", suffixes=("_prior", "_current"))
        comparison["common_ticker_count"] = len(both)
        comparison["score_spearman"] = float(
            both[["score_prior", "score_current"]].corr(method="spearman").iloc[0, 1]
        )
    if canonical_rel:
        input_change_failures = [
            *changed_preflight_inputs(input_audit),
            *changed_price_cache_inputs(price_cache_input_audit),
        ]
        if input_change_failures:
            return block_changed_inputs(input_change_failures)
        canonical_path = repo_path(canonical_rel)
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        scored.to_csv(canonical_path, index=False)

    input_change_failures = [
        *changed_preflight_inputs(input_audit),
        *changed_price_cache_inputs(price_cache_input_audit),
    ]
    if input_change_failures:
        return block_changed_inputs(input_change_failures)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_RESEARCH_SCORED_LATEST",
        "session_date": session.date().isoformat(),
        "decision_time_utc": pd.Timestamp(decision_time).isoformat(),
        "score_available_from": utc_now(),
        "research_only": True,
        "current_decision_only": True,
        "pit_universe_label_clean": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "target_book_generation_executed": False,
        "target_books_mutated": False,
        "backtest_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "next_close_execution_required": True,
        "same_close_execution_allowed": False,
        "source_cache_mutated": False,
        "network_download_batch_count": len(batch_audits),
        "provider_symbol_overrides": dict(PROVIDER_SYMBOL_OVERRIDES),
        "core_candidate_coverage": core_candidate_coverage,
        "ticker_identity": ticker_identity,
        "coverage": {
            "universe_count": len(universe),
            "base_context_count": pre_lifecycle_context_count,
            "expected_pre_lifecycle_context_count": expected_pre_lifecycle_context_count,
            "pre_lifecycle_context_count": pre_lifecycle_context_count,
            "lifecycle_excluded_count": len(lifecycle_excluded_tickers),
            "post_lifecycle_context_count": post_lifecycle_context_count,
            "current_context_count": len(context),
            "core_candidate_coverage_ratio": core_candidate_coverage[
                "coverage_ratio"
            ],
            "security_lifecycle_terminal_event_count": len(terminal_exclusions),
            "security_lifecycle_terminal_exclusion_count": len(lifecycle_excluded_tickers),
            "security_lifecycle_terminal_tickers": sorted(terminal_tickers),
            "security_lifecycle_excluded_tickers": lifecycle_excluded_tickers,
            "exact_session_close_count": len(exact),
            "existing_source_cache_count": len(existing),
            "missing_source_cache_count": len(missing_source),
            "excluded_universe_tickers": excluded,
            "technical_feature_count": len(
                [c for c in technical_latest if c.startswith("technical_")]
            ),
        },
        "score_diagnostics": score_diag,
        "comparison_to_prior_canonical": comparison,
        "source_inputs": {
            name: dict(audit)
            for name, audit in input_audit.items()
        },
        "price_cache_inputs": price_cache_input_audit,
        "security_lifecycle": lifecycle.audit(),
        "outputs": output_records,
        "canonical_output": canonical_rel,
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "recommended_next_step": (
            "run schema/freshness/no-leakage validation, then compute a diagnostic "
            "selection diff only; do not mutate the 2026-07-13 forward ledger or target books"
        ),
    }
    checkpoint.write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--base-selection-context", required=True)
    parser.add_argument("--expected-pre-lifecycle-context-count", type=int, required=True)
    parser.add_argument("--expected-post-lifecycle-context-count", type=int, required=True)
    parser.add_argument("--expected-universe-count", type=int, required=True)
    parser.add_argument("--expected-universe-ticker-set-sha256", required=True)
    parser.add_argument("--expected-pre-lifecycle-ticker-set-sha256", required=True)
    parser.add_argument("--expected-post-lifecycle-ticker-set-sha256", required=True)
    parser.add_argument("--expected-price-cache-contract-sha256", required=True)
    parser.add_argument(
        "--expected-input-sha256",
        action="append",
        default=[],
        metavar="LABEL=SHA256",
        help="Repeat for every upstream-preflight scorer input.",
    )
    parser.add_argument("--base-score-stack", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--model-classification", required=True)
    parser.add_argument("--model-regression", required=True)
    parser.add_argument("--model-bundle", required=True)
    parser.add_argument("--model-meta", required=True)
    parser.add_argument("--scored-oos", required=True)
    parser.add_argument("--overlap-start", default="2026-01-02")
    parser.add_argument("--missing-history-start", default="2021-01-04")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument(
        "--provider-symbol-override",
        action="append",
        default=[],
        help="Repeat logical=provider for a verified symbol change.",
    )
    parser.add_argument(
        "--security-lifecycle-events",
        default="",
        help="Shared PIT lifecycle events for terminal settlement and symbol continuity.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--canonical-output", default=DEFAULT_CANONICAL)
    parser.add_argument("--allow-network-refresh", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "READY_RESEARCH_SCORED_LATEST" else 2


if __name__ == "__main__":
    raise SystemExit(main())
