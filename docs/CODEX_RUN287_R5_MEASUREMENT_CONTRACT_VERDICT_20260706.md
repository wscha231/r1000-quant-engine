# CODEX RUN287 R5 MEASUREMENT-CONTRACT VERDICT 20260706

Status: `research_only_contract_hardened`

This verdict records R5 from
`docs/CODEX_DIRECTIVE_POST_RUN287_REINFORCEMENT_20260706.md`.

No fullrun was dispatched. No market data was downloaded. No target book was
regenerated. No threshold tuning, alpha hook, production promotion, or live
trading action was performed.

## R5 verdict

Verdict: `measurement_contract_fields_hardened`

Contract changes:

- `runner_parity_status` is now a required performance field.
- `survivorship_inflation_estimate` is now a required performance field.
- `survivorship_inflation_label` and
  `survivorship_unmeasured_component` are required caveat fields.
- Forward-label screens are explicitly audit-only and require OOS
  re-validation before any candidate promotion.

Emitter changes:

- `tools/alphaops_governance.py` now standardizes R1/R2 caveat fields.
- `tools/run287_forensics.py` emits those fields at top-level summary scope.
- `tools/run287_forensics.py` emits those fields into metric sidecar summaries
  and tabular performance rows.
- `tests/run287_forensics_smoke.py` fails if the fields are absent.

Updated artifacts:

- `outputs/run287_forensics/summary.json`
- `outputs/run287_forensics/report.md`
- `outputs/run287_forensics/metric_sidecar_arm_metrics.csv`

Current caveats carried forward:

- `runner_parity_status=parity_documented_gap`
- `survivorship_inflation_estimate.label=proxy`
- `survivorship_inflation_estimate_cagr_pp=0.0`
- `survivorship_unmeasured_component=delisted_exclusion`

## Interpretation

The run287 generated-book performance remains research-only evidence. The added
fields prevent the latest-basis CAGR/MDD tables from being read without the two
active caveats:

- local runner parity is documented as a gap, not exact parity
- survivorship inflation is only a one-sided proxy lower bound

`pit_universe_label_clean=false` remains a production blocker. Production
promotion remains `false`.

## Next allowed actions

- R4 remains a user decision: open a new decision-time data feed for
  Concentrated alpha work, or accept Concentrated near `48%` as the current
  honest ceiling on this generated book.
- No new fullrun is allowed without a separate ready gate and explicit user
  approval.
