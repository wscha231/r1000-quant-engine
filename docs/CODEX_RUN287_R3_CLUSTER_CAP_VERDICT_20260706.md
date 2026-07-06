# CODEX RUN287 R3 CLUSTER-CAP VERDICT 20260706

Status: `research_only_negative_evidence`

This verdict records R3 from
`docs/CODEX_DIRECTIVE_POST_RUN287_REINFORCEMENT_20260706.md`.

No fullrun was dispatched. No market data was downloaded. No target book was
regenerated. No threshold tuning, alpha hook, production promotion, or live
trading action was performed.

## R3 verdict

Verdict: `cluster_cap_rejected_proxy_joint_gate_failed`

Artifacts:

- `outputs/run287_cluster_cap/summary.json`
- `outputs/run287_cluster_cap/report.md`
- `outputs/run287_cluster_cap/arm_metrics.csv`
- `outputs/run287_cluster_cap/cluster_exposure_by_date.csv`
- `outputs/run287_cluster_cap/capped_main_target_book.csv`
- `outputs/run287_cluster_cap/proxy_zero_yield_equity_curve.csv`
- `outputs/run287_cluster_cap/proxy_cash_carry_equity_curve.csv`

Contract:

- Research-only measurement: `true`
- Fullrun dispatched: `false`
- Runner parity status: `parity_documented_gap`
- Cluster definition: existing target-book `sector`
- Cluster cap: `30.00%`
- Direct losing-month edit allowed: `false`
- New alpha hook added: `false`
- Production promotion allowed: `false`
- Proxy substrate status: `not_official_reproduction_directional_only`

## Official run287 sidecar baseline

The official broker-ledger sidecar metrics remain below the Main target:

| Arm | Metric mode | CAGR | MaxDD | Target pass |
| --- | --- | ---: | ---: | --- |
| official_generated_zero_yield | broker_ledger_next_close | 32.94% | -25.65% | false |
| official_generated_cash_carry | broker_ledger_next_close_cash_carry | 33.81% | -25.36% | false |

Interpretation:

- Cash-carry does not close the Main target gap on the generated run287 book.
- Main remains below `35% CAGR` and outside the `-25% MaxDD` target on the
  official generated-book sidecar.
- `pit_universe_label_clean=false` remains a production blocker.

## Cluster-cap proxy result

The cheap R3 counterfactual capped aggregate sector exposure at `30%` and moved
freed weight to `CASH`.

| Arm | Metric mode | CAGR | MaxDD | Target pass | Proxy |
| --- | --- | ---: | ---: | --- | --- |
| baseline_proxy_zero_yield | proxy_monthly_target_book_zero_yield | 41.92% | -15.54% | true | true |
| cluster_cap_proxy_zero_yield | proxy_monthly_target_book_zero_yield | 34.14% | -14.76% | false | true |
| baseline_proxy_cash_carry | proxy_monthly_target_book_cash_carry_implied | 42.83% | -15.41% | true | true |
| cluster_cap_proxy_cash_carry | proxy_monthly_target_book_cash_carry_implied | 35.22% | -14.62% | true | true |

Key evidence:

- Capped cluster-date count: `46`
- Max freed weight: `41.76%`
- Cash-carry implied annual yield used by the proxy: `2.2171%`
- Eras inside `-25%` in zero-yield proxy: `3`
- Eras inside `-25%` in cash-carry proxy: `3`
- MDD benefit test under-powered reason: `proxy_dd_never_reaches_minus25`
- Proxy zero-yield CAGR delta versus official broker sidecar: `+8.98pp`
- Proxy cash-carry CAGR delta versus official broker sidecar: `+9.03pp`

Interpretation:

- The cap improves proxy drawdown, but the zero-yield capped arm falls to
  `34.14% CAGR`, below the required `35%` threshold.
- The cash-carry capped proxy barely clears `35%`, but the R3 gate requires
  both zero-yield and cash-carry to pass.
- The proxy substrate materially overstates the official broker-ledger sidecar,
  so this is directional evidence only, not official broker acceptance evidence.
- This does not prove cluster caps have no MDD benefit. The proxy drawdowns
  never reach the `-25%` target boundary, so the MDD-benefit test is
  under-powered until runner-parity broker replay is available.

## Decision

`candidate_allowed=false`

The aggregate sector cluster cap is rejected as a run287 candidate because it
fails the joint gate on the zero-yield arm and because the available
counterfactual substrate does not reproduce official broker-ledger metrics.
It is not rejected as proof that MDD benefit is impossible.

Do not add a cluster-cap hook. Do not tune the cap. Do not dispatch a fullrun
for this R3 idea. The result should be treated as negative evidence for the
cheap sector-cap lever on the current generated-book measurement substrate.

## Next allowed actions

- R4 remains a user decision: either open a new decision-time data feed for
  Concentrated alpha work, or accept the current Concentrated ceiling as
  research evidence on this book.
- R5 measurement-contract hardening may proceed now that R1, R2, and R3 emit
  the required caveat fields and verdicts.
- No new fullrun is allowed without a separate ready gate and explicit user
  approval.
