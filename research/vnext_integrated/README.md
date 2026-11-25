# vNext Integrated — new-model diagnostic replay

This directory is a fresh research experiment. It does **not** replay the prior champion, legacy `score_total`, prior portfolio weights, or the July paper book.

## What is newly recomputed

For every recovered historical decision cross-section, the model recomputes six pillars from raw candidate features:

1. relative strength — 35%
2. industry breadth/leadership — 15%
3. estimate revision — 15%
4. growth/margin/FCF/ROIC/quality acceleration — 15%
5. valuation — 10%
6. moat/quality proxies — 10%

Missing evidence is never turned into zero or a favorable default. A row needs at least 70% of pillar-weight coverage and usable realized volatility before it can enter the ranking. Higher missingness explicitly scales the score down.

Risk features create a penalty; they do not become automatic sell orders. Macro/systemic risk changes only aggregate equity exposure. Main and Concentrated have separate name counts/caps but share the same company model.

Hysteresis is applied by retaining an incumbent inside a wider rank buffer before admitting a new name.

## Outcome and execution semantics

`r_1m` and `bench_r_1m` are outcome labels only. The code freezes ranking and target weights before reading selected outcome values. They are never selection features.

The diagnostic applies stock-notional turnover costs at 5/25/50/100 bps per side. The 25 bps run is the preregistered baseline. Cash earns zero.

## What is deliberately excluded from historical score

Recent work whose historical point-in-time archive is not yet established is **not backfilled**:

- current Theme/ETF mappings and semantic theme research,
- qualitative company opinions,
- strict 13F manager-skill evidence,
- Form4 anomaly evidence,
- current analyst-consensus snapshots,
- actual broker or accepted-target state.

Those are current/shadow overlays until their historical PIT evidence exists.

## Why this is not final OOS

The recovered source archive is real and verified, but the source-recovery audit found that the candidate books lack `feature_available_from` and `valuation_price_cutoff_date`. Historical Russell 1000 membership is also not certified PIT-safe. Therefore this run is a **one-shot architecture diagnostic**, not a production/OOS certification.

The experiment configuration is committed before the workflow is run. After seeing results, do not edit the same experiment to chase CAGR/MDD; create a new experiment ID with a stated hypothesis instead.

No target/paper/actual book, champion, scheduler, broker state, or live order is mutated.
