# Run287 Held-Security Risk Watch Result - 2026-07-14

## Verdict

A current, forward-only held-security risk watch is implemented and wired into
the exact-close daily paper workflow. It is an operator warning layer, not a
stop, exit delay, partial resize, cluster cap, target-book mutation, paper-order
mutation, or live-trading rule.

No historical CAGR/MDD evidence changed and no fullrun was executed.

## Frozen signal contract

The contract uses only observations dated on or before the completed session.
Every distribution threshold is computed from rows strictly before the current
session, with a 756-session lookback and at least 252 prior return observations.

Per held security it records:

- one-session absolute and SPY-relative shock;
- adjusted opening gap shock;
- 21-session SPY-relative trend damage below both MA20 and MA50;
- 63-session drawdown damage below MA50;
- 21-to-126-session realized-volatility ratio spike;
- estimated one-session portfolio return contribution.

The output state is `NORMAL`, `WATCH`, `ALERT`, or `DATA_INSUFFICIENT`.
`ALERT` recommends only `FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW`.
Missing or short history is neutral and cannot force a trade.

## Actual 2026-07-13 exact-close diagnostic

The diagnostic used the frozen 2026-07-10 paper accounts, free adjusted prices
through 2026-07-13, SPY as benchmark, and no intervening trade assumption.
All 15 unique held tickers and SPY had the exact 2026-07-13 close.

| Portfolio | State | Tickers |
| --- | --- | --- |
| Main | ALERT | SNDK, NXT, ALAB, MRVL |
| Main | WATCH | FLEX, WDC, ON, CIEN, MU, QCOM |
| Main | NORMAL | AMD, HPE, UMC, RVMD |
| Concentrated | ALERT | SNDK |
| Concentrated | WATCH | MU |
| Concentrated | NORMAL | AMD, TXN, UMC |

Estimated one-session portfolio return was -5.4295% for Main and -6.0107% for
Concentrated. The two largest risk contributions were SNDK at -1.36 percentage
points in Main and -3.76 percentage points in Concentrated. These are current
diagnostics, not new seven-year metrics.

The current artifact is append-only by portfolio, ticker, and as-of date. A
same-date rerun must reproduce the exact event payload or fail closed.

## Daily automation

`daily_operating_selection_refresh.yml` now runs the watch only after:

1. the completed-session gate passes;
2. every held security has an exact close;
3. the forward paper account is marked to that close.

The risk archive is included in the GitHub artifact/cache and persisted under
`paper_archive/run287_holding_risk_watch` when Google Drive is available.

## Zero-cost provider request

The deterministic 50-row estimate/guidance request was regenerated without
changing row selection:

- 45 active current issuers;
- exactly five ADR/global active issuers;
- five deterministic historical-delisted provider query slots;
- 992 current-equity reference rows;
- 21/63/126/252/504-session outcome compatibility.

The new `provider_request.md` is a provider-ready, no-cost evaluation message.
It explicitly says that it is not a purchase order and that paid work needs
separate approval. No provider request was dispatched because no provider or
contact endpoint is selected.

## Boundaries and next gates

- Do not turn the watch into a forced sell or resize rule from this one event.
- Do not retune thresholds to the 2026-07-13 decline.
- Accumulate forward events and resolve 1/5/21/63/126-session outcomes before
  proposing an execution mechanism.
- Send the zero-cost sample only after a provider/contact is chosen.
- Run the frozen PIT source gate on the returned sample before joining
  21/63/126/252/504-session returns or opening a portfolio A/B.

## Validation

- Held-security risk smoke: pass.
- PIT sample-request smoke: pass.
- Daily workflow artifact smoke: pass.
- Do-not-repeat preflight: `ALLOWED_NEW_COMBINATION` with no exact prior match.
- Local standard PR validation: 139/143 pass. The four failures are the same
  sparse-checkout omissions (`aggressive/`, `auto_learning_v2/`, the IWB seed,
  and the global portfolio-system fixture); the new and adjacent tests pass.

## Evidence

- `docs/run287_holding_risk_watch_contract.json`
- `tools/build_run287_holding_risk_watch.py`
- `tests/run287_holding_risk_watch_smoke.py`
- `outputs/run287_holding_risk_watch_20260714_close_20260713/`
- `outputs/run287_pit_estimate_guidance_sample_request_20260714_v2/`
