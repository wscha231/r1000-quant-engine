# P2 PIT Membership Status - 2026-07-03

## Verdict

P2 is not blocked by missing tooling. The audit and producer tools exist and
their smoke tests pass. The current blocker is the absence of a true
historical point-in-time R1000 membership source.

Current state:

- `pit_universe_label_clean=false`
- `historical_universe_pit_clean=false`
- `official_pit_r1000=false`
- `production_promotion_allowed=false`

This is expected and must remain a production blocker.

## Evidence Checked

Repository branch:

- branch: `codex/integration-fullrun-clean-20260630`
- HEAD at check time: `9e7a87bb`

Run artifact inspected:

- run: `28616190134`
- artifact root:
  `artifacts/run_28616190134_download/official-broker-ledger-global_alpha_universe-28616190134`
- universe health source:
  `artifacts/run_28616190134_download/official-broker-ledger-global_alpha_universe-28616190134/outputs/universe_health/summary.json`

Tooling smoke validation:

- `tests/universe_health_audit_smoke.py`: PASS
- `tests/pit_membership_audit_smoke.py`: PASS
- `tests/pit_membership_producer_smoke.py`: PASS

Command:

```powershell
python -B tools/run_pr_validation.py --only pit_membership_audit_smoke --only pit_membership_producer_smoke --only universe_health_audit_smoke
```

## Current Universe Health

The run's universe health is review-valid but not production/PIT-clean:

- `status=pass`
- `promotion_allowed=true`
- `production_promotion_allowed=false`
- `primary_universe_source=static_iwb_seed`
- `fallback_used=true`
- `r1000_base_count=700`
- `scored_count=741`
- `candidate_count=47434`

Candidate replay source counts:

- `current_constituents_proxy_static_seed`: `44580`
- `current_constituents_proxy_static_seed+strategic_global_hardware`: `1202`
- `adr_whitelist`: `1399`
- `cycle_play_whitelist`: `253`

Scored latest source counts:

- `current_constituents_proxy_static_seed`: `681`
- `current_constituents_proxy_static_seed+strategic_global_hardware`: `19`
- `adr_whitelist`: `31`
- `cycle_play_whitelist`: `6`
- `strategic_global_hardware`: `4`

The important point is that the breadth gate can pass while the membership
source remains a current/static proxy. That is review-only evidence, not
production evidence.

## Historical Membership Source Status

The audit found no historical PIT membership file:

```json
"historical_universe_membership": {
  "file_count": 0,
  "paths": []
}
```

Therefore no file was available to prove:

- membership was known at each rebalance date;
- `membership_available_from <= rebalance_date`;
- current constituents were not backfilled into history;
- delisted/ticker-change coverage was handled;
- source provenance was audited.

## Implementation Status

Existing tools:

- `tools/run_pit_membership_audit.py`
- `tools/build_pit_membership_by_month.py`
- `tools/run_universe_health_audit.py`

Existing validation:

- `tests/pit_membership_audit_smoke.py`
- `tests/pit_membership_producer_smoke.py`
- `tests/universe_health_audit_smoke.py`

These are sufficient for P2 monitoring and for ingesting a future historical
membership source. Do not manually flip `pit_universe_label_clean`.

## Required Next Action For P2

Acquire or generate a true PIT membership source with at least:

- `rebalance_date`
- `ticker`
- `membership_source`
- `membership_available_from`
- `membership_end_date` when available
- `universe_label`
- `official_r1000_membership_proven`
- `proxy_universe_flag`
- `survivorship_status`
- `delisted_coverage_status`
- `ticker_change_coverage_status`
- `membership_pit_status`
- `source_provenance_status`

Then run:

```powershell
python -B tools/build_pit_membership_by_month.py `
  --membership-file <historical_membership_source> `
  --output-dir outputs/pit_membership_by_month_<date> `
  --start-date 2019-05-31 `
  --end-date <latest_rebalance_date> `
  --source-kind official_historical_membership `
  --source-provenance-status reviewed `
  --coverage-floor 900
```

Only if that audit passes should future account evaluation inputs be allowed to
carry `historical_universe_pit_clean=true` or `pit_universe_label_clean=true`.

## External Review Routing

Do not spend Claude tokens on this until a real candidate membership source is
available. Current result is mechanically clear: source missing.

Useful GPT Pro question, if needed:

> Given no PIT R1000 membership source is currently present, what practical
> data-source contract would be acceptable for a public research service:
> licensed index membership, ETF holdings with lag, or a proxy label that stays
> explicitly non-production?

Codex/local implementation can proceed to P4 read-only audit while P2 waits for
the membership data source.

