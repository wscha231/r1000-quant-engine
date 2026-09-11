#!/usr/bin/env python3
"""Private append-only research checkpoints; verify downloaded bytes before commit.

This namespace is independent of Run287 accepted accounts and PR #411's catalog.
One writer is required. Conflicting heads fail closed instead of choosing a winner.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import random
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.macro_history_sources import digest, encoded, exclusive, require, utc_now

SHA = re.compile(r"[a-f0-9]{64}")
MAX_OBJECT = 20 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_FILES = 10000
NAMESPACE = "research/macro_technical_evidence/v1/"


def transport_failure(stderr, command, returncode):
    """Fixed diagnostic categories, never provider bodies, tokens or paths."""
    body = stderr.decode("utf-8", errors="replace").lower()
    categories = {
        # Provider reason takes precedence over wrapper text such as
        # "couldn't find root: ... userRateLimitExceeded".
        "RATE_LIMIT": ("ratelimit", "rate limit", "too many requests", "error 429"),
        "DOWNLOAD_QUOTA": ("downloadquotaexceeded", "download quota"),
        "STORAGE_QUOTA": ("storagequotaexceeded", "storage quota"),
        "AUTHENTICATION": ("invalid_grant", "invalid credentials", "unauthorized", "invalid authentication"),
        "PERMISSION": ("permission", "forbidden", "access denied", "cannotdownloadfile"),
        "QUOTA": ("quota",),
        "DOWNLOAD_RESTRICTED": ("abusive", "malware", "virus"),
        "NOT_DOWNLOADABLE": ("not downloadable", "only files with binary content", "not a file", "is a directory"),
        "TIMEOUT": ("timeout", "timed out", "deadline exceeded"),
        "NOT_FOUND": ("not found", "couldn't find", "doesn't exist", "does not exist"),
    }
    category = next((name for name, terms in categories.items() if any(t in body for t in terms)), "UNCLASSIFIED")
    verb = command if command in {"mkdir", "cat", "lsjson", "copy", "copyto"} else "command"
    return f"research_transport_failed:{verb}:exit_{int(returncode)}:{category}"


def safe_path(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in [path, *path.parents]), "checkpoint_symlink")
    return path


def relative(path):
    require(isinstance(path, str) and not path.startswith("/") and
            all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) and p not in (".", "..")
                for p in path.split("/")), "checkpoint_relative_path")
    return path


def data_path(path):
    relative(path)
    require(re.fullmatch(r"store/(objects/[a-f0-9]{64}|receipts/[a-f0-9]{64}\.json|registries/[a-f0-9]{64}\.json)|reports/[a-z][a-z0-9-]*\.json", path),
            "checkpoint_file_scope")
    return path


def checked_bytes(path, expected=None):
    path = safe_path(path)
    require(path.is_file() and 0 < path.stat().st_size <= MAX_OBJECT, "checkpoint_object_size")
    raw = path.read_bytes()
    if expected:
        require(digest(raw) == expected, "checkpoint_hash")
    return raw


class LocalTransport:
    """Filesystem transport for meaningful offline fault injection, never remote proof."""
    remote_verified = False

    def __init__(self, root):
        self.root = safe_path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def names(self, prefix):
        path = safe_path(self.root / relative(prefix))
        if not path.exists():
            return []
        return sorted(p.name for p in path.iterdir() if p.is_file())

    def read(self, path):
        return checked_bytes(self.root / relative(path))

    def write(self, path, raw):
        exclusive(self.root / relative(path), raw)

    def upload(self, objects):
        for path in objects.iterdir():
            self.write("objects/" + path.name, checked_bytes(path, path.name))

    def download(self, hashes, target):
        for sha in hashes:
            exclusive(target / sha, self.read("objects/" + sha))


class RcloneTransport:
    remote_verified = True

    def __init__(self, remote):
        # No arbitrary remote, broker/ledger path, shell expansion or URL allowed.
        require(re.fullmatch(r"gdrive:(r1000_top30_institutional/)?" + NAMESPACE +
                            r"(scheduled|pr-[1-9][0-9]*)", remote), "research_remote_scope")
        self.root = remote
        self.binary = os.environ.get("MACRO_RCLONE_BIN", "rclone")
        self.folder_id = None
        # An lsjson --stat of the filesystem root may omit its ID. Obtain the
        # directory's ID from its parent's listing instead, rejecting duplicates.
        parent, leaf = remote.rsplit("/", 1)
        def folders():
            rows = json.loads(self.read_call("lsjson", parent, "--dirs-only"))
            require(isinstance(rows, list), "research_parent_listing")
            return [r for r in rows if r.get("Name") == leaf]
        created = False
        try:
            matches = folders()
        except ValueError as exc:
            if not str(exc).endswith(":NOT_FOUND"):
                raise
            self.call("mkdir", self.root + "/commits")
            created = True
            matches = folders()
        if not matches and not created:
            self.call("mkdir", self.root + "/commits")
            matches = folders()
        require(len(matches) == 1, "research_folder_missing_or_ambiguous")
        info = matches[0]
        require(isinstance(info, dict) and info.get("IsDir") is True and
                re.fullmatch(r"[A-Za-z0-9_-]+", info.get("ID", "")), "research_folder_identity")
        # Pin the narrower, already-resolved research folder for this process.
        # Re-resolving every ancestor for each object amplifies API request load.
        self.folder_id = info["ID"]
        self.root = "gdrive:"

    def path(self, suffix):
        return self.root + ("" if self.root.endswith(":") else "/") + relative(suffix)

    def call(self, *args):
        # These names collide with rclone's own environment options. Never pass
        # a whole config secret through rclone's option parser or error output.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("RCLONE_", "MACRO_DRIVE_"))
               and k not in {"FRED_API_KEY", "GH_TOKEN", "GITHUB_TOKEN"}}
        env["RCLONE_CONFIG"] = os.environ["MACRO_RCLONE_CONFIG"]
        root_flags = ["--drive-root-folder-id", self.folder_id] if getattr(self, "folder_id", None) else []
        try:
            result = subprocess.run([self.binary, *map(str, args), *root_flags, "--retries", "2",
                "--low-level-retries", "2", "--contimeout", "20s", "--timeout", "60s",
                "--tpslimit", "2", "--tpslimit-burst", "1"],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=480)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("research_transport_unavailable") from None
        # Rclone diagnostic bodies may include auth/config. Only fixed codes escape.
        if result.returncode:
            raise ValueError(transport_failure(result.stderr, str(args[0]), result.returncode))
        require(len(result.stdout) <= MAX_OBJECT, "transport_output_size")
        return result.stdout

    def names(self, prefix):
        rows = json.loads(self.read_call("lsjson", self.path(prefix), "--files-only"))
        names = [r["Name"] for r in rows]
        require(len(names) == len(set(names)), "duplicate_remote_names")
        return sorted(names)

    def read_call(self, *args, retry_known_file=False):
        # Seven total reads span a one-minute quota window; no individual
        # backoff exceeds 33 seconds, and retries are never indefinite.
        for attempt in range(7):
            try:
                return self.call(*args)
            except ValueError as exc:
                # A known hash-addressed file can briefly disappear from a path
                # lookup after a successful upload/read. Retry the SAME file;
                # persistent absence still blocks and never becomes genesis.
                retry = str(exc).endswith(":RATE_LIMIT") or (
                    retry_known_file and str(exc).endswith(":NOT_FOUND"))
                if not retry or attempt == 6:
                    raise
                time.sleep(2 ** attempt + random.random())

    def read(self, path):
        return self.read_call("cat", self.path(path), retry_known_file=True)

    def write(self, path, raw):
        with tempfile.TemporaryDirectory(prefix="macro-transfer-") as tmp:
            local = Path(tmp) / "payload"
            exclusive(local, raw)
            self.call("copyto", local, self.path(path), "--immutable", "--checksum")
        require(self.read(path) == raw, "remote_write_readback")

    def upload(self, objects):
        self.call("copy", objects, self.path("objects"), "--immutable", "--checksum", "--transfers", "4")

    def download(self, hashes, target):
        with tempfile.TemporaryDirectory(prefix="macro-filelist-") as tmp:
            listing = Path(tmp) / "objects.txt"
            listing.write_text("\n".join(sorted(hashes)) + "\n")
            self.call("copy", self.path("objects"), target, "--files-from-raw", listing,
                      "--immutable", "--checksum", "--transfers", "4", "--max-transfer", "512M",
                      "--cutoff-mode", "HARD")


def read_json(transport, path):
    raw = transport.read(path)
    require(0 < len(raw) <= MAX_OBJECT, "remote_object_size")
    require(digest(raw) == Path(path).stem, "remote_identity")
    return json.loads(raw)


def head(transport):
    """Check the whole commit chain, including fork and duplicate detection."""
    names = transport.names("commits")
    require(len(names) <= MAX_FILES and len(names) == len(set(names)), "commit_count")
    entries = {}
    for name in names:
        require(re.fullmatch(r"[a-f0-9]{64}\.json", name), "commit_filename")
        value = read_json(transport, "commits/" + name)
        require(value.get("schema") == "macro-checkpoint-commit-v1" and
                SHA.fullmatch(value.get("manifest", "")) and
                value.get("eligible_for_selector") is False, "commit_schema")
        entries[name[:-5]] = value
    parent, generation, last = None, 1, None
    while entries:
        candidates = [(sha, v) for sha, v in entries.items() if v.get("parent") == parent]
        require(len(candidates) == 1, "checkpoint_fork_or_broken_chain")
        sha, last = candidates[0]
        require(last.get("generation") == generation, "checkpoint_generation")
        del entries[sha]
        parent, generation = sha, generation + 1
    return (parent, last)


def verify(root, manifest):
    root = safe_path(root)
    require(manifest.get("schema") == "macro-checkpoint-manifest-v1", "manifest_schema")
    files = manifest["files"]
    require(0 < len(files) <= MAX_FILES, "manifest_file_count")
    sizes = manifest["sizes"]
    require(set(sizes) == set(files) and all(type(n) is int and 0 < n <= MAX_OBJECT for n in sizes.values())
            and sum(sizes.values()) <= MAX_TOTAL, "manifest_size_bounds")
    total = 0
    for name, sha in files.items():
        data_path(name)
        require(SHA.fullmatch(sha), "manifest_object_identity")
        raw = checked_bytes(root / name, sha)
        require(len(raw) == sizes[name], "manifest_size_mismatch")
        total += len(raw)
        if name.startswith(("store/objects/", "store/receipts/", "store/registries/")):
            require(Path(name).stem == sha, "store_filename_hash")
        if name.startswith("store/receipts/"):
            receipt = json.loads(raw)
            require(receipt.get("schema") == "macro-history-bundle-v1", "stored_receipt_schema")
            registry_hash = receipt["registry_sha256"]
            require(files.get("store/registries/" + registry_hash + ".json") == registry_hash,
                    "archived_registry_missing")
            for item in receipt["sources"]:
                if item["status"] == "COLLECTED":
                    for object_hash in item["raw_sha256"] + [item["records_sha256"]]:
                        require(files.get("store/objects/" + object_hash) == object_hash,
                                "receipt_dependency_missing")
    require(total <= MAX_TOTAL, "checkpoint_total_size")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() or p.is_symlink()}
    require(actual == set(files), "checkpoint_file_set")
    return {"files": len(files), "bytes": total}


def prepare(root, staging):
    root, staging = safe_path(root), safe_path(staging)
    files, sizes = {}, {}
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "checkpoint_symlink")
        if path.is_file():
            name = data_path(path.relative_to(root).as_posix())
            raw = checked_bytes(path)
            sha = digest(raw)
            exclusive(staging / "objects" / sha, raw)
            files[name] = sha
            sizes[name] = len(raw)
    manifest = dict(schema="macro-checkpoint-manifest-v1", files=files, sizes=sizes,
                    eligible_for_selector=False)
    verify(root, manifest)
    return manifest


def restore_manifest(transport, manifest_sha, destination):
    destination = safe_path(destination)
    require(not destination.exists(), "restore_destination_exists")
    manifest = read_json(transport, "manifests/" + manifest_sha + ".json")
    require(manifest.get("schema") == "macro-checkpoint-manifest-v1", "manifest_schema")
    files = manifest["files"]
    require(0 < len(files) <= MAX_FILES, "manifest_file_count")
    sizes = manifest["sizes"]
    require(set(sizes) == set(files) and all(type(n) is int and 0 < n <= MAX_OBJECT for n in sizes.values())
            and sum(sizes.values()) <= MAX_TOTAL, "manifest_size_bounds")
    for name, sha in files.items():
        data_path(name)
        require(SHA.fullmatch(sha), "manifest_object_identity")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix="macro-restore-") as tmp:
        objects, staged = Path(tmp) / "objects", Path(tmp) / "restored"
        objects.mkdir(); staged.mkdir()
        transport.download(set(files.values()), objects)
        for name, sha in files.items():
            exclusive(staged / name, checked_bytes(objects / sha, sha))
        verified = verify(staged, manifest)
        os.rename(staged, destination)
    return dict(verified, manifest_sha256=manifest_sha,
                remote_verified=transport.remote_verified)


def restore_latest(transport, destination):
    sha, current = head(transport)
    if current is None:
        require(not Path(destination).exists(), "restore_destination_exists")
        return dict(status="GENESIS_REQUIRED", commit=None, remote_verified=False)
    restored = restore_manifest(transport, current["manifest"], destination)
    return dict(restored, status="RESTORED_AND_VERIFIED", commit=sha, generation=current["generation"])


def publish(transport, root, expected_parent, run_id, *, commit=True):
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", run_id), "checkpoint_run_id")
    before, prior = head(transport)
    require(before == expected_parent, "checkpoint_stale_parent")
    with tempfile.TemporaryDirectory(prefix="macro-checkpoint-") as tmp:
        staging = Path(tmp)
        manifest = prepare(root, staging)
        raw = encoded(manifest)
        manifest_sha = digest(raw)
        transport.upload(staging / "objects")
        transport.write("manifests/" + manifest_sha + ".json", raw)
        restored = restore_manifest(transport, manifest_sha, staging / "roundtrip")
        require(prepare(staging / "roundtrip", staging / "second") == manifest, "restore_identity")
    # Expected-parent check again immediately before append; external concurrent
    # writers are unsupported and are detected by the subsequent chain check.
    require(head(transport)[0] == expected_parent, "checkpoint_stale_parent")
    record = dict(schema="macro-checkpoint-commit-v1", parent=before,
        generation=(prior["generation"] + 1) if prior else 1, manifest=manifest_sha,
        run_id=run_id, created_at=utc_now(), eligible_for_selector=False)
    sha = digest(encoded(record))
    if commit:
        if transport.remote_verified:
            print("CHECKPOINT_PREPARED " + json.dumps(dict(
                phase="ROUNDTRIP_VERIFIED_PUBLICATION_PENDING", manifest_sha256=manifest_sha,
                proposed_commit=sha, parent=before, files=restored["files"], bytes=restored["bytes"],
                eligible_for_selector=False), sort_keys=True))
        transport.write("commits/" + sha + ".json", encoded(record))
        require(head(transport)[0] == sha, "checkpoint_publication_conflict")
    return dict(restored, status="COMMITTED" if commit else "ARCHIVED_FAILED_ATTEMPT",
                commit=sha if commit else None, parent=before, eligible_for_selector=False)


def journal(transport, value):
    raw = encoded(value)
    sha = digest(raw)
    transport.write("attempts/" + sha + ".json", raw)
    return sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["publish", "restore"])
    parser.add_argument("--remote", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-id", default="manual")
    parser.add_argument("--expected-parent")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    transport = RcloneTransport(args.remote)
    result = restore_latest(transport, args.root) if args.action == "restore" else publish(
        transport, args.root, args.expected_parent, args.run_id)
    exclusive(args.report, encoded(result))
    print("CHECKPOINT_SUMMARY " + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
