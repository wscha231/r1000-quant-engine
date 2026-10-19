# ETF116 native research backend H1

TASK_KEY: R1000-ETF116-FINAL-INTEGRATION-20261018. Research only.

This integrates the existing prepared ETF calculations on master18571d9 in an
existing clean Main worktree. It preserves the fixed1,009-equity seed and the
separate frozen116-ETF research cohort. It does not grant Source/PIT, economic
or publication authority.

## Existing paths reused

- Pure metrics, dated holdings, cadence planner, offline preflight and runners
  are ported from the supplied ready-for-owner package (SHA256
  b09c0541a68ee9aae74229faedbc145ea7ac72bcc44d8bded8372f6f55ad6168)
  and its reviewed minimal delta (SHA256
  e17959f1132a0c7eaabedeabb0f30909abe7f066c53125670e8879f0939c5567).
- Holdings intake calls the actual
  tools.run_etf_holdings_refresh.normalize_holding_rows function, with explicit
  PERCENT/TOP_ONLY semantics. Unknown publication clocks remain null, even
  though the old normalizer initializes available_from from as_of. No new
  provider collector, canonical holdings lake write, ranking or seed mutation.
- TR consumption calls the current merged ResearchDataReader.read. It first
  verifies the exact generation manifest and requires explicit NAV_TR_INDEX or
  MARKET_TR_INDEX, a methodology hash and TOTAL_RETURN security identity.
  Ordinary RAW/SPLIT_ADJUSTED OHLCV cannot silently become TR. No read_components
  or other unmerged Source627 API is imported. The adapter consumes one pinned
  component; it does not launch a116-name scan or refresh. Exact manifest checks
  currently precede the existing Reader's own check; batch optimization should
  reuse the approved component API after actual upstream integration.
- Reader receipt bytes are the metric rows' immutable source reference, clearly
  labeled READER_RECEIPT_SHA256_NOT_PROVIDER_BYTES. Original provider hashes,
  row-set hash, generation, classifications and clock evidence remain separately
  recorded in the unchanged Reader receipt. This is research-byte consumption,
  not A1 admission or proof of licensed bulk automation.
- The175 restored SPMO issuer NAV rows remain valuation-reference context. The
  classifier never labels them executable market closes or verified daily TR,
  and preserves pending dividend/public-availability verification.

## Corrections and native validation

Missing RF blocks Sharpe/Sortino while preserving independent volatility/MDD
and available matched-basis benchmark metrics. Optional malformed SPY only
blocks its comparison; subject errors still refuse. Holdings reject mixed
as-of within one ETF and aggregate weights above100%; different ETF snapshot
dates remain distinct. Malformed optional JSON receives explicit contract
errors. Availability cannot precede an observation date.

New native tests use the existing Reader fixture builder, not its historical
test suite. All price rows in those tests are synthetic CONTRACT_FIXTUREs and
are never admission evidence. Existing historical61 offline results remain
historical; namespace/import changes and adapters receive native tests.

The new child suite is invoked by the already registered
tests/etf_holdings_overlay_smoke.py entry. DEFAULT_TESTS,
tools/run_pr_validation.py, pr_validation.yml and the protected inventory
verifier are unchanged. A zero-child suite is an explicit failure.

## Existing schedule, disabled independent job

The existing free_data_daily_update.yml cron remains30 23 * * 1-5 UTC.
The additive ETF job has a literal false condition, contents:read, isolated
concurrency, no needs relationship and no Drive/Sheets/broker/target steps.
It cannot run by changing a repository variable. The terminal source guard
also refuses missing admitted TR. Weekly top10 uses the existing pure cadence
planner; no scheduler or new cron is added. This H1 is disabled preparation,
not an automatic data-refresh deployment.

CLI examples (caller-supplied local inputs, no network):

```bash
python tools/run_etf116_offline_research_h1.py --input INPUT.json \
  --frozen research/etf116_v1/frozen_tickers.txt --output UNIQUE_CANDIDATE.json
python tools/run_etf_top3_research_lookthrough_h1.py --holdings HOLDINGS.csv \
  --seed-tickers EXISTING_SEED_SYMBOLS.txt --observed-at UTC_TIMESTAMP \
  --output UNIQUE_LOOKTHROUGH.json
python tools/run_pr_validation.py --only etf_holdings_overlay_smoke
```

The per-ticker output includes explicit consecutive-session daily returns and
blocked-interval counts, rolling TR,1/3/5/10-year matched-window CAGR/MDD,
dated-RF Sharpe/Sortino/volatility and matched-basis
SPY comparisons. Missing history, absent anchors, future clocks and basis
conflicts remain blocked; partial-life windows are not extrapolated. Inputs
and receipts must be supplied by the approved A1 path, not guessed from current
web tables or short unadjusted SIP samples.

Independent A6 also identified an impossible backdated RF availability clock
and an output-overwrite path in the reused preflight CLI. RF now rejects
availability before its observation date. All three candidate CLIs use
exclusive file creation; an existing receipt cannot be silently replaced.

## Remaining operational gates

Hosted review5563925645 found three further P2 boundaries. RF selection retains
release timestamps and requires availability before each UTC return-date start,
conservatively refusing same-day intraday releases because this API receives
date-only sessions. A later review cannot backfill a late historical RF rate.
The EOD close must share the named session's UTC date. Rights-receipt SHA is
bound into the input digest and retained in both prepared and unchanged output;
changed rights evidence is a same-session conflict, not an unchanged retry.

Successor review also required canonical UTC close in the digest and both
result states, explicit malformed-SPY diagnostics including supplied null,
one-read CSV parsing/hash binding and the exact1009 seed identity digest.
The seed file is unchanged; input lists must match its frozen symbol identity.
Independent A6 also rejects supplied malformed/null listing-date maps rather
than coalescing falsey values into an absent optional map.

The current-master successor review also rejects future holdings-refresh
checkpoints before planning a week. Same-date daily TR availability must follow
the actual NYSE close from the existing Reader's offline holiday/half-day helper;
midnight or a guessed regular close is insufficient. A next-UTC-day release is
conservatively after session close. Calendar failures refuse same-date inputs.

At preparation, admitted actual daily TR remains0/116. Existing vendor-return
research cells are preserved and are not described as absent. Source rights,
original immutable bytes, distributions/splits and availability are not newly
certified here. The actual lookthrough21 equities already exist in the fixed
seed; research tags are not A2 admission, ER or BUY.

Prior private copied Sheet27-cell OAuth write/readback proof is reused. It is
not GitHub Actions service-account authorization. No new private-sheet copy,
provider capture, expensive historical recollection, Source campaign budget,
workflow dispatch or protected state transition is performed.

Before activation: approved A1 TR/rights/CA receipts; actual Actions-principal
private-copy write/readback; two real completed-session positive end-to-end
trials; frozen-head CI, independent A6 and protected review. Source's active
master18571 runtime/merge hold is preserved. No merge or activation is included
in this Draft preparation.
