# Claude Review Packet: PR #146 + Full Run 27814870719

Date: 2026-06-20 KST  
Repository: wscha231/r1000-quant-engine  
Current review branch: `codex/fullrun-measurement-artifacts-20260619`  
Current PR: https://github.com/wscha231/r1000-quant-engine/pull/146  
PR head: `63c5aaf1e5653a3d20d28fea6489a230889d6bdf`  
Base: `master`  
Status at Codex check: draft/open/mergeable, GitHub checks green

## 0. Scope Boundary

This packet is for reviewing the current code and the latest 7Y/research full-run result.

Do not review this as an 8Y/10Y expansion task. The user explicitly requested:

- do not work on 8Y or 10Y now
- finish the current 7Y/full-run measurement path
- do not run T3/recovery A/B yet
- do not mutate selection/scoring/cash/target policy/live trading

PR #146 is a measurement/artifact persistence PR, not a strategy PR.

## 1. GitHub / Code State

PR #146:

- URL: https://github.com/wscha231/r1000-quant-engine/pull/146
- Title: `fix: persist full rebuild measurement artifacts`
- Branch: `codex/fullrun-measurement-artifacts-20260619`
- Head: `63c5aaf1`
- Changed files: 6
- Additions/deletions: +228 / -62
- Checks:
  - PR Validation (Fast): success
  - PR Validation (Fast): success
  - Portfolio System Guard: success

Changed files:

- `.github/workflows/full_rebuild_manual.yml`
- `tools/run_full_rebuild_sidecars.py`
- `tools/run_cagr_walkforward.py`
- `tools/run_user_current_report.py`
- `tests/cagr_walkforward_smoke.py`
- `tests/workflow_artifact_smoke.py`

Recent relevant commits:

- `63c5aaf1 feat: add partial-year weighted CAGR view`
- `b6fc2601 fix: persist full rebuild measurement artifacts`
- `d992ae13 fix: unblock full rebuild workflow dispatch (#145)`
- `f44b0b04 feat: add daily market snapshot freshness artifact (#144)`
- `1b0a97ae docs(pages): add docs/public/ placeholder so GitHub Pages can be activated (#143)`
- `f5c41cec feat: add CAGR walk-forward credibility audit (#142)`

## 2. What PR #146 Changes

### 2.1 Full rebuild artifact persistence

`full_rebuild_manual.yml` now preserves measurement outputs that were missing from the previous full-run artifact:

- `outputs/cagr_walkforward/`
- `outputs/daily_market_snapshot/`
- `data_pit/free/market_snapshot/`
- `data_raw/free/market_snapshot/yf_market_info_cache.csv`
- relevant logs

Purpose: future full-run artifacts should contain the B1 credibility sidecar and daily market snapshot evidence without requiring local re-run.

### 2.2 Sidecar execution

`tools/run_full_rebuild_sidecars.py` now builds the daily market snapshot before data freshness checks in the full rebuild paths.

It also keeps B1 CAGR walk-forward as a non-fatal sidecar.

Purpose: avoid stale or missing `daily_market_snapshot` warnings where possible, and make CAGR credibility artifacts appear in the official artifact bundle.

### 2.3 User current fallback isolation

`tools/run_user_current_report.py` was adjusted so local/temp fixture runs do not silently read committed repo-root `cloud_results`.

Purpose: prevent tests and local generated reports from mixing unintended fallback data.

### 2.4 B1 CAGR walk-forward v3

`tools/run_cagr_walkforward.py` schema is now `cagr-walkforward-v3`.

Key behavior:

- rolling full-year average still uses completed full calendar years only: 2020-2025
- 2026 partial year is included only in separate day-weighted reference fields
- `single_oos` fallback pollution is blocked
- if metrics do not provide OOS CAGR:
  - `single_oos_cagr = null`
  - `single_oos_cagr_source = "unavailable"`
  - `inflation_indicator = null`
  - `verdict = "single_oos_unavailable"`
- MDD is path-based, so it is not day-weight averaged
- MDD is reported as:
  - `full_max_drawdown`
  - `worst_full_year_max_drawdown`
  - `partial_year_max_drawdowns_for_reference_only`

Important: this is not a walk-forward retrain. It is rolling calendar-year CAGR segmentation over the same trained broker-ledger equity curve.

## 3. Local Validation Completed

Codex ran:

- `python tests\cagr_walkforward_smoke.py`
- `python tools\run_pr_validation.py --only cagr_walkforward`
- `python tests\workflow_artifact_smoke.py`
- `python tools\run_pr_validation.py`

Result:

- full validation passed: 107/107 tests
- `workflow_artifact_smoke.py` passed
- `cagr_walkforward_smoke.py` passed

## 4. Latest Full Run Under Review

GitHub Actions run:

- Run ID: `27814870719`
- Run URL: https://github.com/wscha231/r1000-quant-engine/actions/runs/27814870719
- Requested mode: 7Y/full run, not 8Y/10Y
- Downloaded local artifacts:
  - `H:\codex\_artifacts\full_rebuild_27814870719\official-broker-ledger-global_alpha_universe-27814870719`
  - `H:\codex\_artifacts\full_rebuild_27814870719\user-operating-minimal-global_alpha_universe-27814870719`

Official metric source:

- `outputs/account_evaluation/official_metrics.json`
- `outputs/broker_replay/main/metrics.json`
- `outputs/broker_replay/concentrated/metrics.json`
- metric mode: `broker_ledger_next_close`

## 5. Full Run Verdict

This run is useful for research and diagnostics, but not promotable.

Reasons:

- broker replay window starts at `2020-05-01`
- end date is `2026-06-17`
- years: about `6.1273`
- evidence window label: `research_7y`
- window gate: `invalid_window`
- `valid_for_production=false`
- `production_promotion_allowed=false`
- `pit_universe_label_clean=false`
- `proxy_8y_10y_evidence_blocked=true`
- `target_contract_status=unresolved_user_decision_required`
- `strengthened_pass=false`

Data readiness is better than the previous blocked run:

- `ready_for_fullrun=true`
- `ready_for_policy_replay=true`
- `status=warn`
- universe health is no longer starved
- current universe used fallback/static seed

This is still not a production promotion run.

## 6. Official Broker-Ledger Results

| Portfolio | CAGR | MDD | Sharpe | Avg Cash | Latest Cash | IS CAGR | OOS CAGR | Tier2 Failure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Main | 39.56% | -24.46% | 1.389 | 26.51% | 15.54% | 25.36% | 76.43% | `oos_is_cagr_ratio_max` |
| Concentrated | 50.62% | -23.83% | 1.518 | 42.25% | 6.33% | 22.35% | 135.19% | `is_cagr_min`, `oos_is_cagr_ratio_max` |

Interpretation:

- headline CAGR/MDD is close to or above mission targets
- OOS/IS dependence is still too high
- concentrated IS CAGR is too weak
- promotion remains blocked

## 7. B1 CAGR Credibility v3 Results

Derived local output:

- `H:\codex\_artifacts\full_rebuild_27814870719\_derived\cagr_walkforward_official_v3`

Report:

| Portfolio | Full CAGR | Full MDD | Single OOS CAGR | Rolling 2020-2025 Avg | Worst Full-Year MDD | Day-Weighted Incl 2026 Partial | Inflation | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Main | 39.56% | -24.46% | 76.43% | 42.34% | -23.78% | 51.92% | 1.81x | `single_oos_moderately_above_rolling_avg` |
| Concentrated | 50.62% | -23.83% | 135.19% | 52.31% | -23.13% | 69.99% | 2.58x | `single_oos_inflated_vs_rolling_avg` |

2026 partial-year detail:

| Portfolio | 2026 Partial CAGR | 2026 Partial MDD |
| --- | ---: | ---: |
| Main | 245.56% | -12.86% |
| Concentrated | 358.53% | -15.01% |

Review note:

- The 2026 annualized CAGR is very high because the observed period is short.
- v3 therefore reports both:
  - completed-year average, excluding 2026
  - day-weighted reference, including observed 2026 time
- MDD is not day-weight averaged. It is reported as actual path drawdown per window.

## 8. Cash Interpretation

Cash is still a key issue.

Official metrics:

- Main avg cash: 26.51%
- Main latest cash: 15.54%
- Concentrated avg cash: 42.25%
- Concentrated latest cash: 6.33%

Cash audit from this run:

- Main cash trap flag: true
- Main green avg cash: about 16.44%
- Concentrated cash trap flag: true
- Concentrated green avg cash: about 22.85%
- cash contract drift rows: 0

Interpretation:

- This does not look like a target-to-broker cash transfer bug.
- It looks more like policy-level cash drag/cash trap in historical regimes.
- We should not simply force cash lower.
- Next valid alpha work should separate:
  - crisis defense cash that reduced MDD
  - green/bull cash that reduced CAGR without improving drawdown

## 9. Current Simulated Holdings

Important: these are simulated broker-ledger holdings, not live brokerage holdings. The action state remains `DO_NOT_TRADE`.

### Main

| Ticker | Weight |
| --- | ---: |
| CASH | 15.54% |
| SNDK | 15.50% |
| WDC | 14.32% |
| MRVL | 11.79% |
| STM | 11.01% |
| CIEN | 5.95% |
| ON | 4.89% |
| MU | 4.74% |
| LITE | 4.51% |
| PWR | 3.99% |
| FIX | 3.26% |
| COHR | 2.26% |
| TER | 1.33% |
| KEYS | 0.91% |

### Concentrated

| Ticker | Weight |
| --- | ---: |
| SNDK | 37.26% |
| BE | 22.22% |
| WDC | 21.71% |
| CIEN | 7.88% |
| CASH | 6.33% |
| LITE | 4.60% |

## 10. Current Selection Logic Interpretation

The current holdings are mostly selected/retained through:

- `MARKET_LEADER`
- `future_winner`
- `DUAL_LEADER`
- `hold_forward_to_latest_close`
- theme active where available
- positive smart-money or ETF evidence where available

Examples from `alphaops_vnext/selected_latest.csv`:

- SNDK: `MARKET_LEADER`, `future_winner`, `DUAL_LEADER`, theme active, positive evidence, regime capacity dampened
- WDC: high score, `MARKET_LEADER`, retained by `vnext_score_and_risk_intact`, but latest gate shows `rejected`
- MRVL: `MARKET_LEADER`, theme active, positive evidence
- STM: ADR/global-alpha fallback, `MARKET_LEADER`
- BE: `MARKET_LEADER`, positive evidence, regime capacity dampened
- CIEN/LITE: communication equipment leaders, theme active, retained/selected by vNext gates
- PWR/FIX: industrial/construction leaders, positive evidence for PWR/FIX
- COHR/TER: retained leaders, but latest candidate gate shows `rejected`

Review note:

- For names with `gate=rejected`, this should not be interpreted as a new buy signal.
- It is better understood as target-book/current-holding replay retention until the next valid rebalance logic decides otherwise.

## 11. Known Output Naming Gap

Planned user-current file names previously included:

- `08_rebalance_decision.json`
- `03_order_preview.csv`

This artifact actually contains:

- `08_broker_rule_backtest.json`
- no `07_name_rationales.csv`
- no `08_rebalance_decision.json`

Current folder:

- `01_current_holdings.csv`
- `02_cash_summary.json`
- `03_period_returns.csv`
- `04_official_metrics.json`
- `05_action_summary.md`
- `06_benchmark_comparison.csv`
- `07_research_sidecar_context.json`
- `08_broker_rule_backtest.json`
- `README_FIRST.md`
- `summary.json`

Please review whether this is acceptable, or whether PR #146 / follow-up should restore the originally planned user-current naming contract.

## 12. Unified Review / Implementation Instruction

Please analyze full run `27814870719` as a research diagnostic, not a production promotion run.

Known facts to preserve in the review:

- official broker-ledger artifact exists
- Main: 39.56% CAGR / -24.46% MDD / Sharpe 1.389
- Concentrated: 50.62% CAGR / -23.83% MDD / Sharpe 1.518
- broker window starts `2020-05-01` and is only about 6.13 years
- `valid_for_production=false`
- `strengthened_pass=false`
- headline Main and Concentrated mission targets appear met, but promotion is blocked by invalid window, Tier2 robustness, and unresolved evidence quality
- Concentrated OOS/IS is high
- cash audit flags both portfolios as cash trap
- current holdings are simulated broker-ledger holdings, not live broker holdings
- action remains `DO_NOT_TRADE`

Critical rule:

Broker-ledger CAGR/MDD is the only mechanically trusted performance metric, but no CAGR/MDD value can be used as production evidence until universe membership PIT is clean enough. If historical membership, delisted coverage, ticker-change handling, survivorship control, or `universe_available_from` is incomplete, label the result as research/proxy/diagnostic only.

Do not:

- treat the 6.13y window as production promotion
- call the 2020-05 onward result final
- use partial-year 2026 annualized CAGR as proof
- use legacy/proxy/weight-level metrics for promotion
- use future returns as live signals
- enable live trading
- mutate production targets
- run T3/recovery A/B before the diagnostics below are produced and reviewed

PR #146 scope:

Treat PR #146 only as measurement artifact persistence, not strategy improvement. It may persist CAGR walk-forward, daily market snapshot, and user-current fallback isolation artifacts. It must not change selection, scoring, target-book policy, cash policy, production gate, workflow dispatch, or live trading.

## 13. Immediate Required Work Before A/B

These items are required before T3/replacement/reentry/recovery A/B. They may be follow-up PRs after PR #146 unless Claude marks any item as a PR #146 blocker.

### 13.1 Restore user_current operating file contract

Required user-facing files:

- `outputs/user_current/02_target_weights.csv`
- `outputs/user_current/03_order_preview.csv`
- `outputs/user_current/07_name_rationales.csv`
- `outputs/user_current/08_rebalance_decision.json`

These must clearly show:

- current simulated holdings
- target weights
- delta / order preview
- action status
- `review_only=true`
- `live_trading_enabled=false`
- `production_mutation_allowed=false`
- `human_approval_required=true`
- `DO_NOT_TRADE` when any safety gate fails

### 13.2 Add name rationale artifact

Create `outputs/user_current/07_name_rationales.csv` explaining each current holding.

Required columns:

- `portfolio`
- `ticker`
- `current_weight`
- `target_weight`
- `selected_vs_retained`
- `lane`
- `theme`
- `sector`
- `subindustry`
- `leader_state`
- `selection_reason`
- `hold_reason`
- `risk_reason`
- `rs_spy_1m`
- `rs_spy_3m`
- `rs_spy_6m`
- `rs_qqq_1m`
- `rs_qqq_3m`
- `rs_qqq_6m`
- `rs_smh_soxx_if_applicable`
- `valuation_flag`
- `quality_flag`
- `evidence_flag`
- `top7_score`
- `form4_score`
- `etf_score`
- `gate_status`
- `is_new_buy_signal`
- `is_replay_retention`
- `data_pit_status`
- `membership_pit_status`

Purpose:

Explain whether a name is newly selected by the current policy or merely retained from broker-ledger replay. Do not allow users to confuse replay-retained holdings with fresh buy signals.

### 13.3 Add cash trap attribution

Create a cash attribution report separating useful defense from cash drag.

Required categories:

- `crisis_defense_cash`
- `green_idle_cash`
- `cap_residual_cash`
- `missing_candidate_cash`
- `reentry_delay_cash`
- `position_risk_exit_cash`
- `unknown_cash`

Required metrics:

- `cash_by_regime`
- `cash_by_crisis_state`
- `green_avg_cash`
- `crisis_avg_cash`
- `reentry_cash_normalization_days`
- `missed_rebound_return`
- `cash_drag_vs_baseline`
- `cash_trap_flag`

Rules:

- GREEN cash > 10% is bad cash unless explicitly justified
- latest cash > 50% outside CRISIS is reject
- cash increased but MDD did not improve by at least 3pp is cash-trap suspect
- reentry normalization > 20 trading days is a reentry failure

### 13.4 Add B2 alpha/beta attribution

Create an attribution layer to separate true stock-selection alpha from factor beta.

Required decomposition:

- SPY beta
- QQQ beta
- SMH/SOXX semiconductor beta
- sector/theme beta
- cash drag
- stock selection residual alpha
- position concentration alpha
- drawdown contribution by name
- top winner contribution

Purpose:

Determine whether SNDK/WDC/MRVL/MU/CIEN/LITE-type holdings create stock alpha or merely reflect semiconductor/storage beta.

### 13.5 Add right-tail / winner-capture diagnostics

Do not reject a concentrated growth strategy merely because returns are concentrated or OOS-heavy. Right-tail capture can be skill if supported by ex-ante signals.

Required diagnostics:

- `winner_capture_rate`: did selected names include future top-decile winners based on T-date observable features?
- `early_entry_score`: was the name bought before major price expansion, not after?
- `hold_winner_score`: did the system hold winners through normal shakeouts?
- `premature_sell_loss`: did sold leaders outperform over the next 63d/126d?
- `top_winner_contribution`: how much CAGR came from top 1/3/5 names?
- `leave_top_winner_out`: does CAGR collapse if top 1 or top 3 winners are removed?
- `theme_leader_capture`: did the system capture semis, AI infra, power, crypto infra, space, and other leading themes when those themes led?
- `factor_adjusted_winner_alpha`: did the winner outperform SPY/QQQ/SMH/SOXX after controlling for theme beta?

Interpretation:

- concentrated right-tail contribution is acceptable for a growth-leader strategy
- it becomes skill only if the winner was ex-ante identifiable by RS, theme leadership, price/volume, earnings/revision/event reaction, Form4/13F/ETF support, or other PIT-visible evidence
- it is luck if the winner cannot be explained by T-date signals, or if the result collapses under leave-top-winner-out and fails robustness checks

### 13.6 Enforce universe membership PIT discipline

Before any production claim, each candidate and selected name must have clean or explicitly labeled membership provenance.

Required fields:

- `rebalance_date`
- `ticker`
- `membership_source`
- `membership_available_from`
- `universe_label`
- `official_r1000_membership_proven`
- `proxy_universe_flag`
- `survivorship_status`
- `delisted_coverage_status`
- `ticker_change_coverage_status`
- `membership_pit_status`

Rules:

- do not retroactively apply current IWB/R1000 membership to past dates as if it were historical PIT membership
- if official historical Russell 1000 membership is unavailable, label the universe as proxy / `pit_proxy_universe`
- proxy universe results may be used for robustness and `ready_for_human_review`, but not as official Russell 1000 production evidence
- any run with unknown/unclean membership PIT must set `production_eligible=false` even if broker-ledger CAGR/MDD is strong

### 13.7 Maintain strict PIT rules

- 2020 decisions must use only data available at that date
- fundamentals must use `accepted_at` / `available_from`, not `report_period`
- 13F must use filing `available_from`, not report period
- Form4 must use `accepted_at`
- ETF holdings must use published `available_from`
- macro data must use observation/publication date as appropriate
- forward returns are audit labels only and must never affect live ranking or historical ex-ante selection

### 13.8 Cadence / operating rules

- Daily after close: refresh prices, volume, RS, macro/crisis, current-vs-target drift, risk alerts, order preview
- Weekly: review warnings, new leaders, missed leaders, and potential additions
- Biweekly: partial rebalance only if triggered by clear leader change, `EXIT_REPLACE`, or `REENTRY_READY`
- Monthly: full target review
- Quarterly: fundamentals, earnings/revisions, 13F, Top7 manager score updates

Daily outputs remain review-only:

- `review_only=true`
- `live_trading_enabled=false`
- `production_mutation_allowed=false`
- `human_approval_required=true`
- `canonical_production_sync=false` unless explicitly approved

## 14. Evidence Tiering

Use these tiers:

Tier 0 `DO_NOT_USE`:

- `data_readiness=false`
- universe starved
- official broker metric missing
- current/order preview invalid
- membership PIT broken with no label

Tier 1 `Research Diagnostic`:

- broker-ledger metric exists
- window or membership PIT is not sufficient for production

Tier 2 `Research / A/B Candidate`:

- clean 7Y broker-ledger or equivalent
- data readiness pass
- universe healthy
- current/target/order preview coherent
- not official promotion

Tier 3 `Robust Candidate`:

- clean 7Y plus proxy_10y robustness pass, or clean 8Y official window pass
- cash trap false
- IS/OOS acceptable
- `ready_for_human_review` only

Tier 4 `Production Candidate`:

- official evidence contract pass
- membership PIT clean or user-approved alternative evidence contract
- `broker_ledger_next_close` targets pass
- IS/OOS gate pass
- cash trap false
- human approval required

## 15. A/B Sequencing

Do not run T3/replacement/reentry A/B until diagnostics above are produced and reviewed.

After diagnostics, run A/B in this order:

1. T3 continuation winner / hysteresis
2. hard replacement cap wiring
3. bull-floor stock exposure
4. reentry quality
5. theme leadership boost
6. concentration cap relaxation
7. era-aware challenger review-only

T3 rules:

- healthy held name can be replaced only if the new candidate is +0.75 sigma stronger
- broken held name can be replaced if the new candidate is +0.35 sigma stronger
- replacement caps:
  - main <= 5 per rebalance
  - concentrated <= 2 per rebalance

## 16. Final Stance To Review

Run `27814870719` is a strong research signal and suggests the system is finally capturing growth leaders. But because the window starts after the COVID crash, membership PIT is not yet production-clean, cash traps remain, and robustness gates fail, it is not a production promotion run.

Treat it as a promising right-tail capture candidate requiring:

- name rationale
- cash attribution
- alpha/beta attribution
- winner-capture diagnostics
- membership PIT labeling

before any A/B or promotion decision.

## 17. Questions For Claude

Please review the current code and results with these questions:

1. Is PR #146 still strictly measurement/artifact-only?
2. Are the changed files appropriate, or is any change outside the intended scope?
3. Is `cagr-walkforward-v3` mathematically correct?
   - full-year CAGR average excludes partial years
   - day-weighted reference includes partial years by observed years/days
   - MDD is not day-weight averaged
4. Should the report use weighted arithmetic CAGR, weighted geometric CAGR, or both?
5. Is it correct to keep 2026 partial-year CAGR as reference only despite adding the day-weighted field?
6. Is the cash interpretation correct: cash issue appears policy-level, not broker cash drift?
7. Are current holdings explainable enough from `selected_latest.csv`, or do we need a dedicated `07_name_rationales.csv` artifact?
8. Should the `user_current` file naming contract be fixed now or deferred?
9. Given this result, should next work be:
   - B2 alpha/beta attribution
   - cash trap attribution
   - user-current rationale artifact
   - or another measurement-only follow-up?
10. Confirm that no 8Y/10Y/proxy work, T3/recovery A/B, bull-floor promote, live trading, or target mutation should be started from PR #146.
11. Does Claude agree that the required follow-up order is:
    - restore `user_current` file contract
    - add `07_name_rationales.csv`
    - add cash trap attribution
    - add B2 alpha/beta attribution
    - add winner-capture diagnostics
    - add membership PIT labels
12. Which of the follow-up items, if any, should be considered a blocker before PR #146 can merge?

## 18. Recommended Next Step From Codex

Codex recommendation:

1. Get Claude/ChatGPT Pro review of PR #146.
2. If review is only docs/schema/test naming cleanup, apply small fix on the same PR.
3. Do not merge automatically.
4. If Claude marks the missing `user_current` contract or name rationale artifact as a PR #146 blocker, implement that first as a measurement/reporting-only fix.
5. Otherwise, after user approval and PR #146 merge, continue with the follow-up diagnostics in this order:
   - user-current file contract / name rationale
   - cash trap attribution
   - B2 alpha/beta attribution
   - right-tail winner-capture diagnostics
   - membership PIT labeling
6. Do not start A/B work until these diagnostics exist and are reviewed.
