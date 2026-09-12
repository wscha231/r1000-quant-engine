#!/usr/bin/env python3
"""Restore, register, collect, reevaluate and checkpoint one bounded research cycle.

All full histories are refreshed in this small first-stage universe. This also
catches delayed releases and old revisions without treating a poll as a release.
"""
from __future__ import annotations

import argparse
import copy
from datetime import timedelta
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import macro_history_sources as source
from tools import macro_research_checkpoint as checkpoint
from tools.macro_technical_study import compare, study

CURRENT = "SP500,NASDAQCOM,DGS2,DGS10,UNRATE,PAYEMS,CPIAUCSL,WALCL,WTREGEN,RRPONTSYD,SOFR,M2SL".split(",")
ARCHIVE = ["UNRATE", "PAYEMS", "CPIAUCSL"]
HISTORY_ID = "macro-technical-fixed-family-v1"


def retain_expired_price_history(store, fresh_receipt, fresh_records, previous_receipt, old_records):
    """Retain prices that aged out of a provider's rolling window, never fill holes.

    Old and new raw responses stay hash-bound; mixed retrieval dates are explicit
    current_only research observations, not a historical PIT certification.
    """
    if not previous_receipt:
        return fresh_receipt, fresh_records
    receipt, records = copy.deepcopy(fresh_receipt), copy.deepcopy(fresh_records)
    previous = {s["series"]: s for s in previous_receipt["sources"] if s["status"] == "COLLECTED"}
    for item in receipt["sources"]:
        sid = item["series"]
        if sid not in {"SP500", "NASDAQCOM"} or item["status"] != "COLLECTED":
            continue
        boundary = item.get("provider_window_start")
        source.require(isinstance(boundary, str) and boundary <= item["earliest"],
                       "provider_window_start_required")
        source.require(source.date.fromisoformat(boundary).isoformat() == boundary,
                       "provider_window_start_required")
        retained = [r for r in old_records.get(sid, []) if r["observation_date"] < boundary]
        prior = previous.get(sid, {})
        retained_missing = [d for d in prior.get("missing_observation_dates", []) if d < boundary]
        if not retained and not retained_missing:
            continue
        records[sid] = sorted(retained + records[sid], key=lambda r: r["observation_date"])
        raw = source.encoded(records[sid])
        sha = source.digest(raw)
        source.exclusive(Path(store) / "objects" / sha, raw)
        item.update(records_sha256=sha, rows=len(records[sid]), observation_periods=len(records[sid]),
            earliest=records[sid][0]["observation_date"],
            raw_sha256=sorted(set(item["raw_sha256"] + previous[sid]["raw_sha256"])),
            retained_expired_provider_rows=len(retained),
            retained_from_receipt_sha256=source.digest(source.encoded(previous_receipt)),
            price_history_policy="OLDER_THAN_NEW_PROVIDER_WINDOW_ONLY; NO_INTERIOR_GAP_FILL")
        item["missing_observation_dates"] = sorted(set(item.get("missing_observation_dates", [])) | set(retained_missing))
        item["missing_value_count"] = len(item["missing_observation_dates"])
        item["retained_missing_dates_complete"] = not (
            prior.get("missing_value_count", 0) and "missing_observation_dates" not in prior
        ) and prior.get("retained_missing_dates_complete", True)
    return receipt, records


def source_changes(before, after):
    """Compare economic records, excluding new retrieval timestamps/receipt IDs."""
    changes = []
    for series in sorted(set(before) | set(after)):
        def values(rows):
            return {(r["observation_date"], r.get("vintage_date")): r["value"] for r in rows}
        old, new = values(before.get(series, [])), values(after.get(series, []))
        added, removed = new.keys() - old.keys(), old.keys() - new.keys()
        revised = {k for k in old.keys() & new.keys() if old[k] != new[k]}
        # Archive interval end changes matter even when the released value is equal.
        def intervals(rows):
            return {(r["observation_date"], r.get("vintage_date")): r.get("realtime_end") for r in rows}
        old_end, new_end = intervals(before.get(series, [])), intervals(after.get(series, []))
        interval_changes = sum(old_end[k] != new_end[k] for k in old_end.keys() & new_end.keys())
        changes.append(dict(series=series, added=len(added), removed=len(removed),
            revised=len(revised), interval_changes=interval_changes,
            changed=bool(added or removed or revised or interval_changes)))
    return changes


def job_plan(as_of, previous, calendar):
    previous_sources = {s["series"]: s for s in (previous or {}).get("sources", []) if s["status"] == "COLLECTED"}
    selected = set(CURRENT)
    jobs = [j for j in source.update_plan(as_of, previous_sources, calendar["events"]) if j["series"] in selected]
    for job in jobs:
        job["collection_action"] = "REFRESH_FULL_HISTORY"
        job["polling_policy"] = "DAILY_WITH_DELAY_AND_REVISION_RECHECK"
        job["calendar_precision"] = "date_only; not intraday event study"
        job["release_confirmed"] = False
    return dict(schema="macro-cycle-plan-v1", as_of=as_of, jobs=jobs,
        calendar_sha256=source.digest(source.encoded(calendar)),
        frequency_is_not_release_confirmation=True,
        declared_family_id=HISTORY_ID, selector_enabled=False)


def engine_context(result):
    source.require(result.get("schema") == "macro-technical-evidence-v1" and
        result.get("eligible_for_selector") is False and result.get("model_promoted") is False,
        "research_evidence_contract")
    fields = ["asset", "feature", "horizon_sessions", "status", "oos_rows",
              "nonoverlap_windows", "effect_per_training_sd_pp", "effect_ci95_pp",
              "family_q_value", "oos_mse_improvement"]
    return dict(schema="macro-engine-context-v1", evidence_sha256=source.digest(source.encoded(result)),
        as_of=result["as_of"], allowed_use="RESEARCH_CONTEXT_ONLY", eligible_for_selector=False,
        stock_selection_weight=0, model_promoted=False,
        causal_effect_identified=False, historical_pit_certified=False,
        predictions_for_future_dates_available=False, coverage=result["coverage"],
        freshness_policy="CHECK_COVERAGE_AND_MISSING_TAIL_BEFORE_DISPLAY",
        rows=[{key: row[key] for key in fields} for row in result["results"]])


def provenance():
    paths = ["tools/macro_research_checkpoint.py", "tools/macro_research_cycle.py",
             "tools/macro_history_sources.py", "tools/macro_technical_study.py",
             "docs/macro_indicator_registry.json"]
    return dict(files={p: source.digest((ROOT / p).read_bytes()) for p in paths},
        python=sys.version.split()[0], packages={n: importlib.metadata.version(n)
            for n in ["numpy", "pandas", "scipy"]},
        research_history_id=HISTORY_ID, canonical_cross_project_census_integrated=False)


def run_cycle(transport, workspace, run_id, *, now=None, collector=source.collect,
              calendar_fetcher=source.fetch_calendar, evaluator=study):
    source.require(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id), "cycle_run_id")
    now = now or source.utc_now()
    through = (source.stamp(now).date() - timedelta(days=1)).isoformat()
    workspace = checkpoint.safe_path(workspace)
    source.require(not workspace.exists(), "cycle_workspace_exists")
    workspace.mkdir(parents=True)
    prior_root, current_root = workspace / "previous", workspace / "current"
    restored = checkpoint.restore_latest(transport, prior_root)
    parent = restored["commit"]
    started = dict(schema="macro-cycle-attempt-v1", phase="STARTED", run_id=run_id,
        started_at=now, parent=parent, requested_start="2000-01-01", requested_through=through,
        provenance=provenance(), declared_family_size=336, eligible_for_selector=False)
    attempt = checkpoint.journal(transport, started)  # durable before providers/evaluation
    previous_receipt, old_current, old_archive, old_result = None, {}, {}, None
    if parent:
        # Keep every prior raw object/receipt. Reports are rebuilt without overwriting
        # the remote predecessor. Old reports remain in its immutable manifest.
        shutil.copytree(prior_root / "store", current_root / "store")
        previous_receipt = json.loads((prior_root / "reports/collection.json").read_bytes())
        old_result = json.loads((prior_root / "reports/alfred-evidence.json").read_bytes())
        for name, output in [("collection.json", old_current), ("alfred-collection.json", old_archive)]:
            receipt = json.loads((prior_root / "reports" / name).read_bytes())
            for item in receipt["sources"]:
                if item["status"] == "COLLECTED":
                    output[item["series"]] = json.loads((prior_root / "store/objects" / item["records_sha256"]).read_bytes())
    registry_raw = source.REGISTRY.read_bytes()
    source.exclusive(current_root / "store/registries" / (source.digest(registry_raw) + ".json"), registry_raw)
    reports = current_root / "reports"
    def save(name, value):
        source.exclusive(reports / (name + ".json"), source.encoded(value))
    save("attempt", dict(started, attempt_sha256=attempt))
    try:
        current, current_path = collector(current_root / "store", CURRENT, "2000-01-01", through)
        save("provider-collection", current)
        archive, archive_path = collector(current_root / "store", ARCHIVE, "2000-01-01", through, mode="alfred")
        save("alfred-collection", archive)
        source.require(all(s["status"] == "COLLECTED" for s in current["sources"] + archive["sources"]),
                       "partial_collection")
        source.require({s["series"] for s in current["sources"]} == set(CURRENT) and
                       {s["series"] for s in archive["sources"]} == set(ARCHIVE), "cycle_source_scope")
        _, current_records = source.load_bundle(current_root / "store", current_path)
        current, _ = retain_expired_price_history(current_root / "store", current, current_records,
                                                  previous_receipt, old_current)
        current_raw = source.encoded(current)
        current_path = current_root / "store/receipts" / (source.digest(current_raw) + ".json")
        source.exclusive(current_path, current_raw)
        # The provider response receipt and the consolidated study receipt are
        # both retained; this report points to the latter for next-cycle restore.
        save("collection", current)
        calendar = calendar_fetcher(ARCHIVE, (source.stamp(now).date() - timedelta(days=30)).isoformat(),
                                   (source.stamp(now).date() + timedelta(days=90)).isoformat())
        save("calendar", calendar)
        plan = job_plan(now, previous_receipt, calendar)
        save("update-plan", plan)
        _, new_current = source.load_bundle(current_root / "store", current_path)
        _, new_archive = source.load_bundle(current_root / "store", archive_path)
        changes = dict(current=source_changes(old_current, new_current),
                       archive=source_changes(old_archive, new_archive))
        save("data-changes", changes)
        result = evaluator(current_root / "store", current_path, source.utc_now(), [archive_path])
        source.require(result.get("tests_declared") == 336 and
                       len(result.get("results", [])) == 336 and
                       set(result.get("coverage", {})) == {"SP500", "NASDAQCOM"}, "cycle_result_scope")
        save("alfred-evidence", result)
        if old_result:
            comparison = compare(old_result, result)
            comparison["economic_data_changed"] = any(r["changed"] for rows in changes.values() for r in rows)
            comparison["new_holdout_claimed"] = False
            save("comparison", comparison)
        save("engine-context", engine_context(result))
        save("cycle", dict(status="EVALUATED_PENDING_REMOTE_VERIFICATION", run_id=run_id,
            attempt_sha256=attempt, previous_commit=parent,
            reevaluated=True, predictions_frozen=False, selector_enabled=False,
            new_holdout_claimed=False, remote_verified=False))
        committed = checkpoint.publish(transport, current_root, parent, run_id)
    except Exception:
        # Do not serialize arbitrary provider/config exceptions or advance the head.
        failed = dict(schema="macro-cycle-attempt-v1", phase="FAILED", run_id=run_id,
            attempt_sha256=attempt, reason="COLLECTION_EVALUATION_OR_PERSISTENCE_BLOCKED",
            checkpoint_state="REQUIRES_REMOTE_RECONCILIATION",
            eligible_for_selector=False, parent=parent, finished_at=source.utc_now())
        try:
            failed["archive"] = checkpoint.publish(transport, current_root, parent, run_id, commit=False)
        except Exception:
            failed["failed_bundle_archived"] = False
        checkpoint.journal(transport, failed)
        raise ValueError("macro_cycle_blocked; inspect verified remote head before retry") from None
    finished = dict(schema="macro-cycle-attempt-v1", phase="COMPLETED", run_id=run_id,
        attempt_sha256=attempt, finished_at=source.utc_now(), checkpoint=committed,
        eligible_for_selector=False, scheduler_liveness_proven=False)
    finish_sha = checkpoint.journal(transport, finished)
    return dict(finished, finish_sha256=finish_sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    result = run_cycle(checkpoint.RcloneTransport(args.remote), args.workspace, args.run_id)
    source.exclusive(args.report, source.encoded(result))
    print("CYCLE_SUMMARY " + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
