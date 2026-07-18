# Run287 Trade Selection Research Result — 2026-07-18

## Verdict

The historical trade notebook confirms that the selector already captures a
large part of the right tail, but neither same-ticker trade memory nor a
conditional high-signal exit delay survives the frozen generalization gates.
Both paths are closed. No fixed-book or generated-book broker replay was
allowed, because doing so after a failed source screen would convert recent
noise into an apparently improved CAGR.

This result is post-hoc closure evidence, not a preregistered pass. The exact
formula and gates are now frozen in
`docs/run287_trade_selection_research_gate_contract_v1.json` so that the same
idea cannot be reopened by changing thresholds after seeing the result.

## Frozen objective and unchanged historical endpoint

| Portfolio | Frozen historical control | Goal | Remaining gap |
|---|---:|---:|---:|
| Main | CAGR 34.4032% / MDD -25.3619% | CAGR >=35% / MDD >=-25% | +0.5968%p CAGR and +0.3619%p MDD |
| Concentrated | CAGR 49.0971% / MDD -22.9552% | CAGR >=50% / MDD >=-25% | +0.9029%p CAGR |

These are the existing frozen historical controls through the 2026-07-10
historical endpoint, not a 2026-07-17 mark-to-market result. This audit did not
change either number and did not select new current holdings.

## Evidence inspected

- Historical trade answer notebook: 740 Main trades, 338 unique tickers,
  402 repeat entries, 2019-04-30 through 2026-02-27.
- Right-tail winner audit: all 14 available Main winners and all 5 available
  Concentrated winners had strong entry evidence. Coverage is partial because
  `positions_latest` omits some fully closed historical winners.
- Target-book drop counterfactuals: 526 Main and 270 Concentrated drop events,
  labeled at fixed 21/63/126-session horizons from the next tradable close.
- Forward returns remained labels only. `used_forward_return_in_ranking=false`
  and the audit found zero leakage rows.

## Lane 1 — same-ticker prior trade answer

The signal used only the most recent trade that had fully exited before the
new entry. A previous `GOOD_ENTRY_POSITIVE_ALPHA` was positive, a previous
`WRONG_ENTRY_LOSS_AND_LAG` was negative, and missing history was neutral.

| Window | Positive n | Negative n | Positive-minus-negative realized alpha |
|---|---:|---:|---:|
| Full | 174 | 129 | +2.3780%p |
| OOS2 from 2023-01-01 | 94 | 81 | -2.0676%p |
| OOS from 2024-07-01 | 52 | 44 | -3.0768%p |

The sign reverses in both validation windows. In addition, the trade notebook
label spans unequal realized holding periods, so it is not an admissible fixed
63-session source label. Verdict:
`REJECT_OOS_DIRECTION_AND_VARIABLE_HOLDING_LABEL`.

## Lane 2 — conditional right-tail retention after a drop

The frozen high-signal state required all three existing conditions:

- `drop_skill_evidence_flag=true`;
- candidate rank percentile at least 0.80; and
- drop signal stack count at least 7.

It was compared with all other actual target-book drops. The primary metric is
63-session SPY excess return. Bootstrap resamples filing/decision-week blocks
2,000 times with a fixed seed.

| Portfolio | Window | High n | Comparator n | Mean spread | 95% block-bootstrap lower |
|---|---|---:|---:|---:|---:|
| Main | Full | 160 | 353 | -2.6209%p | -6.2675%p |
| Main | OOS2 | 77 | 164 | -3.2248%p | -8.7114%p |
| Main | OOS | 44 | 76 | +1.1287%p | -7.1310%p |
| Concentrated | Full | 124 | 138 | -0.7687%p | -5.7985%p |
| Concentrated | OOS2 | 56 | 62 | -0.3071%p | -7.3607%p |
| Concentrated | OOS | 32 | 34 | +2.8075%p | -7.3198%p |

Both books fail full and OOS2 direction. The recent OOS point estimate is
positive but has a negative clustered lower bound and fewer than the frozen 50
high-signal events. Adopting only the recent segment would be endpoint tuning.
Verdict: `REJECT_SOURCE_SCREEN`.

## Consequence

- No selector, rank, score, cash rule, target weight, or current holding changed.
- No fixed-book A/B, generated-book replay, fullrun, order, production, or live
  trading action ran.
- Generic exit delay remains rejected. Adding rank/stack conditions does not
  reopen it on the same history.
- The next historical CAGR/MDD lane still requires a genuinely independent PIT
  source with accepted/available time, adequate ADR and delisted coverage, and
  positive full/OOS2/OOS source evidence before any portfolio A/B.
- The bounded forward archive should continue, but it cannot be backfilled into
  the seven-year CAGR/MDD claim.

## Reproduction

```powershell
python tools/run_right_tail_entry_signal_audit.py `
  --latest-run H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact\outputs `
  --output-dir outputs/run287_right_tail_entry_signal_audit_20260718 `
  --top-n 20

python tools/run_right_tail_drop_counterfactual_audit.py `
  --latest-run H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact\outputs `
  --price-cache H:\codex\tmp_r1000_grossfloor_20260625\outputs\run287_price_cache_full_candidate\cache_prices `
  --output-dir outputs/run287_right_tail_drop_counterfactual_audit_20260718

python tools/audit_run287_trade_selection_research.py `
  --trade-notebook outputs/run287_historical_trade_answer_notebook_20260717/trade_answer_notebook.csv `
  --drop-counterfactuals outputs/run287_right_tail_drop_counterfactual_audit_20260718/drop_counterfactuals.csv `
  --output-dir outputs/run287_trade_selection_research_audit_20260718
```
