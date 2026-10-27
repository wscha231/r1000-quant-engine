# Integrated market analysis V1

Task: R1000-A4-INTEGRATED-MARKET-ANALYSIS-H1-20261027. US research only.

The daily monitor now consumes the incumbent ten-axis Chameleon risk engine
and free market context in one report. It reports native risk state, score,
ready/missing axes, volatility/credit/rates/liquidity observations, qualified
price breadth, futures participant positions and optional household expectations.
No new risk thresholds, blended alpha score, holdings effects or trading rules.
AAII is not required. Sentiment sources add interpretation, not independent
votes that double-count VIX or NFCI's underlying credit/rate components.

## Existing paths reused

- `build_run287_chameleon_macro_risk`: validate the original calendar/metrics/
  context, compute percentiles, axes, hysteresis and fear-recovery stages.
  Readiness remains at least eight axes including breadth, volatility, credit.
- `chameleon_market_context_v2`: original CSV normalization, null/stale logic,
  volatility maturity ratios, family separation, breadth and public positions.
- `free_market_context.cot_observations`: TFF futures-only participant groups,
  contract market codes, open interest and net/long/short provenance.
- Existing candidate-reassessment context adapter and snapshot: A2/A3 typed
  review inputs receive parsed macro, SENTIMENT and POSITIONING rows while every
  dispatch, ER/ranking and canonical-write flag remains false.
- Existing daily crisis workflow, artifact and Drive status publication. No new
  scheduler. `run_daily_crisis_monitor` embeds `market_analysis` in its summary
  and readable report. A blocked unified report returns nonzero, even if an
  unrelated legacy diagnostic was computable. It never upgrades legacy state.

## Source producer handoff

The existing Source writer publishes a bounded current bundle under its existing
Drive base at `outputs/market_analysis_inputs/`. Originals are written first;
`request.json` and its `request.sha256` integrity pin are published last. The
existing daily workflow restores this folder. Its artifact/report is produced
on every invocation, including DATA_BLOCKED when input is unavailable.
A matching SHA authenticates bytes, not a provider, license, PIT or investment
approval. No existing Source campaign, retained history or collector is replaced.
The producer edge is not operationally verified until an actual recurring Source
publication and scheduled consumer receipt are observed.

Request structure:

```json
{
  "schema": "market-analysis-request-v1",
  "market": "US",
  "session": "2026-10-26",
  "available_at": "2026-10-27T09:30:00Z",
  "expires_at": "2026-10-28T09:30:00Z",
  "inputs": [
    {
      "kind": "macro",
      "source_id": "fred:NFCI",
      "path": "raw/NFCI.csv",
      "sha256": "<exact SHA256 of the original bytes>",
      "collected_at": "2026-10-27T09:00:00Z",
      "status": "COLLECTED"
    }
  ]
}
```

Input kinds: `macro`, `cot_tff`, `price_context`, `sce_export`, `risk_metrics`,
`risk_calendar`, `risk_context`. A native risk calculation needs both metrics
and calendar; context is optional under the incumbent contract. Original metrics
must retain their actual per-row observation/availability/decision clocks.
Do not manufacture historical availability from the request creation time.

`price_context` is the JSON array produced by the existing qualified-price
adapter `free_market_context.price_theme_context`. Retain cohort membership,
complete price session grid, eligible/expected denominators, original hashes,
basis and availability. A retained price inventory or single-symbol MU witness
is not enough to certify market-wide breadth. Missing expected coverage remains
visible. This engine does not create a new price feed or authorize price inputs.

`macro` accepts registered exact FRED/Cboe identities; WDTGAL and WTREGEN and
RRPTSYD and RRPONTSYD remain distinct. ANFCI and STLFSI4 are overlapping
financial-conditions diagnostics, not extra native risk-axis votes.

`sce_export` accepts only
`month,mean_probability_stock_prices_higher_12m_percent`. It preserves the mean
subjective probability of higher stock prices in twelve months, separate from
AAII's bullish-respondent percentage. It is an explicit standardized export
adapter; native XLSX retrieval/conversion/original-cell verification is NOT
implemented or certified. No SCE workbook was acquired in this environment.
The report retains original_workbook_verified=false and conversion_verified=false.
This optional gap does not block otherwise eligible native risk diagnostics.

## Clocks, failure and integration boundary

Use the most recent actually completed XNYS session at close plus fifteen minutes,
with actual holidays, DST and early closes. Requests expire within four days;
observations retain their separate daily/weekly/monthly age limits. New collection
or a newly written request cannot freshen an old observation. Unknown latest
values never fall back to favorable earlier values. Failed/stale-retained source
statuses, changed bytes, duplicated roles, path escape and future clocks refuse
the request. No last-good report is consumed as this invocation's success.

The reader caps requests at256KiB, each input at8MiB, total selected bytes at32MiB
and inputs at40. It refuses symlinks/special files before opening and rechecks
file identity. The engine performs zero network requests. Code and contracts
are fingerprinted for the output; no API credentials enter the request.

`market_assessment.state` is the incumbent model's descriptive research state,
not a new RISK_ON portfolio authorization. It stays null when current readiness
fails. Producer authenticity, Source/PIT admission and portfolio authority stay
false even for a complete diagnostic. A2/A3 may read this as thesis context;
A5 receives context with no portfolio-policy effect; A8 may record observations.
ER, security rankings, target books, account/ledger, orders and live activation
are not changed. Actual producer/consumer completion, PIT/OOS economics and
production approval remain separate from implementing this consumer.

## Verification

The active `daily_crisis_monitor_long_crisis_smoke.py` umbrella imports the new
suite without changing the fixed CI registry. Tests exercise native parsers,
the full incumbent risk pipeline, exact session/calendar binding, missing/null/
stale/future/conflicting input, source hashes and preserved authority. Full
risk fixtures are synthetic, not actual collection, rights or PIT evidence.
Actual retained four-series originals are used separately for a partial report.
