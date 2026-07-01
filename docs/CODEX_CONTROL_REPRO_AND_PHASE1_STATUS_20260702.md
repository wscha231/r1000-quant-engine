# AlphaOps vNext Control Repro / Phase 1 Status - 2026-07-02

## Executive Verdict

Do not dispatch another fullrun yet.

Phase 1 produced one real positive result and one hard rejection:

- `cash-carry` is a research-accounting win.
- broad `bull-floor` / gross-floor is rejected and should not be retried.
- selection-side A/B remains blocked until target-book control reproduction is reliable.

The immediate engineering work is not another 4-6 hour fullrun. It is the cheap reproducibility track:

1. freeze or reproduce the official target-book inputs,
2. verify fixed-official-book controls,
3. only then test hold-duration / selection-side changes.

## Phase 1 Results

Reference artifact:

- `artifacts/fullrun_28436307420/official/outputs`
- official end date: `2026-06-29`
- metric mode: `broker_ledger_next_close`

Baseline official broker-ledger:

| Portfolio | CAGR | MaxDD | Sharpe |
| --- | ---: | ---: | ---: |
| Main | 34.27% | -24.11% | 1.249 |
| Concentrated | 47.46% | -24.08% | 1.414 |

Cash-carry replay:

| Portfolio | Baseline | +Cash Carry | Delta |
| --- | ---: | ---: | ---: |
| Main | 34.27% / -24.11% | 35.11% / -23.99% | +0.84pp CAGR, +0.12pp MDD |
| Concentrated | 47.46% / -24.08% | 48.83% / -23.79% | +1.37pp CAGR, +0.28pp MDD |

Interpretation:

- Cash-carry is economically real, but remains research accounting until the user explicitly adopts a production accounting contract.
- Required contract work: rate source, haircut, day-count, PIT materialization, benchmark total-return consistency, full-history rebaseline.

Official-book bull-floor replay:

| Arm | Concentrated CAGR | MaxDD | Verdict |
| --- | ---: | ---: | --- |
| floor 0.00 control | 48.83% | -23.79% | control |
| floor 0.85 | 45.83% | -32.03% | reject |
| floor 0.90 | 45.22% | -33.53% | reject |
| floor 0.95 | 44.71% | -34.90% | reject |

Interpretation:

- Concentrated cash is load-bearing MDD defense, not idle bull-market drag.
- Do not retry broad gross-floor / bull-floor variants.

## Control-Reproduction Findings

Tool added:

- `tools/run_target_book_control_repro_audit.py`
- `outputs/alphaops_vnext/target_generation_input_manifest.json` now records the candidate book, price-cache manifest, required price-file counts, macro/crisis inputs, env flags, code ref, and optional operating append clamp.

Initial reproduction attempts showed:

| Attempt | Candidate Book | Price Cache | Append End | Date Mismatch | Ticker Mismatch | Max Weight Delta |
| --- | --- | --- | --- | ---: | ---: | ---: |
| non-enriched candidate | reports candidate | fresh cache | none | 1 official-only / 1 generated-only | 50 dates | 0.30 |
| SEC-enriched candidate | official SEC-enriched | fresh cache | none | 1 official-only / 1 generated-only | 27 dates | 0.285 |
| SEC-enriched + both portfolios | official SEC-enriched | fresh cache | none | 1 / 1 | 27 dates | 0.285 |
| SEC-enriched + both + append clamp | official SEC-enriched | fresh cache | `2026-06-29` | 0 / 0 | 25 dates | 0.285 |

Conclusion:

- The new append clamp fixes the latest-date mismatch.
- It does not fully reproduce the historical official book.
- Remaining mismatch is not just candidate source or latest close.

## Code Fix Added

`tools/run_alphaops_vnext_policy_replay.py` now supports:

```bash
--operating-append-end-date YYYY-MM-DD
```

Purpose:

- research/audit only;
- allows fresh price cache to be used while holding the latest operating decision to the official artifact end date;
- default production behavior is unchanged: append to latest observable close.

Validation:

```bash
python -m py_compile tools/run_alphaops_vnext_policy_replay.py tests/alphaops_vnext_policy_replay_smoke.py
python tests/alphaops_vnext_policy_replay_smoke.py
python tools/run_pr_validation.py --only alphaops_vnext_policy_replay_smoke --only target_book_control_repro_audit_smoke
```

All passed.

Artifact contract update:

- `full_rebuild_manual.yml` now uploads/preserves the vNext input manifest and small diagnostic files:
  - `target_generation_input_manifest.json`
  - `pit_evidence_audit.csv`
  - `lane_exposure_by_month.csv`
  - `regime_capacity_overlay_audit.csv`
  - `*_block.json`
  - `main_fast_crash_hedge*.{json,csv}`
  - `lane_feature_mapping.json`
  - `crisis_hysteresis_config.json`
- `rejected_by_reason.csv` is included in the official broker-ledger artifact for post-run diagnosis.
- `lane_scores_history.csv` remains excluded from normal artifacts because it is very large.

## Remaining Root Cause

The fullrun artifact does not currently preserve a complete target-generation input snapshot.

Evidence:

- official commit was `2f83cc815a22c70a1c6322e74fb8afe20d1687da`;
- current committed replay code has no committed drift from that file for `run_alphaops_vnext_policy_replay.py`;
- official artifact `cache_prices` contains only one file in the local downloaded artifact;
- latest concentrated holdings price files such as `SNDK`, `BE`, `WDC`, `CIEN`, `LITE` are absent from artifact `cache_prices`;
- artifact `data_pit/macro/long_crisis_daily_features.parquet` is absent in the local artifact snapshot, causing crisis input fallback if used directly.

Therefore control reproduction still depends on current/fresh cache inputs. That is unacceptable for selection-side A/B interpretation.

## Practical Rule Going Forward

Until target-book control reproduction is exact or near-exact:

- selection-side A/B should use fixed official target books where possible;
- regenerated vNext target-book A/B must be labeled diagnostic only;
- no fullrun should be dispatched merely to test selection-side ideas;
- no production claim can rely on regenerated-book deltas.

## Next Engineering Steps

P0 - Artifact Input Snapshot Contract:

- Persist a target-generation input manifest with:
  - code commit,
  - candidate book path and hash,
  - price cache root/hash manifest,
  - macro/crisis input paths and hashes,
  - environment flags,
  - operating append date / latest close date.
- Next hardening option: persist either a compact top-K monthly scored candidate snapshot or the exact price-cache subset needed by target generation. This is not yet implemented because full `lane_scores_history.csv` was about 738MB in the local repro run.

P1 - Control Repro Acceptance:

- rerun `run_alphaops_vnext_policy_replay.py` from the frozen input snapshot;
- run `run_target_book_control_repro_audit.py`;
- require `official_only_date_count=0`, `generated_only_date_count=0`, `ticker_mismatch_date_count=0`, and near-zero weight delta before selection-side A/B.

P2 - Alpha Work After P1:

- hold-duration / leadership persistence on fixed official books first;
- require OOS/IS non-worsening and multi-era contribution;
- do not revive bull-floor / broad cash deployment.

## Standing Production Blockers

- `pit_universe_label_clean=false` remains a production blocker.
- cash-carry is not production accounting until user-approved contract adoption.
- no live trading, no production mutation, no proxy 8Y/10Y, no T3/recovery.
