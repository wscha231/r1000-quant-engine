#!/usr/bin/env python3
"""Build a review-only Buffett/Chameleon dual-tempo state audit.

The tool combines exact-close holding risk, durable-quality evidence, broad
market regime, optional factor/residual damage, and selector challenger
freshness.  It never changes a weight or authorizes an order.  In particular,
ROTATE is impossible without both an exact-accepted fundamental break and a
fresh selector-qualified superior challenger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "run287-dual-tempo-policy-v1"
READY_STATUS = "READY_RUN287_DUAL_TEMPO_POLICY_REVIEW_ONLY"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    return {
        "path": str(path), "exists": True, "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def as_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def numeric(value: Any, default: float = np.nan) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) and np.isfinite(float(parsed)) else default


def tracked_text(path: Path, git_ref: str = "HEAD") -> str:
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return ""
    completed = subprocess.run(
        ["git", "show", f"{git_ref}:{relative}"], cwd=ROOT, check=False,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return completed.stdout if completed.returncode == 0 else ""


def market_context(regime_manifest: Path, latest_regime_text: Path) -> dict[str, Any]:
    crisis_state = "UNKNOWN"
    crisis_date = ""
    if regime_manifest.is_file():
        payload = read_json(regime_manifest)
        current = payload.get("current_state") or {}
        crisis_state = str(current.get("crisis_state") or current.get("raw_state") or "UNKNOWN").upper()
        crisis_date = str(current.get("date") or payload.get("valuation_price_cutoff_date") or "")
    text = tracked_text(latest_regime_text)
    text_source = "local_file" if latest_regime_text.is_file() else ("git_head_blob" if text else "missing")
    label_match = re.search(r"Regime label:\s*([^\r\n]+)", text, re.IGNORECASE)
    date_match = re.search(r"Snapshot\s+[—-]\s+(\d{4}-\d{2}-\d{2})", text)
    above_match = re.search(r"SPY\s*>\s*200MA:\s*(True|False)", text, re.IGNORECASE)
    vix_match = re.search(r"VIX level:\s*([0-9.]+)", text, re.IGNORECASE)
    label = label_match.group(1).strip().lower() if label_match else "unknown"
    latest_date = date_match.group(1) if date_match else ""
    spy_above = above_match.group(1).lower() == "true" if above_match else None
    vix = numeric(vix_match.group(1)) if vix_match else np.nan
    defensive_labels = {"bear", "deep_bear", "risk_off", "crisis", "defensive"}
    warning_labels = {"watch", "neutral", "transition", "caution"}
    if crisis_state in {"RED", "ORANGE", "CRISIS"} or label in defensive_labels or spy_above is False:
        state = "DEFENSIVE"
    elif crisis_state == "WATCH" or label in warning_labels:
        state = "WATCH"
    elif crisis_state == "GREEN" and label in {"normal", "bull", "strong_bull"} and spy_above is not False:
        state = "BENIGN"
    elif label in {"normal", "bull", "strong_bull"} and spy_above is not False:
        state = "BENIGN"
    else:
        state = "DATA_INSUFFICIENT"
    dates = [value for value in (crisis_date, latest_date) if value]
    return {
        "market_state": state,
        "market_as_of_date": max(dates) if dates else "",
        "crisis_state": crisis_state,
        "crisis_as_of_date": crisis_date,
        "latest_regime_label": label,
        "latest_regime_as_of_date": latest_date,
        "spy_above_ma200": spy_above,
        "vix_level": vix,
        "latest_regime_source": text_source,
        "latest_regime_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
    }


def quality_support(row: Mapping[str, Any]) -> tuple[bool, str]:
    exact = numeric(row.get("exact_debt_component_coverage"), 0.0) == 1.0
    core = numeric(row.get("core_quality_coverage"), 0.0) >= 0.55
    economic = numeric(row.get("economic_durability_score")) >= 0.20
    balance = numeric(row.get("balance_resilience_score")) >= 0.0
    future = any(as_bool(row.get(name)) for name in (
        "pit_future_row", "future_fundamental_row", "future_feature_row"
    ))
    reasons = []
    if not exact:
        reasons.append("exact_debt_incomplete")
    if not core:
        reasons.append("core_quality_incomplete")
    if not economic:
        reasons.append("economic_durability_below_gate")
    if not balance:
        reasons.append("balance_resilience_below_gate")
    if future:
        reasons.append("future_row_detected")
    return not reasons, "|".join(reasons) if reasons else "durable_quality_gate_pass"


def fundamental_break_map(path: Path, as_of_available: pd.Timestamp) -> dict[tuple[str, str], bool]:
    if not path.is_file():
        return {}
    frame = pd.read_csv(path, low_memory=False)
    required = {"ticker", "break_status", "available_from"}
    if not required.issubset(frame.columns):
        raise ValueError(f"fundamental break file missing columns: {sorted(required - set(frame.columns))}")
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    if "portfolio_kind" not in frame.columns:
        frame["portfolio_kind"] = "all"
    else:
        frame["portfolio_kind"] = frame["portfolio_kind"].astype(str).str.lower().str.strip()
    frame["available_exact"] = pd.to_datetime(frame["available_from"], errors="coerce", utc=True)
    frame = frame.loc[
        frame["break_status"].astype(str).eq("CONFIRMED_EXACT_ACCEPTED_BREAK")
        & frame["available_exact"].notna()
        & frame["available_exact"].le(as_of_available)
    ]
    return {
        (row.portfolio_kind, row.ticker): True
        for row in frame.itertuples(index=False)
    }


def selector_context(
    current: pd.DataFrame, risk_as_of: str, held: set[tuple[str, str]]
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    frame = current.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["portfolio_kind"] = frame["portfolio_kind"].astype(str).str.lower().str.strip()
    if "scenario" in frame.columns:
        strict = frame["scenario"].astype(str).eq("strict_registered_current")
        frame = frame.loc[strict].copy()
    frame["decision_date_clean"] = pd.to_datetime(frame["decision_date"], errors="coerce").dt.date.astype(str)
    result: dict[str, dict[str, Any]] = {}
    incumbents: dict[tuple[str, str], dict[str, Any]] = {}
    for portfolio, group in frame.groupby("portfolio_kind", sort=False):
        decision_date = max((value for value in group["decision_date_clean"] if value != "NaT"), default="")
        candidates = group.loc[
            group["selector_selected"].map(as_bool)
            & ~group["ticker"].map(lambda ticker: (portfolio, ticker) in held)
        ].copy()
        candidates["rank_clean"] = pd.to_numeric(candidates.get("final_rank"), errors="coerce")
        candidates = candidates.sort_values(["rank_clean", "ticker"], na_position="last")
        best = candidates.iloc[0] if not candidates.empty else None
        result[portfolio] = {
            "selector_decision_date": decision_date,
            "selector_fresh_for_risk": bool(decision_date and decision_date >= risk_as_of),
            "challenger_ticker": str(best["ticker"]) if best is not None else "",
            "challenger_rank": numeric(best.get("final_rank")) if best is not None else np.nan,
            "challenger_selector_selected": best is not None,
        }
        for incumbent in group.loc[
            group["ticker"].map(lambda ticker: (portfolio, ticker) in held)
        ].to_dict("records"):
            incumbents[(portfolio, str(incumbent["ticker"]))] = {
                "incumbent_rank": numeric(incumbent.get("final_rank")),
                "incumbent_selector_selected": as_bool(incumbent.get("selector_selected")),
            }
    return result, incumbents


def recent_recovery(history: pd.DataFrame, portfolio: str, ticker: str, current_clear: bool) -> bool:
    if history.empty or not current_clear:
        return False
    prior = history.loc[
        history["portfolio_kind"].astype(str).eq(portfolio)
        & history["ticker"].astype(str).eq(ticker)
    ].sort_values("as_of_date")
    if prior.empty or str(prior.iloc[-1].get("tempo_state")) not in {"DEFEND", "ROTATE", "WATCH"}:
        return False
    recent = prior.tail(10)
    had_defense = recent["tempo_state"].astype(str).isin({"DEFEND", "ROTATE"}).any()
    clear_streak = 0
    for row in reversed(prior.to_dict("records")):
        clear = (
            str(row.get("risk_state")) == "NORMAL"
            and as_bool(row.get("quality_supports_compound"))
            and str(row.get("market_state")) == "BENIGN"
        )
        if not clear:
            break
        clear_streak += 1
    return bool(had_defense and clear_streak + 1 >= 2)


def classify_state(
    row: Mapping[str, Any], history: pd.DataFrame
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    risk_state = str(row.get("risk_state") or "DATA_INSUFFICIENT").upper()
    quality_known = as_bool(row.get("quality_evidence_present"))
    quality_ok = as_bool(row.get("quality_supports_compound"))
    market_state = str(row.get("market_state") or "DATA_INSUFFICIENT")
    factor_member = as_bool(row.get("factor_member"))
    factor_state = str(row.get("factor_risk_state") or "NOT_AVAILABLE").upper()
    residual_alert = as_bool(row.get("sector_residual_alert"))
    fundamental_break = as_bool(row.get("exact_fundamental_break"))
    fresh_challenger = (
        as_bool(row.get("selector_fresh_for_risk"))
        and as_bool(row.get("challenger_selector_selected"))
        and as_bool(row.get("challenger_superior"))
    )
    if risk_state == "DATA_INSUFFICIENT" or not quality_known:
        reasons.append("risk_or_quality_data_insufficient")
        return "DATA_INSUFFICIENT", reasons
    if (risk_state == "ALERT" or residual_alert) and fundamental_break and fresh_challenger:
        reasons.extend(["defend_evidence", "exact_fundamental_break", "fresh_superior_challenger"])
        return "ROTATE", reasons
    if risk_state == "ALERT" or residual_alert:
        reasons.append("security_alert" if risk_state == "ALERT" else "factor_residual_alert")
        if not fundamental_break:
            reasons.append("rotate_blocked_no_exact_fundamental_break")
        if not fresh_challenger:
            reasons.append("rotate_blocked_no_fresh_challenger")
        return "DEFEND", reasons
    current_clear = risk_state == "NORMAL" and quality_ok and market_state == "BENIGN" and not (
        factor_member and factor_state in {"WATCH", "ALERT", "DEFENSIVE"}
    )
    if recent_recovery(history, str(row.get("portfolio_kind")), str(row.get("ticker")), current_clear):
        reasons.append("two_clear_observations_after_recent_defense")
        return "REBUILD", reasons
    if risk_state == "WATCH":
        reasons.append("security_watch")
    if factor_member and factor_state in {"WATCH", "ALERT", "DEFENSIVE"}:
        reasons.append("factor_watch")
    if market_state != "BENIGN":
        reasons.append("market_not_benign")
    if not quality_ok:
        reasons.append(str(row.get("quality_gate_reasons") or "durable_quality_incomplete"))
    if reasons:
        return "WATCH", reasons
    return "COMPOUND_HOLD", ["risk_normal_durable_quality_complete_market_benign"]


def portfolio_states(detail: pd.DataFrame, contract: Mapping[str, Any]) -> pd.DataFrame:
    config = contract.get("portfolio_review") or {}
    rows: list[dict[str, Any]] = []
    for portfolio, group in detail.groupby("portfolio_kind", sort=True):
        count = len(group)
        alerts = int(group["tempo_state"].isin({"DEFEND", "ROTATE"}).sum())
        watches = int(group["tempo_state"].eq("WATCH").sum())
        rotates = int(group["tempo_state"].eq("ROTATE").sum())
        weights = pd.to_numeric(group["current_weight"], errors="coerce").fillna(0.0)
        gross = float(weights.sum())
        alert_weight = float(weights[group["tempo_state"].isin({"DEFEND", "ROTATE"})].sum())
        alert_fraction = alerts / count if count else 0.0
        small_concentrated = portfolio == "concentrated" and count <= int(
            config.get("small_concentrated_position_count_max", 5)
        ) and alerts >= int(config.get("small_concentrated_alert_count_min", 2))
        if rotates:
            state = "ROTATE"
        elif alert_fraction >= float(config.get("defend_alert_fraction_min", 1.0 / 3.0)) or small_concentrated:
            state = "DEFEND"
        elif alerts or watches or not bool(group["tempo_state"].eq("COMPOUND_HOLD").all()):
            state = "WATCH"
        else:
            state = "COMPOUND_HOLD"
        rows.append({
            "as_of_date": str(group["as_of_date"].max()),
            "portfolio_kind": portfolio,
            "portfolio_tempo_state": state,
            "position_count": count,
            "compound_hold_count": int(group["tempo_state"].eq("COMPOUND_HOLD").sum()),
            "watch_count": watches,
            "defend_count": int(group["tempo_state"].eq("DEFEND").sum()),
            "rotate_count": rotates,
            "rebuild_count": int(group["tempo_state"].eq("REBUILD").sum()),
            "data_insufficient_count": int(group["tempo_state"].eq("DATA_INSUFFICIENT").sum()),
            "defend_or_rotate_fraction": alert_fraction,
            "gross_weight": gross,
            "defend_or_rotate_weight": alert_weight,
            "defend_or_rotate_weight_fraction": alert_weight / gross if gross > 0 else np.nan,
            "orders_generated": False,
            "target_books_mutated": False,
            "cash_policy_mutated": False,
        })
    return pd.DataFrame(rows)


def append_history(path: Path, current: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "as_of_date", "available_from", "portfolio_kind", "ticker", "tempo_state",
        "risk_state", "quality_supports_compound", "market_state", "factor_risk_state",
        "sector_residual_alert", "exact_fundamental_break", "selector_fresh_for_risk",
        "challenger_ticker", "challenger_superior", "reason_codes",
    ]
    new = current[columns].copy()
    if path.is_file():
        old = pd.read_csv(path, low_memory=False)
        keys = ["as_of_date", "portfolio_kind", "ticker"]
        overlap = old.merge(new, on=keys, how="inner", suffixes=("_old", "_new"))
        for column in [c for c in columns if c not in keys]:
            left = overlap[f"{column}_old"].fillna("").astype(str)
            right = overlap[f"{column}_new"].fillna("").astype(str)
            if not left.equals(right):
                raise ValueError(f"same-date dual-tempo history conflict: {column}")
        combined = pd.concat([old, new], ignore_index=True).drop_duplicates(keys, keep="first")
    else:
        combined = new
    combined = combined.sort_values(["as_of_date", "portfolio_kind", "ticker"]).reset_index(drop=True)
    combined.to_csv(path, index=False, lineterminator="\n")
    return combined


def build(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = repo_path(args.contract)
    risk_path = repo_path(args.risk_watch)
    quality_path = repo_path(args.quality_universe)
    current_path = repo_path(args.current_status)
    regime_path = repo_path(args.regime_manifest)
    latest_regime_path = repo_path(args.latest_regime_text)
    factor_summary_path = repo_path(args.factor_summary) if str(args.factor_summary or "").strip() else Path()
    residual_path = repo_path(args.factor_residuals) if str(args.factor_residuals or "").strip() else Path()
    breaks_path = repo_path(args.fundamental_breaks) if str(args.fundamental_breaks or "").strip() else Path()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contract = read_json(contract_path)
    risk = pd.read_csv(risk_path, low_memory=False)
    quality = pd.read_csv(quality_path, low_memory=False)
    current = pd.read_parquet(current_path)
    required_risk = {"as_of_date", "available_from", "portfolio_kind", "ticker", "current_weight", "risk_state"}
    missing = required_risk - set(risk.columns)
    if missing:
        raise ValueError(f"risk watch missing columns: {sorted(missing)}")
    risk["portfolio_kind"] = risk["portfolio_kind"].astype(str).str.lower().str.strip()
    risk["ticker"] = risk["ticker"].astype(str).str.upper().str.strip()
    risk_as_of = str(pd.to_datetime(risk["as_of_date"], errors="raise").max().date())
    available = pd.to_datetime(risk["available_from"], errors="raise", utc=True).max()
    quality["ticker"] = quality["ticker"].astype(str).str.upper().str.strip()
    quality = quality.sort_values("ticker").drop_duplicates("ticker", keep="last")
    quality_map = quality.set_index("ticker").to_dict("index")
    held = set(zip(risk["portfolio_kind"], risk["ticker"]))
    selectors, incumbents = selector_context(current, risk_as_of, held)
    market = market_context(regime_path, latest_regime_path)
    factor_summary = read_json(factor_summary_path) if factor_summary_path.is_file() else {}
    factor_state = str(factor_summary.get("factor_risk_state") or "NOT_AVAILABLE").upper()
    factor_as_of = str(factor_summary.get("as_of_date") or "")
    factor_fresh = bool(factor_as_of and factor_as_of >= risk_as_of)
    residuals: dict[str, dict[str, Any]] = {}
    if residual_path.is_file():
        residual = pd.read_csv(residual_path, low_memory=False)
        residual["ticker"] = residual["ticker"].astype(str).str.upper().str.strip()
        residuals = residual.drop_duplicates("ticker", keep="last").set_index("ticker").to_dict("index")
    breaks = fundamental_break_map(breaks_path, available)
    history_path = output_dir / "state_history.csv"
    history = pd.read_csv(history_path, low_memory=False) if history_path.is_file() else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for held_row in risk.to_dict("records"):
        portfolio = str(held_row["portfolio_kind"])
        ticker = str(held_row["ticker"])
        quality_row = quality_map.get(ticker)
        quality_ok, quality_reasons = quality_support(quality_row or {})
        selector = selectors.get(portfolio, {})
        incumbent = incumbents.get((portfolio, ticker), {})
        residual = residuals.get(ticker, {})
        exact_break = breaks.get((portfolio, ticker), breaks.get(("all", ticker), False))
        row = {
            **held_row,
            **market,
            "quality_evidence_present": quality_row is not None,
            "quality_supports_compound": quality_ok if quality_row is not None else False,
            "quality_gate_reasons": quality_reasons if quality_row is not None else "quality_identity_missing",
            "candidate_status": str((quality_row or {}).get("candidate_status") or "NOT_AVAILABLE"),
            "core_quality_coverage": numeric((quality_row or {}).get("core_quality_coverage")),
            "balance_resilience_score": numeric((quality_row or {}).get("balance_resilience_score")),
            "economic_durability_score": numeric((quality_row or {}).get("economic_durability_score")),
            "market_confirmation_score": numeric((quality_row or {}).get("market_confirmation_score_clean")),
            "exact_debt_component_coverage": numeric((quality_row or {}).get("exact_debt_component_coverage"), 0.0),
            "factor_risk_state": (
                factor_state if ticker in residuals and factor_fresh
                else ("DATA_STALE" if ticker in residuals else "NOT_APPLICABLE")
            ),
            "factor_as_of_date": factor_as_of,
            "factor_fresh_for_risk": factor_fresh,
            "factor_member": ticker in residuals and factor_fresh,
            "sector_residual_alert": factor_fresh and as_bool(residual.get("sector_residual_alert")),
            "factor_residual_1d": numeric(residual.get("soxx_residual_1d")),
            "exact_fundamental_break": exact_break,
            **selector,
            **incumbent,
            "portfolio_action_authorized": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "cash_policy_mutated": False,
        }
        challenger_rank = numeric(row.get("challenger_rank"))
        incumbent_rank = numeric(row.get("incumbent_rank"))
        row["challenger_superior"] = bool(
            as_bool(row.get("challenger_selector_selected"))
            and (
                not np.isfinite(incumbent_rank)
                or not as_bool(row.get("incumbent_selector_selected"))
                or (np.isfinite(challenger_rank) and challenger_rank < incumbent_rank)
            )
        )
        state, reasons = classify_state(row, history)
        row["tempo_state"] = state
        row["reason_codes"] = "|".join(reasons)
        row["review_cadence"] = (contract.get("response_tempo") or {}).get(state, "review_only")
        row["incremental_buy_authorized"] = False
        row["sell_or_rotate_authorized"] = False
        rows.append(row)
    detail = pd.DataFrame(rows).sort_values(["portfolio_kind", "tempo_state", "ticker"]).reset_index(drop=True)
    portfolios = portfolio_states(detail, contract)
    history = append_history(history_path, detail)
    detail.to_csv(output_dir / "security_tempo_state.csv", index=False, lineterminator="\n")
    portfolios.to_csv(output_dir / "portfolio_tempo_state.csv", index=False, lineterminator="\n")
    report_lines = [
        "# Run287 dual-tempo policy audit", "", f"- as_of_date: `{risk_as_of}`",
        f"- market_state: `{market['market_state']}`",
        f"- factor_state: `{factor_state}`", "- review_only: `true`", "",
        "## Portfolio states", "",
    ]
    for row in portfolios.itertuples(index=False):
        report_lines.append(
            f"- {row.portfolio_kind}: `{row.portfolio_tempo_state}` "
            f"(compound={row.compound_hold_count}, watch={row.watch_count}, "
            f"defend={row.defend_count}, rotate={row.rotate_count})"
        )
    report_lines.extend(["", "No row authorizes an order, target change, cash change, or production activation.", ""])
    (output_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")
    state_counts = detail["tempo_state"].value_counts().to_dict()
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "as_of_date": risk_as_of,
        "available_from": pd.Timestamp(available).isoformat(),
        "market_context": market,
        "factor_risk_state": factor_state,
        "factor_as_of_date": factor_as_of,
        "factor_fresh_for_risk": factor_fresh,
        "security_state_counts": {str(k): int(v) for k, v in state_counts.items()},
        "portfolio_states": portfolios.set_index("portfolio_kind")["portfolio_tempo_state"].to_dict(),
        "rotate_count": int(detail["tempo_state"].eq("ROTATE").sum()),
        "rotate_blocked_no_exact_break_count": int(detail["reason_codes"].str.contains("no_exact_fundamental_break").sum()),
        "rotate_blocked_no_fresh_challenger_count": int(detail["reason_codes"].str.contains("no_fresh_challenger").sum()),
        "history_row_count": int(len(history)),
        "source_inputs": {
            "contract": fingerprint(contract_path), "risk_watch": fingerprint(risk_path),
            "quality_universe": fingerprint(quality_path), "current_status": fingerprint(current_path),
            "regime_manifest": fingerprint(regime_path), "latest_regime_text": fingerprint(latest_regime_path),
            "factor_summary": fingerprint(factor_summary_path), "factor_residuals": fingerprint(residual_path),
            "fundamental_breaks": fingerprint(breaks_path),
        },
        "advisory_only": True,
        "model_mutated": False,
        "score_mutated": False,
        "rank_mutated": False,
        "selector_mutated": False,
        "target_books_mutated": False,
        "cash_policy_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="docs/run287_dual_tempo_policy_contract_v1.json")
    parser.add_argument("--risk-watch", required=True)
    parser.add_argument("--quality-universe", required=True)
    parser.add_argument("--current-status", required=True)
    parser.add_argument("--regime-manifest", default="")
    parser.add_argument("--latest-regime-text", default="cloud_results/paper_runs/latest_regime.txt")
    parser.add_argument("--factor-summary", default="")
    parser.add_argument("--factor-residuals", default="")
    parser.add_argument("--fundamental-breaks", default="")
    parser.add_argument("--output-dir", default="outputs/run287_dual_tempo_policy")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(build(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
