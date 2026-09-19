"""Offline, bounded pure-task execution. Not a market/PIT or performance certifier.

One trusted coordinator writes a private local SQLite cache. Workers compute
only registered, reviewed Python functions; there is no shell/network dispatcher.
Callbacks must be pure. Source dependencies must be registered explicitly. This
is NOT a sandbox for hostile callbacks or a distributed/account transaction lock.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
import multiprocessing
import os
from pathlib import Path
import platform
import re
import sqlite3
import stat
import sys
import time
from typing import Any, Callable

VERSION = "exact-compute-v1"
MAX_BLOB = 16 * 1024 * 1024
MAX_PLAN_BYTES = 128 * 1024 * 1024
MAX_TASKS = 4096
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}")


class ComputeError(ValueError):
    pass


def need(ok: bool, reason: str) -> None:
    if not ok:
        raise ComputeError(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    # This contract intentionally allows JSON primitives only, with no floats:
    # numeric policy values use explicit strings to avoid NaN/type/coercion drift.
    def walk(v: Any, depth: int = 0) -> None:
        need(depth <= 32, "JSON_DEPTH")
        if type(v) is dict:
            need(all(type(k) is str for k in v), "JSON_KEY_TYPE")
            for k, child in v.items():
                need(len(k) <= 240, "JSON_KEY_LENGTH")
                walk(child, depth + 1)
        elif type(v) in (list, tuple):
            for child in v:
                walk(child, depth + 1)
        else:
            need(v is None or type(v) in (str, int, bool), "JSON_VALUE_TYPE")
            if type(v) is str:
                need(len(v) <= 1000000, "JSON_TEXT_LENGTH")
            if type(v) is int:
                need(abs(v) < 10**120, "JSON_INTEGER_RANGE")
    walk(value)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    need(len(raw) <= MAX_BLOB, "JSON_SIZE")
    return raw


def runtime_identity() -> dict[str, str]:
    return {"implementation": platform.python_implementation(),
            "python": platform.python_version(), "platform": sys.platform,
            "machine": platform.machine(), "byteorder": sys.byteorder,
            "optimize": str(sys.flags.optimize)}


def _id(value: Any) -> str:
    need(type(value) is str and ID.fullmatch(value) is not None, "INVALID_ID")
    return value


def cutoff(value: str) -> str:
    need(type(value) is str and "T" in value, "AWARE_CUTOFF_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ComputeError("INVALID_CUTOFF") from None
    need(parsed.tzinfo is not None, "AWARE_CUTOFF_REQUIRED")
    return parsed.astimezone(timezone.utc).isoformat()


def safe_file(path: Path, limit: int = MAX_BLOB) -> bytes:
    """Private workspace read; no symlink paths. Hostile concurrent writers excluded."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        need(not part.is_symlink(), "SYMLINK_PATH")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_size <= limit, "FILE_SIZE_OR_TYPE")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    need(len(raw) == before.st_size and len(raw) <= limit, "FILE_SIZE_CHANGED")
    need((before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size),
         "FILE_CHANGED_DURING_READ")
    return raw


@dataclass(frozen=True)
class Operator:
    name: str
    function: Callable[[dict[str, bytes], dict[str, Any]], bytes]
    # All transitive code/config dependencies outside function's own module.
    source_files: tuple[tuple[str, str], ...] = ()

    def identity(self) -> dict[str, Any]:
        _id(self.name)
        fn = self.function
        need(inspect.isfunction(fn) and "<locals>" not in fn.__qualname__
             and fn.__name__ != "<lambda>" and fn.__closure__ is None,
             "MODULE_LEVEL_FUNCTION_REQUIRED")
        source = inspect.getsourcefile(fn)
        need(source is not None, "SOURCE_REQUIRED")
        files = [("runtime", str(Path(__file__))), ("operator", source)]
        files += list(self.source_files)
        aliases = [alias for alias, _ in files]
        need(len(aliases) == len(set(aliases)), "DUPLICATE_SOURCE_ALIAS")
        return {"name": self.name, "callable": fn.__module__ + ":" + fn.__qualname__,
                "sources": {_id(alias): sha(safe_file(Path(path)))
                            for alias, path in sorted(files)},
                "runtime": runtime_identity()}


@dataclass(frozen=True)
class Task:
    task_id: str
    operation: str
    inputs: dict[str, bytes]
    parameters: dict[str, Any]
    # named argument -> predecessor task id. No time partitioning implied.
    dependencies: dict[str, str]
    context: dict[str, Any]


def shard_ids(ids: list[str], shards: int) -> list[list[str]]:
    need(type(shards) is int and 1 <= shards <= 128, "SHARD_COUNT")
    need(type(ids) is list and 1 <= len(ids) <= 20000, "ID_COUNT")
    for identity in ids:
        _id(identity)
    need(len(ids) == len(set(ids)), "DUPLICATE_IDS")
    groups: list[list[str]] = [[] for _ in range(shards)]
    for identity in sorted(ids):
        groups[int(sha(identity.encode()), 16) % shards].append(identity)
    return groups


def join_shards(expected: list[str], groups: list[list[str]]) -> list[str]:
    need(type(expected) is list and len(expected) == len(set(expected)), "DUPLICATE_IDS")
    flat = [identity for group in groups for identity in group]
    need(len(flat) == len(set(flat)), "DUPLICATE_SHARD_MEMBER")
    need(set(flat) == set(expected), "INCOMPLETE_SHARD_SET")
    return sorted(flat)


class ExactCache:
    """Atomic per-task commits. A local digest detects damage, not malicious forgery.

    Keep this DB in a private trusted workspace. Never restore an untrusted public
    Actions cache or treat this as an accepted ledger. No approximate-key fallback.
    """
    def __init__(self, directory: Path):
        self.directory = Path(os.path.abspath(directory))
        for part in (self.directory, *self.directory.parents):
            need(not part.is_symlink(), "SYMLINK_CACHE")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "compute.sqlite3"
        for suffix in ("", "-journal", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            need(not p.is_symlink(), "SYMLINK_CACHE")
            if p.exists():
                need(p.is_file(), "NONREGULAR_CACHE")
        self.db = sqlite3.connect(self.path, timeout=5)
        try:
            self.db.execute("PRAGMA trusted_schema=OFF")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("CREATE TABLE IF NOT EXISTS results ("
                            "key TEXT PRIMARY KEY, spec BLOB NOT NULL, "
                            "output BLOB NOT NULL, output_hash TEXT NOT NULL)")
            self.db.commit()
        except Exception:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> ExactCache:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def get(self, spec: bytes) -> bytes | None:
        key = sha(spec)
        lengths = self.db.execute("SELECT length(spec),length(output) FROM results WHERE key=?",
                                  (key,)).fetchone()
        if lengths is None:
            return None
        need(0 <= lengths[0] <= MAX_BLOB and 0 <= lengths[1] <= MAX_BLOB, "CACHE_SIZE")
        row = self.db.execute("SELECT spec,output,output_hash FROM results WHERE key=?",
                              (key,)).fetchone()
        need(row is not None and row[0] == spec and sha(row[0]) == key, "CACHE_SPEC_MISMATCH")
        need(type(row[1]) is bytes and sha(row[1]) == row[2], "CACHE_OUTPUT_MISMATCH")
        return row[1]

    def put(self, spec: bytes, output: bytes) -> None:
        need(type(output) is bytes and len(output) <= MAX_BLOB, "OUTPUT_SIZE_OR_TYPE")
        key = sha(spec)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO results VALUES (?,?,?,?)",
                            (key, spec, output, sha(output)))
            # Same key with different output is nondeterminism, not permission to replace.
            need(self.get(spec) == output, "CACHE_CONFLICT")


def _worker(op: Operator, expected_identity: dict[str, Any],
            payloads: dict[str, bytes], params: bytes) -> dict[str, Any]:
    begin, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        need(op.identity() == expected_identity, "WORKER_CODE_CHANGED")
        value = op.function(dict(payloads), json.loads(params))
        need(type(value) is bytes and len(value) <= MAX_BLOB, "OUTPUT_SIZE_OR_TYPE")
        need(op.identity() == expected_identity, "WORKER_CODE_CHANGED")
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss_bytes = int(rss if sys.platform == "darwin" else rss * 1024)
        except ImportError:
            rss_bytes = None
        return {"ok": True, "output": value, "cpu_ns": time.process_time_ns() - cpu,
                "elapsed_ns": time.perf_counter_ns() - begin, "peak_rss_bytes": rss_bytes,
                "worker_pid": os.getpid()}
    except Exception as exc:
        # No raw API exception/payload disclosure in execution receipts.
        return {"ok": False, "error_type": type(exc).__name__}


def _freeze(tasks: list[Task], registry: dict[str, Operator]) -> dict[str, Task]:
    need(type(tasks) is list and 1 <= len(tasks) <= MAX_TASKS, "TASK_COUNT")
    result: dict[str, Task] = {}
    size = 0
    for t in tasks:
        need(type(t) is Task, "TASK_TYPE")
        _id(t.task_id); _id(t.operation)
        need(t.task_id not in result, "DUPLICATE_TASK")
        need(t.operation in registry and registry[t.operation].name == t.operation, "UNKNOWN_OPERATOR")
        need(type(t.inputs) is dict and type(t.parameters) is dict
             and type(t.dependencies) is dict and type(t.context) is dict, "TASK_MAPPING")
        for name, raw in t.inputs.items():
            _id(name)
            need(type(raw) is bytes and len(raw) <= MAX_BLOB, "INPUT_SIZE_OR_TYPE")
            size += len(raw)
        need(size <= MAX_PLAN_BYTES, "PLAN_INPUT_SIZE")
        for name, dep in t.dependencies.items():
            _id(name); _id(dep)
        need(not set(t.inputs) & set(t.dependencies), "INPUT_DEP_ALIAS_COLLISION")
        ctx = json.loads(canonical(t.context))
        need("decision_cutoff" in ctx and "universe_sha256" in ctx, "CONTEXT_REQUIRED")
        ctx["decision_cutoff"] = cutoff(ctx["decision_cutoff"])
        need(type(ctx["universe_sha256"]) is str and
             re.fullmatch(r"[0-9a-f]{64}", ctx["universe_sha256"]) is not None, "UNIVERSE_HASH_FORMAT")
        # This is exact context identity, NOT authentication of PIT/universe claims.
        result[t.task_id] = Task(t.task_id, t.operation, dict(t.inputs),
                                json.loads(canonical(t.parameters)), dict(t.dependencies), ctx)
    need(all(dep in result for t in result.values() for dep in t.dependencies.values()), "MISSING_DEPENDENCY")
    remaining, done = set(result), set()
    while remaining:
        ready = {i for i in remaining if set(result[i].dependencies.values()) <= done}
        need(bool(ready), "DEPENDENCY_CYCLE")
        done |= ready
        remaining -= ready
    return result


def run(tasks: list[Task], registry: dict[str, Operator], cache_dir: Path,
        *, workers: int = 1, stop_after_tasks: int | None = None) -> dict[str, Any]:
    """Run a bounded DAG; successes survive failure. No economic/ledger side effects.

    stop_after_tasks is a cooperative test/resume boundary, not hard-kill recovery
    of a task already in flight. Complete individual tasks are the checkpoints.
    """
    need(type(workers) is int and 1 <= workers <= 4, "WORKER_BUDGET")
    need(stop_after_tasks is None or type(stop_after_tasks) is int
         and stop_after_tasks >= 1, "STOP_BUDGET")
    graph = _freeze(tasks, registry)
    identities = {name: registry[name].identity() for name in sorted({t.operation for t in tasks})}
    start = time.perf_counter_ns()
    results: dict[str, bytes] = {}
    receipts: dict[str, dict[str, Any]] = {}
    remaining = set(graph)
    executed = hits = deduped = 0
    stored_output_bytes = 0
    pool: ProcessPoolExecutor | None = None
    with ExactCache(cache_dir) as cache:
        try:
            while remaining:
                ready = sorted(i for i in remaining if all(d in receipts for d in graph[i].dependencies.values()))
                need(bool(ready), "INTERNAL_DAG_DEADLOCK")
                work = []
                for i in ready:
                    t = graph[i]
                    if any(d not in results for d in t.dependencies.values()):
                        receipts[i] = {"status": "BLOCKED_DEPENDENCY"}
                        remaining.remove(i)
                        continue
                    dep_info = {name: {"task_key": receipts[d]["task_key"], "output_hash": sha(results[d])}
                                for name, d in sorted(t.dependencies.items())}
                    spec = canonical({"version": VERSION, "operator": identities[t.operation],
                                      "inputs": {k: sha(v) for k, v in sorted(t.inputs.items())},
                                      "dependencies": dep_info, "parameters": t.parameters,
                                      "context": t.context})
                    value = cache.get(spec)
                    if value is not None:
                        need(stored_output_bytes + len(value) <= MAX_PLAN_BYTES, "PLAN_OUTPUT_SIZE")
                        stored_output_bytes += len(value)
                        results[i] = value; hits += 1
                        receipts[i] = {"status": "CACHE_HIT", "task_key": sha(spec), "output_hash": sha(value)}
                        remaining.remove(i)
                    else:
                        payloads = dict(t.inputs) | {k: results[d] for k, d in t.dependencies.items()}
                        need(sum(len(v) for v in payloads.values()) <= MAX_PLAN_BYTES, "TASK_PAYLOAD_SIZE")
                        work.append((i, spec, payloads))
                # Fixed bounded batches; one coordinator commits/cache-publishes outcomes.
                for offset in range(0, len(work), workers):
                    if stop_after_tasks is not None and executed >= stop_after_tasks:
                        break
                    batch = work[offset:offset + workers]
                    if stop_after_tasks is not None:
                        batch = batch[:stop_after_tasks - executed]
                    unique: dict[str, tuple[str, bytes, dict[str, bytes]]] = {}
                    aliases: dict[str, list[str]] = {}
                    for i, spec, payloads in batch:
                        key = sha(spec)
                        aliases.setdefault(key, []).append(i)
                        unique.setdefault(key, (i, spec, payloads))
                    futures = {}
                    completed = []
                    for key, (i, spec, payloads) in unique.items():
                        # Earlier batch may have produced this exact key.
                        cached = cache.get(spec)
                        if cached is not None:
                            completed.append((key, {"ok": True, "output": cached, "reused": True}))
                            continue
                        t = graph[i]
                        args = (registry[t.operation], identities[t.operation], payloads, canonical(t.parameters))
                        if workers == 1 or len(unique) == 1:
                            completed.append((key, _worker(*args)))
                        else:
                            if pool is None:
                                pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))
                            futures[pool.submit(_worker, *args)] = key
                    for future in as_completed(futures):
                        try:
                            result = future.result()
                        except Exception as exc:
                            result = {"ok": False, "error_type": type(exc).__name__}
                        completed.append((futures[future], result))
                    for key, result in sorted(completed):
                        _, spec, _ = unique[key]
                        reused = result.get("reused", False)
                        if reused: hits += len(aliases[key])
                        else: executed += 1
                        if result["ok"]:
                            added_bytes = len(result["output"]) * len(aliases[key])
                            need(stored_output_bytes + added_bytes <= MAX_PLAN_BYTES, "PLAN_OUTPUT_SIZE")
                            stored_output_bytes += added_bytes
                            cache.put(spec, result["output"])
                        for n, i in enumerate(aliases[key]):
                            receipt = {"task_key": key, "status": "FAILED"}
                            if result["ok"]:
                                results[i] = result["output"]
                                receipt |= {"output_hash": sha(result["output"]),
                                            "status": "CACHE_HIT" if reused else "DEDUPLICATED" if n else "COMPUTED"}
                                if not reused and n: deduped += 1
                                if not reused and n == 0:
                                    receipt |= {k: v for k, v in result.items() if k not in {"ok", "output"}}
                            else:
                                receipt["error_type"] = result["error_type"]
                            receipts[i] = receipt; remaining.remove(i)
                    if stop_after_tasks is not None and executed >= stop_after_tasks:
                        break
                if stop_after_tasks is not None and executed >= stop_after_tasks and remaining:
                    break
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
    for i in sorted(remaining):
        receipts[i] = {"status": "PENDING_RESUME"}
    for name, identity in identities.items():
        need(registry[name].identity() == identity, "COORDINATOR_CODE_CHANGED")
    semantic = {i: sha(raw) for i, raw in sorted(results.items())}
    complete = len(results) == len(graph)
    return {"status": "COMPLETE" if complete else "INCOMPLETE",
            "operator_identities": identities,
            "outputs": results, "output_hashes": semantic,
            "semantic_output_hash": sha(canonical(semantic)) if complete else None,
            "task_receipts": dict(sorted(receipts.items())),
            "stats": {"tasks": len(graph), "computed": executed, "cache_hits": hits,
                      "deduplicated": deduped, "workers": workers,
                      "elapsed_ns": time.perf_counter_ns() - start,
                      "worker_cpu_ns": sum(r.get("cpu_ns", 0) for r in receipts.values()),
                      "worker_peak_rss_bytes": max((r.get("peak_rss_bytes") or 0 for r in receipts.values()), default=0)},
            "authority": "RESEARCH_ONLY", "mission_status": "NOT_PROVEN",
            "orders_allowed": False, "production_promotion_allowed": False}
