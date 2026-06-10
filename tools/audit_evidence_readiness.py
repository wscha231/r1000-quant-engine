#!/usr/bin/env python3
"""Audit SEC/Form4/13F/ETF evidence readiness before strategy testing.

This is a C0.2 foundation preflight. It is intentionally diagnostic and
research-only: it does not mutate evidence data, it does not alter production
score columns, and it does not promote any strategy. It answers whether the
existing evidence lakes are healthy enough to proceed to D1/D5/C5/C4 work.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def parse_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def latest_iso(series: pd.Series) -> str:
    parsed = parse_ts(series).dropna()
    return parsed.max().isoformat() if not parsed.empty else ""


def days_old(value: str) -> int | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    return int((datetime.now(timezone.utc) - parsed.to_pydatetime()).days)


def ticker_count(frame: pd.DataFrame, candidates: list[str]) -> int:
    for col in candidates:
        if col in frame.columns:
            values = frame[col].astype(str).str.upper().str.strip()
            return int(values[values.ne("") & values.ne("NAN")].nunique())
    return 0


def table_health(
    paths: list[Path],
    *,
    ticker_cols: list[str],
    available_col: str = "available_from",
    accepted_col: str = "accepted_at",
    min_rows: int = 1,
    min_tickers: int = 1,
) -> dict[str, Any]:
    selected = first_existing(paths)
    frame = read_table(selected) if selected else pd.DataFrame()
    out: dict[str, Any] = {
        "path": str(selected or paths[0]),
        "exists": bool(selected and selected.exists()),
        "rows": int(len(frame)),
        "ticker_count": ticker_count(frame, ticker_cols),
        "latest_available_from": latest_iso(frame[available_col]) if available_col in frame.columns else "",
        "missing_available_from": 0,
        "missing_accepted_at": 0,
        "available_from_before_accepted_at": 0,
        "min_rows": int(min_rows),
        "min_tickers": int(min_tickers),
        "healthy": False,
    }
    if frame.empty:
        out["healthy"] = False
        return out
    if available_col in frame.columns:
        available = parse_ts(frame[available_col])
        out["missing_available_from"] = int(available.isna().sum())
    else:
        available = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
        out["missing_available_from"] = int(len(frame))
    if accepted_col in frame.columns:
        accepted = parse_ts(frame[accepted_col])
        out["missing_accepted_at"] = int(accepted.isna().sum())
        comparable = accepted.notna() & available.notna()
        out["available_from_before_accepted_at"] = int((available[comparable] < accepted[comparable]).sum())
    out["latest_available_from_age_days"] = days_old(str(out["latest_available_from"]))
    out["healthy"] = bool(
        out["rows"] >= min_rows
        and out["ticker_count"] >= min_tickers
        and out["missing_available_from"] == 0
        and out["available_from_before_accepted_at"] == 0
    )
    return out


def signal_health(paths: list[Path], *, ticker_cols: list[str], min_tickers: int) -> dict[str, Any]:
    selected = first_existing(paths)
    frame = read_table(selected) if selected else pd.DataFrame()
    available_col = "latest_available_from" if "latest_available_from" in frame.columns else "available_from"
    out = {
        "path": str(selected or paths[0]),
        "exists": bool(selected and selected.exists()),
        "rows": int(len(frame)),
        "ticker_count": ticker_count(frame, ticker_cols),
        "latest_available_from": latest_iso(frame[available_col]) if available_col in frame.columns else "",
        "min_tickers": int(min_tickers),
        "healthy": False,
    }
    out["latest_available_from_age_days"] = days_old(str(out["latest_available_from"]))
    out["healthy"] = bool(out["rows"] > 0 and out["ticker_count"] >= int(min_tickers))
    return out


def switch_health() -> dict[str, Any]:
    try:
        from r1000_config import EngineConfig  # type: ignore

        cfg = EngineConfig()
        evidence_live = bool(getattr(cfg, "evidence_fusion_apply_to_live_score", False))
        pda_live = bool(getattr(cfg, "pda_apply_to_live_score", False))
        return {
            "loaded": True,
            "evidence_fusion_apply_to_live_score": evidence_live,
            "pda_apply_to_live_score": pda_live,
            "w_pda_13f": float(getattr(cfg, "w_pda_13f", 0.0)),
            "w_pda_form4": float(getattr(cfg, "w_pda_form4", 0.0)),
            "w_pda_13d": float(getattr(cfg, "w_pda_13d", 0.0)),
            "w_pda_etf": float(getattr(cfg, "w_pda_etf", 0.0)),
            "healthy": bool(not evidence_live and not pda_live),
        }
    except Exception as exc:
        return {"loaded": False, "healthy": False, "error": f"{type(exc).__name__}: {exc}"}


def evidence_restore_manifest(latest_run: Path) -> dict[str, Any]:
    paths = [
        latest_run / "full_rebuild_logs" / "sec_evidence_restore_manifest.json",
        latest_run / "full_rebuild_logs" / "sec_gdrive_restore_manifest.json",
        REPO_ROOT / "outputs" / "full_rebuild_logs" / "sec_evidence_restore_manifest.json",
        REPO_ROOT / "outputs" / "full_rebuild_logs" / "sec_gdrive_restore_manifest.json",
    ]
    selected = first_existing(paths)
    payload = read_json(selected) if selected else {}
    return {
        "path": str(selected or paths[0]),
        "exists": bool(selected and selected.exists()),
        "payload": payload,
    }


def evidence_score_columns(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    columns = []
    for col in frame.columns:
        name = str(col).lower()
        if "evidence" in name or name.startswith("sec_") or name.startswith("etf_"):
            if any(token in name for token in ["score", "signal", "confidence"]):
                columns.append(str(col))
    return columns


def evidence_nonzero_count(frame: pd.DataFrame) -> int:
    columns = evidence_score_columns(frame)
    if frame.empty or not columns:
        return 0
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce").fillna(0.0).abs()
    return int((numeric.sum(axis=1) > 1e-12).sum())


def ticker_set(frame: pd.DataFrame) -> set[str]:
    if frame.empty:
        return set()
    for col in ["ticker", "ticker_mapped", "holding_ticker", "issuer_ticker"]:
        if col in frame.columns:
            values = frame[col].astype(str).str.upper().str.strip()
            return set(values[values.ne("") & values.ne("NAN")])
    return set()


def selection_impact(latest_run: Path) -> dict[str, Any]:
    scored = read_table(latest_run / "scored_latest.csv")
    if scored.empty:
        scored = read_table(repo_path("outputs/scored_latest.csv"))
    scored_tickers = ticker_set(scored)
    nonzero_tickers: set[str] = set()
    if not scored.empty:
        columns = evidence_score_columns(scored)
        if columns:
            numeric = scored[columns].apply(pd.to_numeric, errors="coerce").fillna(0.0).abs()
            mask = numeric.sum(axis=1) > 1e-12
            nonzero_tickers = ticker_set(scored.loc[mask].copy())

    selected_frames = [
        read_table(latest_run / "portfolio_latest.csv"),
        read_table(latest_run / "concentrated_portfolio_latest.csv"),
        read_table(latest_run / "reports" / "operating_main_target_book.csv"),
        read_table(latest_run / "reports" / "operating_concentrated_target_book.csv"),
    ]
    selected = set().union(*(ticker_set(frame) for frame in selected_frames))
    selected_nonzero = selected & nonzero_tickers
    return {
        "status": "completed" if scored_tickers or selected else "missing_inputs",
        "scored_ticker_count": int(len(scored_tickers)),
        "evidence_nonzero_ticker_count": int(len(nonzero_tickers)),
        "selected_ticker_count": int(len(selected)),
        "selected_evidence_nonzero_ticker_count": int(len(selected_nonzero)),
        "selection_impact_confirmed": bool(selected_nonzero),
        "rank_delta_available": False,
        "target_overlap_delta_available": False,
        "note": "Nonzero evidence is necessary but not sufficient; broker_impact must pass before promotion.",
    }


def broker_impact(latest_run: Path) -> dict[str, Any]:
    candidates = [
        latest_run / "post_disclosure_alpha_pipeline" / "broker_grid_summary.csv",
        latest_run / "post_disclosure_alpha_pipeline" / "broker_grid_results.csv",
        latest_run / "post_disclosure_overlay_challenger" / "summary.json",
        latest_run / "phase_g_crisis_evidence_liquidity" / "crisis_governed_broker_metrics.csv",
    ]
    selected = first_existing(candidates)
    if not selected:
        return {
            "status": "not_evaluated",
            "broker_ledger_required": True,
            "official_metric_only": True,
            "promotion_allowed": False,
            "path": "",
        }
    payload: dict[str, Any] = {
        "status": "available",
        "broker_ledger_required": True,
        "official_metric_only": True,
        "promotion_allowed": False,
        "path": str(selected),
    }
    frame = read_table(selected)
    if not frame.empty:
        payload["rows"] = int(len(frame))
        payload["columns"] = list(map(str, frame.columns[:30]))
    else:
        payload["payload"] = read_json(selected)
    return payload


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    form4_min = int(args.min_form4_signal_tickers)
    f13_min = int(args.min_13f_signal_tickers)
    etf_min = int(args.min_etf_signal_tickers)

    form4_raw = table_health(
        [repo_path(args.form4_transactions)],
        ticker_cols=["issuer_ticker", "ticker"],
        min_rows=1,
        min_tickers=1,
    )
    form4_signals = signal_health(
        [
            latest_run / "sec_ownership_signals" / "form4_latest.parquet",
            latest_run / "sec_ownership_signals" / "form4_latest.csv",
            repo_path("data_pit/sec/sec_ownership_signals.parquet"),
            repo_path("outputs/sec_ownership_signals/form4_latest.parquet"),
            repo_path("outputs/sec_ownership_signals/form4_latest.csv"),
        ],
        ticker_cols=["ticker", "issuer_ticker"],
        min_tickers=form4_min,
    )
    f13_raw = table_health(
        [repo_path(args.institutional_13f)],
        ticker_cols=["ticker_mapped", "ticker"],
        min_rows=1,
        min_tickers=1,
    )
    f13_signals = signal_health(
        [
            latest_run / "sec_institutional_signals" / "13f_latest.parquet",
            latest_run / "sec_institutional_signals" / "13f_latest.csv",
            latest_run / "sec_institutional_signals" / "signals_latest.parquet",
            latest_run / "sec_institutional_signals" / "signals_latest.csv",
            repo_path("outputs/sec_institutional_signals/13f_latest.parquet"),
            repo_path("outputs/sec_institutional_signals/13f_latest.csv"),
            repo_path("outputs/sec_institutional_signals/signals_latest.parquet"),
            repo_path("outputs/sec_institutional_signals/signals_latest.csv"),
        ],
        ticker_cols=["ticker", "ticker_mapped"],
        min_tickers=f13_min,
    )
    etf_raw = table_health(
        [repo_path(args.etf_holdings)],
        ticker_cols=["holding_ticker", "ticker"],
        available_col="available_from",
        accepted_col="available_from",
        min_rows=1,
        min_tickers=1,
    )
    etf_signals = signal_health(
        [
            latest_run / "etf_thematic_signals" / "signals_latest.parquet",
            latest_run / "etf_thematic_signals" / "signals_latest.csv",
            latest_run / "etf_thematic_signals" / "etf_latest.csv",
            repo_path("outputs/etf_thematic_signals/signals_latest.parquet"),
            repo_path("outputs/etf_thematic_signals/signals_latest.csv"),
            repo_path("outputs/etf_thematic_signals/etf_latest.csv"),
            repo_path("data_pit/etf_holdings/etf_thematic_signals.parquet"),
        ],
        ticker_cols=["ticker", "holding_ticker"],
        min_tickers=etf_min,
    )
    switches = switch_health()
    manifest = evidence_restore_manifest(latest_run)
    selection = selection_impact(latest_run)
    broker = broker_impact(latest_run)

    blockers: list[str] = []
    warnings: list[str] = []
    next_actions: list[str] = []

    if not switches.get("healthy"):
        blockers.append("SEC/ETF/PDA live-score switch is enabled or EngineConfig could not be loaded")
    if bool(args.require_form4) and not (form4_raw["healthy"] and form4_signals["healthy"]):
        blockers.append("Form 4 evidence is not ready: raw PIT data or signal coverage failed")
        next_actions.append("Run or restore sec_form4_daily_refresh and canonical Form 4 shard merge before D5.")
    if bool(args.require_13f) and not (f13_raw["healthy"] and f13_signals["healthy"]):
        blockers.append("13F evidence is not ready: holdings, CUSIP/ticker mapping, or signal coverage failed")
        next_actions.append("Fix 13F CUSIP/ticker mapping, then rerun sec_13f_quarterly_refresh before D1.")
    if bool(args.require_etf) and not (etf_raw["healthy"] and etf_signals["healthy"]):
        blockers.append("ETF holdings evidence is not ready and ETF was required")
        next_actions.append("Run etf_holdings_monthly_refresh or mark ETF unavailable before C5.")
    elif not (etf_raw["healthy"] and etf_signals["healthy"]):
        warnings.append("ETF holdings evidence is not ready; C5 remains blocked, but D1/D5 can proceed")

    for name, item in [
        ("form4_raw", form4_raw),
        ("13f_raw", f13_raw),
        ("etf_raw", etf_raw),
    ]:
        if int(item.get("available_from_before_accepted_at", 0)) > 0:
            blockers.append(f"{name} has available_from before accepted_at")
        if int(item.get("missing_available_from", 0)) > 0:
            blockers.append(f"{name} has missing available_from values")

    if not manifest["exists"]:
        warnings.append("SEC/ETF restore manifest is missing; Drive restore provenance is not documented")

    ready_for_d1 = bool(f13_raw["healthy"] and f13_signals["healthy"] and switches.get("healthy"))
    ready_for_d5 = bool(form4_raw["healthy"] and form4_signals["healthy"] and switches.get("healthy"))
    ready_for_c5 = bool(etf_raw["healthy"] and etf_signals["healthy"] and switches.get("healthy"))
    ready_for_c4 = bool(ready_for_d1 and ready_for_d5 and (ready_for_c5 or not bool(args.require_etf_for_c4)))
    status = "blocked" if blockers else ("warn" if warnings else "ready")
    payload = {
        "schema_version": "evidence-readiness-v1",
        "generated_at_utc": now_utc(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "status": status,
        "ready_for_d1_13f_events": ready_for_d1,
        "ready_for_d5_form4_event_study": ready_for_d5,
        "ready_for_c5_etf_pit": ready_for_c5,
        "ready_for_c4_broker_challenger": ready_for_c4,
        "output_dir": str(output_dir),
        "switches": switches,
        "restore_manifest": manifest,
        "sources": {
            "form4_raw": form4_raw,
            "form4_signals": form4_signals,
            "institutional_13f_holdings": f13_raw,
            "institutional_13f_signals": f13_signals,
            "etf_holdings": etf_raw,
            "etf_signals": etf_signals,
        },
        "impact_audit": {
            "data_health": "see sources",
            "signal_health": {
                "form4_signal_tickers": form4_signals.get("ticker_count", 0),
                "institutional_13f_signal_tickers": f13_signals.get("ticker_count", 0),
                "etf_signal_tickers": etf_signals.get("ticker_count", 0),
            },
            "selection_impact": selection,
            "broker_impact": broker,
        },
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": sorted(set(next_actions)),
    }
    return payload


def render_report(payload: dict[str, Any]) -> str:
    sources = payload.get("sources", {})
    lines = [
        "# Evidence Readiness Audit",
        "",
        f"- status: `{payload.get('status')}`",
        f"- ready_for_d1_13f_events: `{str(payload.get('ready_for_d1_13f_events')).lower()}`",
        f"- ready_for_d5_form4_event_study: `{str(payload.get('ready_for_d5_form4_event_study')).lower()}`",
        f"- ready_for_c5_etf_pit: `{str(payload.get('ready_for_c5_etf_pit')).lower()}`",
        f"- ready_for_c4_broker_challenger: `{str(payload.get('ready_for_c4_broker_challenger')).lower()}`",
        "",
        "## Source Health",
        "",
        "| source | rows | tickers | latest available | healthy |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for name, item in sources.items():
        lines.append(
            "| {name} | {rows} | {tickers} | {latest} | {healthy} |".format(
                name=name,
                rows=item.get("rows", 0),
                tickers=item.get("ticker_count", 0),
                latest=item.get("latest_available_from", ""),
                healthy=str(item.get("healthy")).lower(),
            )
        )
    lines.extend(["", "## Kill Switches", ""])
    switches = payload.get("switches", {})
    lines.append(f"- evidence_fusion_apply_to_live_score: `{switches.get('evidence_fusion_apply_to_live_score')}`")
    lines.append(f"- pda_apply_to_live_score: `{switches.get('pda_apply_to_live_score')}`")
    lines.extend(["", "## Blockers", ""])
    blockers = payload.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- none"])
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings") or []
    lines.extend([f"- {item}" for item in warnings] if warnings else ["- none"])
    impact = payload.get("impact_audit", {})
    selection = impact.get("selection_impact", {}) if isinstance(impact, dict) else {}
    broker = impact.get("broker_impact", {}) if isinstance(impact, dict) else {}
    lines.extend(
        [
            "",
            "## Evidence Impact Audit",
            "",
            f"- evidence_nonzero_ticker_count: `{selection.get('evidence_nonzero_ticker_count', 0)}`",
            f"- selected_evidence_nonzero_ticker_count: `{selection.get('selected_evidence_nonzero_ticker_count', 0)}`",
            f"- selection_impact_confirmed: `{selection.get('selection_impact_confirmed', False)}`",
            f"- broker_impact_status: `{broker.get('status', 'not_evaluated')}`",
            "- rule: nonzero evidence is not promotion evidence without selection and broker impact.",
        ]
    )
    lines.extend(["", "## Next Actions", ""])
    actions = payload.get("next_actions") or []
    lines.extend([f"- {item}" for item in actions] if actions else ["- none"])
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "evidence_health.json", payload)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/evidence_readiness")
    parser.add_argument("--form4-transactions", default="data_pit/sec/form4_transactions.parquet")
    parser.add_argument("--institutional-13f", default="data_pit/sec/institutional_13f_holdings.parquet")
    parser.add_argument("--etf-holdings", default="data_pit/etf_holdings/etf_holdings.parquet")
    parser.add_argument("--min-form4-signal-tickers", type=int, default=300)
    parser.add_argument("--min-13f-signal-tickers", type=int, default=100)
    parser.add_argument("--min-etf-signal-tickers", type=int, default=10)
    parser.add_argument("--require-form4", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-13f", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-etf", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--require-etf-for-c4", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when readiness blockers are present.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    write_outputs(payload, repo_path(args.output_dir))
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    if args.strict and payload.get("blockers"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
