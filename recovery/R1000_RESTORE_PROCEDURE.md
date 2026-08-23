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
if (-not (Test-Path -LiteralPath $recovery -PathType Container)) {
  throw "Recovery root does not exist: $recovery"
}
if (Test-Path -LiteralPath $restore) {
  throw "Restore root already exists; choose a new restore ID: $restore"
}

New-Item -ItemType Directory -Path $restore | Out-Null

function Assert-Native([string] $operation) {
  if ($LASTEXITCODE -ne 0) {
    throw "$operation failed with exit code $LASTEXITCODE"
  }
}
```

Never delete or overwrite a directory as part of a restore test. Create a new
restore ID when the destination already exists.

## 2. Verify archive hashes

Use the four tracked indexes from the reviewed recovery commit:

- `recovery/r1000_bundle_sha256.txt`;
- `recovery/r1000_snapshot_sha256.txt`;
- `recovery/r1000_gitdb_snapshot_manifests_sha256.txt`;
- `recovery/r1000_raw_report_manifests_sha256.txt`.

The first two bind bundles and TARs. The latter two bind external per-file
manifests. Verifying only a per-file manifest's own hash is insufficient: every
file named inside it must be re-hashed, and the governed directory must contain
no missing or extra files.

```powershell
$control = [IO.Path]::GetFullPath((Get-Location).Path)
if (-not (Test-Path -LiteralPath (Join-Path $control 'recovery') -PathType Container)) {
  throw 'Run the verification from the reviewed repository root'
}

function Read-Sha256Index([string] $path) {
  $rows = @()
  foreach ($line in Get-Content -LiteralPath $path) {
    if ($line -notmatch '^(?<sha>[0-9a-f]{64})  (?<path>.+)$') {
      throw "Malformed SHA-256 row in ${path}: $line"
    }
    $rows += [pscustomobject]@{ Sha = $Matches.sha; Path = $Matches.path }
  }
  return $rows
}

function Resolve-RecoveryMember([string] $relativePath) {
  if ([IO.Path]::IsPathRooted($relativePath) -or
      $relativePath.Split('/') -contains '..') {
    throw "Unsafe recovery-relative path: $relativePath"
  }
  $full = [IO.Path]::GetFullPath((Join-Path $recovery $relativePath))
  $prefix = $recovery.TrimEnd('\') + '\'
  if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Recovery member escapes root: $relativePath"
  }
  return $full
}

function Assert-Sha256Index([string] $indexPath) {
  foreach ($row in Read-Sha256Index $indexPath) {
    $member = Resolve-RecoveryMember $row.Path
    if (-not (Test-Path -LiteralPath $member -PathType Leaf)) {
      throw "Missing recovery member: $($row.Path)"
    }
    $actual = (Get-FileHash -LiteralPath $member -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $row.Sha) {
      throw "SHA-256 mismatch: $($row.Path)"
    }
  }
}

function Assert-ExactDirectory([string] $manifestPath, [string] $directoryPath) {
  $expected = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
  )
  $directoryPrefix = [IO.Path]::GetFullPath($directoryPath).TrimEnd('\') + '\'
  foreach ($row in Read-Sha256Index $manifestPath) {
    $member = Resolve-RecoveryMember $row.Path
    if (-not $member.StartsWith($directoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Manifest member is outside governed directory: $($row.Path)"
    }
    if (-not $expected.Add($member)) {
      throw "Duplicate manifest member: $($row.Path)"
    }
    if (-not (Test-Path -LiteralPath $member -PathType Leaf)) {
      throw "Missing governed member: $($row.Path)"
    }
    $actual = (Get-FileHash -LiteralPath $member -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $row.Sha) {
      throw "Per-file SHA-256 mismatch: $($row.Path)"
    }
  }
  $actualFiles = @(Get-ChildItem -LiteralPath $directoryPath -File -Recurse |
    ForEach-Object { [IO.Path]::GetFullPath($_.FullName) })
  if ($actualFiles.Count -ne $expected.Count) {
    throw "File-count mismatch under $directoryPath"
  }
  foreach ($file in $actualFiles) {
    if (-not $expected.Contains($file)) {
      throw "Unexpected file under governed directory: $file"
    }
  }
}

$bundleIndex = Join-Path $control 'recovery\r1000_bundle_sha256.txt'
$snapshotIndex = Join-Path $control 'recovery\r1000_snapshot_sha256.txt'
$gitdbIndex = Join-Path $control 'recovery\r1000_gitdb_snapshot_manifests_sha256.txt'
$reportIndex = Join-Path $control 'recovery\r1000_raw_report_manifests_sha256.txt'

Assert-Sha256Index $bundleIndex
Assert-Sha256Index $snapshotIndex
Assert-Sha256Index $gitdbIndex
Assert-Sha256Index $reportIndex

foreach ($row in Read-Sha256Index $gitdbIndex) {
  $manifest = Resolve-RecoveryMember $row.Path
  $id = [IO.Path]::GetFileName($row.Path).Replace('.gitdb_files_sha256.txt', '')
  Assert-ExactDirectory $manifest (Join-Path $recovery "gitdb_snapshots\$id")
}

$reportDirectories = @{
  'worktree_status_sha256.txt' = 'worktree_status'
  'object_db_reports_sha256.txt' = 'object_db_reports'
}
foreach ($row in Read-Sha256Index $reportIndex) {
  $manifest = Resolve-RecoveryMember $row.Path
  $name = [IO.Path]::GetFileName($row.Path)
  if (-not $reportDirectories.ContainsKey($name)) {
    throw "Unknown raw-report manifest: $name"
  }
  Assert-ExactDirectory $manifest `
    (Join-Path $recovery $reportDirectories[$name])
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
Assert-Native "git bundle verify for $id"
```

The 2026-08-23 validation passed for all eight bundles. A verification failure
against an unrelated repository does not prove corruption; it can mean that
the verifier lacks a prerequisite object.

## 4. Restore refs from a verified bundle

Create a new bare repository, enumerate every head advertised by the bundle,
and map each one into an explicit `refs/recovery/<id>/...` namespace. Do not
assume that heads, tags, and remotes cover bundle-only `HEAD`, stash, notes,
custom refs, or linked-worktree heads.

```powershell
$id = "db07_official_current"
$bare = Join-Path $restore "$id.git"
$bundle = Join-Path $recovery "bundles\$id.bundle"

git init --bare $bare
Assert-Native "git init --bare for $id"

$listed = @(git bundle list-heads $bundle)
Assert-Native "git bundle list-heads for $id"
$expectedRefs = @{}
$refspecs = @()
foreach ($line in $listed) {
  if ($line -notmatch '^(?<oid>[0-9a-f]{40}) (?<source>.+)$') {
    throw "Malformed bundle head for ${id}: $line"
  }
  $source = $Matches.source
  $destination = "refs/recovery/$id/$source"
  git check-ref-format $destination
  Assert-Native "git check-ref-format for $destination"
  if ($expectedRefs.ContainsKey($destination)) {
    throw "Duplicate bundle destination: $destination"
  }
  $expectedRefs[$destination] = $Matches.oid
  $refspecs += "+${source}:${destination}"
}
if ($refspecs.Count -eq 0) {
  throw "Bundle advertises no heads: $id"
}

git --git-dir=$bare fetch --atomic $bundle @refspecs
Assert-Native "atomic bundle fetch for $id"

$actualRefs = @{}
$lines = @(git --git-dir=$bare for-each-ref `
  --format='%(objectname) %(refname)' "refs/recovery/$id")
Assert-Native "restored ref inventory for $id"
foreach ($line in $lines) {
  if ($line -notmatch '^(?<oid>[0-9a-f]{40}) (?<ref>.+)$') {
    throw "Malformed restored ref for ${id}: $line"
  }
  $actualRefs[$Matches.ref] = $Matches.oid
}
if ($actualRefs.Count -ne $expectedRefs.Count) {
  throw "Restored ref count mismatch for $id"
}
foreach ($ref in $expectedRefs.Keys) {
  if ($actualRefs[$ref] -ne $expectedRefs[$ref]) {
    throw "Restored ref mismatch for $ref"
  }
}

git --git-dir=$bare fsck --full --no-reflogs
Assert-Native "clean usable bundle fsck for $id"
```

Then clone or create a worktree from an exact recorded branch or SHA:

```powershell
$worktree = Join-Path $restore "official-current-worktree"
$capturedHead = 'faf01e1cc2d30e7c5e125352cbc9ba9712151b85'
git --git-dir=$bare worktree add --detach $worktree $capturedHead
Assert-Native "worktree creation at exact captured head"
$actualHead = git -C $worktree rev-parse HEAD
Assert-Native "restored HEAD observation"
if ($actualHead -ne $capturedHead) {
  throw "Restored HEAD mismatch"
}
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
Assert-Native "dirty/untracked TAR extraction"
```

The TAR contains working-tree bytes and preserves relative paths. A tracked
deletion is represented by the status report rather than a nonexistent file.
No tracked deletion was present in this recovery set.

Staged state is preserved in the corresponding, per-file-hashed Git-directory
snapshot index. Only copy an index into this disposable restore after verifying
that its recorded HEAD matches exactly. Linked worktree indexes live below the
matching `gitdb_snapshots/<id>/worktrees/<admin-name>/index`.

Do not accept matching counts or a broad dirty class. The hash-bound raw report
contains exact `[status_tracked]`, `[staged_name_status]`,
`[unstaged_name_status]`, and `[untracked_paths]` sections. Compare those exact
normalized lines, and compare the index's exact stage/mode/object/path rows.

```powershell
function Read-ReportSection([string] $path, [string] $name) {
  $lines = @(Get-Content -LiteralPath $path)
  $header = "[$name]"
  $start = [Array]::IndexOf($lines, $header)
  if ($start -lt 0) { throw "Missing report section: $header" }
  $rows = @()
  for ($i = $start + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^\[.+\]$') { break }
    if ($lines[$i] -ne '') { $rows += $lines[$i] }
  }
  return $rows
}

function Assert-ExactLines($expected, $actual, [string] $label) {
  if (@($expected).Count -ne @($actual).Count) {
    throw "$label line-count mismatch"
  }
  for ($i = 0; $i -lt @($expected).Count; $i++) {
    if ($expected[$i] -cne $actual[$i]) {
      throw "$label mismatch at line $($i + 1)"
    }
  }
}

$statusReport = Join-Path $recovery 'worktree_status\r1000-quant-engine.txt'
$capturedGitDir = Join-Path $recovery 'gitdb_snapshots\db07_official_current'
$capturedIndex = Join-Path $capturedGitDir 'index'
$restoredGitDir = git -C $worktree rev-parse --absolute-git-dir
Assert-Native "restored Git-directory observation"
$restoredIndex = Join-Path $restoredGitDir 'index'

$previousIndex = $env:GIT_INDEX_FILE
try {
  $env:GIT_INDEX_FILE = $capturedIndex
  $expectedStage = @(git --git-dir=$capturedGitDir `
    --work-tree=$worktree ls-files --stage)
  Assert-Native "captured staged-index inventory"
} finally {
  $env:GIT_INDEX_FILE = $previousIndex
}
Copy-Item -LiteralPath $capturedIndex -Destination $restoredIndex
$actualStage = @(git -C $worktree ls-files --stage)
Assert-Native "restored staged-index inventory"
Assert-ExactLines $expectedStage $actualStage 'staged index'

$actualTracked = @(git -C $worktree status --short --untracked-files=no)
Assert-Native "tracked status inventory"
$actualStaged = @(git -C $worktree diff --cached --name-status)
Assert-Native "staged name/status inventory"
$actualUnstaged = @(git -C $worktree diff --name-status)
Assert-Native "unstaged name/status inventory"
$actualUntracked = @(git -C $worktree ls-files --others --exclude-standard)
Assert-Native "untracked path inventory"

Assert-ExactLines (Read-ReportSection $statusReport 'status_tracked') `
  $actualTracked 'tracked status'
Assert-ExactLines (Read-ReportSection $statusReport 'staged_name_status') `
  $actualStaged 'staged name/status'
Assert-ExactLines (Read-ReportSection $statusReport 'unstaged_name_status') `
  $actualUnstaged 'unstaged name/status'
Assert-ExactLines (Read-ReportSection $statusReport 'untracked_paths') `
  $actualUntracked 'untracked paths'
```

The example uses the official worktree. For a linked worktree, select its exact
hash-bound report and its exact `worktrees/<admin-name>/index`; never infer an
index from a similar branch name.

## 6. Restore loose R1000 material separately

Loose material from the `eth-dashboard` workspace is intentionally not overlaid
onto a Git checkout automatically.

```powershell
$loose = Join-Path $recovery `
  "loose_r1000_material\loose_r1000_material_20260823.tar"
$quarantine = Join-Path $restore "loose-material-quarantine"
if (Test-Path -LiteralPath $quarantine) {
  throw "Loose-material quarantine already exists: $quarantine"
}
New-Item -ItemType Directory -Path $quarantine | Out-Null
tar -xf $loose -C $quarantine
Assert-Native "loose-material TAR extraction"
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
not valid merge, replay, or promotion inputs. A usable restore from the current
healthy-only db03 bundle must pass `git fsck --full --no-reflogs` with zero
missing objects. Only the separately restored exact Git-directory snapshot may
retain the three documented missing commits, and that quarantine must never
satisfy the usable-restore completion gate.

## 8. Completion checks

A restore drill is complete only when:

- all selected SHA-256 values match;
- every per-file Git-directory and raw-report manifest has no missing, extra,
  or mismatched member;
- the matching bundle verifies;
- every advertised bundle head is present at the exact OID in its explicit
  recovery namespace;
- the restored HEAD matches the manifest;
- every usable bundle restore, including db03, passes `git fsck` with zero
  missing objects;
- TAR extraction succeeds and the exact tracked, staged, unstaged, untracked,
  and staged-object inventories match their hash-bound evidence;
- no original path was modified;
- no target, paper ledger, champion, production, or live-trading state changed.
