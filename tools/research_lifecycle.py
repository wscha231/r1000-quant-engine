#!/usr/bin/env python3
"""Immutable research inputs and reevaluation plans, independent of paper state.

This module does not select stocks, run a backtest or certify source authenticity.
Public availability and our retrieval clock are distinct. SQLite serializes
head changes; content-addressed partitions preserve every earlier snapshot.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from urllib.parse import urlsplit


SCHEMA = "research-lifecycle-v1"
KINDS = {"price", "fundamental", "macro", "membership", "corporate_action", "quality", "fx", "benchmark"}
EVIDENCE = {"public_archive", "current_only", "retrospective_price"}
FIELDS = {"source", "kind", "entity", "field", "effective_at", "available_at", "value", "evidence"}
SHA = re.compile(r"^[a-f0-9]{64}$")
LABEL = re.compile(r"^[A-Za-z0-9:._-]{1,100}$")
MAX_JSON = 32 * 1024 * 1024


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def timestamp(value):
    require(isinstance(value, str), "timestamp_type")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(dt.tzinfo is not None and dt.utcoffset() is not None, "timestamp_requires_timezone")
    return dt.astimezone(timezone.utc)


def iso(value):
    return timestamp(value).isoformat().replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def safe_path(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink_path")
    return path


def read_json(path):
    path = safe_path(path)
    require(path.is_file() and path.stat().st_size <= MAX_JSON, "json_missing_or_size_bound")
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate_json_key")
            out[key] = value
        return out
    return json.loads(path.read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite_json")))


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_record(record, retrieved_at):
    require(isinstance(record, dict) and set(record) == FIELDS, "observation_schema")
    result = dict(record)
    for name in ("source", "entity", "field"):
        require(isinstance(result[name], str) and LABEL.fullmatch(result[name]), "observation_label")
    require(result["kind"] in KINDS and result["evidence"] in EVIDENCE, "observation_kind_or_evidence")
    result["effective_at"], result["available_at"] = iso(result["effective_at"]), iso(result["available_at"])
    require(timestamp(result["available_at"]) <= timestamp(retrieved_at), "publication_after_retrieval")
    if result["evidence"] == "current_only":
        require(result["available_at"] == iso(retrieved_at), "current_snapshot_backdated")
    if result["evidence"] == "retrospective_price":
        require(result["kind"] in {"price", "fx", "benchmark"}, "retrospective_price_wrong_kind")
        require(timestamp(result["effective_at"]) <= timestamp(result["available_at"]), "price_before_effective_time")
    v = result["value"]
    require(v is None or type(v) in {str, bool, int, float}, "observation_value_type")
    if type(v) in {int, float}:
        require(math.isfinite(v), "observation_nonfinite")
    if isinstance(v, str):
        require(len(v) <= 4000 and not any(ord(c) < 32 for c in v), "observation_text_bound")
    if result["kind"] in {"price", "fx", "benchmark"}:
        require(type(v) in {int, float} and v > 0, "nonpositive_price")
    return result


def logical_key(record):
    return tuple(record[x] for x in ("source", "kind", "entity", "field", "effective_at"))


def revision_key(record):
    return (*logical_key(record), record["available_at"])


def partition_key(record):
    # Human/provider names never become paths. Calendar month bounds updates.
    return digest([record[x] for x in ("source", "kind", "entity")] + [record["effective_at"][:7]])


class Store:
    def __init__(self, root, *, clock=utc_now):
        self.clock = clock
        self.root = safe_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects = safe_path(self.root / "objects")
        self.objects.mkdir(exist_ok=True)
        self.catalog = safe_path(self.root / "catalog.sqlite")
        with self.db() as con:
            con.executescript("""
              CREATE TABLE IF NOT EXISTS heads (name TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, object_sha TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, object_sha TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS finishes (id TEXT PRIMARY KEY, object_sha TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        con = sqlite3.connect(safe_path(self.catalog), timeout=10)
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def put(self, value):
        raw = canonical(value)
        require(len(raw) <= MAX_JSON, "object_size_bound")
        sha = hashlib.sha256(raw).hexdigest()
        destination = safe_path(self.objects / (sha + ".json"))
        if destination.exists():
            require(destination.read_bytes() == raw, "object_corruption")
            return sha
        fd, temporary = tempfile.mkstemp(dir=self.objects, prefix="pending-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError:
                require(destination.read_bytes() == raw, "object_collision")
            # Commit directory metadata before SQLite can publish a reference.
            directory = os.open(self.objects, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return sha

    def get(self, sha):
        require(isinstance(sha, str) and SHA.fullmatch(sha), "object_id")
        value = read_json(self.objects / (sha + ".json"))
        require(digest(value) == sha, "object_corruption")
        return value

    def head(self, name):
        require(isinstance(name, str) and LABEL.fullmatch(name), "dataset_name")
        with self.db() as con:
            row = con.execute("SELECT snapshot FROM heads WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def snapshot(self, sha):
        value = self.get(sha)
        require(value.get("schema_version") == SCHEMA and value.get("type") == "dataset", "snapshot_schema")
        return value

    def ingest(self, batch, *, expected_head):
        require(set(batch) == {"dataset", "data_kind", "retrieved_at", "source_uri", "raw_sha256", "records"}, "batch_schema")
        name, kind = batch["dataset"], batch["data_kind"]
        require(isinstance(name, str) and LABEL.fullmatch(name), "dataset_name")
        require(kind in {"REAL", "SYNTHETIC"}, "data_kind")
        retrieved = iso(batch["retrieved_at"])
        recorded = iso(self.clock())
        require(timestamp(retrieved) <= timestamp(recorded), "retrieval_in_future")
        uri = urlsplit(batch["source_uri"])
        require(uri.scheme == "https" and uri.hostname and not uri.username and not uri.password and
                not uri.query and not uri.fragment, "public_source_uri_required")
        require(SHA.fullmatch(batch["raw_sha256"] or ""), "raw_hash")
        require(isinstance(batch["records"], list) and 0 < len(batch["records"]) <= 100000, "batch_empty_or_too_large")
        records = [validate_record(row, retrieved) for row in batch["records"]]
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT snapshot FROM heads WHERE name=?", (name,)).fetchone()
            previous = row[0] if row else None
            require(previous == expected_head, "stale_dataset_head")
            old = self.snapshot(previous) if previous else {"partitions": {}, "data_kind": kind}
            require(old["data_kind"] == kind, "mixed_real_synthetic")
            parts, loaded, added = dict(old["partitions"]), {}, []
            for record in records:
                key = partition_key(record)
                if key not in loaded:
                    content = self.get(parts[key])["records"] if key in parts else []
                    loaded[key] = {revision_key(r): r for r in content}
                existing = loaded[key]
                # A repeated current-vintage download is a receipt, not new
                # history. Reuse first seen time only for an unchanged latest
                # observation, never after an intervening changed value.
                matches = [r for r in existing.values() if logical_key(r) == logical_key(record)]
                latest = max(matches, key=lambda r: timestamp(r["available_at"]), default=None)
                if latest and record["evidence"] == latest["evidence"] == "current_only":
                    require(timestamp(record["available_at"]) >= timestamp(latest["available_at"]), "retrieval_clock_regression")
                    if record["value"] == latest["value"]:
                        continue
                rkey = revision_key(record)
                if rkey in existing:
                    require(existing[rkey] == record, "ambiguous_same_time_revision")
                else:
                    existing[rkey] = record
                    added.append(record)
            for key, rows in loaded.items():
                parts[key] = self.put({"schema_version": SCHEMA, "type": "partition",
                                      "records": sorted(rows.values(), key=revision_key)})
            if parts == old["partitions"]:
                current = previous
            else:
                current = self.put({"schema_version": SCHEMA, "type": "dataset", "name": name,
                                    "data_kind": kind, "parent": previous, "partitions": parts})
            receipt = {"schema_version": SCHEMA, "type": "receipt", "dataset": name,
                       "snapshot": current, "parent": previous, "retrieved_at": retrieved, "recorded_at": recorded,
                       "source_uri": batch["source_uri"], "raw_sha256": batch["raw_sha256"],
                       "received_records": len(records), "added_records": len(added),
                       "input_records_hash": digest(records), "source_authenticity_verified": False}
            receipt_sha = self.put(receipt)
            con.execute("INSERT OR IGNORE INTO receipts VALUES (?,?)", (receipt_sha, receipt_sha))
            con.execute("INSERT INTO heads VALUES (?,?) ON CONFLICT(name) DO UPDATE SET snapshot=excluded.snapshot", (name, current))
        return {"status": "UNCHANGED" if current == previous else "UPDATED", "snapshot": current,
                "previous_snapshot": previous, "receipt": receipt_sha, "added_records": len(added),
                "changed_partitions": sum(parts.get(k) != old["partitions"].get(k) for k in parts),
                "historical_replay_ready": False, "orders_allowed": False}

    def records(self, snapshot):
        for sha in self.snapshot(snapshot)["partitions"].values():
            partition = self.get(sha)
            require(partition.get("type") == "partition", "partition_schema")
            yield from partition["records"]

    def as_of(self, snapshot, decision_at, *, evidence_mode="ARCHIVED_RECONSTRUCTION", retrieved_by=None):
        require(evidence_mode in {"ARCHIVED_RECONSTRUCTION", "FORWARD_RECORDED"}, "asof_mode")
        cutoff = timestamp(decision_at)
        if evidence_mode == "FORWARD_RECORDED":
            require(retrieved_by is not None and timestamp(retrieved_by) <= cutoff, "forward_retrieval_cutoff")
            # Receipt-set membership matters: a later receipt for unchanged
            # values must not backdate the system's first actual observation.
            allowed = set()
            with self.db() as con:
                receipts = [self.get(row[0]) for row in con.execute("SELECT object_sha FROM receipts")]
            ancestors, current = set(), snapshot
            while current:
                ancestors.add(current)
                current = self.snapshot(current)["parent"]
            for receipt in receipts:
                if (receipt["snapshot"] in ancestors and timestamp(receipt["retrieved_at"]) <= timestamp(retrieved_by)
                        and timestamp(receipt["recorded_at"]) <= timestamp(retrieved_by)):
                    allowed.update(digest(r) for r in self.records(receipt["snapshot"]))
        selected = {}
        for record in self.records(snapshot):
            if timestamp(record["available_at"]) > cutoff:
                continue
            if evidence_mode == "ARCHIVED_RECONSTRUCTION" and record["evidence"] == "current_only":
                continue
            if evidence_mode == "FORWARD_RECORDED" and digest(record) not in allowed:
                continue
            # Future-effective membership/actions are announcements, not
            # permission to apply an unoccurred event or a future price.
            if record["kind"] in {"price", "fx", "benchmark", "membership", "corporate_action"} and timestamp(record["effective_at"]) > cutoff:
                continue
            key = logical_key(record)
            if key not in selected or timestamp(selected[key]["available_at"]) < timestamp(record["available_at"]):
                selected[key] = record
        return sorted(selected.values(), key=revision_key)

    def begin(self, attempt_id, request, *, now):
        validate_request(request)
        self.snapshot(request["dataset_snapshot"])
        require(LABEL.fullmatch(attempt_id or ""), "attempt_id")
        require(timestamp(now) >= timestamp(request["window_end"]), "evaluation_before_window_end")
        recorded = iso(self.clock())
        require(timestamp(now) <= timestamp(recorded), "attempt_in_future")
        record = {"schema_version": SCHEMA, "type": "attempt", "attempt_id": attempt_id,
                  "started_at": iso(now), "recorded_at": recorded,
                  "request": request, "request_hash": digest(request)}
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            require(not con.execute("SELECT 1 FROM attempts WHERE id=?", (attempt_id,)).fetchone(), "attempt_already_registered")
            for row in con.execute("SELECT object_sha FROM attempts"):
                prior = self.get(row[0])["request"]
                require(prior["research_history_id"] == request["research_history_id"], "research_history_cannot_reset")
            sha = self.put(record)
            con.execute("INSERT INTO attempts VALUES (?,?)", (attempt_id, sha))
        return sha

    def finish(self, attempt_id, *, status, result_hash, reason, now):
        require(status in {"COMPLETED", "BLOCKED", "FAILED"}, "attempt_status")
        require(status != "COMPLETED" or SHA.fullmatch(result_hash or ""), "completed_result_hash")
        require(status == "COMPLETED" or result_hash is None, "blocked_result_hash")
        require(isinstance(reason, str) and LABEL.fullmatch(reason), "controlled_reason_required")
        with self.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT object_sha FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            require(row is not None, "unregistered_attempt")
            started = self.get(row[0])
            require(timestamp(now) >= timestamp(started["started_at"]), "finish_before_start")
            recorded = iso(self.clock())
            require(timestamp(now) <= timestamp(recorded), "finish_in_future")
            require(not con.execute("SELECT 1 FROM finishes WHERE id=?", (attempt_id,)).fetchone(), "attempt_already_finished")
            sha = self.put({"schema_version": SCHEMA, "type": "finish", "attempt_id": attempt_id,
                            "started_object": row[0], "status": status, "result_hash": result_hash,
                            "reason": reason, "finished_at": iso(now), "recorded_at": recorded, "performance_verified": False,
                            "promotion_allowed": False})
            con.execute("INSERT INTO finishes VALUES (?,?)", (attempt_id, sha))
        return sha

    def attempts(self):
        with self.db() as con:
            rows = list(con.execute("SELECT a.object_sha,f.object_sha FROM attempts a LEFT JOIN finishes f ON a.id=f.id ORDER BY a.id"))
        return [{"started": self.get(a), "finished": self.get(f) if f else None} for a, f in rows]

    def backup(self, destination):
        """Portable verified research checkpoint; never replace an existing path.

        SQLite's backup API snapshots the catalog consistently. Objects are
        immutable and published before catalog references, so copying objects
        afterwards is safe (unreferenced objects are harmless).
        """
        destination = safe_path(destination)
        require(not destination.exists(), "backup_destination_exists")
        require(destination != self.root and self.root not in destination.parents, "backup_inside_source")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent, prefix="research-backup-") as staging:
            staged = Path(staging) / "store"
            copy = Store(staged)
            with self.db() as source, copy.db() as target:
                source.backup(target)
            for path in self.objects.glob("*.json"):
                sha = path.stem
                require(copy.put(self.get(sha)) == sha, "backup_object_hash")
            with copy.db() as con:
                require(con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "backup_catalog_integrity")
                for row in con.execute("SELECT snapshot FROM heads"):
                    current = row[0]
                    while current:
                        snap = copy.snapshot(current)
                        for part in snap["partitions"].values():
                            copy.get(part)
                        current = snap["parent"]
                for table in ("receipts", "attempts", "finishes"):
                    for row in con.execute("SELECT object_sha FROM " + table):
                        copy.get(row[0])
            os.rename(staged, destination)
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return {"status": "VERIFIED_LOCAL_BACKUP", "remote_persistence_verified": False,
                "orders_allowed": False}


def validate_request(value):
    required = {"dataset_snapshot", "strategy_hash", "code_sha", "window_start", "window_end", "environment", "evidence_mode", "research_history_id"}
    require(isinstance(value, dict) and set(value) == required, "evaluation_request_schema")
    require(SHA.fullmatch(value["dataset_snapshot"]) and SHA.fullmatch(value["strategy_hash"]), "evaluation_hash")
    require(re.fullmatch(r"[a-f0-9]{40}", value["code_sha"] or ""), "evaluation_code_sha")
    require(timestamp(value["window_start"]) < timestamp(value["window_end"]), "evaluation_window")
    require(value["evidence_mode"] in {"ARCHIVED_RECONSTRUCTION", "FORWARD_RECORDED"}, "evaluation_evidence_mode")
    require(LABEL.fullmatch(value["research_history_id"] or ""), "research_history_id")
    env = value["environment"]
    require(isinstance(env, dict) and {"initial_cash_usd", "objective", "costs", "universe_policy", "benchmark_policy", "calendar_policy", "max_drawdown_abs"} <= set(env), "evaluation_environment")
    require(env["initial_cash_usd"] == 100000 and env["objective"] == "after_cost_usd_cagr", "fund_objective")
    require(isinstance(env["costs"], dict) and bool(env["costs"]), "cost_model_required")
    for name in ("universe_policy", "benchmark_policy", "calendar_policy"):
        require(isinstance(env[name], str) and LABEL.fullmatch(env[name]), "environment_policy_required")
    require(type(env["max_drawdown_abs"]) in {int, float} and 0 < env["max_drawdown_abs"] < 1, "drawdown_limit")
    canonical(value)


def reevaluation_plan(store, request, previous=None):
    validate_request(request)
    new = store.snapshot(request["dataset_snapshot"])
    base = {"schema_version": SCHEMA, "type": "reevaluation_plan", "request_hash": digest(request),
            "data_kind": new["data_kind"], "objective": "after_cost_usd_cagr",
            "initial_cash_usd": 100000, "historical_replay_ready": False,
            "automatic_promotion_allowed": False, "orders_allowed": False,
            "source_authenticity_verified": False, "unseen_holdout_claimed": False}
    if previous is None:
        return dict(base, status="INITIAL_RESEARCH", reason="new_independent_baseline",
                    affected_from=request["window_start"], execution="FULL_CHRONOLOGICAL_REPLAY",
                    legacy_artifacts_required=False)
    validate_request(previous)
    require(previous["research_history_id"] == request["research_history_id"], "research_history_cannot_reset")
    old = store.snapshot(previous["dataset_snapshot"])
    require(old["name"] == new["name"] and old["data_kind"] == new["data_kind"], "dataset_comparison_mismatch")
    require(timestamp(request["window_end"]) >= timestamp(previous["window_end"]), "evaluation_end_regression")
    changed_rules = [key for key in ("strategy_hash", "code_sha", "window_start", "environment", "evidence_mode") if previous[key] != request[key]]
    if changed_rules:
        environment_changed = any(key in changed_rules for key in ("environment", "window_start", "evidence_mode"))
        return dict(base, status="FULL_REEVALUATION", reason="policy_code_or_environment_changed",
                    changed_rules=changed_rules, affected_from=request["window_start"],
                    execution="FULL_CHRONOLOGICAL_REPLAY", paired_comparison_required=True,
                    comparison_kind="ENVIRONMENT_SENSITIVITY" if environment_changed else "STRATEGY_OR_CODE_STUDY",
                    direct_alpha_comparison_allowed=False,
                    comparison_requirement="rerun_both_strategies_on_identical_data_window_costs_universe_and_benchmarks")
    changed_parts = {k for k in set(old["partitions"]) | set(new["partitions"]) if old["partitions"].get(k) != new["partitions"].get(k)}
    times, affected_entities, changed_records = [], set(), 0
    for key in changed_parts:
        before = {digest(r): r for r in store.get(old["partitions"][key])["records"]} if key in old["partitions"] else {}
        after = {digest(r): r for r in store.get(new["partitions"][key])["records"]} if key in new["partitions"] else {}
        for h in before.keys() ^ after.keys():
            record = (before if h in before else after)[h]
            if request["evidence_mode"] == "ARCHIVED_RECONSTRUCTION" and record["evidence"] == "current_only":
                continue
            when = timestamp(record["available_at"])
            if record["kind"] in {"price", "fx", "benchmark", "membership", "corporate_action"}:
                when = max(when, timestamp(record["effective_at"]))
            if when <= timestamp(request["window_end"]):
                times.append(when)
                affected_entities.add(record["entity"])
                changed_records += 1
    extension = timestamp(request["window_end"]) > timestamp(previous["window_end"])
    if not times and not extension:
        return dict(base, status="NO_RELEVANT_CHANGE", reason="no_new_usable_inputs", execution="VERIFY_PRIOR_RESULT_BEFORE_REUSE",
                    reuse_requires_verified_result=True, affected_from=None,
                    changed_partitions=len(changed_parts), changed_records=0)
    if extension:
        times.append(timestamp(previous["window_end"]))
    affected = max(timestamp(request["window_start"]), min(times)).isoformat().replace("+00:00", "Z")
    return dict(base, status="DATA_REEVALUATION", reason="new_or_revised_observations" if changed_records else "window_extended",
                affected_from=affected, affected_entities=sorted(affected_entities), changed_records=changed_records,
                changed_partitions=len(changed_parts), paired_comparison_required=bool(changed_records),
                execution="FULL_CHRONOLOGICAL_REPLAY", preprocessing_reuse_before=affected,
                checkpoint_resume_supported=False,
                portfolio_path_dependency="rerun_all_holdings_cash_and_orders_together")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--batch", required=True)
    ingest.add_argument("--expected-head", default=None)
    plan = commands.add_parser("plan")
    plan.add_argument("--request", required=True)
    plan.add_argument("--previous")
    begin = commands.add_parser("begin")
    begin.add_argument("--attempt-id", required=True)
    begin.add_argument("--request", required=True)
    finish = commands.add_parser("finish")
    finish.add_argument("--attempt-id", required=True)
    finish.add_argument("--status", choices=["COMPLETED", "BLOCKED", "FAILED"], required=True)
    finish.add_argument("--result-hash")
    finish.add_argument("--reason", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--destination", required=True)
    commands.add_parser("attempts")
    args = parser.parse_args()
    store = Store(args.store)
    if args.command == "ingest":
        result = store.ingest(read_json(args.batch), expected_head=args.expected_head)
    elif args.command == "plan":
        result = reevaluation_plan(store, read_json(args.request), read_json(args.previous) if args.previous else None)
    elif args.command == "begin":
        result = {"attempt_object": store.begin(args.attempt_id, read_json(args.request), now=utc_now())}
    elif args.command == "finish":
        result = {"finish_object": store.finish(args.attempt_id, status=args.status, result_hash=args.result_hash,
                                               reason=args.reason, now=utc_now())}
    elif args.command == "backup":
        result = store.backup(args.destination)
    else:
        result = store.attempts()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
