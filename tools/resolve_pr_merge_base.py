#!/usr/bin/env python3
"""Resolve the actual base parent of an authenticated PR merge checkout.

The event base may be older than the synthetic merge's actual base. Comparing
that stale base to HEAD incorrectly attributes upstream bot artifacts to a PR.
No fallback, network, tree mutation, guard exceptions or approval is provided.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys


class MergeScopeError(ValueError):
    """The checked-out merge cannot be bound to the event's PR identity."""


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=root, check=True,
                                capture_output=True, text=True, timeout=15)
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        raise MergeScopeError("PR_SCOPE_GIT_OBJECTS_OR_ANCESTRY_UNAVAILABLE") from exc


def resolve_base(root: Path, *, event_base: str, event_head: str) -> str:
    """Bind the two actual parents, then preserve the existing merge-tree guard."""
    for value in (event_base, event_head):
        if type(value) is not str or not re.fullmatch(r"[0-9a-f]{40}", value):
            raise MergeScopeError("PR_SCOPE_EXACT_SHA_REQUIRED")
    # cat-file, unlike rev-list in a shallow clone, exposes the real commit
    # headers. A missing parent object still causes the ancestry check to fail.
    headers = _git(root, "cat-file", "-p", "HEAD").split("\n\n", 1)[0]
    parents = [line.removeprefix("parent ") for line in headers.splitlines()
               if line.startswith("parent ")]
    if len(parents) != 2 or parents[1] != event_head:
        raise MergeScopeError("PR_SCOPE_NOT_EXPECTED_TWO_PARENT_MERGE")
    base = parents[0]
    if base == event_head or event_base == event_head:
        raise MergeScopeError("PR_SCOPE_IDENTICAL_PARENTS")
    for sha in (event_base, event_head, base):
        _git(root, "cat-file", "-e", sha + "^{commit}")
    # Allow only a forward-moving base, never an unrelated/replaced base.
    _git(root, "merge-base", "--is-ancestor", event_base, base)
    return base


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-base", required=True)
    parser.add_argument("--event-head", required=True)
    args = parser.parse_args(argv)
    try:
        print(resolve_base(Path(__file__).resolve().parents[1],
                           event_base=args.event_base, event_head=args.event_head))
        return 0
    except MergeScopeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
