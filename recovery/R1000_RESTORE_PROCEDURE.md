# R1000 local recovery procedure

This procedure restores the 2026-08-23 P0-1 recovery set without modifying
any original worktree. Use a new, explicit restore directory. Do not restore
directly over `H:/codex`, `H:/r1000-quant-engine`, or another existing repo.

## 1. Set and validate explicit paths

```powershell
$recovery = [IO.Path]::GetFullPath(
  "H:\backup\r1000-recovery-20260823"
)
$restore = [IO.Path]::GetFullPath(
  "H:\restore\r1000-recovery-20260823"
)

if (-not $recovery.StartsWith("H:\backup\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Unexpected recovery root: $recovery"
}
if (-not $restore.StartsWith("H:\restore\", [StringComparison]::OrdinalIgnoreCase)) {
  throw "Unexpected restore root: $restore"
}

New-Item -ItemType Directory -Path $restore -Force
```

Never delete or overwrite a directory as part of a restore test. Create a new
restore ID when the destination already exists.

## 2. Verify archive hashes

Compare every external bundle against
`recovery/r1000_bundle_sha256.txt`, every TAR against
`recovery/r1000_snapshot_sha256.txt`, and each Git-directory file manifest
against `recovery/r1000_gitdb_snapshot_manifests_sha256.txt`.

Example for one bundle:

```powershell
$bundle = Join-Path $recovery "bundles\db07_official_current.bundle"
$actual = (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
$expected = "9d0abe47f80dab4acfa50ad1ac857e855b004c039d02c4ce3d3821035d95dda0"
if ($actual -ne $expected) {
  throw "Bundle SHA-256 mismatch"
}
```

Stop on any mismatch. Do not attempt a partial restore from a mismatched
archive.

## 3. Verify each bundle against its preserved object database

`git bundle verify` evaluates prerequisites relative to a Git object database.
Use the matching snapshot, not an unrelated clone.

```powershell
$id = "db07_official_current"
$gitDir = Join-Path $recovery "gitdb_snapshots\$id"
$bundle = Join-Path $recovery "bundles\$id.bundle"

git --git-dir=$gitDir bundle verify $bundle
if ($LASTEXITCODE -ne 0) {
  throw "Bundle verification failed for $id"
}
```

The 2026-08-23 validation passed for all eight bundles. A verification failure
against an unrelated repository does not prove corruption; it can mean that
the verifier lacks a prerequisite object.

## 4. Restore refs from a verified bundle

Create a new bare repository, then fetch all preserved namespaces. This is
safer than assuming that every historical bundle advertises a usable `HEAD`.

```powershell
$id = "db07_official_current"
$bare = Join-Path $restore "$id.git"
$bundle = Join-Path $recovery "bundles\$id.bundle"

git init --bare $bare
git --git-dir=$bare fetch $bundle `
  "+refs/heads/*:refs/heads/*" `
  "+refs/tags/*:refs/tags/*" `
  "+refs/remotes/*:refs/remotes/*"
git --git-dir=$bare fsck --full
```

Then clone or create a worktree from an exact recorded branch or SHA:

```powershell
$worktree = Join-Path $restore "official-current-worktree"
git clone $bare $worktree
git -C $worktree switch --detach faf01e1cc2d30e7c5e125352cbc9ba9712151b85
```

Do not merge or cherry-pick a recovered historical branch merely because it is
present. Recovery preserves evidence; branch census and causal reimplementation
remain separate work.

## 5. Restore dirty and untracked files

Select the TAR named for the recorded worktree in
`recovery/r1000_worktree_status/summary.tsv`. Extract it only after the restored
Git worktree is at the exact captured HEAD.

```powershell
$tar = Join-Path $recovery `
  "dirty_worktrees\r1000-quant-engine.dirty_untracked.tar"
$worktree = Join-Path $restore "official-current-worktree"

tar -xf $tar -C $worktree
git -C $worktree status --short --branch
```

The TAR contains working-tree bytes and preserves relative paths. A tracked
deletion is represented by the status report rather than a nonexistent file.
No tracked deletion was present in this recovery set.

Staged state is preserved in the corresponding Git-directory snapshot index.
Only copy an index into a disposable restore after verifying that its recorded
HEAD matches exactly. Linked worktree indexes live below the matching
`gitdb_snapshots/<id>/worktrees/<admin-name>/index`. Recheck `git status` before
staging or committing anything.

## 6. Restore loose R1000 material separately

Loose material from the `eth-dashboard` workspace is intentionally not overlaid
onto a Git checkout automatically.

```powershell
$loose = Join-Path $recovery `
  "loose_r1000_material\loose_r1000_material_20260823.tar"
$quarantine = Join-Path $restore "loose-material-quarantine"
New-Item -ItemType Directory -Path $quarantine
tar -xf $loose -C $quarantine
```

Review this quarantine by provenance before moving a file into the current
engine. It includes legacy run outputs, replay artifacts, recovery diagnostics,
and local R1000 scripts, not a branch authorized for merge.

The source `H:/codex/.env` was copied to `sensitive_local_only` outside both Git
and the loose TAR. Never copy it into a repository or upload it to GitHub or
Drive. Recreate required credentials through the approved secret store instead.

## 7. Special handling for `db03_codex_dev2_alternate`

This object database already lacked three parent commits before recovery:

```text
87300e3e63ff5dea5ca68babbe170501f2b955a1
0a70ff41ba3ea89dd7c29912af0a057cc50ad07d
3ffaf09b2034501aa129fc0f3c3226817bd3f23a
```

Direct SHA fetch from GitHub did not recover them. The verified bundle contains
the 18 refs whose histories are traversable. The full Git-directory snapshot
still preserves all 126 original refs, all extant objects, the alternate path,
and the exact list of 108 incomplete refs.

If a future source provides all three missing commits:

1. restore the `db02_codex_quant_engine` object database first;
2. point the restored db03 `objects/info/alternates` at the restored db02
   `objects` directory, never at an original source path;
3. import the three recovered commits and their required trees/blobs;
4. run `git fsck --full --no-reflogs`;
5. create and verify a replacement all-ref bundle under a new recovery ID.

Until that succeeds, the 108 incomplete refs are quarantine evidence and are
not valid merge, replay, or promotion inputs.

## 8. Completion checks

A restore drill is complete only when:

- all selected SHA-256 values match;
- the matching bundle verifies;
- the restored ref and HEAD match the manifest;
- `git fsck` has no new missing objects beyond the documented db03 caveat;
- the TAR extracts without error and `git status` matches the recorded class;
- no original path was modified;
- no target, paper ledger, champion, production, or live-trading state changed.
