#!/usr/bin/env python3
"""Audit why fixed-book replacement-quality events under-fire in policy hooks.

This is a W1/root-cause diagnostic. It does not run broker replay, mutate target
books, or approve a fullrun. It compares fixed-book swaps against a generated
policy target book and, optionally, the fixed baseline book, candidate book, and
policy rejection log.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def repo_path(path_like: str | Path | None) -> Path | None:
    if path_like is None or str(path_like).strip() == "":
        return None
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def norm_text(value: Any) -> str:
    raw = "" if value is None else str(value)
    if raw.lower() in {"nan", "none", "nat"}:
        return ""
    return raw.strip()


def norm_ticker(value: Any) -> str:
    return norm_text(value).upper()


def norm_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).date().isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_book(path: Path | None) -> pd.DataFrame:
    frame = read_csv(path)
    if frame.empty:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "weight"])
    if "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        raise ValueError(f"{path} must contain rebalance_date and ticker")
    weight_col = "weight" if "weight" in frame.columns else "target_weight"
    if weight_col not in frame.columns:
        frame["weight"] = 0.0
        weight_col = "weight"
    out = frame.copy()
    out["rebalance_date"] = out["rebalance_date"].map(norm_date)
    out["ticker"] = out["ticker"].map(norm_ticker)
    out["weight"] = pd.to_numeric(out[weight_col], errors="coerce").fillna(0.0)
    out = out[out["rebalance_date"].ne("") & out["ticker"].ne("")].copy()
    return out


def normalize_swaps(path: Path) -> pd.DataFrame:
    frame = read_csv(path)
    required = {"rebalance_date", "added_ticker", "removed_ticker"}
    if frame.empty or not required.issubset(set(frame.columns)):
        raise ValueError(f"{path} must contain {sorted(required)}")
    out = frame.copy()
    out["rebalance_date"] = out["rebalance_date"].map(norm_date)
    out["added_ticker"] = out["added_ticker"].map(norm_ticker)
    out["removed_ticker"] = out["removed_ticker"].map(norm_ticker)
    out["replacement_weight"] = pd.to_numeric(
        out.get("replacement_weight", pd.Series(0.0, index=out.index)), errors="coerce"
    ).fillna(0.0)
    out = out[out["rebalance_date"].ne("") & out["added_ticker"].ne("") & out["removed_ticker"].ne("")].copy()
    out["event_key"] = out["rebalance_date"] + "|" + out["added_ticker"] + "|" + out["removed_ticker"]
    return out.drop_duplicates(subset=["event_key"]).reset_index(drop=True)


def normalize_candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["rebalance_date"] = out["rebalance_date"].map(norm_date)
    out["ticker"] = out["ticker"].map(norm_ticker)
    return out[out["rebalance_date"].ne("") & out["ticker"].ne("")].copy()


def normalize_rejection_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["rebalance_date"] = out["rebalance_date"].map(norm_date)
    if "ticker" not in out.columns:
        out["ticker"] = ""
    if "replacement_test_weakest_ticker" not in out.columns:
        out["replacement_test_weakest_ticker"] = ""
    out["ticker"] = out["ticker"].map(norm_ticker)
    out["replacement_test_weakest_ticker"] = out["replacement_test_weakest_ticker"].map(norm_ticker)
    if "portfolio_kind" in out.columns:
        out = out[out["portfolio_kind"].astype(str).str.lower().eq("concentrated")].copy()
    return out[out["rebalance_date"].ne("")].copy()


def day_tickers(book: pd.DataFrame, dt: str) -> set[str]:
    if book.empty:
        return set()
    return set(book.loc[book["rebalance_date"].eq(dt), "ticker"].astype(str))


def day_rows(book: pd.DataFrame, dt: str, ticker: str) -> pd.DataFrame:
    if book.empty:
        return pd.DataFrame()
    return book[book["rebalance_date"].eq(dt) & book["ticker"].eq(ticker)].copy()


def candidate_snapshot(candidate: pd.DataFrame, dt: str, ticker: str) -> dict[str, Any]:
    if candidate.empty:
        return {"candidate_present": False}
    rows = candidate[candidate["rebalance_date"].eq(dt) & candidate["ticker"].eq(ticker)].copy()
    if rows.empty:
        return {"candidate_present": False}
    row = rows.iloc[0].to_dict()
    return {
        "candidate_present": True,
        "candidate_leader_rank_ex_ante": safe_float(row.get("leader_rank_ex_ante"), float("nan")),
        "candidate_revenue_growth": safe_float(row.get("revenue_growth"), float("nan")),
        "candidate_rs_spy_3m": safe_float(row.get("rs_spy_3m"), safe_float(row.get("rs_benchmark_3m"), float("nan"))),
        "candidate_primary_lane": norm_text(row.get("primary_lane")),
        "candidate_holding_state": norm_text(row.get("holding_state")),
        "candidate_hold_replace_decision": norm_text(row.get("hold_replace_decision")),
    }


def rejection_snapshot(rejections: pd.DataFrame, dt: str, added: str, removed: str) -> dict[str, Any]:
    if rejections.empty:
        return {"policy_rejection_exact": False, "policy_rejection_same_candidate": False}
    same_candidate = rejections[rejections["rebalance_date"].eq(dt) & rejections["ticker"].eq(added)]
    exact = same_candidate[same_candidate["replacement_test_weakest_ticker"].eq(removed)]
    source = exact if not exact.empty else same_candidate
    row = source.iloc[0].to_dict() if not source.empty else {}
    return {
        "policy_rejection_exact": bool(not exact.empty),
        "policy_rejection_same_candidate": bool(not same_candidate.empty),
        "policy_rejection_reason": norm_text(row.get("rejection_reason")),
        "policy_rejection_weakest_ticker": norm_ticker(row.get("replacement_test_weakest_ticker")),
    }


def classify(row: dict[str, Any]) -> str:
    if row["hook_applied_exact"]:
        return "exact_match"
    if row["generated_has_donor"]:
        return "generated_has_donor_but_hook_not_applied"
    if row["fixed_has_donor"]:
        return "generated_book_missing_fixed_donor"
    if row["candidate_present"]:
        return "fixed_event_donor_not_in_fixed_book"
    return "candidate_or_event_missing_from_inputs"


def render_report(payload: dict[str, Any], detail: pd.DataFrame) -> str:
    lines = [
        "# Replacement-Quality Donor-Missing Audit",
        "",
        f"- status: `{payload['status']}`",
        f"- fixed events: `{payload['fixed_event_count']}`",
        f"- generated missing fixed donor: `{payload['generated_missing_fixed_donor_count']}`",
        f"- exact hook matches: `{payload['exact_hook_match_count']}`",
        f"- fullrun allowed: `{payload['fullrun_allowed']}`",
        "",
        "## Classification",
        "",
    ]
    for key, value in payload["classification_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    missing = detail[detail["classification"].eq("generated_book_missing_fixed_donor")]
    if not missing.empty:
        lines.extend(["", "## Missing Fixed Donors", ""])
        for row in missing.to_dict("records"):
            lines.append(
                f"- {row['rebalance_date']} `{row['added_ticker']}` replacing `{row['removed_ticker']}`: "
                f"fixed donor present={row['fixed_has_donor']}, generated donor present={row['generated_has_donor']}"
            )
    lines.extend(
        [
            "",
            "Interpretation: do not substitute alternate donors for missing fixed-book donors. "
            "That would create a different lever than the validated fixed-book counterfactual.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    assert output_dir is not None
    output_dir.mkdir(parents=True, exist_ok=True)

    fixed_swaps_path = repo_path(args.fixed_swaps)
    generated_book_path = repo_path(args.generated_book)
    fixed_book_path = repo_path(args.fixed_book)
    candidate_book_path = repo_path(args.candidate_book)
    policy_rejections_path = repo_path(args.policy_rejections)
    assert fixed_swaps_path is not None and generated_book_path is not None

    swaps = normalize_swaps(fixed_swaps_path)
    generated = normalize_book(generated_book_path)
    fixed = normalize_book(fixed_book_path)
    candidate = normalize_candidate_frame(read_csv(candidate_book_path))
    rejections = normalize_rejection_frame(read_csv(policy_rejections_path))

    rows: list[dict[str, Any]] = []
    for swap in swaps.to_dict("records"):
        dt = swap["rebalance_date"]
        added = swap["added_ticker"]
        removed = swap["removed_ticker"]
        fixed_tickers = day_tickers(fixed, dt)
        generated_tickers = day_tickers(generated, dt)
        generated_added_rows = day_rows(generated, dt, added)
        hook_applied_exact = False
        if not generated_added_rows.empty and "concentrated_replacement_quality_applied" in generated_added_rows.columns:
            applied = generated_added_rows["concentrated_replacement_quality_applied"].astype(str).str.lower().isin(
                {"1", "true", "yes", "y", "t"}
            )
            removed_col = generated_added_rows.get(
                "concentrated_replacement_quality_removed_ticker", pd.Series("", index=generated_added_rows.index)
            ).map(norm_ticker)
            hook_applied_exact = bool((applied & removed_col.eq(removed)).any())
        base = {
            "event_key": swap["event_key"],
            "rebalance_date": dt,
            "added_ticker": added,
            "removed_ticker": removed,
            "replacement_weight": safe_float(swap.get("replacement_weight")),
            "fixed_has_donor": removed in fixed_tickers if fixed_tickers else False,
            "fixed_has_added": added in fixed_tickers if fixed_tickers else False,
            "generated_has_donor": removed in generated_tickers,
            "generated_has_added": added in generated_tickers,
            "fixed_ticker_count": len(fixed_tickers),
            "generated_ticker_count": len(generated_tickers),
            "generated_tickers": ",".join(sorted(generated_tickers)),
            "hook_applied_exact": hook_applied_exact,
        }
        base.update(candidate_snapshot(candidate, dt, added))
        base.update(rejection_snapshot(rejections, dt, added, removed))
        base["classification"] = classify(base)
        rows.append(base)

    detail = pd.DataFrame(rows)
    detail.to_csv(output_dir / "donor_missing_detail.csv", index=False)
    missing = detail[detail["classification"].eq("generated_book_missing_fixed_donor")].copy()
    missing.to_csv(output_dir / "generated_missing_fixed_donors.csv", index=False)
    counts = detail["classification"].value_counts().sort_index().to_dict() if not detail.empty else {}
    payload = {
        "status": "completed",
        "schema_version": "replacement-quality-donor-missing-audit-v1",
        "fixed_swaps": str(fixed_swaps_path),
        "generated_book": str(generated_book_path),
        "fixed_book": str(fixed_book_path) if fixed_book_path else "",
        "candidate_book": str(candidate_book_path) if candidate_book_path else "",
        "policy_rejections": str(policy_rejections_path) if policy_rejections_path else "",
        "fixed_event_count": int(len(detail)),
        "exact_hook_match_count": int(detail["hook_applied_exact"].sum()) if not detail.empty else 0,
        "generated_missing_fixed_donor_count": int(len(missing)),
        "classification_counts": {str(k): int(v) for k, v in counts.items()},
        "fullrun_allowed": False,
        "production_activation_allowed": False,
        "research_only": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "next_action": (
            "resolve_target_book_reproduction_or_use_official_book_event_source"
            if len(missing)
            else "rerun_event_reconciliation"
        ),
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload, detail), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixed-swaps", required=True)
    parser.add_argument("--generated-book", required=True)
    parser.add_argument("--output-dir", default="outputs/replacement_quality_donor_missing_audit")
    parser.add_argument("--fixed-book", default="")
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--policy-rejections", default="")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
