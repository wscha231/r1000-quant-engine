"""Public status/count/hash metadata; private financial bytes never copied.

This writer does not parse analysis payloads or certify their completion.
Full outputs keep their existing private Drive publication/readback contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

SCHEMA = 'a4-public-metadata-v1'
OUTCOMES = frozenset({'success', 'failure', 'cancelled', 'skipped', 'NOT_RUN'})
MAX_FILE_BYTES = 32*1024**2
MAX_TOTAL_BYTES = 64*1024**2
FILES = {
    'daily': ('daily_crisis_monitor', ('summary.json', 'crisis_action_status.md')),
    'cloud': ('a4_research/attempts/{attempt}', ('cycle.json', 'market_analysis.json', 'market_analysis.md',
        'learning_context.json', 'learning_context.md', 'learning_attempt.json', 'drive-readback.json')),
    'primary': ('a4_primary_collection/{attempt}', ('execution.json', 'publication_failed.json',
        'market_analysis.json', 'market_analysis.md')),
    'native': ('a4_native_preparation/{attempt}', ('native-preparation.json',)),
    'data_center': ('a4_data_center/{attempt}', ('catalog.json', 'catalog.md', 'audit.json', 'execution.json',
        'publication_failed.json', 'failure.json', 'market_analysis.json', 'market_analysis.md')),
}


def need(ok):
    if not ok:
        raise ValueError('PUBLIC_METADATA_INVALID')


def regular_hash(path):
    """Bounded immutable-file read, without decoding private contents."""
    need(not any(p.is_symlink() for p in (path, *path.parents)))
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FILE_BYTES)
        sha, count = hashlib.sha256(), 0
        with os.fdopen(fd, 'rb') as handle:
            fd = None
            while chunk := handle.read(min(65536, MAX_FILE_BYTES-count+1)):
                count += len(chunk)
                need(count <= MAX_FILE_BYTES)
                sha.update(chunk)
            after = os.fstat(handle.fileno())
        current = path.lstat()
        fingerprint = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        need(fingerprint(before) == fingerprint(after) == fingerprint(current) and count == before.st_size)
        return sha.hexdigest(), count
    finally:
        if fd is not None:
            os.close(fd)


def build(outputs_root, *, attempt, code_sha, outcomes, restore='NOT_RUN', persist='NOT_RUN'):
    need(type(attempt) is str and re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*', attempt))
    need(type(code_sha) is str and re.fullmatch(r'[a-f0-9]{40}', code_sha))
    need(type(outcomes) is dict and set(outcomes) == set(FILES) and
         all(type(value) is str and value in OUTCOMES for value in outcomes.values()))
    need(type(restore) is str and restore in OUTCOMES and type(persist) is str and persist in OUTCOMES)
    root = Path(outputs_root)
    need(not any(p.is_symlink() for p in (root, *root.parents)))
    result, total = {}, 0
    for group, (directory, names) in FILES.items():
        references = []
        # A skipped step must never advertise a restored or checked-in old file.
        if outcomes[group] not in {'skipped', 'NOT_RUN'}:
            for name in names:
                path = root/directory.format(attempt=attempt)/name
                need(not any(p.is_symlink() for p in (path, *path.parents)))
                if not path.exists():
                    continue
                sha, size = regular_hash(path)
                total += size
                need(total <= MAX_TOTAL_BYTES)
                references.append(dict(name=name, sha256=sha, bytes=size))
        result[group] = dict(schema=SCHEMA, category=group, attempt=attempt, code_sha=code_sha,
            source_step_outcome=outcomes[group], restore_step_outcome=restore, persist_step_outcome=persist,
            private_file_count=len(references), private_files=references,
            financial_payload_included=False, semantic_validation='NOT_PERFORMED_HASH_METADATA_ONLY')
    return result


def write(outputs_root, **kwargs):
    receipts = build(outputs_root, **kwargs)
    dest = Path(outputs_root)/'a4_public_receipts'/kwargs['attempt']
    need(not any(p.is_symlink() for p in (dest, *dest.parents)))
    bodies = {dest/(key+'.json'): (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode()
              for key, value in receipts.items()}
    # Refuse a conflicting destination before any metadata publication.
    for path, raw in bodies.items():
        need(not path.is_symlink())
        if path.exists():
            sha, size = regular_hash(path)
            need(size == len(raw) and sha == hashlib.sha256(raw).hexdigest())
    dest.mkdir(parents=True, exist_ok=True)
    for path, raw in bodies.items():
        if not path.exists():
            with path.open('xb') as handle:
                handle.write(raw)
        sha, size = regular_hash(path)
        need(size == len(raw) and sha == hashlib.sha256(raw).hexdigest())
    return receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outputs-root', default='outputs')
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--code-sha', required=True)
    args = parser.parse_args()
    try:
        result = write(args.outputs_root, attempt=args.attempt, code_sha=args.code_sha,
            outcomes={key: os.environ.get('A4_PUBLIC_'+key.upper(), '') or 'NOT_RUN' for key in FILES},
            restore=os.environ.get('A4_PUBLIC_RESTORE', '') or 'NOT_RUN',
            persist=os.environ.get('A4_PUBLIC_PERSIST', '') or 'NOT_RUN')
        print(json.dumps(dict(status='PUBLIC_METADATA_WRITTEN', receipt_count=len(result))))
        return 0
    except (ValueError, OSError, TypeError, KeyError):
        print('{"status":"BLOCKED","blocker":"PUBLIC_METADATA_INVALID"}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
