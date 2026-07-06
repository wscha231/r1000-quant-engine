# Run287 R3 Cluster-Cap Counterfactual

Status: `completed`
Decision label: `cluster_cap_rejected_proxy_joint_gate_failed`

Research-only measurement. No fullrun, production mutation, new alpha hook,
or threshold sweep was performed.

## Contract

- runner_parity_status: `parity_documented_gap`
- cluster_column: `sector`
- cluster_cap: `30.00%`
- cash_carry_proxy_source: `generated_book_cash_carry_vs_zero_yield_sidecar_implied_flat_yield`
- proxy_substrate_status: `not_official_reproduction_directional_only`

## Metrics

| Arm | Metric | CAGR | MaxDD | Target pass | Proxy |
| --- | --- | ---: | ---: | --- | --- |
| official_generated_zero_yield | broker_ledger_next_close | 32.94% | -25.65% | False | False |
| official_generated_cash_carry | broker_ledger_next_close_cash_carry | 33.81% | -25.36% | False | False |
| baseline_proxy_zero_yield | proxy_monthly_target_book_zero_yield | 41.92% | -15.54% | True | True |
| cluster_cap_proxy_zero_yield | proxy_monthly_target_book_zero_yield | 34.14% | -14.76% | False | True |
| baseline_proxy_cash_carry | proxy_monthly_target_book_cash_carry_implied | 42.83% | -15.41% | True | True |
| cluster_cap_proxy_cash_carry | proxy_monthly_target_book_cash_carry_implied | 35.22% | -14.62% | True | True |

## Verdict

- proxy_joint_gate_pass: `false`
- candidate_allowed: `false`
- mdd_benefit_test_underpowered_reason: `proxy_dd_never_reaches_minus25`
- eras_inside_minus_25_count_cash_carry: `3`
- proxy zero-yield CAGR delta vs official: `8.98pp`
- proxy cash-carry CAGR delta vs official: `9.03pp`

The capped arms are proxy target-book calculations, not official
broker-ledger acceptance evidence. This proxy does not reproduce the
official broker-ledger substrate, so it is directional only. If a
proxy ever passes, it still requires runner-parity broker replay
before becoming a candidate.

The cluster-cap idea is rejected because the CAGR cost is too high and
the proxy substrate does not reproduce official broker-ledger metrics.
This does not prove the cap has no MDD benefit: when proxy drawdowns
never reach the -25% target boundary, the MDD-benefit test is
under-powered until runner-parity broker replay is available.
