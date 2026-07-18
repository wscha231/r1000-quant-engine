#!/usr/bin/env python3
"""Audit why research candidates do or do not reach Run287 target books.

The audit keeps research intake separate from the frozen operating universe. It
joins current universe coverage, latest scoring gates, a research overlay,
operating target books, historical selector rejections, local price caches and
accepted-time SEC indexes. Selected-only artifacts never receive an invented
causal rejection reason.

This tool is diagnostic and append-only. It does not score a new security,
change a universe, generate a target book, run a backtest/fullrun, or create an
order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


SCHEMA_VERSION = "run287-candidate-evaluation-funnel-v2"
DEFAULT_INTAKE = "docs/run287_candidate_evaluation_intake_20260715.csv"
DEFAULT_UNIVERSE = "outputs/free_historical_data_coverage/universe_coverage.csv"
DEFAULT_SCORED = (
    "outputs/run287_scored_latest_refresh_20260714_close_20260713_v2/scored_latest.csv"
)
DEFAULT_OVERLAY_RANKED = (
    "outputs/free_data_selection_overlay_scored_20260713_v2/ranked_universe.csv"
)
DEFAULT_OVERLAY_SELECTED = (
    "outputs/free_data_selection_overlay_scored_20260713_v2/selected_candidates.csv"
)
DEFAULT_MAIN = (
    "outputs/daily_operating_selection_refresh_29305572139/outputs/reports/"
    "operating_main_target_book.csv"
)
DEFAULT_CONCENTRATED = (
    "outputs/daily_operating_selection_refresh_29305572139/outputs/reports/"
    "operating_concentrated_target_book.csv"
)
DEFAULT_REJECTIONS = (
    "outputs/run287_selector_reproduction_20260711/attempt_05/reproduced/"
    "rejected_by_reason.csv"
)
DEFAULT_CURRENT_ADVISORY_REJECTIONS = (
    "outputs/run287_current_selector_no_write_20260714_close_20260713_v2/"
    "advisory_rejection_audit.csv"
)
DEFAULT_CURRENT_ADVISORY_PROJECTION = (
    "outputs/run287_current_selector_no_write_20260714_close_20260713_v2/"
    "advisory_policy_projection.csv"
)
DEFAULT_COMPANY_TICKERS = "data_raw/sec/company_tickers.json"
DEFAULT_OUTPUT = "outputs/run287_candidate_evaluation_funnel_20260715"
CANONICAL_PRICE_FLOOR = pd.Timestamp("2019-05-09")
FOREIGN_FORMS = {"20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A"}
DOMESTIC_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def clean_ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    return "" if text == "NAN" else text


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": ""}
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def read_table(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = out["ticker"].map(clean_ticker)
    return out.loc[out["ticker"].ne("")].copy()


def latest_rows(frame: pd.DataFrame) -> pd.DataFrame:
    out = normalize_frame(frame)
    if out.empty:
        return out
    for column in ("rebalance_date", "feature_date", "decision_date"):
        if column not in out.columns:
            continue
        dates = pd.to_datetime(out[column], errors="coerce")
        if dates.notna().any():
            out = out.loc[dates.eq(dates.max())].copy()
            break
    return out.drop_duplicates("ticker", keep="first")


def ticker_map(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out = normalize_frame(frame)
    if out.empty:
        return {}
    return {
        clean_ticker(row.get("ticker")): row
        for row in out.drop_duplicates("ticker", keep="first").to_dict("records")
    }


def company_ticker_map(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.values() if isinstance(payload, dict) else []
    return {
        clean_ticker(row.get("ticker")): {
            "identity_cik10": str(int(row.get("cik_str"))).zfill(10),
            "identity_name": str(row.get("title") or ""),
        }
        for row in rows
        if clean_ticker(row.get("ticker")) and str(row.get("cik_str") or "").isdigit()
    }


def target_tickers(path: Path) -> set[str]:
    frame = latest_rows(read_table(path))
    if frame.empty:
        return set()
    if "weight" in frame.columns:
        weights = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
        frame = frame.loc[weights.gt(1e-10)].copy()
    return set(frame["ticker"].map(clean_ticker)) - {"CASH"}


def rejection_map(path: Path, candidates: set[str]) -> dict[str, dict[str, Any]]:
    frame = normalize_frame(read_table(path))
    if frame.empty:
        return {}
    frame = frame.loc[frame["ticker"].isin(candidates)].copy()
    if frame.empty:
        return {}
    frame["_date"] = pd.to_datetime(frame.get("rebalance_date"), errors="coerce")
    result: dict[str, dict[str, Any]] = {}
    for ticker, group in frame.groupby("ticker", sort=True):
        if group["_date"].notna().any():
            group = group.loc[group["_date"].eq(group["_date"].max())].copy()
        parts: list[str] = []
        for row in group.to_dict("records"):
            portfolio = str(row.get("portfolio_kind") or "unknown")
            variant = str(row.get("variant_id") or "")
            reason = str(row.get("rejection_reason") or "")
            parts.append(f"{portfolio}:{variant}:{reason}")
        result[str(ticker)] = {
            "historical_rejection_asof": (
                group["_date"].max().date().isoformat()
                if group["_date"].notna().any()
                else ""
            ),
            "historical_rejection_reasons": "|".join(sorted(set(parts))),
            "historical_rejection_is_current_causal": False,
        }
    return result


def current_advisory_map(
    rejection_path: Path,
    projection_path: Path,
    candidates: set[str],
) -> dict[str, dict[str, Any]]:
    """Summarize the same-date no-write selector without calling it operating causal."""
    rejected = normalize_frame(read_table(rejection_path))
    projected = normalize_frame(read_table(projection_path))
    result: dict[str, dict[str, Any]] = {}

    if not rejected.empty:
        rejected = rejected.loc[rejected["ticker"].isin(candidates)].copy()
        date_col = "date" if "date" in rejected.columns else "rebalance_date"
        rejected["_date"] = pd.to_datetime(rejected.get(date_col), errors="coerce")
        if rejected["_date"].notna().any():
            rejected = rejected.loc[rejected["_date"].eq(rejected["_date"].max())].copy()
        for ticker, group in rejected.groupby("ticker", sort=True):
            reasons: list[str] = []
            for row in group.to_dict("records"):
                reasons.append(
                    ":".join(
                        [
                            str(row.get("portfolio_kind") or "unknown"),
                            str(row.get("scenario") or "unknown"),
                            str(row.get("rejection_reason") or "unknown"),
                        ]
                    )
                )
            result[str(ticker)] = {
                "current_advisory_selector_evaluated": True,
                "current_advisory_selected": False,
                "current_advisory_selected_scenarios": "",
                "current_advisory_rejection_reasons": "|".join(sorted(set(reasons))),
                "current_advisory_reason_available": True,
                "current_advisory_is_operating_causal": False,
            }

    if not projected.empty:
        projected = projected.loc[projected["ticker"].isin(candidates)].copy()
        date_col = "date" if "date" in projected.columns else "rebalance_date"
        projected["_date"] = pd.to_datetime(projected.get(date_col), errors="coerce")
        if projected["_date"].notna().any():
            projected = projected.loc[projected["_date"].eq(projected["_date"].max())].copy()
        if "advisory_weight" in projected.columns:
            weights = pd.to_numeric(projected["advisory_weight"], errors="coerce").fillna(0.0)
            projected = projected.loc[weights.gt(1e-10)].copy()
        for ticker, group in projected.groupby("ticker", sort=True):
            scenarios = sorted(
                {
                    f"{row.get('portfolio_kind', 'unknown')}:{row.get('scenario', 'unknown')}"
                    for row in group.to_dict("records")
                }
            )
            record = result.setdefault(str(ticker), {})
            record.update(
                {
                    "current_advisory_selector_evaluated": True,
                    "current_advisory_selected": True,
                    "current_advisory_selected_scenarios": "|".join(scenarios),
                    "current_advisory_reason_available": True,
                    "current_advisory_is_operating_causal": False,
                }
            )
            record.setdefault("current_advisory_rejection_reasons", "")
    return result


def price_file_map(roots: Iterable[Path], tickers: set[str]) -> dict[str, list[Path]]:
    file_to_ticker = {px_cache_name(ticker): ticker for ticker in tickers}
    result: dict[str, list[Path]] = {ticker: [] for ticker in tickers}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.parquet"):
            ticker = file_to_ticker.get(path.name)
            if ticker:
                result[ticker].append(path)
    return result


def is_under(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def price_audit(
    paths: list[Path],
    as_of: pd.Timestamp,
    authoritative_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    for path in paths:
        try:
            frame = pd.read_parquet(path)
            dates = pd.to_datetime(frame.index, errors="coerce").dropna()
        except Exception:
            continue
        if len(dates) == 0:
            continue
        start = pd.Timestamp(dates.min()).tz_localize(None).normalize()
        end = pd.Timestamp(dates.max()).tz_localize(None).normalize()
        record = {
            "price_history_path": str(path),
            "price_history_rows": int(len(frame)),
            "price_history_start": start.date().isoformat(),
            "price_history_end": end.date().isoformat(),
            "price_history_span_days": int((end - start).days),
            "price_history_authoritative_full_fetch": is_under(path, authoritative_roots),
        }
        key = (
            record["price_history_span_days"],
            record["price_history_rows"],
            record["price_history_end"],
            record["price_history_authoritative_full_fetch"],
        )
        if best is None or key > best["_key"]:
            best = {**record, "_key": key}
    if best is None:
        return {
            "price_history_path": "",
            "price_history_rows": 0,
            "price_history_start": "",
            "price_history_end": "",
            "price_history_span_days": 0,
            "price_history_authoritative_full_fetch": False,
            "price_history_status": "MISSING_LOCAL_PRICE_HISTORY",
            "price_backfill_required": True,
            "canonical_7y_price_eligible": False,
        }
    best.pop("_key", None)
    start = pd.Timestamp(best["price_history_start"])
    end = pd.Timestamp(best["price_history_end"])
    if end < as_of - pd.Timedelta(days=7):
        status = "PRICE_HISTORY_STALE"
        backfill_required = True
    elif start > CANONICAL_PRICE_FLOOR:
        if best["price_history_authoritative_full_fetch"]:
            status = "FULL_AVAILABLE_HISTORY_SHORT_LISTING"
            backfill_required = False
        else:
            status = "HISTORY_SHORTER_THAN_CANONICAL_WINDOW"
            backfill_required = True
    else:
        status = "CANONICAL_7Y_PRICE_READY"
        backfill_required = False
    return {
        **best,
        "price_history_status": status,
        "price_backfill_required": backfill_required,
        "canonical_7y_price_eligible": start <= CANONICAL_PRICE_FLOOR,
    }


def load_sec_indexes(paths: Iterable[Path], candidates: set[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = normalize_frame(read_table(path))
        if frame.empty:
            continue
        frame = frame.loc[frame["ticker"].isin(candidates)].copy()
        if not frame.empty:
            frame["_source_path"] = str(path)
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if "accession_number" in out.columns:
        out = out.drop_duplicates(["ticker", "accession_number"], keep="last")
    return out


def sec_map(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for ticker, group in frame.groupby("ticker", sort=True):
        accepted = pd.to_datetime(group.get("accepted_at"), errors="coerce", utc=True)
        forms = sorted(set(group.get("form_type", pd.Series(dtype=str)).astype(str).str.upper()))
        form_set = set(forms)
        exact = int(accepted.notna().sum())
        if form_set & FOREIGN_FORMS:
            route = "FOREIGN_ACCEPTED_TIME_ROUTE"
        elif form_set & DOMESTIC_FORMS:
            route = "DOMESTIC_ACCEPTED_TIME_ROUTE"
        else:
            route = "UNCLASSIFIED_SEC_ROUTE"
        out[str(ticker)] = {
            "sec_history_rows": int(len(group)),
            "sec_history_first_accepted": accepted.min().isoformat() if accepted.notna().any() else "",
            "sec_history_last_accepted": accepted.max().isoformat() if accepted.notna().any() else "",
            "sec_exact_acceptance_rows": exact,
            "sec_exact_acceptance_ratio": float(exact / len(group)) if len(group) else 0.0,
            "sec_forms": "|".join(forms),
            "sec_route_status": route,
            "sec_backfill_required": not (len(group) > 0 and exact == len(group)),
        }
    return out


def score_date(frame: pd.DataFrame) -> str:
    for column in ("rebalance_date", "feature_date"):
        if column in frame.columns:
            dates = pd.to_datetime(frame[column], errors="coerce").dropna()
            if not dates.empty:
                return pd.Timestamp(dates.max()).date().isoformat()
    return ""


def choose_exclusion(record: dict[str, Any]) -> tuple[str, str]:
    if record["selected_main_current"] or record["selected_concentrated_current"]:
        return "SELECTED_CURRENT_TARGET", "No exclusion; retain normal portfolio rules."
    if not record["in_frozen_universe"]:
        return (
            "RESEARCH_CONTEXT_ONBOARDING_REQUIRED",
            "Build research-only identity, price, fundamental and filing context; do not mutate the operating universe.",
        )
    if not record["in_latest_score"]:
        return "CURRENT_CONTEXT_BUILD_REQUIRED", "Repair the frozen-universe feature context before ranking."
    if not record["ranking_eligible"]:
        return (
            "CANDIDATE_GATE_REJECTED",
            "Keep the gate fixed; identify missing/failed components and re-evaluate only after source coverage improves.",
        )
    if record["current_advisory_selected"]:
        return (
            "CURRENT_ADVISORY_SELECTED_OPERATING_DIVERGENCE",
            "The same-date no-write selector selected this name, but the operating book did not; reconcile selector inputs and provenance before any promotion.",
        )
    if record["current_advisory_rejection_reasons"]:
        return (
            "CURRENT_ADVISORY_REJECTED",
            "Use the same-date advisory rejection as diagnostic evidence only; it is not the causal operating-book rejection ledger.",
        )
    if record["overlay_top_n"]:
        return (
            "SELECTOR_CAUSE_NOT_IDENTIFIABLE_FROM_SELECTED_ONLY_ARTIFACT",
            "Archive the exact same-date selector input and per-candidate rejection ledger; do not infer rejection from target holdings.",
        )
    if record["in_overlay_ranked"]:
        return (
            "RESEARCH_OVERLAY_BELOW_CUTOFF",
            "Continue full-universe ranking; missing evidence stays neutral and no manual promotion is allowed.",
        )
    return (
        "OPERATING_SELECTOR_NOT_SELECTED",
        "Preserve the selector and archive a complete same-date candidate funnel before changing any rule.",
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    paths = {
        "intake": repo_path(args.intake),
        "universe": repo_path(args.universe),
        "scored": repo_path(args.scored),
        "overlay_ranked": repo_path(args.overlay_ranked),
        "overlay_selected": repo_path(args.overlay_selected),
        "main_target": repo_path(args.main_target),
        "concentrated_target": repo_path(args.concentrated_target),
        "historical_rejections": repo_path(args.historical_rejections),
        "current_advisory_rejections": repo_path(args.current_advisory_rejections),
        "current_advisory_projection": repo_path(args.current_advisory_projection),
        "company_tickers": repo_path(args.company_tickers),
    }
    required = ("intake", "universe", "scored")
    missing = [name for name in required if not paths[name].is_file()]
    if missing:
        raise FileNotFoundError(f"missing required inputs: {','.join(missing)}")

    intake = normalize_frame(read_table(paths["intake"]))
    if intake.empty:
        raise ValueError("candidate intake is empty")
    if intake["ticker"].duplicated().any():
        raise ValueError("candidate intake contains duplicate tickers")
    for column in ("intake_promotes_universe", "intake_promotes_portfolio"):
        if column in intake.columns and intake[column].map(truthy).any():
            raise ValueError(f"research intake cannot promote state: {column}")

    candidates = set(intake["ticker"])
    universe = ticker_map(read_table(paths["universe"]))
    scored_frame = latest_rows(read_table(paths["scored"]))
    scored = ticker_map(scored_frame)
    overlay_ranked = ticker_map(latest_rows(read_table(paths["overlay_ranked"])))
    overlay_selected = set(latest_rows(read_table(paths["overlay_selected"])).get("ticker", pd.Series(dtype=str)))
    main = target_tickers(paths["main_target"])
    concentrated = target_tickers(paths["concentrated_target"])
    rejections = rejection_map(paths["historical_rejections"], candidates)
    current_advisory = current_advisory_map(
        paths["current_advisory_rejections"],
        paths["current_advisory_projection"],
        candidates,
    )
    identities = company_ticker_map(paths["company_tickers"])

    price_roots = [repo_path(path) for path in args.price_search_root]
    authoritative_price_roots = [repo_path(path) for path in args.authoritative_price_root]
    price_paths = price_file_map(price_roots, candidates)
    as_of = pd.Timestamp(args.as_of or score_date(scored_frame) or datetime.now(timezone.utc).date()).normalize()
    sec_paths = [repo_path(path) for path in args.sec_index]
    sec = sec_map(load_sec_indexes(sec_paths, candidates))

    issuer_sec_proxies: dict[str, str] = {}
    if "issuer_key" in intake.columns:
        for issuer_key, group in intake.groupby("issuer_key", sort=True):
            proxy_tickers = sorted(
                ticker
                for ticker in group["ticker"].map(clean_ticker)
                if ticker in sec
            )
            if proxy_tickers:
                issuer_sec_proxies[str(issuer_key)] = proxy_tickers[0]

    rows: list[dict[str, Any]] = []
    for base in intake.to_dict("records"):
        ticker = clean_ticker(base.get("ticker"))
        u = universe.get(ticker, {})
        s = scored.get(ticker, {})
        o = overlay_ranked.get(ticker, {})
        identity = identities.get(ticker, {})
        in_score = bool(s)
        ranking_eligible = truthy(s.get("ranking_eligible")) or truthy(
            s.get("registered_ranking_eligible")
        )
        overlay_rank = pd.to_numeric(
            pd.Series([o.get("free_data_selection_rank", o.get("rank"))]),
            errors="coerce",
        ).iloc[0]
        record: dict[str, Any] = {
            **base,
            **identity,
            "in_frozen_universe": ticker in universe,
            "universe_cik10": str(u.get("cik10") or u.get("reference_cik10") or ""),
            "in_latest_score": in_score,
            "score_decision_date": score_date(scored_frame),
            "research_score_rank": s.get("research_score_rank", s.get("score_rank", "")),
            "score_total": s.get("score_total", ""),
            "portfolio_candidate_minimum_pass": s.get("portfolio_candidate_minimum_pass", ""),
            "portfolio_candidate_gate_label": s.get("portfolio_candidate_gate_label", ""),
            "portfolio_sleeve_label": s.get("portfolio_sleeve_label", ""),
            "ranking_eligible": ranking_eligible,
            "data_history_quality_label": s.get("data_history_quality_label", ""),
            "fund_join_status": s.get("fund_join_status", ""),
            "fundamental_history_coverage_score": s.get("fundamental_history_coverage_score", ""),
            "in_overlay_ranked": ticker in overlay_ranked,
            "overlay_rank": "" if pd.isna(overlay_rank) else int(overlay_rank),
            "overlay_top_n": ticker in overlay_selected,
            "selected_main_current": ticker in main,
            "selected_concentrated_current": ticker in concentrated,
            "exact_operating_selector_reason_available": False,
            "exact_current_selector_reason_available": False,
            **rejections.get(
                ticker,
                {
                    "historical_rejection_asof": "",
                    "historical_rejection_reasons": "",
                    "historical_rejection_is_current_causal": False,
                },
            ),
            **current_advisory.get(
                ticker,
                {
                    "current_advisory_selector_evaluated": False,
                    "current_advisory_selected": False,
                    "current_advisory_selected_scenarios": "",
                    "current_advisory_rejection_reasons": "",
                    "current_advisory_reason_available": False,
                    "current_advisory_is_operating_causal": False,
                },
            ),
            **price_audit(
                price_paths.get(ticker, []),
                as_of,
                authoritative_price_roots,
            ),
            **sec.get(
                ticker,
                {
                    "sec_history_rows": 0,
                    "sec_history_first_accepted": "",
                    "sec_history_last_accepted": "",
                    "sec_exact_acceptance_rows": 0,
                    "sec_exact_acceptance_ratio": 0.0,
                    "sec_forms": "",
                    "sec_route_status": "MISSING_SEC_ACCEPTED_HISTORY",
                    "sec_backfill_required": True,
                },
            ),
            "research_only": True,
            "universe_membership_mutation_allowed": False,
            "portfolio_weight_mutation_allowed": False,
            "historical_backtest_promotion_allowed": False,
            "production_activation_allowed": False,
        }
        issuer_key = str(base.get("issuer_key") or ticker)
        proxy_ticker = issuer_sec_proxies.get(issuer_key, "")
        is_home_market = str(base.get("listing_route_hint") or "").upper() == "HOME_MARKET_NON_US"
        record["issuer_sec_proxy_ticker"] = proxy_ticker if proxy_ticker != ticker else ""
        record["issuer_sec_proxy_available"] = bool(proxy_ticker and proxy_ticker != ticker)
        record["sec_proxy_not_listing_specific"] = bool(proxy_ticker and proxy_ticker != ticker)
        record["home_market_filing_backfill_required"] = bool(
            is_home_market and record["sec_backfill_required"]
        )
        reason, action = choose_exclusion(record)
        record["evaluation_stage_outcome"] = reason
        record["next_evaluation_action"] = action
        record["data_acquisition_required"] = bool(
            record["price_backfill_required"] or record["sec_backfill_required"]
        )
        if not record["in_frozen_universe"]:
            priority = "P0_OUTSIDE_CONTEXT"
        elif record["data_acquisition_required"]:
            priority = "P1_COVERAGE_REPAIR"
        else:
            priority = "P2_NO_FETCH_REQUIRED"
        record["data_acquisition_priority"] = priority
        rows.append(record)

    audit = pd.DataFrame(rows).sort_values(
        ["data_acquisition_priority", "evaluation_stage_outcome", "research_score_rank", "ticker"],
        na_position="last",
    )
    queue = audit.loc[audit["data_acquisition_required"]].copy()
    queue["requested_price_start"] = "1900-01-01"
    queue["requested_price_end_exclusive"] = (as_of + pd.Timedelta(days=2)).date().isoformat()
    queue["required_sec_forms"] = "10-K|10-K/A|10-Q|10-Q/A|8-K|8-K/A|20-F|20-F/A|40-F|40-F/A|6-K|6-K/A"
    queue.loc[
        queue["home_market_filing_backfill_required"].astype(bool),
        "required_sec_forms",
    ] = "HOME_MARKET_FILING_SOURCE_REQUIRED;SEC_ISSUER_PROXY_IS_NOT_LISTING_SPECIFIC"
    queue["missing_evidence_policy"] = "neutral"
    queue["collection_dispatch_allowed"] = True
    queue["portfolio_promotion_allowed"] = False

    context_queue = audit.loc[~audit["in_frozen_universe"]].copy()
    context_queue["shadow_feature_build_required"] = True
    context_queue["required_feature_contract"] = (
        "same decision-time technical|fundamental|macro|risk;missing-neutral"
    )
    context_queue["operating_universe_append_allowed"] = False
    context_queue["evaluation_route"] = "SHADOW_CANONICAL_WINDOW_ELIGIBLE"
    context_queue.loc[
        ~context_queue["canonical_7y_price_eligible"].astype(bool),
        "evaluation_route",
    ] = "SHADOW_AVAILABLE_HISTORY_AND_FORWARD_ONLY"
    context_queue.loc[
        context_queue["home_market_filing_backfill_required"].astype(bool),
        "evaluation_route",
    ] = "BLOCKED_HOME_MARKET_FILING_SOURCE"

    reconciliation_queue = audit.loc[
        audit["evaluation_stage_outcome"].eq(
            "CURRENT_ADVISORY_SELECTED_OPERATING_DIVERGENCE"
        )
    ].copy()
    reconciliation_queue["required_evidence"] = (
        "exact same-session operating selector inputs|per-candidate rejection ledger|artifact hashes"
    )
    reconciliation_queue["trade_authorization"] = False

    audit_path = output_dir / "candidate_evaluation_funnel.csv"
    queue_path = output_dir / "data_acquisition_queue.csv"
    stage_path = output_dir / "stage_summary.csv"
    context_queue_path = output_dir / "research_context_queue.csv"
    reconciliation_queue_path = output_dir / "selector_reconciliation_queue.csv"
    audit.to_csv(audit_path, index=False)
    queue.to_csv(queue_path, index=False)
    context_queue.to_csv(context_queue_path, index=False)
    reconciliation_queue.to_csv(reconciliation_queue_path, index=False)
    stage = (
        audit.groupby(["evaluation_stage_outcome", "data_acquisition_priority"], dropna=False)
        .size()
        .reset_index(name="ticker_count")
    )
    stage.to_csv(stage_path, index=False)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_RESEARCH_ONLY_CANDIDATE_EVALUATION",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.date().isoformat(),
        "git_head": git_head(),
        "candidate_count": int(len(audit)),
        "in_frozen_universe_count": int(audit["in_frozen_universe"].sum()),
        "in_latest_score_count": int(audit["in_latest_score"].sum()),
        "ranking_eligible_count": int(audit["ranking_eligible"].sum()),
        "selected_main_count": int(audit["selected_main_current"].sum()),
        "selected_concentrated_count": int(audit["selected_concentrated_current"].sum()),
        "price_backfill_required_count": int(audit["price_backfill_required"].sum()),
        "sec_backfill_required_count": int(audit["sec_backfill_required"].sum()),
        "exact_current_selector_reason_available_count": int(
            audit["exact_current_selector_reason_available"].sum()
        ),
        "exact_operating_selector_reason_available_count": int(
            audit["exact_operating_selector_reason_available"].sum()
        ),
        "current_advisory_selector_evaluated_count": int(
            audit["current_advisory_selector_evaluated"].sum()
        ),
        "current_advisory_selected_operating_divergence_count": int(
            audit["evaluation_stage_outcome"]
            .eq("CURRENT_ADVISORY_SELECTED_OPERATING_DIVERGENCE")
            .sum()
        ),
        "research_context_queue_count": int(len(context_queue)),
        "selector_reconciliation_queue_count": int(len(reconciliation_queue)),
        "stage_counts": {
            str(key): int(value)
            for key, value in audit["evaluation_stage_outcome"].value_counts().items()
        },
        "inputs": {name: fingerprint(path) for name, path in paths.items()},
        "sec_indexes": [fingerprint(path) for path in sec_paths],
        "price_search_roots": [str(path) for path in price_roots],
        "authoritative_price_roots": [str(path) for path in authoritative_price_roots],
        "outputs": {
            "candidate_evaluation_funnel": fingerprint(audit_path),
            "data_acquisition_queue": fingerprint(queue_path),
            "stage_summary": fingerprint(stage_path),
            "research_context_queue": fingerprint(context_queue_path),
            "selector_reconciliation_queue": fingerprint(reconciliation_queue_path),
        },
        "network_requests_executed": 0,
        "fullrun_executed": False,
        "backtest_executed": False,
        "orders_generated": False,
        "universe_mutated": False,
        "portfolio_weights_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    manifest_path = output_dir / "manifest.json"
    report_path = output_dir / "report.md"
    manifest_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_report(summary, audit), encoding="utf-8")
    return summary


def render_report(summary: dict[str, Any], audit: pd.DataFrame) -> str:
    lines = [
        "# Run287 candidate evaluation funnel",
        "",
        f"Status: `{summary['status']}`.",
        "",
        "This is a research-only intake and exclusion audit. It changes no universe, target book, weight, cash, order, backtest, fullrun, production, or live-trading state.",
        "",
        "## Coverage",
        "",
        f"- intake candidates: `{summary['candidate_count']}`",
        f"- in frozen universe: `{summary['in_frozen_universe_count']}`",
        f"- in latest score: `{summary['in_latest_score_count']}`",
        f"- ranking eligible: `{summary['ranking_eligible_count']}`",
        f"- price backfill required: `{summary['price_backfill_required_count']}`",
        f"- SEC accepted-time backfill required: `{summary['sec_backfill_required_count']}`",
        f"- exact same-date causal selector reasons available: `{summary['exact_current_selector_reason_available_count']}`",
        f"- same-date no-write advisory selector evaluated: `{summary['current_advisory_selector_evaluated_count']}`",
        f"- advisory-selected / operating-book divergence: `{summary['current_advisory_selected_operating_divergence_count']}`",
        f"- outside-context shadow build queue: `{summary['research_context_queue_count']}`",
        "",
        "## Funnel outcomes",
        "",
        "| outcome | count |",
        "|---|---:|",
    ]
    for key, value in sorted(summary["stage_counts"].items()):
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Highest-ranked non-selected current-context names",
            "",
            "| ticker | rank | gate | overlay rank | outcome | price | SEC |",
            "|---|---:|---|---:|---|---|---|",
        ]
    )
    view = audit.loc[
        audit["in_latest_score"]
        & ~audit["selected_main_current"]
        & ~audit["selected_concentrated_current"]
    ].sort_values("research_score_rank", na_position="last").head(15)
    for row in view.to_dict("records"):
        lines.append(
            f"| {row.get('ticker')} | {row.get('research_score_rank', '')} | "
            f"{row.get('portfolio_candidate_gate_label', '')} | {row.get('overlay_rank', '')} | "
            f"`{row.get('evaluation_stage_outcome')}` | `{row.get('price_history_status')}` | "
            f"`{row.get('sec_route_status')}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- A name outside the frozen universe enters a research context first; it is not appended to the operating universe.",
            "- Missing data remains neutral. Coverage repair may reopen evaluation, but cannot by itself promote a name.",
            "- The current operating artifact is selected-only. Exact same-date selector inputs and per-candidate rejection rows must be archived before claiming a causal exclusion reason.",
            "- The same-date no-write advisory selector is reported separately. Its selected/rejected status is diagnostic and is never relabeled as the causal operating-book decision.",
            "- Historical rejection rows are diagnostic context only and are explicitly marked non-causal for the current date.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", default=DEFAULT_INTAKE)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE)
    parser.add_argument("--scored", default=DEFAULT_SCORED)
    parser.add_argument("--overlay-ranked", default=DEFAULT_OVERLAY_RANKED)
    parser.add_argument("--overlay-selected", default=DEFAULT_OVERLAY_SELECTED)
    parser.add_argument("--main-target", default=DEFAULT_MAIN)
    parser.add_argument("--concentrated-target", default=DEFAULT_CONCENTRATED)
    parser.add_argument("--historical-rejections", default=DEFAULT_REJECTIONS)
    parser.add_argument(
        "--current-advisory-rejections",
        default=DEFAULT_CURRENT_ADVISORY_REJECTIONS,
    )
    parser.add_argument(
        "--current-advisory-projection",
        default=DEFAULT_CURRENT_ADVISORY_PROJECTION,
    )
    parser.add_argument("--company-tickers", default=DEFAULT_COMPANY_TICKERS)
    parser.add_argument("--price-search-root", nargs="+", default=["outputs"])
    parser.add_argument("--authoritative-price-root", nargs="*", default=[])
    parser.add_argument("--sec-index", nargs="*", default=["data_pit/sec/sec_filings_index.parquet"])
    parser.add_argument("--as-of", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
