# R1000 local worktree status snapshot

Captured on 2026-08-23 before any cleanup or branch census mutation.

- 23 R1000 worktrees were mapped to eight distinct common Git directories.
- 12 worktrees had staged, unstaged, or untracked paths and have a matching
  path-preserving TAR snapshot under the external recovery root.
- The pre-snapshot and post-snapshot HEAD, branch, staged, unstaged, and
  untracked counts matched for all 23 worktrees.
- Full path lists, reflogs, refs, stash listings, `git fsck` output, archive
  validation, and per-file Git-directory hashes remain outside Git at
  `H:/backup/r1000-recovery-20260823`.
- `H:/codex` itself is `wscha231/eth-dashboard`; it was not bundled as an
  R1000 repository. Only clearly identified loose R1000/Run287 material was
  copied into the dedicated loose-material TAR.

`summary.tsv` is the tracked index. Blank ahead/behind values mean that the
worktree had no configured upstream at capture time.
