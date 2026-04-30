# Codex Review Brief - Claude Branch `claude/analyze-updated-code-OfEbu`

Generated: 2026-04-30 KST

Compare URL:
https://github.com/wscha231/r1000-quant-engine/compare/master...claude/analyze-updated-code-OfEbu

Codex review branch:
`codex/claude-review-OfEbu`

## Executive Verdict

Do not run a production full rebuild directly from the Claude branch yet.

The branch adds useful research scaffolding for tactical alpha, explosion
patterns, trade journaling, feature-gate proposals, and unified mandate
orchestration. However, it diverged from the current `master` and would regress
several already-shipped fixes if used as-is.

The right next step is to port/rebase the Claude changes onto current
`origin/master`, preserving the master fixes listed below, then run smoke/audit
and one cloud full rebuild from the reconciled branch.

## Must Preserve From Current Master

Current `origin/master` contains work that is missing from the Claude branch:

- `7d6429a fix(adr): normalize market cap to USD proxy`
- `b57027e chore(cache): bump engine version for adr mktcap fix`
- `d94c6e9 fix(concentrated): allow continuation winners`
- `8b5cc75 chore(baseline): rotate CURRENT_BASELINE to Phase 15-D`
- `b5a2b2e feat(phase16): CAGR push 24.51% -> ~28-30% target`
- `e6aa6c6 feat(phase17v3-stepA): aggressive sleeve tilt + cash 0% + manual_pin BE/PLUG/RIVN/ENPH`
- current `full_rebuild_manual.yml` support for `global_alpha_universe`,
  `backtest_years`, `fast_mode`, first-run cache preflight, and GDrive sync.

## Critical Findings

1. Baseline regression risk

   Claude branch `run_local.py` still compares against Phase 9 C3 + CE v2
   (`cagr=0.2291`, `sharpe=1.1721`, `max_dd=-0.2626`). Current master baseline
   is Phase 15-D (`cagr=0.2451`, `sharpe=1.2453`, `max_dd=-0.2579`). Using the
   stale baseline can falsely mark a weaker branch as SHIP.

2. Workflow regression risk

   Claude branch `.github/workflows/full_rebuild_manual.yml` predates the
   current production workflow. It lacks `global_alpha_universe`, `backtest_years`,
   `fast_mode`, newer cache preflight, and GDrive handling. A full run from this
   branch will not be comparable to current master.

3. ADR/global market-cap regression risk

   Claude branch lacks the ADR USD market-cap normalization fix. This matters for
   TSM and other foreign issuers because raw market-cap/fundamental sources may
   mix currency conventions. Keep the master USD proxy logic and cache version.

4. Concentrated CAGR regression risk

   Claude branch lacks the continuation-winner override that re-admits high
   momentum winners despite low entry-quality. Without it, concentrated results
   can fall back below the prior 30%+ champion behavior.

5. Tactical alpha is research-only until backtested

   The tactical sleeve is a good direction for high-CAGR optionality, but the new
   scripts need scored-history availability and a clean A/B test before they
   influence production weights. The current orchestrator caps tactical at 0-10%
   by regime, so it will not materially lift total-portfolio CAGR unless promoted
   after evidence.

6. Orchestrator is additive scaffolding, not a replacement allocation model

   `r1000_orchestrator.py` composes main/concentrated/tactical sleeves, but
   conflict handling currently uses max-weight-per-ticker. That is conservative
   and can leave cash when mandates agree on the same winner. Backtest before
   enabling it as the production portfolio composer.

7. Auto baseline rotation should stay off for production master

   `auto_baseline_rotation_weekly.yml` can commit directly to master if gates
   pass. It should be converted to PR-only or explicitly disabled until metrics
   path discovery and sleeve-count checks are aligned with current cloud outputs.

## Codex Patch Applied On Review Branch

- Fixed tactical liquidity filtering to accept both current
  `dollar_vol_20d` and legacy `dollar_vol_avg_20d`.
- Rewrote new CLI docstrings to ASCII so `argparse --help` works on Windows
  default consoles.
- Added this review brief.

## Recommended Port Order

1. Start from current `origin/master`, not from the Claude branch head.
2. Cherry-pick or manually port additive modules:
   - `r1000_trade_journal.py`
   - `r1000_tactical_backtest.py`
   - `r1000_orchestrator.py`
   - new `tools/*` scripts
   - PR-only feature-gate workflow
3. Do not overwrite current master versions of:
   - `.github/workflows/full_rebuild_manual.yml`
   - `run_local.py`
   - `r1000_config.py`
   - `r1000_features.py`
   - `r1000_pipeline.py`
   - `r1000_signals.py`
   until conflicts are reconciled line-by-line.
4. Keep `ENGINE_REUSE_VERSION` at or beyond
   `2026-04-29-concentrated-continuation`.
5. Run:
   - `py -3 tests\smoke_test.py`
   - `py -3 tests\audit_features.py --no-runtime`
   - CLI `--help` smoke tests for all new scripts.
6. Only then trigger cloud `full_rebuild_manual` with:
   - `universe_mode=global_alpha_universe`
   - `backtest_years=8`
   - `fast_mode=true` first
   - `skip_collector=false` if cache is uncertain

## Strategy Opinion

The plan is directionally right: keep core growth-biased but diversified, keep
concentrated as a separate high-CAGR sleeve, and use tactical/explosive movers as
evidence-gated optional alpha rather than blindly increasing turnover.

For the user's target:

- Core: target stable 25% CAGR first, with drawdown and concentration controls.
- Concentrated: target 35-50% CAGR as a separate sleeve, accepting higher
  turnover and drawdown, but only after continuation and exit rules are
  backtested.
- Tactical: use as a small, fast sleeve until it proves high hit-rate and
  positive post-cost alpha over at least 6-8 years.

The next real CAGR improvement should come from measured selection/exit tests,
not from raising weights blindly:

- continuation winners versus entry-quality gate
- daily/weekly exit trigger overlays on concentrated names
- tactical explosion-entry score A/B
- sell discipline after momentum break or overextension
- sector/theme leadership as a boost, not a hard override
