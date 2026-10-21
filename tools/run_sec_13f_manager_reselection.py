#!/usr/bin/env python3
"""Build a semiannual research-only SEC 13F manager reselection candidate list.

This tool does not overwrite the active manager universe. It freezes a
return-ranked research proposal from explicit comparable performance evidence.
The old manager-alpha/AUM mix remains a separately labeled diagnostic only.
"""
from __future__ import annotations

import argparse
import hashlib
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

from tools.build_sec_13f_manager_universe import DEFAULT_MANAGER_UNIVERSE, load_manager_universe  # noqa: E402
from tools.run_sec_submissions_collector import cik10, repo_path  # noqa: E402

DEFAULT_HOLDINGS = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_MANAGER_ALPHA = "outputs/sec_evidence_signal_audit/13f_manager_alpha.csv"
DEFAULT_OUTPUT_DIR = "outputs/sec_institutional_signals"
DEFAULT_PERFORMANCE = "outputs/sec_evidence_signal_audit/manager_performance_evidence/receipt.json"
PERFORMANCE_BASES = ("FUND_NAV_NET_TOTAL_RETURN", "DISCLOSED_13F_LONG_PROXY_TOTAL_RETURN")
MAX_PERFORMANCE_AGE_DAYS = 92  # Source research guard; permits the latest quarter-end window.
SELECTED_COLUMNS = ["manager_cik", "manager_name", "total_return", "evidence_sha256",
                    "source_available_at", "performance_rank"]


def review_cycle(decision_at: str) -> tuple[datetime, date]:
    """Use the existing June/December 5 05:00 UTC schedule, without day drift."""
    decision = exact_stamp(decision_at)
    anchors = [datetime(y, m, 5, 5, tzinfo=timezone.utc)
               for y in (decision.year - 1, decision.year, decision.year + 1) for m in (6, 12)]
    cutoff = max(t for t in anchors if t <= decision)
    return cutoff, min(t for t in anchors if t > cutoff).date()


def exact_stamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing aware timestamp")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("missing aware timestamp")
    return stamp.astimezone(timezone.utc)


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def return_ranked_selection(universe: pd.DataFrame, evidence: Path, *, decision_at: str,
                            top_n: int, performance_basis: str) -> dict[str, Any]:
    """Research proposal from explicit comparable returns; never a NAV authenticator.

    Legacy manager-alpha diagnostics have forward-return labels and no evaluation
    cutoff. They cannot substitute for this frozen, source-bound evidence.
    """
    cutoff, next_due = review_cycle(decision_at)
    out: dict[str, Any] = dict(
        schema="sec-manager-return-selection-v1", status="blocked", reasons=[],
        cycle_id=cutoff.date().isoformat(), selection_cutoff=cutoff.isoformat(),
        next_review_due=next_due.isoformat(), performance_basis=performance_basis,
        requested_managers=top_n, eligible_managers=0, selected_managers=[], excluded=[],
        max_performance_age_days=MAX_PERFORMANCE_AGE_DAYS,
        research_only=True, active_manager_universe_changed=False,
        source_authenticated=False, production_activation_allowed=False,
        canonical_write_allowed=False, selection_scope="supplied_verified_manager_universe",
    )
    if type(top_n) is not int or top_n < 10 or performance_basis not in PERFORMANCE_BASES:
        out["reasons"] = ["require_at_least_10_and_one_explicit_performance_basis"]
        return out
    if not evidence.is_file():
        out["reasons"] = ["missing_comparable_performance_evidence"]
        return out
    try:
        if evidence.stat().st_size > 4_000_000:
            raise ValueError("budget")
        raw = evidence.read_bytes()
        receipt = json.loads(raw, object_pairs_hook=unique_pairs)
        start, end = (date.fromisoformat(receipt[k]) for k in ("window_start", "window_end"))
        if (receipt["schema"] != "sec-manager-performance-evidence-v1"
                or receipt["performance_basis"] != performance_basis
                or not start < end < cutoff.date()
                or not datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)
                <= exact_stamp(receipt["calculated_at"]) <= cutoff
                or receipt["selection_cycle"] != out["cycle_id"]
                or not isinstance(receipt["currency"], str) or len(receipt["currency"]) != 3
                or not receipt["currency"].isascii() or not receipt["currency"].isalpha()
                or not receipt["currency"].isupper()
                or not isinstance(receipt["methodology_id"], str) or not receipt["methodology_id"].strip()
                or type(receipt["managers"]) is not list or len(receipt["managers"]) > 10000):
            raise ValueError("incomparable")
        out.update(performance_evidence_sha256=hashlib.sha256(raw).hexdigest(),
                   window_start=start.isoformat(), window_end=end.isoformat(),
                   methodology_id=receipt["methodology_id"], currency=receipt["currency"])
        if (cutoff.date() - end).days > MAX_PERFORMANCE_AGE_DAYS:
            out["reasons"] = ["stale_performance_window"]
            return out
        known = {str(r["cik10"]): r for r in universe.to_dict("records") if r.get("verified_flag")}
        seen: set[str] = set()
        eligible = []
        for record in receipt["managers"]:
            raw_cik = record.get("manager_cik")
            if not isinstance(raw_cik, str) or len(raw_cik) != 10 or not raw_cik.isascii() or not raw_cik.isdigit():
                raise ValueError("CIK")
            if raw_cik in seen:
                raise ValueError("duplicate CIK")
            seen.add(raw_cik)
            reason = None
            if raw_cik not in known:
                reason = "manager_identity_not_verified"
            elif record.get("status") != "COMPLETE":
                reason = "performance_missing_or_incomplete"
            elif any(record.get(k) != receipt[k] for k in
                     ("window_start", "window_end", "performance_basis", "methodology_id", "currency")):
                reason = "incomparable_return_definition"
            value = record.get("total_return")
            if type(value) not in (float, int) or not math.isfinite(value) or value < -1:
                reason = "missing_or_invalid_return"
            if not reason:
                # Evidence bytes are immutable references, not authentication of a
                # provider or a claim that reported NAV is globally comparable.
                relative = Path(record["evidence_file"])
                source = (evidence.parent / relative).resolve()
                if relative.is_absolute() or not source.is_relative_to(evidence.parent.resolve()):
                    raise ValueError("evidence scope")
                if (not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != record["evidence_sha256"]
                        or not datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)
                        <= exact_stamp(record["source_available_at"]) <= exact_stamp(receipt["calculated_at"])):
                    reason = "source_bytes_or_availability_invalid"
            if reason:
                out["excluded"].append(dict(manager_cik=raw_cik, reason=reason))
            else:
                eligible.append(dict(manager_cik=raw_cik, manager_name=known[raw_cik]["manager_name"],
                                     total_return=value, evidence_sha256=record["evidence_sha256"],
                                     source_available_at=record["source_available_at"]))
        eligible.sort(key=lambda r: (-r["total_return"], r["manager_cik"]))
        out["eligible_managers"] = len(eligible)
        if len(eligible) < top_n:
            out["reasons"] = ["insufficient_comparable_managers"]
        else:
            out["status"] = "completed"
            out["selected_managers"] = [dict(r, performance_rank=i + 1) for i, r in enumerate(eligible[:top_n])]
    except (ValueError, TypeError, KeyError, OSError, AttributeError):
        out["reasons"] = ["invalid_performance_evidence"]
        out["selected_managers"] = []
    out["selection_id"] = hashlib.sha256(json.dumps(out, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return out


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_selected(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    pd.DataFrame(rows, columns=SELECTED_COLUMNS).to_csv(temporary, index=False)
    temporary.replace(path)


def safe_num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        out = float(str(value).replace(",", "").replace("%", ""))
        return out if math.isfinite(out) else default
    except Exception:
        return default


def minmax(series: pd.Series, *, default: float = 0.0) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(default).astype(float)
    lo = float(s.min()) if len(s) else 0.0
    hi = float(s.max()) if len(s) else 0.0
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        return pd.Series(default, index=s.index, dtype=float)
    return ((s - lo) / (hi - lo)).clip(0.0, 1.0)


def numeric_column(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype(float)


def holdings_manager_stats(holdings: pd.DataFrame) -> pd.DataFrame:
    if holdings.empty:
        return pd.DataFrame(columns=["manager_cik"])
    d = holdings.copy()
    if "manager_name" not in d.columns:
        d["manager_name"] = ""
    if "issuer_name" not in d.columns:
        d["issuer_name"] = d.get("ticker_mapped", "")
    d = d[d["manager_cik"].astype(str).str.strip().ne("")].copy()
    if d.empty:
        return pd.DataFrame(columns=["manager_cik"])
    d["manager_cik"] = d["manager_cik"].map(cik10)
    d["report_period_ts"] = pd.to_datetime(d.get("report_period"), errors="coerce").dt.normalize()
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    d["market_value_usd"] = pd.to_numeric(d.get("market_value_usd", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)
    d = d[d["report_period_ts"].notna()].copy()
    if d.empty:
        return pd.DataFrame(columns=["manager_cik"])
    d = d.sort_values(["manager_cik", "issuer_name", "report_period_ts", "available_from_ts"])
    d = d.drop_duplicates(["manager_cik", "issuer_name", "report_period_ts"], keep="last")
    latest_period = d.groupby("manager_cik")["report_period_ts"].transform("max")
    latest = d[d["report_period_ts"].eq(latest_period)].copy()
    total = latest.groupby("manager_cik")["market_value_usd"].transform("sum").replace(0.0, pd.NA)
    latest["manager_position_weight"] = (latest["market_value_usd"] / total).fillna(0.0).clip(0.0, 1.0)
    grouped = (
        latest.groupby("manager_cik", dropna=False)
        .agg(
            manager_name_holdings=("manager_name", lambda s: next((str(v) for v in s if str(v).strip()), "")),
            latest_report_period=("report_period_ts", "max"),
            latest_available_from=("available_from_ts", "max"),
            latest_13f_aum_usd=("market_value_usd", "sum"),
            latest_holdings_count=("issuer_name", "nunique"),
            latest_top_position_weight=("manager_position_weight", "max"),
        )
        .reset_index()
    )
    return grouped


def build_candidates(
    universe: pd.DataFrame,
    manager_alpha: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    max_managers: int,
    min_observations: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not universe.empty:
        base = universe.copy()
        base["manager_cik"] = base["cik10"].map(cik10)
        base["manager_name_seed"] = base.get("manager_name", "").astype(str)
        base["label"] = base.get("label", "").astype(str).str.upper().str.strip()
        frames.append(base)
    else:
        base = pd.DataFrame(columns=["manager_cik", "manager_name_seed", "label"])
        frames.append(base)

    stats = holdings_manager_stats(holdings)
    alpha = manager_alpha.copy() if not manager_alpha.empty else pd.DataFrame(columns=["manager_cik"])
    if not alpha.empty:
        alpha["manager_cik"] = alpha["manager_cik"].map(cik10)
    known = pd.concat([frame[["manager_cik"]] for frame in [base, stats, alpha] if "manager_cik" in frame.columns], ignore_index=True)
    known = known.dropna().drop_duplicates()
    if known.empty:
        return pd.DataFrame()
    out = known.merge(base, on="manager_cik", how="left")
    out = out.merge(stats, on="manager_cik", how="left")
    out = out.merge(alpha, on="manager_cik", how="left", suffixes=("", "_alpha"))
    out["manager_name"] = (
        out.get("manager_name_seed", pd.Series("", index=out.index)).fillna("").astype(str).str.strip()
    )
    if "manager_name_alpha" in out.columns:
        out.loc[out["manager_name"].eq(""), "manager_name"] = out.loc[out["manager_name"].eq(""), "manager_name_alpha"].fillna("")
    if "manager_name_holdings" in out.columns:
        out.loc[out["manager_name"].eq(""), "manager_name"] = out.loc[out["manager_name"].eq(""), "manager_name_holdings"].fillna("")
    out.loc[out["manager_name"].eq(""), "manager_name"] = "CIK" + out.loc[out["manager_name"].eq(""), "manager_cik"].astype(str)
    out["observations"] = numeric_column(out, "observations", 0.0)
    out["hit_rate_excess_positive"] = numeric_column(out, "hit_rate_excess_positive", 0.0).clip(0.0, 1.0)
    out["manager_quality_score"] = numeric_column(out, "manager_quality_score", 0.0).clip(0.0, 1.0)
    if "latest_13f_aum_usd" not in out.columns and "aum_13f_usd_num" in out.columns:
        out["latest_13f_aum_usd"] = out["aum_13f_usd_num"]
    if "latest_holdings_count" not in out.columns and "holdings_count" in out.columns:
        out["latest_holdings_count"] = out["holdings_count"]
    out["latest_13f_aum_usd"] = numeric_column(out, "latest_13f_aum_usd", 0.0)
    out["latest_holdings_count"] = numeric_column(out, "latest_holdings_count", 0.0)
    out["latest_top_position_weight"] = numeric_column(out, "latest_top_position_weight", 0.0).clip(0.0, 1.0)
    out["user_priority_num"] = numeric_column(out, "user_priority_num", 999.0)
    out["active_flag"] = out.get("active_flag", False).fillna(False).astype(bool) if "active_flag" in out.columns else False
    out["verified_flag"] = out.get("verified_flag", False).fillna(False).astype(bool) if "verified_flag" in out.columns else False

    out["sample_score"] = (out["observations"] / max(float(min_observations), 1.0)).clip(0.0, 1.0)
    out["aum_score"] = minmax(out["latest_13f_aum_usd"].map(lambda v: math.log1p(max(float(v), 0.0))))
    out["coverage_score"] = minmax(out["latest_holdings_count"])
    out["concentration_score"] = out["latest_top_position_weight"].clip(0.0, 1.0)
    out["seed_priority_score"] = (1.0 - (out["user_priority_num"].clip(1.0, 100.0) - 1.0) / 99.0).clip(0.0, 1.0)
    out["manager_reselection_score"] = (
        0.40 * out["manager_quality_score"]
        + 0.18 * out["aum_score"]
        + 0.14 * out["hit_rate_excess_positive"]
        + 0.12 * out["sample_score"]
        + 0.08 * out["concentration_score"]
        + 0.05 * out["coverage_score"]
        + 0.03 * out["seed_priority_score"]
    ).clip(0.0, 1.0)
    out["reselection_action"] = "watch"
    out.loc[out["manager_reselection_score"].ge(0.62) & out["observations"].ge(min_observations), "reselection_action"] = "candidate_include"
    out.loc[out["active_flag"] & out["verified_flag"] & out["manager_reselection_score"].lt(0.25), "reselection_action"] = "candidate_review_or_retire"
    out.loc[out["active_flag"] & out["verified_flag"] & out["manager_reselection_score"].ge(0.25), "reselection_action"] = "keep_active"
    out["research_only"] = True
    out["production_activation_allowed"] = False
    out = out.sort_values(
        ["manager_reselection_score", "manager_quality_score", "latest_13f_aum_usd", "observations"],
        ascending=[False, False, False, False],
    )
    if max_managers > 0:
        out = out.head(int(max_managers)).copy()
    keep_cols = [
        "manager_cik",
        "label",
        "manager_name",
        "reselection_action",
        "manager_reselection_score",
        "manager_quality_score",
        "observations",
        "hit_rate_excess_positive",
        "avg_excess_return",
        "latest_13f_aum_usd",
        "latest_holdings_count",
        "latest_top_position_weight",
        "latest_report_period",
        "latest_available_from",
        "active_flag",
        "verified_flag",
        "user_priority_num",
        "research_only",
        "production_activation_allowed",
    ]
    for col in keep_cols:
        if col not in out.columns:
            out[col] = ""
    return out[keep_cols]


def render_report(summary: dict[str, Any], candidates: pd.DataFrame) -> str:
    lines = [
        "# SEC 13F Manager Reselection",
        "",
        "Research-only semiannual manager universe review. The active manager CSV is not overwritten.",
        "",
        f"- status: {summary.get('status')}",
        f"- candidates: {summary.get('candidate_rows', 0)}",
        f"- selected include candidates: {summary.get('candidate_include_count', 0)}",
        f"- return-ranked selection: {summary.get('performance_selection_status')}",
        f"- comparable eligible managers: {summary.get('performance_eligible_managers')}",
        f"- selected managers: {summary.get('performance_selected_managers')}",
        f"- selection blockers: {summary.get('reason')}",
        f"- next review due: {summary.get('next_review_due')}",
        "",
        "## Legacy Diagnostic Candidates (not return-ranked selection)",
        "",
        "| manager | action | score | quality | obs | hit rate | latest AUM |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, row in candidates.head(25).iterrows():
        lines.append(
            "| {name} | {action} | {score:.3f} | {quality:.3f} | {obs:.0f} | {hit:.1%} | ${aum:,.0f} |".format(
                name=row.get("manager_name", ""),
                action=row.get("reselection_action", ""),
                score=safe_num(row.get("manager_reselection_score")),
                quality=safe_num(row.get("manager_quality_score")),
                obs=safe_num(row.get("observations")),
                hit=safe_num(row.get("hit_rate_excess_positive")),
                aum=safe_num(row.get("latest_13f_aum_usd")),
            )
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = repo_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "manager_reselection_summary.json", dict(status="blocked", reason="attempt_incomplete"))
    write_json(out_dir / "manager_performance_selection.json", dict(
        schema="sec-manager-return-selection-v1", status="blocked", reasons=["attempt_incomplete"],
        selected_managers=[], research_only=True, source_authenticated=False,
        canonical_write_allowed=False, production_activation_allowed=False))
    write_selected(out_dir / "manager_performance_selected.csv", [])
    universe = load_manager_universe(repo_path(args.manager_universe), extra=str(args.extra or ""))
    decision_at = getattr(args, "decision_at", "") or datetime.now(timezone.utc).isoformat()
    selection = return_ranked_selection(
        universe, repo_path(getattr(args, "performance_evidence", DEFAULT_PERFORMANCE)),
        decision_at=decision_at, top_n=int(getattr(args, "top_n", 10)),
        performance_basis=getattr(args, "performance_basis", PERFORMANCE_BASES[0]),
    )
    frozen = out_dir / f"manager_selection_{selection['cycle_id']}.json"
    if selection["status"] == "completed":
        if frozen.exists():
            if frozen.read_bytes() != (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode():
                selection = {**selection, "status": "blocked", "reasons": ["frozen_cycle_conflict"],
                             "selected_managers": []}
                selection["selection_id"] = hashlib.sha256(json.dumps(
                    {k: v for k, v in selection.items() if k != "selection_id"}, sort_keys=True).encode()).hexdigest()
    manager_alpha = read_table(repo_path(args.manager_alpha))
    holdings = read_table(repo_path(args.holdings))
    candidates = build_candidates(
        universe,
        manager_alpha,
        holdings,
        max_managers=int(args.max_managers),
        min_observations=int(args.min_observations),
    )
    candidates_csv = out_dir / "manager_reselection_candidates.csv"
    candidates.to_csv(candidates_csv, index=False)
    candidate_review_csv = repo_path(args.output_candidate_universe)
    if str(args.output_candidate_universe).strip():
        candidate_review_csv.parent.mkdir(parents=True, exist_ok=True)
        candidates.to_csv(candidate_review_csv, index=False)
    summary = {
        "status": selection["status"],
        "reason": ";".join(selection["reasons"]),
        "research_only": True,
        "production_activation_allowed": False,
        "active_manager_universe_changed": False,
        "review_interval_days": int(args.review_interval_days),
        "review_cadence": "existing_June_5_December_5_0500_UTC",
        "decision_at": decision_at,
        "next_review_due": selection["next_review_due"],
        "performance_selection_status": selection["status"],
        "performance_eligible_managers": selection["eligible_managers"],
        "performance_selected_managers": len(selection["selected_managers"]),
        "selection_id": selection.get("selection_id"),
        "candidate_rows": int(len(candidates)),
        "candidate_include_count": int((candidates.get("reselection_action", pd.Series(dtype=str)) == "candidate_include").sum())
        if not candidates.empty
        else 0,
        "manager_universe": str(repo_path(args.manager_universe)),
        "manager_alpha": str(repo_path(args.manager_alpha)),
        "holdings": str(repo_path(args.holdings)),
        "outputs": {
            "manager_reselection_candidates": str(candidates_csv),
            "manager_review_candidate_universe": str(candidate_review_csv) if str(args.output_candidate_universe).strip() else "",
            "report": str(out_dir / "manager_reselection_report.md"),
            "performance_selection": str(out_dir / "manager_performance_selection.json"),
            "selected_managers": str(out_dir / "manager_performance_selected.csv"),
        },
    }
    (out_dir / "manager_reselection_report.md").write_text(render_report(summary, candidates), encoding="utf-8")
    # No positive current or new frozen output until every required read/report
    # succeeds. The summary commits the attempt last and binds the selected bytes.
    if selection["status"] == "completed" and not frozen.exists():
        write_json(frozen, selection)
    write_selected(out_dir / "manager_performance_selected.csv", selection["selected_managers"])
    write_json(out_dir / "manager_performance_selection.json", selection)
    summary["output_sha256"] = {name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
                                for name in ("manager_performance_selection.json", "manager_performance_selected.csv")}
    write_json(out_dir / "manager_reselection_summary.json", summary)
    print(json.dumps({"status": summary["status"], "candidate_rows": summary["candidate_rows"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager-universe", default=DEFAULT_MANAGER_UNIVERSE)
    parser.add_argument("--manager-alpha", default=DEFAULT_MANAGER_ALPHA)
    parser.add_argument("--holdings", default=DEFAULT_HOLDINGS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-candidate-universe", default="research/sec_13f_manager_universe_20260519/managers_candidate.csv")
    parser.add_argument("--extra", default="")
    parser.add_argument("--max-managers", type=int, default=40)
    parser.add_argument("--min-observations", type=int, default=10)
    parser.add_argument("--review-interval-days", type=int, default=183,
                        help="Legacy metadata only; selection follows the existing June/December calendar")
    parser.add_argument("--performance-evidence", default=DEFAULT_PERFORMANCE)
    parser.add_argument("--performance-basis", choices=PERFORMANCE_BASES, default=PERFORMANCE_BASES[0])
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--decision-at", default="", help="Aware research cutoff; default current UTC")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
