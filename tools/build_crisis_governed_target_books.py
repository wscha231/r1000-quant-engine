#!/usr/bin/env python3
"""Build research-only crisis-governed target books for broker-ledger replay.

This is Phase G2: convert the Phase E crisis governor from an equity-curve
counterfactual into observable target-book rows that can be replayed by
`tools/run_broker_ledger_replay.py` with next-close fills, integer shares,
cash ledger, and fees.

No production defaults are changed. The generated books are challenger
artifacts only; promotion still requires human approval after broker-ledger
metrics and stress-window review.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_crisis_governor import apply_exposure_ladder, evaluate_exposure_target  # noqa: E402
from r1000_long_crisis_liquidity import cash_raise_decision  # noqa: E402
from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_TICKERS,
    filter_concentrated_champion,
    replay,
    resolve_concentrated_champion_filters,
)


DEFAULT_OUTPUT_DIR = "outputs/crisis_governed_target_books"
DEFAULT_REPORTS_DIR = "outputs/reports"

GOVERNOR_MODES: dict[str, dict[str, Any]] = {
    "off": {"enabled": False, "low": 0.30, "mid": 0.50, "high": 0.70},
    "conservative": {"enabled": True, "low": 0.30, "mid": 0.50, "high": 0.70},
    "aggressive": {"enabled": True, "low": 0.20, "mid": 0.40, "high": 0.60},
    # Defaults are intentionally conservative. When --thresholds-json is
    # supplied, the learned governor thresholds override these values.
    "learned": {"enabled": True, "low": 0.35, "mid": 0.55, "high": 0.75},
}


@dataclass
class NormalizedTargets:
    frame: pd.DataFrame
    filter_meta: dict[str, Any]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_crisis_features(path: Path) -> pd.DataFrame:
    """Load daily crisis features with a normalized date index.

    The function accepts parquet or csv. It never fills forward beyond the
    supplied rows; downstream schedule construction only uses feature dates
    that exist in the file plus target-book rebalance dates.
    """
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(path)
        else:
            frame = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()
    if frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    date_col = None
    for candidate in ("date", "Date", "rebalance_date"):
        if candidate in out.columns:
            date_col = candidate
            break
    if date_col is not None:
        idx = pd.to_datetime(out.pop(date_col), errors="coerce")
    else:
        idx = pd.to_datetime(out.index, errors="coerce")
    out.index = idx
    out = out[~out.index.isna()].sort_index()
    out.index = pd.DatetimeIndex(out.index).normalize()
    if "crisis_score" not in out.columns:
        out["crisis_score"] = 0.0
    out["crisis_score"] = pd.to_numeric(out["crisis_score"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
    return out


def load_learned_thresholds(path: Path | None, mode: str) -> dict[str, Any]:
    """Resolve governor thresholds for mode, optionally from long-crisis search."""
    thresholds = dict(GOVERNOR_MODES[mode])
    if path is None or not path.exists():
        return thresholds
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return thresholds
    learned = payload.get("governor_thresholds") if isinstance(payload, dict) else None
    if not isinstance(learned, dict):
        learned = payload
    for key in ("low", "mid", "high"):
        if key in learned:
            try:
                thresholds[key] = float(learned[key])
            except (TypeError, ValueError):
                pass
    thresholds["enabled"] = bool(thresholds.get("enabled", True))
    return thresholds


def _cash_gate_for_feature_row(
    feature_row: pd.Series,
    crisis_score: float,
    thresholds: dict[str, Any],
    enabled: bool,
) -> dict[str, Any]:
    if not enabled or feature_row.empty:
        return {
            "cash_hard_gate_enabled": bool(enabled),
            "cash_hard_gate_allowed": True,
            "cash_hard_gate_reason": "disabled_or_no_features",
            "effective_crisis_score": float(crisis_score),
            "liquidity_confirmation_score": float(feature_row.get("liquidity_confirmation_score", 0.0)) if not feature_row.empty else 0.0,
            "market_trend_damage_score": float(feature_row.get("market_trend_damage_score", 0.0)) if not feature_row.empty else 0.0,
            "credit_stress_score": float(feature_row.get("credit_stress_score", 0.0)) if not feature_row.empty else 0.0,
            "shakeout_guard_score": float(feature_row.get("shakeout_guard_score", 0.0)) if not feature_row.empty else 0.0,
        }
    # Preserve the old Phase G behavior when the long-crisis liquidity columns
    # are absent. This keeps PR #48 research outputs reproducible.
    known_cols = {"liquidity_confirmation_score", "market_trend_damage_score", "credit_stress_score", "shakeout_guard_score"}
    if not known_cols.intersection(set(feature_row.index.astype(str))):
        return {
            "cash_hard_gate_enabled": True,
            "cash_hard_gate_allowed": True,
            "cash_hard_gate_reason": "missing_liquidity_columns_allow_legacy_behavior",
            "effective_crisis_score": float(crisis_score),
            "liquidity_confirmation_score": 0.0,
            "market_trend_damage_score": 0.0,
            "credit_stress_score": 0.0,
            "shakeout_guard_score": 0.0,
        }
    decision = cash_raise_decision(
        feature_row,
        crisis_score,
        mid_threshold=float(thresholds.get("mid", 0.50)),
    )
    return {
        "cash_hard_gate_enabled": True,
        "cash_hard_gate_allowed": bool(decision.allowed),
        "cash_hard_gate_reason": decision.reason,
        "effective_crisis_score": float(decision.effective_crisis_score),
        "liquidity_confirmation_score": float(decision.liquidity_confirmation_score),
        "market_trend_damage_score": float(decision.market_trend_damage_score),
        "credit_stress_score": float(decision.credit_stress_score),
        "shakeout_guard_score": float(decision.shakeout_guard_score),
    }


def normalize_targets(target_book: Path, portfolio_kind: str) -> NormalizedTargets:
    raw = read_csv(target_book)
    if raw.empty or not {"rebalance_date", "ticker", "weight"}.issubset(raw.columns):
        return NormalizedTargets(
            pd.DataFrame(),
            {
                "status": "blocked",
                "reason": "target book missing required rebalance_date/ticker/weight columns",
                "target_book": str(target_book),
            },
        )
    filters, source, warning = resolve_concentrated_champion_filters(
        target_book=target_book,
        raw_targets=raw,
        portfolio_kind=portfolio_kind,
        explicit_filters=None,
    )
    d = filter_concentrated_champion(raw, portfolio_kind, filters).copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["weight"] > 1e-12)].copy()
    d = d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    return NormalizedTargets(
        d,
        {
            "target_book_filter": filters,
            "target_book_filter_source": source,
            "target_book_filter_warning": warning,
        },
    )


def _canonical_ticker(ticker: Any) -> str:
    text = str(ticker or "").upper().strip()
    return "CASH" if text in CASH_TICKERS else text


def _period_weights(period: pd.DataFrame) -> pd.Series:
    weights: dict[str, float] = {}
    for row in period.to_dict("records"):
        ticker = _canonical_ticker(row.get("ticker"))
        if not ticker:
            continue
        weights[ticker] = weights.get(ticker, 0.0) + max(0.0, float(row.get("weight") or 0.0))
    if not weights:
        return pd.Series(dtype=float)
    out = pd.Series(weights, dtype=float)
    total = float(out.sum())
    if total > 1.0 + 1e-9:
        out = out / total
    return out


def _templates(period: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in period.to_dict("records"):
        ticker = _canonical_ticker(row.get("ticker"))
        if ticker:
            out[ticker] = dict(row)
    return out


def _feature_row_asof(features: pd.DataFrame, dt: pd.Timestamp) -> pd.Series:
    if features.empty:
        return pd.Series(dtype=float)
    loc = features.loc[features.index <= pd.Timestamp(dt).normalize()]
    if loc.empty:
        return pd.Series(dtype=float)
    return loc.iloc[-1]


def _schedule_dates(targets: pd.DataFrame, features: pd.DataFrame, thresholds: dict[str, Any], mode: str) -> list[pd.Timestamp]:
    base_dates = [pd.Timestamp(x).normalize() for x in sorted(targets["rebalance_date"].dropna().unique())]
    if not base_dates:
        return []
    if mode == "off" or features.empty:
        return base_dates
    low = float(thresholds.get("low", 0.30))
    min_dt = min(base_dates)
    max_dt = max(max(base_dates), pd.Timestamp(features.index.max()).normalize())
    feat = features[(features.index >= min_dt) & (features.index <= max_dt)].copy()
    if feat.empty:
        return base_dates
    score = pd.to_numeric(feat["crisis_score"], errors="coerce").fillna(0.0)
    active = score.ge(low) | score.shift(1).fillna(0.0).ge(low)
    zone = score.map(lambda x: evaluate_exposure_target(float(x), cfg_thresholds=thresholds).zone)
    zone_change = zone.ne(zone.shift(1))
    feature_dates = [pd.Timestamp(x).normalize() for x in feat.index[active | zone_change]]
    return sorted(set(base_dates + feature_dates))


def _rows_for_snapshot(
    *,
    snapshot_date: pd.Timestamp,
    adjusted_weights: pd.Series,
    templates: dict[str, dict[str, Any]],
    portfolio_kind: str,
    mode: str,
    crisis_score: float,
    raw_crisis_score: float,
    zone: str,
    target_cash_floor: float,
    event_reason: str,
    gate_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ticker, weight in adjusted_weights.sort_index().items():
        w = float(weight)
        if w <= 1e-12:
            continue
        base = dict(templates.get(ticker, {}))
        base["rebalance_date"] = snapshot_date.date().isoformat()
        base["ticker"] = ticker
        base["weight"] = w
        base["portfolio_kind"] = portfolio_kind
        base["crisis_governed_target_book"] = True
        base["research_only"] = True
        base["governor_mode"] = mode
        base["crisis_score"] = float(crisis_score)
        base["raw_crisis_score"] = float(raw_crisis_score)
        base["crisis_zone"] = zone
        base["target_cash_floor"] = float(target_cash_floor)
        base["event_reason"] = event_reason
        for key, value in gate_meta.items():
            if key != "effective_crisis_score":
                base[key] = value
        rows.append(base)
    return rows


def build_governed_book(
    *,
    target_book: Path,
    crisis_features: Path,
    portfolio_kind: str,
    mode: str = "conservative",
    allow_normal_cash_deploy: bool = False,
    cash_hard_gate: bool = False,
    thresholds_json: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Return governed target book, schedule audit, and summary metadata."""
    if mode not in GOVERNOR_MODES:
        raise ValueError(f"unknown governor mode: {mode}")
    normalized = normalize_targets(target_book, portfolio_kind)
    targets = normalized.frame
    if targets.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "blocked",
            "portfolio_kind": portfolio_kind,
            "mode": mode,
            **normalized.filter_meta,
        }
    features = load_crisis_features(crisis_features)
    thresholds = load_learned_thresholds(thresholds_json, mode)
    dates = _schedule_dates(targets, features, thresholds, mode)
    rows: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    prior_weights: dict[str, float] | None = None
    base_dates = [pd.Timestamp(x).normalize() for x in sorted(targets["rebalance_date"].dropna().unique())]

    for dt in dates:
        eligible_base_dates = [x for x in base_dates if x <= dt]
        if not eligible_base_dates:
            continue
        base_dt = max(eligible_base_dates)
        period = targets[targets["rebalance_date"].eq(base_dt)].copy()
        weights = _period_weights(period)
        if weights.empty:
            continue
        feature_row = _feature_row_asof(features, dt)
        raw_crisis_score = float(feature_row.get("crisis_score", 0.0)) if not feature_row.empty else 0.0
        gate_meta = _cash_gate_for_feature_row(feature_row, raw_crisis_score, thresholds, cash_hard_gate)
        crisis_score = float(gate_meta["effective_crisis_score"])
        target = evaluate_exposure_target(crisis_score, cfg_thresholds=thresholds)
        should_apply = mode != "off" and (target.zone != "normal" or allow_normal_cash_deploy)
        adjusted = (
            apply_exposure_ladder(weights, crisis_score, target=target)
            if should_apply
            else weights.copy()
        )
        total = float(adjusted.sum())
        if total > 0:
            adjusted = adjusted / total
        rounded = {str(k): round(float(v), 10) for k, v in adjusted.items() if float(v) > 1e-12}
        is_base_date = dt in set(base_dates)
        if prior_weights is not None and rounded == prior_weights and not is_base_date:
            continue
        prior_weights = rounded
        event_reason = "base_rebalance"
        if should_apply:
            event_reason = f"crisis_governor_{target.zone}"
        elif target.zone == "normal" and dt != base_dt:
            event_reason = "crisis_governor_reentry"
        snapshot_rows = _rows_for_snapshot(
            snapshot_date=dt,
            adjusted_weights=adjusted,
            templates=_templates(period),
            portfolio_kind=portfolio_kind,
            mode=mode,
            crisis_score=crisis_score,
            raw_crisis_score=raw_crisis_score,
            zone=target.zone,
            target_cash_floor=target.target_cash_floor,
            event_reason=event_reason,
            gate_meta=gate_meta,
        )
        rows.extend(snapshot_rows)
        audit.append(
            {
                "snapshot_date": dt.date().isoformat(),
                "base_rebalance_date": base_dt.date().isoformat(),
                "portfolio_kind": portfolio_kind,
                "governor_mode": mode,
                "crisis_score": crisis_score,
                "raw_crisis_score": raw_crisis_score,
                "crisis_zone": target.zone,
                "event_reason": event_reason,
                "stock_weight": float(adjusted[[idx for idx in adjusted.index if str(idx).upper() not in CASH_TICKERS]].sum()),
                "cash_weight": float(adjusted[[idx for idx in adjusted.index if str(idx).upper() in CASH_TICKERS]].sum()),
                "row_count": len(snapshot_rows),
                **{k: v for k, v in gate_meta.items() if k != "effective_crisis_score"},
            }
        )

    book = pd.DataFrame(rows)
    audit_df = pd.DataFrame(audit)
    summary = {
        "status": "completed" if not book.empty else "blocked",
        "reason": "" if not book.empty else "no governed rows generated",
        "portfolio_kind": portfolio_kind,
        "mode": mode,
        "thresholds": thresholds,
        "thresholds_json": str(thresholds_json) if thresholds_json else "",
        "cash_hard_gate": bool(cash_hard_gate),
        "research_only": True,
        "valid_for_production": False,
        "official_metric_required": "broker_ledger_next_close",
        "promotion_allowed_without_human_approval": False,
        "target_book": str(target_book),
        "crisis_features": str(crisis_features),
        "target_row_count": int(len(book)),
        "snapshot_count": int(audit_df["snapshot_date"].nunique()) if not audit_df.empty else 0,
        "max_cash_weight": float(audit_df["cash_weight"].max()) if not audit_df.empty else 0.0,
        "max_crisis_score": float(audit_df["crisis_score"].max()) if not audit_df.empty else 0.0,
        **normalized.filter_meta,
    }
    return book, audit_df, summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Crisis-Governed Target Books",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Generated at: `{payload.get('generated_at')}`",
        f"- Research only: `{payload.get('research_only')}`",
        f"- Official metric required: `{payload.get('official_metric_required')}`",
        f"- Promotion without human approval: `{payload.get('promotion_allowed_without_human_approval')}`",
        "",
        "## Portfolios",
        "",
        "| portfolio | status | target rows | snapshots | max cash | broker status | CAGR | MDD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in sorted((payload.get("portfolios") or {}).items()):
        broker = row.get("broker_replay") or {}
        cagr = broker.get("cagr")
        mdd = broker.get("max_dd")
        lines.append(
            "| {name} | {status} | {rows} | {snapshots} | {cash:.2%} | {broker_status} | {cagr} | {mdd} |".format(
                name=name,
                status=row.get("status"),
                rows=int(row.get("target_row_count") or 0),
                snapshots=int(row.get("snapshot_count") or 0),
                cash=float(row.get("max_cash_weight") or 0.0),
                broker_status=broker.get("status", "not_run"),
                cagr="" if cagr is None else f"{float(cagr):.2%}",
                mdd="" if mdd is None else f"{float(mdd):.2%}",
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This is G2 target-book materialization, not production activation.",
            "- G1 counterfactual verdicts remain research-only and are not promotion evidence.",
            "- Broker-ledger replay output is official only when `metric_mode` is `broker_ledger_next_close` and `valid_for_production` is true.",
        ]
    )
    return "\n".join(lines) + "\n"


def _metric_value(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        try:
            if value is None or value == "":
                continue
            out = float(value)
            if pd.notna(out):
                return out
        except Exception:
            continue
    return None


def _gate_for_portfolio(portfolio: str, base: dict[str, Any], governed: dict[str, Any]) -> dict[str, Any]:
    base_cagr = _metric_value(base, "cagr")
    base_mdd = _metric_value(base, "max_dd", "mdd")
    gov_cagr = _metric_value(governed, "cagr")
    gov_mdd = _metric_value(governed, "max_dd", "mdd")
    cagr_delta = None if base_cagr is None or gov_cagr is None else gov_cagr - base_cagr
    mdd_improvement = None if base_mdd is None or gov_mdd is None else gov_mdd - base_mdd
    if portfolio == "main":
        candidate_pass = bool(cagr_delta is not None and mdd_improvement is not None and cagr_delta >= -0.005 and mdd_improvement >= 0.05)
        research_pass = bool(cagr_delta is not None and mdd_improvement is not None and cagr_delta >= -0.02 and mdd_improvement >= 0.08)
        promotion_candidate = bool(cagr_delta is not None and mdd_improvement is not None and cagr_delta >= 0.0 and mdd_improvement >= 0.05)
    else:
        candidate_pass = bool(cagr_delta is not None and gov_mdd is not None and cagr_delta >= -0.03 and gov_mdd >= -0.32)
        research_pass = candidate_pass
        promotion_candidate = bool(gov_cagr is not None and gov_mdd is not None and gov_cagr >= 0.35 and -0.28 <= gov_mdd <= -0.25)
        if gov_mdd is not None and gov_mdd < -0.35:
            candidate_pass = False
            research_pass = False
            promotion_candidate = False
    return {
        "portfolio_kind": portfolio,
        "base_cagr": base_cagr,
        "governed_cagr": gov_cagr,
        "cagr_delta": cagr_delta,
        "base_max_dd": base_mdd,
        "governed_max_dd": gov_mdd,
        "max_dd_improvement": mdd_improvement,
        "candidate_pass": candidate_pass,
        "research_pass": research_pass,
        "promotion_candidate": promotion_candidate,
        "promotion_allowed_without_human_approval": False,
        "metric_mode": governed.get("metric_mode", "broker_ledger_next_close"),
    }


def write_decision_outputs(payload: dict[str, Any], latest_run: Path, output_dir: Path) -> None:
    rows: list[dict[str, Any]] = []
    for portfolio, item in (payload.get("portfolios") or {}).items():
        base = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
        governed = item.get("broker_replay") if isinstance(item, dict) else {}
        if not isinstance(governed, dict):
            governed = {}
        rows.append(_gate_for_portfolio(str(portfolio), base, governed))
    decision = {
        "schema_version": "phase-g-crisis-decision-v1",
        "generated_at": now_utc(),
        "research_only": True,
        "valid_for_production": False,
        "official_metric_required": "broker_ledger_next_close",
        "promotion_allowed_without_human_approval": False,
        "rows": rows,
        "overall_status": "candidate_pass" if rows and all(row.get("candidate_pass") for row in rows) else "review_or_reject",
    }
    write_json(output_dir / "decision_summary.json", decision)
    if rows:
        pd.DataFrame(rows).to_csv(output_dir / "crisis_governed_broker_metrics.csv", index=False)
    status_lines = [
        "# Phase G Crisis Action Status",
        "",
        f"- overall_status: `{decision['overall_status']}`",
        "- auto_trade_allowed: `false`",
        "- production_activation_allowed: `false`",
        "",
        "| portfolio | base CAGR | governed CAGR | base MDD | governed MDD | candidate pass | promotion candidate |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        status_lines.append(
            "| {p} | {bc:.2%} | {gc:.2%} | {bm:.2%} | {gm:.2%} | {cp} | {pc} |".format(
                p=row.get("portfolio_kind"),
                bc=float(row.get("base_cagr") or 0.0),
                gc=float(row.get("governed_cagr") or 0.0),
                bm=float(row.get("base_max_dd") or 0.0),
                gm=float(row.get("governed_max_dd") or 0.0),
                cp=str(row.get("candidate_pass")).lower(),
                pc=str(row.get("promotion_candidate")).lower(),
            )
        )
    write_text(output_dir / "crisis_action_status.md", "\n".join(status_lines) + "\n")


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    reports_dir = repo_path(args.reports_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    crisis_features = repo_path(args.crisis_features)
    latest_run = repo_path(args.latest_run) if args.latest_run else REPO_ROOT / "outputs"
    target_books = {
        "main": repo_path(args.main_target_book) if args.main_target_book else latest_run / "reports" / "operating_main_target_book.csv",
        "concentrated": repo_path(args.concentrated_target_book) if args.concentrated_target_book else latest_run / "reports" / "operating_concentrated_target_book.csv",
    }
    selected = ["main", "concentrated"] if args.portfolio_kind == "both" else [args.portfolio_kind]
    payload: dict[str, Any] = {
        "status": "completed",
        "generated_at": now_utc(),
        "research_only": True,
        "valid_for_production": False,
        "official_metric_required": "broker_ledger_next_close",
        "promotion_allowed_without_human_approval": False,
        "mode": args.mode,
        "crisis_features": str(crisis_features),
        "cash_hard_gate": bool(args.cash_hard_gate),
        "thresholds_json": str(repo_path(args.thresholds_json)) if args.thresholds_json else "",
        "portfolios": {},
    }
    for portfolio_kind in selected:
        book, audit_df, summary = build_governed_book(
            target_book=target_books[portfolio_kind],
            crisis_features=crisis_features,
            portfolio_kind=portfolio_kind,
            mode=args.mode,
            allow_normal_cash_deploy=bool(args.allow_normal_cash_deploy),
            cash_hard_gate=bool(args.cash_hard_gate),
            thresholds_json=repo_path(args.thresholds_json) if args.thresholds_json else None,
        )
        book_path = reports_dir / f"crisis_governed_{portfolio_kind}_target_book.csv"
        audit_path = output_dir / f"{portfolio_kind}_schedule_audit.csv"
        if not book.empty:
            book.to_csv(book_path, index=False)
        if not audit_df.empty:
            audit_df.to_csv(audit_path, index=False)
        summary["governed_target_book"] = str(book_path)
        summary["schedule_audit"] = str(audit_path)
        if args.run_broker_replay and summary.get("status") == "completed":
            metrics = replay(
                target_book=book_path,
                price_cache=repo_path(args.price_cache),
                output_dir=output_dir / "broker_replay" / portfolio_kind,
                portfolio_kind=portfolio_kind,
                starting_capital=float(args.starting_capital),
                fill_mode="next_close",
                cost_bps=float(args.cost_bps),
                integer_shares=True,
            )
            summary["broker_replay"] = metrics
        payload["portfolios"][portfolio_kind] = summary
    if any(row.get("status") != "completed" for row in payload["portfolios"].values()):
        payload["status"] = "partial"
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    write_decision_outputs(payload, latest_run, output_dir)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--main-target-book", default="")
    parser.add_argument("--concentrated-target-book", default="")
    parser.add_argument("--crisis-features", default="outputs/crisis_signals/daily_features.parquet")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated", "both"], default="both")
    parser.add_argument("--mode", choices=sorted(GOVERNOR_MODES), default="conservative")
    parser.add_argument("--allow-normal-cash-deploy", action="store_true")
    parser.add_argument("--cash-hard-gate", action="store_true", help="Require liquidity/trend/credit confirmation before defense/crisis cash raises")
    parser.add_argument("--thresholds-json", default="", help="Optional best_thresholds.json from long crisis learning")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reports-dir", default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--run-broker-replay", action="store_true")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps({"status": payload.get("status"), "portfolios": list(payload.get("portfolios", {}))}, indent=2))
    return 0 if payload.get("status") in {"completed", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
