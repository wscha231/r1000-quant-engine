# Universe Fallback Decision

- status: `pass`
- action: `ALLOW_REVIEW_ONLY`
- promotion_allowed: `true`
- universe_mode: `global_alpha_universe`
- r1000_base_count: `700`
- scored_count: `737`
- candidate_count: `45990`
- primary_universe_source: `static_iwb_seed`
- fallback_used: `true`

## Blockers

- none

## Required Fallback Order

1. live_iShares_IWB_holdings_fetch
2. restored_Drive_or_cache_IWB_holdings
3. previous_healthy_current_constituents_proxy
4. committed_static_IWB_seed
5. hard_fail

## Next Actions

- none
