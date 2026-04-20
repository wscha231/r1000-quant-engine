"""r1000 Quant Engine — pure utility helpers.

This module owns small, dependency-free utility functions extracted from
`r1000_top30_institutional.py` during Refactor Phase A Stage 2.

Stage 2a (this commit): the smallest/safest helpers — git commit SHA
resolver, phase-toggle env-var check, timestamp + log print helpers.
All stdlib-only; no numpy/pandas, no r1000_config, no r1000_top30.

Import discipline
-----------------
    r1000_config.py           (pure data, stdlib)
        ^
        |
    r1000_helpers.py          (pure helpers, stdlib + maybe numpy/pandas
                               in later sub-stages)
        ^                     ^
        |                     |
    r1000_top30_institutional.py
        ^
        |
    r1000_data_collector.py
    r1000_operator.py
    r1000_portfolio_state.py

r1000_helpers.py may import from r1000_config.py (e.g. EngineConfig for
`to_cfg`), but NEVER from the main engine or collectors. This keeps the
dependency graph acyclic.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from r1000_config import (
    CASH_PROXY_TICKER,
    ENGINE_REUSE_VERSION,
    EXCLUDE_NAME,
    EngineConfig,
    ROBUST_Z_CLIP,
    ROBUST_Z_WINSOR_P,
    SEC_COMPANYFACTS_MEMBER_RE,
    TICKER_RE,
    YF_OVERRIDES,
)


# ---------------------------------------------------------------------
# Git commit SHA provenance (Stage 2a)
# ---------------------------------------------------------------------

def _resolve_engine_commit_sha() -> str:
    """Return short git SHA of the engine repo for run provenance.

    Printed in every run banner so logs/notebooks self-identify which
    code version produced them. Falls back to '(unknown)' if git isn't
    available (e.g. engine installed as a wheel instead of a clone, or
    the git binary is missing from PATH).
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        sha = (result.stdout or "").strip()
        return sha if sha else "(unknown)"
    except Exception:
        return "(unknown)"


# Evaluated once at import time. The main engine imports this symbol for
# run-banner prints. If pre-computing at import is undesirable (e.g. for
# test isolation), callers can invoke `_resolve_engine_commit_sha()`
# directly instead.
ENGINE_COMMIT_SHA = _resolve_engine_commit_sha()


# ---------------------------------------------------------------------
# Phase toggle dual-gate: cfg flag + PHASE_<KEY>_ENABLED env var (Stage 2a)
# ---------------------------------------------------------------------
# Every phase (1 .. 9) has a pair:
#     cfg.phaseN_*_enabled: bool  (programmatic override)
#     PHASE_PHASEN_*_ENABLED env  (runtime override, wins vs cfg)
# This function reads the env; the cfg branch is handled at call site.
#
# Usage (main engine or notebook):
#     import os
#     os.environ["PHASE_PHASE1_ALPHA_ENABLED"] = "0"       # disable Phase 1
#     os.environ["PHASE_PHASE2_INDUSTRY_ENABLED"] = "0"    # disable Phase 2
#
# Any of: "0", "false", "no", "off", "disabled" (case-insensitive) turns
# a phase OFF.  Anything else (including unset) leaves it at the default.

def phase_is_enabled(phase_key: str, default: bool = True) -> bool:
    """Check env var PHASE_{KEY}_ENABLED.  Returns `default` when unset."""
    env_name = f"PHASE_{phase_key.upper()}_ENABLED"
    raw = os.environ.get(env_name, "")
    val = str(raw).strip().lower()
    if val == "":
        return bool(default)
    if val in ("0", "false", "no", "off", "disabled"):
        return False
    if val in ("1", "true", "yes", "on", "enabled"):
        return True
    return bool(default)


# ---------------------------------------------------------------------
# Timestamp + log helpers (Stage 2a)
# ---------------------------------------------------------------------

def now_ts() -> str:
    """Return current local time as YYYYMMDD_HHMMSS (used in archive paths)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def log(msg: str) -> None:
    """Stamp `msg` with [HH:MM:SS] and print to stdout.

    Intentionally simple — all engine progress logging uses this single
    function so a future switch to `logging.getLogger` is one-file.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ---------------------------------------------------------------------
# Config helpers (Stage 2b) — transform EngineConfig instances
# ---------------------------------------------------------------------
# All 3 functions operate on EngineConfig (from r1000_config) or dict
# form thereof. Require pandas for date arithmetic in
# configure_last_n_years_backtest.

def apply_fast_mode(cfg: "EngineConfig") -> "EngineConfig":
    """Apply runtime-reduction overrides when cfg.fast_mode is True.

    Phase 1/2 savings:
      - live fundamentals refresh limited to the highest-liquidity subset
      - slower-changing statement supplements refreshed less often
      - yfinance quarterly supplement capped to a smaller stale subset

    Phase 4 savings:
      - CatBoost iterations cut ~40%: reg 350→200, cls 350→200, rank 250→150
      - ranking_enabled disabled: ~30% faster per retrain cycle
      - retrain frequency halved: 3m→6m  (fewer training windows)

    Phase 5 savings:
      - regime-per-regime comparison disabled (-12 backtests)
      - AI four-sleeve comparison disabled (-13 backtests)
      - regime-map-method comparison disabled (-2 backtests)
      - standalone sleeve comparison disabled (-6 backtests)
      - sleeve-cap policy candidates reduced to 3 (-3 backtests vs default 6)
    Net: ~5 backtests instead of ~44.  Estimated runtime: ~1.5h vs ~8h.
    """
    if not cfg.fast_mode:
        return cfg
    # Phase 1/2 — collector I/O and supplement refresh
    cfg.live_refresh_days = max(int(cfg.live_refresh_days), 2)
    cfg.max_live_refresh_tickers = min(int(cfg.max_live_refresh_tickers), 400)
    cfg.latest_statement_repair_refresh_days = max(int(cfg.latest_statement_repair_refresh_days), 14)
    cfg.yf_quarterly_refresh_days = max(int(cfg.yf_quarterly_refresh_days), 14)
    cfg.yf_quarterly_max_tickers_per_run = min(int(cfg.yf_quarterly_max_tickers_per_run), 120)
    # Phase 4 — model complexity
    cfg.cat_reg_iterations = 200
    cfg.cat_cls_iterations = 200
    cfg.cat_rank_iterations = 150
    cfg.ranking_enabled = False
    cfg.walkforward_retrain_frequency_months = 6
    cfg.cat_validation_months = 4
    # Phase 5 — comparison suites
    cfg.run_sleeve_regime_comparison = False
    cfg.run_ai_four_sleeve_comparison = False
    cfg.run_regime_map_method_comparison = False
    cfg.run_standalone_sleeve_backtest_comparison = False
    cfg.run_concentrated_backtest_comparison = True
    # Phase 9 CE (2026-04-18): fast_mode used to strip concentrated grid to
    # [N=1,2,3] × [monthly] × [conviction_curve] = 3 backtests. Expand to the
    # CE grid so fast_mode runs still measure the full concentration ladder.
    # Cost: 7 × 3 × 3 = 63 concentrated backtests × ~6s each = ~6.3 min extra,
    # negligible next to walk-forward training time.
    cfg.concentrated_top_n_candidates = [1, 2, 3, 4, 5, 7, 10]
    cfg.concentrated_rebalance_intervals = [1, 2, 3]
    cfg.concentrated_weighting_modes = ["conviction_curve", "winner_take_all", "score_power"]
    cfg.sleeve_cap_policy_max_candidates = 3
    log("[fast_mode] ON -- lighter collector refresh + ~5 backtests, retrain every 6m; Phase 9 CE concentrated grid expanded to 63 combos.")
    return cfg

def to_cfg(cfg: Optional[dict | EngineConfig]) -> EngineConfig:
    if cfg is None:
        return EngineConfig()
    if isinstance(cfg, EngineConfig):
        return cfg
    base = EngineConfig()
    allowed = set(asdict(base).keys())
    for k, v in cfg.items():
        if k in allowed:
            setattr(base, k, v)
    if not base.alpha_vantage_api_key:
        base.alpha_vantage_api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not base.sec_user_agent or "your_email" in base.sec_user_agent:
        base.sec_user_agent = os.getenv("SEC_USER_AGENT", base.sec_user_agent)
    return base

def configure_last_n_years_backtest(
    cfg: Optional[dict | EngineConfig] = None,
    years: int = 5,
    *,
    end_date: Optional[str] = None,
    train_lookback_years: Optional[int] = None,
) -> EngineConfig:
    cfg_obj = to_cfg(cfg)
    years = int(years)
    if years < 1:
        raise ValueError("years must be >= 1")
    end_ts = pd.Timestamp(end_date or cfg_obj.end_date).normalize()
    if pd.isna(end_ts):
        raise ValueError("end_date could not be parsed")
    start_ts = (end_ts - pd.DateOffset(years=years)).normalize()
    cfg_obj.start_date = str(start_ts.date())
    cfg_obj.end_date = str(end_ts.date())
    if train_lookback_years is not None:
        cfg_obj.train_lookback_years = int(train_lookback_years)
    return cfg_obj

# ---------------------------------------------------------------------
# Stats primitives (Stage 2c) -- numpy/pandas pure-function helpers
# ---------------------------------------------------------------------
# All pure (no side effects except log() in edge cases). Heavily called
# by Phase 1-9 signal computation + sleeve composition paths.

def winsorize(s: pd.Series, p: float = 0.01) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").astype(float)
    if s.dropna().empty:
        return s
    lo, hi = s.quantile(p), s.quantile(1 - p)
    return s.clip(lo, hi)


def robust_z(s: pd.Series) -> pd.Series:
    base = winsorize(pd.to_numeric(s, errors="coerce").astype(float), ROBUST_Z_WINSOR_P)
    x = base.values
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    if mad == 0 or np.isnan(mad):
        return pd.Series(np.zeros(len(s)), index=s.index)
    z = pd.Series((x - med) / (1.4826 * mad), index=s.index)
    return z.clip(lower=-ROBUST_Z_CLIP, upper=ROBUST_Z_CLIP)


def squeeze_series(x: Any) -> pd.Series:
    if isinstance(x, pd.DataFrame):
        if x.shape[1] == 0:
            return pd.Series([], dtype=float)
        return x.iloc[:, 0].copy()
    if isinstance(x, pd.Series):
        return x.copy()
    return pd.Series(x)


def hard_sanitize(df: pd.DataFrame, cols: Iterable[str], clip: float = 1e12) -> pd.DataFrame:
    d = df.copy()
    # Phase 8 review fix (2026-04-17): dedup `cols` to prevent pandas
    # `ValueError: Columns must be same length as key` when callers pass
    # overlapping lists (e.g. DEFAULT_FEATURES contains Phase 1 columns
    # which are also in PHASE1_ALPHA_COLUMNS, and similarly for Phase 8b).
    # `d[cols] = d[cols].replace(...)` requires len(cols) to match the
    # right-hand-side column count; with duplicates in `cols`, the RHS
    # returns one column per unique name, so shapes mismatch.
    # dict.fromkeys preserves order + removes duplicates in one pass.
    cols = [c for c in dict.fromkeys(cols) if c in d.columns]
    if not cols:
        return d
    d[cols] = d[cols].replace([np.inf, -np.inf], np.nan)
    for c in cols:
        d[c] = pd.to_numeric(d[c], errors="coerce").clip(-clip, clip)
    return d

def safe_float(x: Any, default: float = np.nan) -> float:
    try:
        if x is None or (isinstance(x, str) and x.strip() == ""):
            return float(default)
        return float(x)
    except Exception:
        return float(default)


LIVE_CACHE_ALPHA_PRESERVE_FIELDS = [
    "av_forward_pe",
    "av_peg_ratio",
    "av_trailing_pe",
    "av_price_to_sales",
    "av_ev_to_ebitda",
    "av_profit_margin",
    "av_operating_margin",
    "av_return_on_equity",
    "av_quarterly_earnings_growth_yoy",
    "av_quarterly_revenue_growth_yoy",
    "eps_est_q_next",
    "rev_est_q_next",
    "eps_revision_proxy",
    "eps_est_fy1",
    "rev_est_fy1",
    "eps_est_fy2",
    "rev_est_fy2",
]

def cross_sectional_robust_z(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.zeros(len(df)), index=df.index, dtype=float)
    if "rebalance_date" not in df.columns:
        return robust_z(pd.to_numeric(df[col], errors="coerce")).fillna(0.0)
    return (
        df.groupby("rebalance_date", group_keys=False)[col]
        .apply(lambda s: robust_z(pd.to_numeric(s, errors="coerce")).fillna(0.0))
        .reindex(df.index)
        .fillna(0.0)
    )


def cross_sectional_robust_z_by_sector(df: pd.DataFrame, col: str, sector_col: str = "sage_sector") -> pd.Series:
    """Sector-gated robust z-score: standardizes col within each (rebalance_date, sage_sector) group.
    Falls back to universe-wide cross_sectional_robust_z when sage_sector is absent or a group is too small."""
    if col not in df.columns:
        return pd.Series(np.zeros(len(df)), index=df.index, dtype=float)
    if sector_col not in df.columns or "rebalance_date" not in df.columns:
        return cross_sectional_robust_z(df, col)
    result = pd.Series(np.nan, index=df.index, dtype=float)
    for (rd, sc), grp in df.groupby(["rebalance_date", sector_col], group_keys=False):
        vals = pd.to_numeric(grp[col], errors="coerce")
        if vals.notna().sum() >= 5:
            result.loc[grp.index] = robust_z(vals).fillna(0.0)
        else:
            result.loc[grp.index] = 0.0
    # Fill any gaps with universe-wide z-score
    gap_mask = result.isna()
    if gap_mask.any():
        result.loc[gap_mask] = cross_sectional_robust_z(df, col).loc[gap_mask]
    return result.fillna(0.0)

def numeric_series_or_default(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.full(len(df), default), index=df.index, dtype=float)
    raw = df[col]
    if isinstance(raw, pd.DataFrame):
        # Duplicate column names can appear after merges; keep the first non-null value per row.
        raw = raw.bfill(axis=1).iloc[:, 0]
    out = pd.to_numeric(raw, errors="coerce")
    if not isinstance(out, pd.Series):
        out = pd.Series(out, index=df.index, dtype=float)
    return out.reindex(df.index).fillna(default)

def rolling_robust_z(s: pd.Series, window: int = 63) -> pd.Series:
    """Rolling robust z-score (median / MAD).

    Post-2026-04-17 hardening (see DIAGNOSIS_BUGS.md): the previous
    implementation only replaced `mad == 0` with NaN, leaving very small
    MAD values (e.g. 1e-10) to produce z-scores like 1e14 when the
    rolling window happened to have near-constant values followed by a
    jump. This was the root cause of the 2024-06 macro corruption that
    propagated `labor_softening_score = -2e14` to all 600 stock-level
    scores via `compute_macro_regime_features`.

    Fix:
    - Floor MAD at `max(|median| * 0.01, 1e-6)` so the denominator can
      never collapse below a scale-aware floor.
    - Clip the final z-score to [-10, 10]. Any legitimate rolling z-score
      beyond +-10 standard-MADs is almost certainly a data artefact;
      clipping here is cheaper than relying on downstream hard_sanitize.
    """
    x = pd.to_numeric(s, errors="coerce").astype(float)
    min_periods = max(12, window // 3)
    med = x.rolling(window, min_periods=min_periods).median()
    mad = (x - med).abs().rolling(window, min_periods=min_periods).median()
    # Scale-aware MAD floor: prevents near-zero-denominator blow-ups.
    abs_med = med.abs().fillna(0.0)
    mad_floor = np.maximum(abs_med * 0.01, 1e-6)
    mad_safe = np.maximum(mad.fillna(0.0), mad_floor)
    z = (x - med) / (1.4826 * mad_safe)
    z = z.replace([np.inf, -np.inf], np.nan)
    return z.clip(lower=-10.0, upper=10.0)


def row_mean(parts: list[pd.Series], index: pd.Index) -> pd.Series:
    clean = [pd.to_numeric(p, errors="coerce").reindex(index) for p in parts if p is not None]
    if not clean:
        return pd.Series(np.nan, index=index, dtype=float)
    return pd.concat(clean, axis=1).mean(axis=1)

def weighted_sleeve_composite(
    weight_pairs: list[tuple[float, pd.Series]],
    index: pd.Index,
    *,
    renorm_enabled: bool = False,
    l1_target: float = 0.0,
) -> pd.Series:
    """Compute a sleeve composite score from (weight, z-score-series) pairs.

    renorm_enabled=False (default) -> equivalent to
        row_mean([w * s for w, s in pairs])
    This matches the legacy pre-Phase-3 behaviour exactly, so flipping the
    toggle off yields byte-identical sleeve scores.

    renorm_enabled=True -> per-row weighted average
        sum_valid(w_i * s_i) / L1_valid
    where L1_valid is either `l1_target` when positive, or the sum of
    |w_i| over the terms that are non-NaN on that specific row. Rows
    with a NaN z-score for term i have both the numerator contribution
    AND the denominator contribution skipped, matching `row_mean`'s
    NaN-skipping semantics so the A/B measurement isolates the
    "weighted-vs-equal" effect from NaN handling differences.

    L1 semantics with negative weights (penalties):
        Dividing by sum(|w|) rather than sum(w) is intentional. Phase 3's
        stated goal is that each factor's contribution stays proportional
        to its own |w_i| / L1. A negative weight (penalty) still consumes
        |w_i| of the L1 budget and contributes proportionally to the
        numerator with the correct sign. Using sum(w) would shrink the
        denominator when penalties are large, which paradoxically
        strengthens the penalty's relative impact — the opposite of what
        the "magnitude-preserving weighted average" semantics want.

    Notes on downstream compatibility:
        The renorm path typically produces a composite whose magnitude is
        ~N/L1 times the legacy row_mean magnitude. For the sleeve tables
        built in `compute_portfolio_sleeve_columns` this ratio is
        ~2x. Downstream `winsorize(..).clip(-6,6)` handles this, but any
        post-processing additive penalty (e.g. `sparse_history_penalty`)
        calibrated to the legacy magnitude should be scaled by the same
        ratio to keep its relative strength constant — see the
        `compute_portfolio_sleeve_columns` penalty block for the
        Phase-3-aware scaling.
    """
    if not weight_pairs:
        return pd.Series(0.0, index=index, dtype=float)
    weighted_terms: list[pd.Series] = []
    abs_weights: list[float] = []
    for w, s in weight_pairs:
        if s is None:
            continue
        # Phase 8 review fix (2026-04-17): skip weight-0 pairs to prevent
        # row_mean denominator dilution. `row_mean` computes
        # `sum / count_of_non_NaN`, so `0.0 * non_NaN_z_score = 0.0`
        # would count as a valid term and silently dilute every other
        # factor's effective weight by ~1/N. Phase 8a.1 (negative-IC
        # drop), 8a.4 (hold-persistence when inactive), 8b.1 (multi-year
        # when inactive), 8c (when inactive) all set weight to 0 to mean
        # "drop this factor" — without this guard they'd be producing
        # the opposite effect. Threshold 1e-10 catches exact zeros but
        # preserves intentionally-small weights like 0.05.
        if abs(float(w)) < 1e-10:
            continue
        weighted_terms.append(float(w) * s)
        abs_weights.append(abs(float(w)))
    if not weighted_terms:
        return pd.Series(0.0, index=index, dtype=float)
    if not renorm_enabled:
        return row_mean(weighted_terms, index).fillna(0.0)
    # Renorm path: per-row NaN-aware weighted average.
    term_df = pd.concat(
        [pd.to_numeric(t, errors="coerce").reindex(index) for t in weighted_terms],
        axis=1,
    )
    abs_w_arr = np.asarray(abs_weights, dtype=float)
    valid_mask = term_df.notna().to_numpy(dtype=float)  # (n_rows, n_terms)
    if l1_target and l1_target > 0.0:
        denom = np.full(len(index), float(l1_target), dtype=float)
    else:
        denom = valid_mask @ abs_w_arr  # per-row L1, excluding NaN terms
    total = term_df.fillna(0.0).sum(axis=1).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denom > 1e-8, total / denom, 0.0)
    return pd.Series(result, index=index, dtype=float).fillna(0.0)

# ---------------------------------------------------------------------
# IO + ticker + cache helpers (Stage 2d)
# ---------------------------------------------------------------------
# Mix of pure validators (ticker regex check, normalize_ticker), file-system
# helpers (safe_mkdir, safe_read_*, append_history_parquet), cache cadence
# calculators (is_cache_fresh, effective_*_refresh_*), run-identity bookkeeping
# (current_git_commit, build_run_identity, archive_run_outputs), and robust
# HTTP retry wrapper (_robust_retry, _http_get_inner). Mostly used during
# collector setup + latest-scoring export.

def mount_drive_if_colab() -> None:
    try:
        from google.colab import drive  # type: ignore
        if not os.path.ismount("/content/drive"):
            drive.mount("/content/drive")
    except Exception:
        pass


def safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def append_history_parquet(
    path: Path,
    frame: pd.DataFrame,
    dedupe_subset: Optional[list[str]] = None,
    sort_columns: Optional[list[str]] = None,
) -> None:
    if frame is None or frame.empty:
        return
    combined = frame.copy()
    if path.exists():
        try:
            existing = pd.read_parquet(path)
        except Exception:
            existing = pd.DataFrame()
        if not existing.empty:
            combined = pd.concat([existing, combined], ignore_index=True, sort=False)
    if dedupe_subset:
        keep_cols = [col for col in dedupe_subset if col in combined.columns]
        if keep_cols:
            combined = combined.drop_duplicates(subset=keep_cols, keep="last")
    if sort_columns:
        keep_sort = [col for col in sort_columns if col in combined.columns]
        if keep_sort:
            combined = combined.sort_values(keep_sort).reset_index(drop=True)
    combined.to_parquet(path, index=False)


def safe_read_json_file(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_read_parquet_file(path: Path) -> pd.DataFrame:
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def safe_run_token(value: Any, default: str = "na") -> str:
    txt = str(value or "").strip()
    if not txt:
        txt = str(default)
    txt = re.sub(r"[^A-Za-z0-9._-]+", "-", txt)
    txt = txt.strip("-._")
    return txt or str(default)


def current_git_commit() -> str:
    candidates = []
    try:
        candidates.append(Path.cwd())
    except Exception:
        pass
    try:
        candidates.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    seen: set[str] = set()
    for base in candidates:
        for candidate in [base, *base.parents]:
            txt = str(candidate)
            if txt in seen:
                continue
            seen.add(txt)
            try:
                proc = subprocess.run(
                    ["git", "-C", txt, "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
            except Exception:
                continue
            if proc.returncode == 0:
                sha = str(proc.stdout).strip()
                if sha:
                    return sha
    return ""


def build_run_identity(cfg: EngineConfig, *, scope: str = "run_archive") -> dict[str, str]:
    run_ts = now_ts()
    git_commit = current_git_commit()
    engine_version = str(ENGINE_REUSE_VERSION)
    config_fingerprint = reuse_fingerprint(cfg, scope)
    run_id = "__".join(
        [
            safe_run_token(run_ts),
            safe_run_token(git_commit[:7] if git_commit else "nogit"),
            safe_run_token(engine_version),
        ]
    )
    return {
        "run_ts": run_ts,
        "git_commit": git_commit,
        "engine_version": engine_version,
        "config_fingerprint": config_fingerprint,
        "run_id": run_id,
    }


def archive_run_outputs(
    paths: dict[str, Path],
    *,
    run_id: str,
    manifest: Mapping[str, Any],
    output_files: Mapping[str, Any],
) -> dict[str, Any]:
    archive_root = paths["out"] / "archive"
    archive_dir = archive_root / safe_run_token(run_id)
    safe_mkdir(archive_root)
    safe_mkdir(archive_dir)

    archived_files: dict[str, str] = {}
    for key, raw_path in dict(output_files or {}).items():
        if not raw_path:
            continue
        src = Path(str(raw_path))
        if not src.exists() or src.is_dir():
            continue
        try:
            rel = src.relative_to(paths["out"])
            dst = archive_dir / rel
        except Exception:
            dst = archive_dir / "external" / src.name
        safe_mkdir(dst.parent)
        try:
            shutil.copy2(src, dst)
            archived_files[str(key)] = str(dst)
        except Exception:
            continue

    manifest_payload = dict(manifest or {})
    manifest_payload["archive_dir"] = str(archive_dir)
    manifest_payload["archived_output_files"] = archived_files
    manifest_path = archive_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    latest_manifest_path = paths["out"] / "run_manifest.json"
    latest_manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    archived_files["run_manifest.json"] = str(manifest_path)
    return {
        "archive_dir": str(archive_dir),
        "manifest_path": str(manifest_path),
        "latest_manifest_path": str(latest_manifest_path),
        "archived_output_files": archived_files,
    }


def get_paths(cfg: EngineConfig) -> dict[str, Path]:
    base = Path(cfg.base_dir)
    out = base / "outputs"
    archive = out / "archive"
    ops = out / "ops"
    reports = out / "reports"
    baseline = base / "baseline"
    data_raw = base / "data_raw"
    cache_prices = base / "cache_prices"
    cache_fsds = base / "cache_fsds"
    cache_misc = base / "cache_misc"
    cache_macro = base / "cache_macro"
    cache_live_fund = base / "cache_live_fund"
    cache_sec_actual = base / "cache_sec_actual"
    feature_store = base / "feature_store"
    models = base / "models"
    checkpoints = out / "checkpoints"
    for p in [
        base,
        out,
        archive,
        ops,
        reports,
        baseline,
        data_raw,
        cache_prices,
        cache_fsds,
        cache_misc,
        cache_macro,
        cache_live_fund,
        cache_sec_actual,
        feature_store,
        models,
        checkpoints,
    ]:
        safe_mkdir(p)
    return {
        "base": base,
        "out": out,
        "archive": archive,
        "ops": ops,
        "reports": reports,
        "baseline": baseline,
        "data_raw": data_raw,
        "cache_prices": cache_prices,
        "cache_fsds": cache_fsds,
        "cache_misc": cache_misc,
        "cache_macro": cache_macro,
        "cache_live_fund": cache_live_fund,
        "cache_sec_actual": cache_sec_actual,
        "feature_store": feature_store,
        "models": models,
        "checkpoints": checkpoints,
    }


def load_previous_live_weights(paths: dict[str, Path], latest_dt: Optional[pd.Timestamp] = None) -> dict[str, float]:
    payload = load_previous_live_policy(paths, latest_dt=latest_dt)
    if not isinstance(payload, dict):
        return {}
    holdings = payload.get("holdings") or {}
    if not isinstance(holdings, dict):
        return {}
    prev_w: dict[str, float] = {}
    for key, value in holdings.items():
        ticker = normalize_ticker(key)
        weight = safe_float(value)
        if ticker and pd.notna(weight) and float(weight) > 1e-10:
            prev_w[ticker] = float(weight)
    total = float(sum(prev_w.values()))
    if total > 0:
        prev_w = {k: float(v / total) for k, v in prev_w.items()}
    return prev_w


def load_previous_live_policy(paths: dict[str, Path], latest_dt: Optional[pd.Timestamp] = None) -> dict[str, Any]:
    payload = safe_read_json_file(paths["out"] / "weights_latest.json", default={})
    if not isinstance(payload, dict):
        return {}
    prev_dt = pd.to_datetime(payload.get("rebalance_date"), errors="coerce")
    if pd.notna(prev_dt) and pd.notna(latest_dt) and pd.Timestamp(prev_dt) >= pd.Timestamp(latest_dt):
        return {}
    return payload


def _robust_retry(func, max_retries=3, backoff_factor=2.0):
    """Wrap *func* with exponential-backoff retry on transient errors."""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except requests.exceptions.HTTPError as exc:
                # 404/401/403 등 영구적 에러는 재시도 불필요
                if exc.response is not None and exc.response.status_code in (400, 401, 403, 404, 405, 410, 422):
                    raise
                last_exc = exc
                wait = backoff_factor ** attempt
                log(f"[WARN] {func.__name__} attempt {attempt + 1}/{max_retries} failed: {exc}. Retry in {wait:.1f}s")
                time.sleep(wait)
            except Exception as exc:
                last_exc = exc
                wait = backoff_factor ** attempt
                log(f"[WARN] {func.__name__} attempt {attempt + 1}/{max_retries} failed: {exc}. Retry in {wait:.1f}s")
                time.sleep(wait)
        raise last_exc  # type: ignore[misc]
    return wrapper


def _http_get_inner(url: str, headers: Optional[dict[str, str]] = None, timeout: int = 120) -> requests.Response:
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r


http_get = _robust_retry(_http_get_inner, max_retries=3, backoff_factor=2.0)


def normalize_ticker(t: Any) -> Optional[str]:
    if pd.isna(t):
        return None
    return str(t).strip().upper().replace("/", "-").replace("\n", "").replace("\r", "")


def is_valid_ticker(t: Optional[str]) -> bool:
    return (t is not None) and (len(t) <= 12) and bool(TICKER_RE.match(t))


def is_valid_price_symbol(t: Optional[str]) -> bool:
    if t is None:
        return False
    txt = str(t).strip().upper()
    if not txt or len(txt) > 16:
        return False
    if txt.startswith("^"):
        return bool(re.match(r"^\^[A-Z0-9.-]{1,15}$", txt))
    return is_valid_ticker(txt)


def looks_like_noncommon(ticker: str, name: Optional[str] = None) -> bool:
    if re.search(r"[A-Z]{1,3}\d{1,2}$", ticker):
        return True
    if re.search(r"\d", ticker) and len(ticker) >= 5:
        return True
    if ticker.endswith(("FUT", "-W", "-WS", "-RT")):
        return True
    if name and any(k in str(name).upper() for k in EXCLUDE_NAME):
        return True
    return False


def px_cache_name(ticker: str) -> str:
    return f"{hashlib.sha1(ticker.encode('utf-8')).hexdigest()[:16]}.parquet"


def to_yf_symbol(ticker: str) -> str:
    return YF_OVERRIDES.get(ticker, ticker.replace(".", "-"))


# Stage 3d-i-prep (2026-04-20): CIK normalization helpers moved from main
# to unblock Stage 3d-i (recompute_fund_panel_derived_columns references
# normalize_cik_series).

def companyfacts_cache_file(paths: dict[str, Path], cik: str) -> Path:
    return paths["cache_sec_actual"] / f"companyfacts_{str(cik).zfill(10)}.json"


def normalize_cik10(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    txt = str(value).strip()
    if not txt or txt.lower() in {"nan", "none", "nat"}:
        return None
    m = re.search(r"\d+", txt)
    if not m:
        return None
    digits = str(m.group(0))
    if not digits or int(digits) == 0:
        return None
    return digits.zfill(10)


def normalize_cik_list(values: Iterable[Any]) -> list[str]:
    out = {cik for cik in (normalize_cik10(v) for v in values) if cik}
    return sorted(out)


def normalize_cik_series(values: Iterable[Any], index: Optional[pd.Index] = None) -> pd.Series:
    normalized = [normalize_cik10(v) for v in values]
    return pd.Series(normalized, index=index, dtype=object)


# Stage 2c (2026-04-20): winsorize + robust_z + squeeze_series + hard_sanitize moved to r1000_helpers.py.


def cache_live_file(paths: dict[str, Path], ticker: str) -> Path:
    return paths["cache_live_fund"] / f"{ticker.upper()}.json"


def cache_live_statement_file(paths: dict[str, Path], ticker: str) -> Path:
    return paths["cache_live_fund"] / f"{ticker.upper()}_statement.json"


def is_cache_fresh(path: Path, days: int) -> bool:
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime).days < days


def effective_alpha_vantage_refresh_tickers(cfg: EngineConfig) -> int:
    limit = int(getattr(cfg, "max_alpha_vantage_refresh_tickers", 0))
    if bool(getattr(cfg, "alpha_vantage_free_tier_mode", False)):
        limit = min(limit, int(getattr(cfg, "alpha_vantage_free_refresh_tickers", limit)))
    return max(limit, 0)


def effective_latest_statement_repair_tickers(cfg: EngineConfig) -> int:
    limit = int(getattr(cfg, "latest_statement_repair_tickers", 0))
    if bool(getattr(cfg, "alpha_vantage_free_tier_mode", False)):
        limit = min(limit, int(getattr(cfg, "alpha_vantage_free_statement_repair_tickers", limit)))
    return max(limit, 0)


def effective_latest_statement_refresh_days(cfg: EngineConfig) -> int:
    days = int(getattr(cfg, "latest_statement_repair_refresh_days", 0))
    if bool(getattr(cfg, "alpha_vantage_free_tier_mode", False)):
        days = max(days, int(getattr(cfg, "alpha_vantage_free_statement_refresh_days", days)))
    return max(days, 0)


def alpha_vantage_pause_seconds(cfg: Optional[EngineConfig], statement: bool = False) -> float:
    if cfg is not None and bool(getattr(cfg, "alpha_vantage_free_tier_mode", False)):
        return 0.90 if statement else 0.75
    return 0.20 if not statement else 0.15


# Stage 2c (2026-04-20): safe_float moved to r1000_helpers.py.

__all__ = [
    "_resolve_engine_commit_sha",
    "phase_is_enabled",
    "now_ts",
    "log",
    "apply_fast_mode",
    "to_cfg",
    "configure_last_n_years_backtest",
    "winsorize",
    "robust_z",
    "squeeze_series",
    "hard_sanitize",
    "safe_float",
    "cross_sectional_robust_z",
    "cross_sectional_robust_z_by_sector",
    "numeric_series_or_default",
    "rolling_robust_z",
    "row_mean",
    "weighted_sleeve_composite",
    "mount_drive_if_colab",
    "safe_mkdir",
    "append_history_parquet",
    "safe_read_json_file",
    "safe_read_parquet_file",
    "safe_run_token",
    "current_git_commit",
    "build_run_identity",
    "archive_run_outputs",
    "get_paths",
    "load_previous_live_weights",
    "load_previous_live_policy",
    "_robust_retry",
    "_http_get_inner",
    "normalize_ticker",
    "is_valid_ticker",
    "is_valid_price_symbol",
    "looks_like_noncommon",
    "px_cache_name",
    "to_yf_symbol",
    "companyfacts_cache_file",
    "normalize_cik10",
    "normalize_cik_list",
    "normalize_cik_series",
    "cache_live_file",
    "cache_live_statement_file",
    "is_cache_fresh",
    "effective_alpha_vantage_refresh_tickers",
    "effective_latest_statement_repair_tickers",
    "effective_latest_statement_refresh_days",
    "alpha_vantage_pause_seconds",
    "ENGINE_COMMIT_SHA",
    "LIVE_CACHE_ALPHA_PRESERVE_FIELDS",
]
