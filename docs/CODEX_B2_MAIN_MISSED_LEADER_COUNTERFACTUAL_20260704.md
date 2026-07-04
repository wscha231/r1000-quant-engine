# B2 Main Missed-Leader Counterfactual Closeout — 2026-07-04

## Verdict

`screen_reject_main_missed_leader_replacement`

Main missed-leader replacement does **not** repair the current Main gap. The same research-only fixed-book broker counterfactual that found a live Concentrated candidate was generalized to `portfolio_kind=main` and run on the latest `28616190134` book with cash-carry accounting and the official 2026-07-02 replay window.

Every tested arm reduced CAGR and either worsened or failed to repair MDD. This path should not be promoted to a policy hook and should not justify a fullrun.

## Setup

- Tool: `tools/run_concentrated_cap_replacement_broker_counterfactual.py`
- New parameter: `--portfolio-kind {main,concentrated}`
- Portfolio: `main`
- Target book: `artifacts/run_28616190134_download/user-operating-minimal-global_alpha_universe-28616190134/outputs/reports/operating_main_target_book.csv`
- Missed leaders: `artifacts/run_28616190134_download/user-operating-minimal-global_alpha_universe-28616190134/outputs/stock_selection_quality/missed_leaders_audit.csv`
- Price cache: `outputs/p4_cap_replacement_broker_counterfactual_28616190134/cache_prices`
- Baseline metrics: `outputs/p4_main_cap_replacement_broker_counterfactual_28616190134_cash_carry_control/broker/metrics.json`
- Output: `outputs/p4_main_cap_replacement_broker_counterfactual_28616190134_cash_carry/`
- Fullrun executed: `false`
- Production activation allowed: `false`
- Forward labels used for ranking: `false`

## Baseline

Main cash-carry control:

| CAGR | MaxDD | Sharpe | End Date | Metric Mode |
|---:|---:|---:|---|---|
| 33.53% | -26.03% | 1.221 | 2026-07-02 | `broker_ledger_next_close_cash_carry` |

This confirms the current Main book remains below the 35% CAGR target and the -25% MDD target under long-only/cash-carry accounting.

## Results

| Arm | Swaps | Full ΔCAGR | Full ΔMDD | ΔSharpe | IS ΔCAGR | OOS ΔCAGR | Interpretation |
|---|---:|---:|---:|---:|---:|---:|---|
| `rank_top15` | 33 | -1.96pp | -0.38pp | -0.050 | -1.82pp | -2.40pp | Reject |
| `rs3_ge20` | 30 | -1.54pp | -0.06pp | -0.040 | -1.69pp | -0.94pp | Reject |
| `rs3_ge30` | 20 | -0.75pp | -0.35pp | -0.019 | -0.71pp | -0.86pp | Reject |
| `rank_top15_or_rs3_ge20` | 33 | -1.96pp | -0.38pp | -0.050 | -1.82pp | -2.40pp | Reject |
| `rank_top15_and_revenue_ge10` | 26 | -1.11pp | -0.37pp | -0.027 | -1.02pp | -1.42pp | Reject |
| `rs3_ge20_and_revenue_ge10` | 19 | -0.66pp | -0.06pp | -0.015 | -0.60pp | -0.86pp | Reject |
| `rs3_ge30_and_revenue_ge10` | 15 | -0.75pp | -0.34pp | -0.019 | -0.71pp | -0.88pp | Reject |

## Interpretation

- The Main sleeve does not benefit from the same cap/replacement missed-leader substitution that helped Concentrated.
- The effect is consistently negative across broad rank, RS, and revenue-confirmed filters.
- This is not a concentration artifact: the tool preserved cash weight and total exposure, and all arms kept portfolio concentration within guardrails.
- The result suggests Main's current bottleneck is not "missed high-rank leaders in cap/replacement rejection rows." The Main problem remains a combination of lower IS CAGR and the long-only 2020 drawdown.

## Next Engineering Direction

1. Keep the Concentrated event-matched replacement-quality candidate alive; it remains the strongest evidence-backed CAGR lever.
2. Do not build a Main policy hook from this B2 path.
3. For Main, prioritize:
   - long-only target/governance clarification;
   - W1 target-book control reproduction;
   - shock/exit telemetry and backend-only alerts;
   - selection-quality diagnostics only after W1 is resolved.
4. Do not dispatch a fullrun from this result.

## Validation

- `python -B -m py_compile tools/run_concentrated_cap_replacement_broker_counterfactual.py tests/concentrated_cap_replacement_broker_counterfactual_smoke.py`
- `python -B tests/concentrated_cap_replacement_broker_counterfactual_smoke.py`
- `python -B tools/run_pr_validation.py --only concentrated_cap_replacement_broker_counterfactual_smoke --only replacement_quality_donor_missing_audit_smoke`

