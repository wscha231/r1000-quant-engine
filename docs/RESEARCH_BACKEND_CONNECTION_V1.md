# Research backend connection V1

Task `R1000-PREIMPL-PIPELINE-RUNNER-20261018` prepares a one-shot, local,
supplied-byte connection on base `35b36d289dbae9104042c2158532466076844f9b`.
It connects the actual `research.research_path_connection_v1` output to
`tools.research_risk_connection` through `company_research`. A missing real
input remains missing. Synthetic fixtures test execution and never establish
source admission, current selection, independently validated ER or A5 eligibility.

## Entry points

```python
from pathlib import Path
from tools.run_research_backend_connection import run_bundle

result = run_bundle(
    Path("C:/research-input/bundle/manifest.json"),
    Path("C:/research-output/research-case-001-attempt-001"),
)
```

```text
python -B tools/run_research_backend_connection.py --help
python -B tools/run_research_backend_connection.py --manifest C:/research-input/bundle/manifest.json --output-dir C:/research-output/research-case-001-attempt-001
```

Both paths are explicit absolute paths. The output parent must exist; the
`research-*` output leaf must be new and outside both input and code roots.
An existing output directory is refused without reading its old summary.
Every invocation checks supplied clocks, expiry and actual bytes again. No
reuse cache or mutable latest/CURRENT alias is created. CLI exit 0 means local
invocations completed; exit 2 means BLOCKED. Neither grants economic authority.
In this version the research adapter preserves BLOCKED for unadmitted ER, so a
positive synthetic execution ordinarily has exit 2 with useful stage results.

## Explicit manifest

The root has exactly these keys:

| Key | Meaning |
| --- | --- |
| `schema` | `research-backend-bundle-v1` |
| `case_id` | Explicit stable case identifier, at most 128 allowed ASCII characters |
| `cutoff` | Explicit timezone-aware decision cutoff |
| `input_root` | Existing absolute directory containing the named input files |
| `identifiers` | Exactly `security_id`, `issuer_id`, `benchmark_id` strings |
| `inputs` | Optional named file descriptors, or explicit null |
| `artifacts` | Immutable artifact ID to explicit file descriptor |
| `code_sha` | Declared 40-character Git revision; metadata, not remote authentication |
| `code_pins` | Repository-relative actual file names to expected SHA256 |
| `config` | Exactly `{ "synthetic_fixture": true/false }` |

`inputs` accepts `identities`, `events`, `registry`, `er`, `cohort`,
`delta_previous`, `delta_current`, `a3_packet` and `risk_request`. The research
inputs are passed as the original bytes. `risk_request` is decoded JSON using
the existing risk adapter's contract. The runner alone adds `company_research`;
a supplied field with that name is refused.

Every non-null descriptor has exactly:

```json
{
  "path": "events.json",
  "expected_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "available_at": "2026-10-17T20:00:00Z",
  "collected_at": "2026-10-17T20:01:00Z",
  "valid_through": "2026-10-19T00:00:00Z"
}
```

Paths use relative `/` segments with no traversal, alternate streams or links.
Availability <= collection <= cutoff < valid-through is required before a
file read; the existing validators additionally inspect embedded clocks and
references. These remain caller assertions, not authenticated CURRENT status.
Actual SHA256 must equal the declared digest. Outer metadata cannot replace
the inner original ER, Registry, event, outcome or A3 contracts.

Schema inventory entries use the exact immutable IDs
`SCHEMA:<filename>` required by `a2_research_intake_v1.SCHEMAS`. Supply the
original pinned Git blob bytes and their actual digest. Runtime line-ending
normalization, hash rebinding, latest-file search, provider lookup and schema
network resolution are absent. Other artifacts may be arbitrary raw bytes;
their consuming validators own their meaning.

Required minimum `code_pins` are the runner and both connection modules:

```text
tools/run_research_backend_connection.py
research/research_path_connection_v1.py
tools/research_risk_connection.py
```

Callers can explicitly pin further dependencies. Checked file hashes and the
declared Git SHA are separate evidence fields; these minimum pins do not claim
authentication of a complete executable dependency closure or a remote HEAD.
The actual underlying risk calls also retain their existing code-file hashes.
The result additionally records actual source-byte SHA256 snapshots for the
fixed intake, A3, Registry, Chameleon, reassessment, free-context, hold-policy,
policy-replay and lifecycle consumers. An unavailable dependency is null with
`runtime_dependency_status=NOT_VERIFIED`; a complete fixed inventory is labeled
`SOURCE_BYTES_HASHED_NOT_COMPLETE_CLOSURE`. This records provenance without
claiming interpreter/import closure or authenticated data/PIT admission.

## Bounds, publication and evidence

Manifest bytes are limited to 1 MiB, each input to 4 MiB, evidence inventory to
32 MiB/128 artifacts and code pins to 32 MiB/256 names. Structured inputs reject
duplicate keys, nonfinite numbers, depth >32, >100,000 lexical tokens or
>50,000 value nodes before reaching an investment consumer. Output is limited
to 16 MiB with room reserved for its physical-publication metadata. File reads
reject symlinks, Windows junction/reparse points, input/output overlap and
changes observed during the read.
Non-regular paths are refused before opening. POSIX opens also use nonblocking
mode, then recheck the opened file type, so a FIFO replacement cannot wait for
a writer. The direct risk adapter returns a compact, closed BLOCKED envelope
if retained company research plus diagnostics exceeds its output budget; only
the original company hash remains, never silently truncated research.

The new output contains `result.json`, `inputs.json` and `receipt.json`.
All three are written and fsynced in a new sibling temporary directory,
hash-checked, renamed as one directory batch without replacing any existing
destination, then physically reread and hash-checked. The staged directory's
actual device/inode identity must still match after publication and readback;
identical bytes in a replacement directory cannot substitute for it.
Windows uses its no-replace rename; Linux requires libc/filesystem support for
renameat2(RENAME_NOREPLACE). Other platforms or unavailable support refuse
publication, with no fallback to an existence check followed by replacing rename.

Disk `receipt.json` is always `status=UNACCEPTED` / `publication_state=PREPARED_ONLY`.
Its `result_status` is a computation result, not publication completion. Only a
successful call returns `publication.acceptance` with LOCAL_READBACK_ACCEPTED,
attempt ID, observed directory identity, exact three-file hashes and a separate
acceptance SHA256. This returned receipt is not written into its own batch.
Consumers must preserve that exact returned acceptance separately; disk bytes,
directory appearance, or a reconstructed hash alone cannot replace it. Losing
the returned acceptance leaves the batch unaccepted. This is a local readback
protocol, not authenticated source or economic admission.

Failure returns no publication/acceptance. It performs no path-based recursive
cleanup: a path may belong to another process after rename. Failed staging,
published or moved batches may remain, bounded by this invocation's existing
output limits, with no accepted completion in them. They require explicit owner
inspection; no automatic cleanup or retry is introduced. Earlier cleanup-on-
failure test expectations are superseded by this no-delete refusal protocol.
An identity/hash check records the readback instant and does not lock future
filesystem changes. Later consumers must recheck the returned identity/hashes.
Directory rename/fsync on a local filesystem is not a claim of durable Drive
persistence or power-loss proof.

The result retains case, manifest/input/artifact/code/config hashes, cutoff,
actual module call list, each stage result and its SHA256. Inner NOT_RUN and
BLOCKED states remain visible. Errors use bounded reason codes. Unknown
validated ER stays null, all root authorities stay exact false and
`A5_eligible_input` remains false. No canonical Registry/current write,
Approved Target, paper/broker book, orders, fullrun, scheduler, dispatch,
source admission or production operation is connected.

## Reproducible focused tests and integration handoff

```text
python -B tests/research_backend_connection_smoke.py -v
python -B -O tests/research_backend_connection_smoke.py -v
```

`fixture(bundle_root)` in that smoke file creates a reproducible synthetic
manifest, raw identity/event/risk inputs and original code-pinned schemas.
The tests call both actual connection modules and the existing hold policy,
run the actual CLI, verify returned-to-physical hashes and closed authority,
and exercise missing/tampered/stale/future inputs, path overlap/traversal,
real directory links, strict JSON bounds, old-result refusal and post-rename
readback failure. Real input admission and full repository validation are not
claimed by these tests.

The existing Main B writer should register the three new smoke routes in
`tools/run_pr_validation.py` and append the short lesson candidate supplied in
`receipts/REGISTRATION_AND_LESSON_CANDIDATE.md`. This preparation does not edit
the protected shared runner or lesson ledger.
