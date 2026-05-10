# R1000 AlphaOps Research Notes

Date: 2026-05-02 KST
Branch reviewed: `codex/integrate-phase17-19`
Latest local HEAD reviewed: `242f02f chore(bot): full rebuild [global_alpha_universe] 2026-04-30 [skip ci]`

## Purpose

This note converts the weekend research into an implementation-ready system map.
It is intentionally not a code change. The goal is to decide how the existing
Phase 17-19 parts should be promoted from research sidecars into the production
decision path without blindly changing weights, gates, or risk behavior.

The desired long-term system is the R1000 AlphaOps Engine:

1. Discover high-quality winners early.
2. Hold proven winners longer.
3. Cut broken names quickly.
4. Convert every trade outcome into a future rule or model test.

## Sources Reviewed

- `C:/Users/.../Downloads/codex_final_research_brief.md`
- `C:/Users/.../Downloads/codex_alphaops_implementation_plan.md`
- `C:/Users/.../Downloads/codex_agent_prompt.md`
- `C:/Users/.../Downloads/r1000 integrate-phase17-19 ... report.pdf`
- `C:/Users/.../Downloads/kr-quant-engine ... report.pdf`
- `PHASE17_19_INTEGRATION_NOTES.md`
- `r1000_config.py`
- `r1000_pipeline.py`
- `r1000_signals.py`
- `r1000_orchestrator.py`
- `r1000_risk_sensing.py`
- `r1000_trade_journal.py`
- `r1000_tactical_backtest.py`
- `r1000_operator.py`
- `r1000_paper_executor.py`
- `.github/workflows/*.yml`
- Latest cloud output under `cloud_results/full_rebuild/latest_global_alpha_universe/`

## Current Performance State

Latest successful cloud result after the ADR market-cap cache fix:

| Track | CAGR | Sharpe | MaxDD | Notes |
| --- | ---: | ---: | ---: | --- |
| Phase 15-D baseline | 24.51% | 1.2453 | -25.79% | Shipped baseline |
| Current main run | 23.35% | 1.2949 | -23.74% | PARTIAL vs baseline |
| Current concentrated | 37.33% | 1.4471 | -23.06% | Strong, but still below 50% stretch target |

Other latest-run observations:

- Main portfolio latest: 17 names.
- Backtest average names: 25.4.
- Monthly turnover: 48.7%.
- Cash average: 7.6%.
- ADR rows in `scored_latest.csv`: 28.
- Selected ADR/global names: `TSM`, `ZTO`.
- Cycle play rows: 2; selected: `BE`.
- `regime_state` exists but latest distribution is all `neutral`.
- `explosion_*` columns exist but are currently zero because no trained explosion model is active.
- Trade journal produced 712 trades and 2123 holdings rows.
- Auto-learning generated proposals, but promotion was blocked on main CAGR floor.

Interpretation:

- The engine has useful sidecar observability, but the main production selection
  still relies on the legacy portfolio path.
- Concentrated sleeve alpha exists, but main book alpha has not yet converted
  into a 30%+ CAGR / lower drawdown production profile.
- The current weakness is not "missing one more factor"; it is controlled
  promotion of sidecar knowledge into sizing, risk, timing, and postmortem
  learning.

## Production Path Today

The current production path is roughly:

```text
run_local.py
  -> run_default_pipeline()
    -> r1000_pipeline.run_all()
      -> collect/reuse data
      -> build_feature_store()
      -> compute sleeve columns in r1000_signals.py
      -> train/walk-forward score
      -> backtest_portfolio()
      -> build_latest_recommendations()
      -> export_outputs()
```

Main selection and weighting still depend primarily on:

- `r1000_pipeline.py`
- `r1000_signals.py`
- `EngineConfig` fields in `r1000_config.py`
- `build_latest_recommendations()`
- `backtest_portfolio()`
- concentrated comparison logic inside the pipeline

## Sidecar / Research Path Today

The Phase 17-19 integration added important parts, but most are not yet
production allocation drivers:

| Component | Current status | Production behavior impact |
| --- | --- | --- |
| `r1000_orchestrator.py` | Pure transform, inspection-only | Not used by production backtest |
| `r1000_risk_sensing.py` | Good risk-action model, CLI stub | Not wired into live operator target |
| `r1000_tactical_backtest.py` | Research-only tactical sleeve | Not part of main production allocation |
| `r1000_trade_journal.py` | Writes holdings/trades/grades | Diagnostic and learning sidecar |
| `tools/trade_insights.py` | IC, cluster, SHAP diagnostics | Research report only |
| `tools/feature_gate_proposal.py` | Generates proposals | No effect unless active YAML exists |
| `tools/auto_learning_promote.py` | Conservative promotion checker | Blocked if challenger metrics fail |
| `explosion_*` columns | Present, fallback zero | Not in `DEFAULT_FEATURES` |
| ETF leadership | Sidecar/report | Does not alter sector caps |

This conservative separation is correct. The next step is not to bypass it.
The next step is to promote each sidecar through explicit A/B gates.

## Config Audit

Important current defaults:

- Official manual full rebuild window default: 8 years.
- `price_history_years`: 15.
- `fsds_quarters_backfill`: 60.
- `trade_cost_bps_per_side`: 25 bps.
- `roundtrip_cost_bps`: 50 bps.
- `rebalance_interval_months`: 1.
- sleeve rebalance defaults: core 1m, future 2m, early 1m.
- `turnover_cap_monthly`: 0.55.
- concentrated target sizes tested: 3, 4, 5, 1, 2, 7, 10.
- concentrated continuation override enabled at quantile 0.90.
- `MANDATE_REGISTRY.main.default_target_n`: 20.
- `MANDATE_REGISTRY.concentrated.default_target_n`: 5.
- `MANDATE_REGISTRY.tactical.default_target_n`: 5.
- tactical capacity: 0 in deep_bear/bear/neutral, 5% in bull, 10% in strong_bull.

Potential default conflicts:

1. Research target says main book should often be 7-10 names, but current
   main/default machinery still produces 17 latest names and 25.4 average names.
   This may be the largest CAGR drag, but it is a high-risk behavior change and
   needs A/B testing.
2. Current concentrated result is strong, but any direct anti-chase penalty could
   conflict with the continuation-winner override that preserved 30%+ CAGR.
3. `colab_run.ipynb` and GitHub Actions use different fast/full expectations.
   This is acceptable if documented, but dangerous if users compare results
   without noting the mode.
4. Auto feature gates are proposal-only and currently inactive. That is correct.
   They should not be activated without a challenger run.
5. `regime_state` is currently all neutral. Any regime-conditioned allocation
   needs a regime classifier health test before it can drive capital.

## What Should Be Promoted First

The safest promotion order is:

1. Baseline and artifact registry.
2. Config/default audit report.
3. Orchestrator shadow output.
4. Risk sensing to operator recommendations.
5. Order ticket / cost model.
6. Trade journal postmortem reports.
7. Auto-gate challenger A/B.
8. Tactical sleeve ship-gated integration.
9. Target-N and regime capacity A/B.
10. Dynamic theme engine.
11. Conditional leverage.

Reasoning:

- Steps 1-6 improve decision quality and operations without changing selection.
- Steps 7-9 change behavior, so they need controlled A/B gates.
- Step 10 expands discovery but should begin as a sidecar.
- Step 11 can only amplify proven unlevered edge.

## What Should Not Be Turned On Yet

Do not directly enable the following as production defaults:

- Auto baseline rotation.
- Auto feature gate activation.
- ETF leadership -> sector cap changes.
- Leverage overlay.
- Tactical sleeve allocation in neutral/bear regimes.
- Chase penalties that block known continuation winners.
- Dynamic theme membership as a hard filter.
- Fully automatic broker execution.

These may be valuable after A/B tests, but they are not safe defaults now.

## Core Hypotheses To Test

H1: Main CAGR is diluted by too many names.

- Test target N: 8, 10, 12, 17, 20, 30.
- Preserve cost and max drawdown gates.
- Compare against Phase 15-D and latest `242f02f`.

H2: Regime-conditioned capital can reduce drawdown without killing CAGR.

- Keep tactical at 0 in neutral/bear until the regime classifier is healthy.
- Test main/concentrated capacity maps separately from security selection.

H3: Tactical explosive alpha should be isolated to a small sleeve.

- Use tactical only in bull/strong_bull.
- Require standalone positive excess return after 25 bps per side cost.
- Require no portfolio-level drawdown damage.

H4: Trade journal can identify bad entry patterns without overfitting.

- Use feature gates as challenger-only.
- Promote only if full pipeline metrics pass.

H5: Stronger risk sensing can lower MDD while preserving winners.

- Prefer risk actions that reduce broken positions and halt new buys.
- Avoid rules that force-sell proven winners unless price/RS/regime damage is real.

## Open Decisions Before Implementation

1. Should the main production book target 7-10 names, or is 15-20 the practical
   operating target because of capacity and drawdown?
2. What is the max single-name cap for the main book after orchestrator unifies
   main/concentrated/tactical?
3. Should concentrated remain a separate report or become a fixed 5-15% sleeve?
4. Which risk actions are allowed to override monthly rebalance in signal-only
   mode?
5. Should auto-learning proposals create PRs only, or may they create inactive
   YAML candidates on the branch?
6. What is the minimum paper/signal-only period before broker execution?

## Recommended Weekend Scope

The weekend should not attempt a full strategy rewrite. The highest-value safe
scope is:

1. Lock the current baseline registry.
2. Add a config/default audit command.
3. Add orchestrator shadow CSV outputs and equivalence checks.
4. Connect risk_sensing outputs to operator-plan recommendations in report-only
   mode.
5. Expand trade-journal postmortem reports.
6. Define the A/B matrix and ship gates before running another full rebuild.

Only after these are in place should behavior-changing experiments begin.

