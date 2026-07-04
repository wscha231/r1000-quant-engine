# Active Execution Queue - W0/S1 Governance Applied

## Purpose

This document converts the latest GPT Pro governance review into executable
Codex work. It replaces older packets that still ask whether cash-carry, the MDD
bar, or long-only Main policy should be adopted. Those questions are resolved.

Do not send another governance question packet for these items. Execute the
decisions below.

## Binding Governance

1. `broker_ledger_next_close_cash_carry` is the official research baseline.
   - Rate source: DGS3MO.
   - PIT lag: 1 business day.
   - Haircut: 50 bps.
   - Day count: ACT/365.
   - Zero-yield metrics must remain reported side-by-side.
2. Mission MDD bar remains canonical: `max_dd >= -25%` for Main and
   Concentrated.
   - Remove `-28%` interim-cap language from active target contracts.
3. Main official policy is long-only.
   - SH fast-crash hedge is not part of the official Main policy.
   - Main cannot be quoted as solved until a hedge-OFF fixed-book replay exists.
4. Public website display remains blocked.
   - Internal/review-only artifacts are allowed.
   - Current holdings are process outputs, not forward CAGR/MDD promises.
5. Production promotion remains blocked while `pit_universe_label_clean=false`.

## Current Reflections Already In This Branch

- Forward-service snapshot hashing already carries:
  - `public_snapshot_hash`
  - `broker_state_hash`
  - `target_snapshot_hash`
  - `hash_method`
  - `snapshot_hash` as a backward-compatible alias of `public_snapshot_hash`
- The snapshot smoke already checks idempotency and state sensitivity:
  `tests/forward_service_snapshot_smoke.py`.
- Replacement-quality is no longer treated as an active implementation hook.
  The readiness audit classifies it as blocked until control reproduction and
  event matching are fixed.

## Immediate Execution Queue

### P1 - Hedge-OFF Main Baseline Replay

Main is officially long-only. Run a cheap fixed-book replay that removes SH rows
from the official Main target book and measures both zero-yield and cash-carry
modes.

Required output:

- `outputs/main_hedge_off_baseline/metrics.json`
- `outputs/main_hedge_off_baseline/report.md`
- `outputs/main_hedge_off_baseline/hedge_on_vs_off.csv`

Required fields:

- `hedge_on_cagr`
- `hedge_on_max_dd`
- `hedge_off_cagr`
- `hedge_off_max_dd`
- `hedge_off_cash_carry_cagr`
- `hedge_off_cash_carry_max_dd`
- `delta_cagr`
- `delta_max_dd`
- `end_date_matches_official`
- `quote_long_only_allowed`

If hedge-OFF Main breaches `-25%`, mark:

`status=governance_reopen_required`

Do not quote Main as solved until this completes.

### P2 - Contract Updates

Update the active data/system contract to reflect:

- cash-carry official research baseline
- zero-yield side-by-side reporting
- Main target: `CAGR >= 35%`, `MDD >= -25%`
- Concentrated target: `CAGR >= 50%`, `MDD >= -25%`
- production blocked by `pit_universe_label_clean=false`

### P3 - S1 Sustainment Wiring

The next system work is operational sustainment, not a new alpha hook.

Implement backend-only:

- daily alert evaluator
- `outputs/alerts/alerts_latest.json`
- `outputs/alerts/UNRESOLVED_<date>.md`
- forward ledger append
- `outputs/system_health/summary.json`

Alarm levels:

- `0 normal`
- `1 watch`
- `2 decay_alert`
- `3 kill_switch`

Any `WARNING`, `EXIT_REVIEW`, or alarm level >= 1 requires human resolution
within 2 trading days. Until notification channels are explicitly enabled,
alerts remain backend-only.

### P4 - Weekly Cron Empty-Input Fix

Fix the weekly evaluation cron so missing inputs produce a structured blocked
summary instead of a silent crash.

2026-07-04 implementation note:

- `full_rebuild_manual.yml` scheduled runs now normalize empty `inputs.*`
  values inside the shell step:
  - `UNIVERSE_MODE=${UNIVERSE_MODE:-global_alpha_universe}`
  - `BACKTEST_YEARS=${BACKTEST_YEARS:-7}`
  - `LEADER_RESCUE_MODE=${LEADER_RESCUE_MODE:-latest_only}`
  - `REQUESTED_SKIP_COLLECTOR=${INPUT_SKIP_COLLECTOR:-true}`
  - `FAST_MODE_FLAG=${INPUT_FAST_MODE:-true}`
- `tests/weekly_cron_input_defaults_smoke.py` guards against reintroducing
  `--fast-mode ""` or direct `inputs.skip_collector` shell checks.

Required output field:

- `weekly_evaluation_status`

Allowed statuses include:

- `ok`
- `blocked_missing_input`
- `failed_with_error`

### P5 - Branch/PR Hygiene Index

The branch/PR inventory must be machine-readable. Do not close or delete
anything automatically.

Required fields:

- `pr_number`
- `title`
- `branch`
- `state`
- `draft`
- `mergeability`
- `ci_status`
- `changed_files`
- `classification`
- `decision_reason`
- `superseded_by_pr`
- `related_evidence_doc`
- `last_measured_artifact`
- `required_action_owner`
- `safe_to_close_after_user_approval`

### P6 - W1 Target-Book Control Reproduction

Acceptance wording must be numeric, not "near zero".

Required pass criteria:

- `official_only_date_count = 0`
- `generated_only_date_count = 0`
- `ticker_mismatch_date_count = 0`
- `max_weight_delta_abs <= 1e-9`

A looser threshold such as `<= 0.001` is allowed only with a documented floating
exception and must not be used silently.

Until W1 passes:

- regenerated selection-side A/B is diagnostic only
- replacement-quality remains `diagnostic_candidate / blocked_by_W1`

## Explicitly Not Next

- No fullrun.
- No live trading.
- No production promotion.
- No new alpha hook.
- No broad bull-floor, broad hold-delay, broad sizing, or broad cash-redeployment
  revival.
- No public website display.
