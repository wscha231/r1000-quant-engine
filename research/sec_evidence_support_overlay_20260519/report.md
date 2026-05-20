# SEC Evidence Support Overlay Plan

Research-only plan for using SEC Form 4 and Form 13F as additive support for
existing future-winner and market-confirmed selectors. This does not promote
SEC evidence to production scoring and does not change `score_total`.

## Official Data Rules

- Form 4 availability must use `accepted_at` / `available_from`, not
  `transaction_date`.
- 13F availability must use `accepted_at` / `available_from`, not
  `report_period`.
- SEC evidence can be evaluated with forward returns only inside research
  diagnostics; target-book construction cannot read forward-return columns.
- Promotion evidence remains `broker_ledger_next_close` with
  `valid_for_production=true`.

Reference facts:

- SEC Form 4 reports insider ownership changes and is generally filed within
  two business days after the reportable transaction. See
  https://www.sec.gov/files/forms-3-4-5.pdf.
- Form 13F is filed by institutional investment managers that exercise
  investment discretion over at least $100 million in Section 13(f) securities;
  filings are due within 45 days after quarter end. See
  https://www.sec.gov/divisions/investment/13ffaq and
  https://www.sec.gov/info/edgar/forms/form13f.pdf.
- Situational Awareness LP is identifiable in EDGAR as CIK `0002045724`; SEC
  submissions show 13F-HR filings through the 2026 Q1 filing window.
- Duquesne Family Office LLC is identifiable in EDGAR as CIK `0001536411`; it
  can be used as a named manager in 13F manager-quality learning.

## Backtest Design

The first reliable test is not "every listed U.S. stock forever." It is:

1. Load the repo's historical candidate replay book, typically about eight
   years of monthly candidate rows.
2. Backfill Form 4 and 13F rows with `available_from`.
3. For each candidate row, attach only SEC evidence whose `available_from` is
   on or before that rebalance date and inside the configured lookback window.
4. Compare each evidence bucket's subsequent `period_forward_return` against
   the same-date candidate universe average.
5. Learn only small overlay weights, then verify any target-book candidate with
   the broker-ledger next-close replay.

This means the audit answers: "when the system could have known this SEC
evidence, did the stock outperform from that selection point?" It does not
assume the stock was bought on the insider transaction date or the 13F
quarter-end date.

## Form 4 Scoring Policy

Use Form 4 buys as triggers only when they are open-market purchases:

- Code `P`: positive buy trigger.
- CEO/CFO/director/10% owner purchases: stronger evidence.
- Cluster buys by multiple reporting owners: stronger evidence.
- Dollar value matters, but is capped to avoid one filing dominating the score.

Sales are not treated as a hard sell signal:

- Code `S` can reflect diversification, taxes, scheduled plans, or liquidity.
- Sale value is retained as `sec_form4_sale_pressure_score`.
- The overlay uses `sec_form4_sale_risk_score`, a weaker risk flag.
- If buy and sale evidence coexist, the sale penalty is deliberately smaller.

New support fields:

- `sec_form4_net_buy_score`
- `sec_form4_sale_risk_score`

## 13F Scoring Policy

13F is delayed institutional validation, not a fast entry trigger.

Positive evidence:

- More managers accumulating the same name.
- More buying managers than selling managers.
- New positions.
- Higher manager conviction within the manager's own book.
- Positive dollar value delta relative to the candidate's market cap.
- Strong historical manager quality.

Separate risk evidence:

- Stale filing age.
- Extreme crowding after a name is already widely owned.

The implementation now separates broad institutional support from crowding
risk:

- `sec_13f_breadth_score`: positive support from manager count.
- `sec_13f_crowding_score`: risk only after manager count is already high.

## Manager Quality

13F manager quality is learned from the repo data, not hardcoded by reputation.

For each `manager_cik`, the audit joins manager holdings to candidate rows after
`available_from` and measures:

- observation count
- average forward return
- average excess return over same-date universe
- excess hit rate
- average value delta
- value delta to market cap
- manager position weight and conviction rank

The resulting `manager_quality_score` can give more support to managers whose
historical disclosed holdings outperformed in this system. This is how a named
manager such as Duquesne can receive higher weight if the data supports it.

Manager tracking is controlled by:

```text
research/sec_13f_manager_universe_20260519/managers.csv
```

The file supports annual review fields:

- `external_performance_2y`
- `performance_26q1`
- `aum_13f_usd`
- `holdings_count`
- `last_review_date`
- `next_review_due`

These fields rank what to collect and review. They do not override the repo's
learned `manager_quality_score`.

## Integration Rule

SEC evidence should strengthen the existing best model, not replace it.

The preferred selector is `sec_support_overlay`:

- keeps future-winner and market confirmation as the majority of the score
- adds a smaller SEC support boost
- leaves Form 4 sale pressure as a weak risk flag
- treats 13F breadth as support and crowding as a separate risk

The broker grid should now test portfolio-specific ranges:

- main: `target_n = 12, 15, 18`, caps `0.10, 0.15, 0.20`
- concentrated: `target_n = 2, 3, 5`, caps `0.33, 0.45, 0.50`

Promotion remains blocked unless a candidate improves the locked baseline on
official broker-ledger metrics and passes human approval.

## Price-Follow Adaptive Learning

The fixed Form 4 / 13F score recipes are no longer the only research path.
`run_sec_evidence_signal_audit.py` emits `sec_score_policy_recommendation.json`,
which classifies each SEC feature as support, risk, neutral, disabled, or
insufficient coverage based on historical forward-return alignment.

`run_sec_evidence_learning_pipeline.py` now converts that policy into a
research-only `price_follow_adaptive_overlay` preset:

- Features with positive directional IC and positive top-vs-bottom decile
  spread can receive small support weights.
- Risk features are used only when price-follow diagnostics validate the
  direction.
- Low-coverage Form 4 fields are not trusted until the full shard backfill is
  merged.
- The generated preset is compared only inside `score_weight_grid.csv` and does
  not change `score_total` or production target books.

This keeps the SEC layer data-driven: if CEO/CFO buys, 10% owner buys, 13F
breadth, or crowding do not align with later price behavior in the repo's own
historical candidate book, the policy report can neutralize or disable them
instead of forcing conventional assumptions into the engine.
