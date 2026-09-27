# Canonical SYSTEM_STATE materialization (#533)

`tools/materialize_system_state.py` extends the existing `system-state-v2`
schema and A0 consumer. It is a deterministic read-only materializer, not a
collector, scheduler, receipt store or economic authorization service.

## Acquisition and trust boundary

A trusted caller refreshes GitHub default-branch/run/issue observations and the
canonical Drive execution/commit/catalog/quality/readback objects. Save their
original bytes beneath one evidence root. Supply their exact source identities,
SHA-256 and observation/availability/collection/expiry metadata in the existing
schema's `$defs/source_intake`. An intake is a transport inventory, not proof
that its creator is trusted. Never accept a worker's invented source pins or
use a saved state's own identities as the current observation.

The intake has `observed_at`, `expires_at` (maximum one hour), `sources`, and
optional existing `requests` / `completed_tasks`. Each source role contains zero,
one, or conflicting multiple descriptors. Descriptors extend the existing
artifact definition with `identity`; missing roles become UNKNOWN and conflicting
sources become BLOCKED. Paths are relative to the evidence root; traversal and
symlinks are rejected. Source text is read only after SHA-256 verification.

Roles:

- `code`: repository, default_branch, master_sha, observed_at and g0_run
  (run_id in `history-RUN-ATTEMPT` form, head_sha, original conclusion).
- `mission`: mission_contract_id, mission_contract_sha256, official_metric_mode,
  mission_contract_values, exactly as derived from the checked-out canonical
  mission configuration. Missing/mismatched identity blocks research.
- `execution`, `commit`, `catalog`, `quality`: unchanged long-history-v1 objects.
- `drive_readback`: existing workflow `publication.json`; its remote verification,
  execution/catalog/commit linkage, consumer and quality must agree. Verified
  here means receipt/readback byte agreement; it is not a fresh download of every
  historical pack and does not certify historical PIT.
- `control`: observed_at, handoff_ref, and the current issue objects (number,
  state, url; optional title/update metadata). Issue closure cannot certify data.
- `current_status`: original CURRENT_STATUS Markdown, with its original snapshot.
- Four independent optional books (`actual_broker`, `approved_target`,
  `verified_paper`, `model_portfolio`) and `regime`: receipt source identities.

No existing A0 contract binds an accepted domain verifier for these optional
book/regime receipts. Absence is UNKNOWN, expired evidence STALE, and present
unadmitted receipts BLOCKED with `accepted_domain_receipt_verifier_not_bound`.
A simulation, worker PASS or QA-only receipt is never promoted to accepted book
state. Connecting those domain verifiers is explicitly deferred; this change
does not implement #537 business logic or invent a second book authority.

## Invoke and consume

```sh
python tools/materialize_system_state.py \
  --canonical-inputs /scratch/evidence/intake.json \
  --evidence-root /scratch/evidence \
  --output-dir outputs/control_plane
python tools/run_agent_board.py --latest-run outputs \
  --system-state outputs/control_plane/system_state.json \
  --canonical-inputs /scratch/evidence/intake.json \
  --evidence-root /scratch/evidence --output-dir outputs/agent_board
```

The caller must refresh the intake before consumption. `build_tasks` and the
CLI reject legacy self-declared snapshots and compare the saved state with a
fresh deterministic materialization. The private `_plan_tasks` function is
only the existing proposal-routing unit; it grants no canonical state authority.
The schema retains its planning fields for existing packet unit fixtures.

Semantic SHA-256 excludes only `generated_at` and the hash field itself.
`as_of`, expiry, all source descriptors, code/mission identity, independent
capabilities, requests and completion receipts remain bound. The output manifest
also hashes actual JSON/Markdown bytes. Build start revokes the output manifest;
failed refresh never admits retained success. No source or accepted artifact is
written. Changing a source, current master, mission or durable execution prevents
prior-state reuse. A0 task identity includes the new dependency identity, so a
new data execution cannot retain SKIP_UNCHANGED.

## Meaning of permissions

- PARTIAL/PARTIAL_COVERAGE/readback VERIFIED/workflow failure coexist.
- `research_allowed` and `model_portfolio_allowed` mean exploration using only
  catalog datasets in `research_dataset_keys`, through the existing verified
  reader. They are not A3 ER, A5 readiness, ranking, approved target or portfolio
  calculation permission. Existing task/dependency/QA gates still apply.
- Mixed-frequency catalog data has no invented common `data_as_of`; per-dataset
  original dates are exposed. Quality/report collection time is not a market date.
- Unknown Actual Broker blocks account-rebalance/current-holdings claims, while
  independently admitted model research may remain possible.
- Long-history-v1 never grants selector eligibility. Current-snapshot history
  remains proxy evidence; all historical R1000 certification flags remain false.
  Closing #531 alone cannot change this without its domain certification evidence.
- Fullrun, target/paper/broker mutation and production activation are always false.
- CURRENT_STATUS's operational snapshot is parsed without advancing its date.
  A recent hand-edited narrative is at most UNKNOWN, never verification evidence.

The registered `tests/agent_board_smoke.py` executes both planning and materializer
regressions. No frozen Tier-1 registry, review policy or protected evidence pin is
changed. No workflow hook is necessary: generation is an explicit bounded command.
