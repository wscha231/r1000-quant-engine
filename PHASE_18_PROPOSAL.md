# Phase 18 — AlphaTrade Journal & Self-Improvement Loop

## Status
- **18a** (this commit) — Trade journal infrastructure + automatic grading
- **18b** (next) — IC-by-regime matrix + pattern clustering + SHAP attribution
- **18c** (after 18b) — Auto feature-gate + auto pattern blocklist + self-improving loop

## Motivation

Current ship gate is CAGR / Sharpe / MaxDD aggregates. That tells us
*whether* a change shipped, not *why* — there's no feedback on which
specific trades won, lost, or were "trap" entries. Without trade-level
attribution we can't answer:

  * Which signal correctly identified our winners last year?
  * Which signal mis-fired in bear regimes?
  * Are there feature patterns that consistently produce losses?
  * Did our stop-loss rules cut winners short?

Phase 18 builds the foundation (18a), the analysis layer (18b), and the
auto-improvement layer (18c).

## Design philosophy — "AlphaGo for trading"

```
AlphaGo                    →  AlphaTrade
─────────────────────────     ──────────────────────────
1. Value network              1. Phase 11 P(entry/tp/sl) (already exists)
2. Policy network             2. score + sleeve (already exists)
3. MCTS rollouts              3. backtest + per_position_replay (exists)
4. Self-play training data    4. ★ trade journal (18a — this commit)
5. Iterative retraining       5. ★ auto-gate + retrain (18b/c)
```

Walk-forward backtest is the source of training data. Each
historical month's trades reflect the **current engine's decisions**
under **point-in-time information** — they ARE the trades we would
have made. After one FULL rebuild we have ~1,680 trade records (84
months × ~20 names). No need to wait for paper-trade accumulation.

## 18a — Schemas

### `outputs/trade_journal/holdings_history.parquet`
Per-month holding snapshot (one row per ticker per rebalance date).
Mirrors the in-memory `BacktestResult.holdings` plus per-row entry
signal breakdown JSON + regime tag.

```
rebalance_date          datetime
ticker                  str
weight                  float
raw_score               float
portfolio_sleeve_label  str   (core_compounder / future_winner / early_scout / cash)
portfolio_sleeve_role   str
portfolio_selection_path str
period_forward_return   float
weighted_forward_return float
target_n                int
entry_signal_breakdown  json  ← Phase 14 + 15 + 17 signal contributions
regime_state            str   ← deep_bear / bear / neutral / bull / strong_bull
regime_state_score      int
engine_version          str   ← e.g. "2026-04-29-phase17v3-l11-explosion"
```

### `outputs/trade_journal/trades.parquet`
Entry-exit pair for each held position. One row per round-trip.

```
trade_id                str   uuid
ticker                  str
entry_date              datetime
entry_price             float
entry_score             float
entry_sleeve            str
entry_regime_state      str
entry_signal_breakdown  json  (copied from holdings row)
exit_date               datetime
exit_price              float
exit_reason             str   (scheduled_rebalance / sleeve_flip / dropped_from_topk)
holding_days            int
realized_return         float
benchmark_return_same_period  float
alpha_vs_benchmark      float
engine_version          str
```

Note: 18a's `exit_reason` is limited to what `holdings_rows` already
exposes (`rebalance_action`). Stop-loss / trailing / revision_break
reasons live in the in-memory backtest loop (`r1000_pipeline.py:9616-10042`)
but aren't propagated to `holdings_rows`. **18a-followup** will
propagate them; 18a ships with the limited set so we don't block.

### `outputs/trade_journal/grades.parquet`
Auto-applied label per trade (18a Stage 2).

```
trade_id            str
grade_label         str   (WIN / LOSS / TRAP / GOOD_EXIT / NEUTRAL)
grade_reason        str   (human-readable explanation)
realized_return     float
alpha_vs_benchmark  float
holding_days        int
regime_at_entry     str
```

Grade rules (18a default; tunable in 18b):
* `WIN`: realized > +5% AND alpha > +2%
* `LOSS`: realized < -10%
* `TRAP`: realized < -20% AND held ≥ 60 days (deep loss, not noise)
* `GOOD_EXIT`: positive trade with timely exit (top quartile alpha)
* `NEUTRAL`: everything else

## 18a — Module surface

`r1000_trade_journal.py` (new module):

* `attach_signal_breakdown(row, month_df, ticker)` — extract Phase 14+17 signals from `month_df` for a single ticker, return JSON-encoded dict
* `persist_holdings_history(holdings_df, paths, engine_version)` — write parquet + CSV
* `pair_entries_with_exits(holdings_df, paths, engine_version)` — build `trades.parquet`
* `grade_trades(trades_df, benchmark_returns)` — compute labels, write `grades.parquet`
* `summary_digest(grades_df) -> dict` — counts per label, top 10 wins/losses

`tools/grade_trades.py` (new CLI): runs `pair_entries_with_exits` +
`grade_trades` on existing journal files. Useful when journal already
exists from a prior backtest and we want to re-grade with updated
rules without re-running the backtest.

## 18a — Wire-in points

Two minimal hooks in `r1000_pipeline.py`:

1. Inside `holdings_rows.append({...})` at line 9994:
   add `entry_signal_breakdown` + `regime_state` + `regime_state_score` +
   `engine_version` columns.

2. After `holdings_df = pd.DataFrame(holdings_rows)` at line 10324:
   ```python
   from r1000_trade_journal import (
       persist_holdings_history,
       pair_entries_with_exits,
       grade_trades,
   )
   if not holdings_df.empty:
       persist_holdings_history(holdings_df, paths, ENGINE_REUSE_VERSION)
       trades_df = pair_entries_with_exits(holdings_df, paths, ENGINE_REUSE_VERSION)
       if trades_df is not None and not trades_df.empty:
           grade_trades(trades_df, benchmark_returns_df, paths)
   ```

No behavior change — only adds files under `outputs/trade_journal/`.

## 18a — Smoke + verification

* Smoke: round-trip JSON encoding of signal breakdown
* Smoke: pairing logic correctness on synthetic 3-month holdings
* Smoke: grade rule logic on synthetic trade records
* Manual: after first FULL rebuild, inspect `outputs/trade_journal/grades.parquet`

## 18a — Ship gate

* Smoke 60+ tests pass
* `outputs/trade_journal/grades.parquet` produced after one local QUICK
  rebuild with non-trivial WIN/LOSS counts
* No regression in main backtest CAGR/Sharpe/MaxDD

## 18b roadmap (next session)

1. `tools/trade_insights.py`:
   * IC matrix per signal × regime (rank correlation of signal value vs
     subsequent realized_return)
   * k-means on entry_signal_breakdown → cluster win-rate table
   * SHAP attribution on a meta-XGBoost trained on entry features →
     realized_return (treats each trade as supervised label)

2. `tools/feature_gate_proposal.py`:
   * Read `outputs/trade_journal/insights/*.json`
   * Auto-generate `research/auto_feature_gates.yaml` with proposed
     gates (signal × regime, e.g. "disable theme_phase in deep_bear")
   * Human review checkpoint

3. Quarterly Telegram digest: top 3 strengths / top 3 weaknesses / top
   3 proposed gates.

## 18c roadmap

* `r1000_pipeline.py` reads `auto_feature_gates.yaml` during scoring.
  When (signal, current_regime) matches a gate, multiply that signal's
  weight by 0 (or by the proposed reduction factor).
* Gate proposals enter via `auto_feature_gate.yml` workflow → human
  approves with PR merge → next FULL rebuild applies gates → L14
  baseline rotation verifies the change is net-positive.
* Annual full retraining: collect 12 months of new gates + updated
  insights, regenerate models.

## Open questions (defer to 18b)

* Backfill: should we re-grade pre-Phase-17 historical trades when
  signal columns weren't yet computed? (Likely yes — re-run FULL
  rebuild on current engine version regenerates entire journal.)
* Cross-validation of grades: compare 6mo-forward grade label to
  3mo-forward grade label for the same trade — measures rule stability.
* Engine version drift: if engine bump is small (no new signals),
  should we mark old journal "still valid" instead of regenerating?
  (Add `engine_version_compatible_until` field to journal manifest.)
