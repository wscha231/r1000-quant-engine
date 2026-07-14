# Run287 proposed-candidate risk watch result - 2026-07-14

## Decision

The seven proposed new entries from the 2026-07-13 exact-close no-write
selector now have the same frozen past-only price-risk evaluation used for
held securities. The packet is `READY_CANDIDATE_RISK_REVIEW_ONLY`.

This closes the missing-risk-data gap, but it does not approve a portfolio
transition. `NORMAL` means only that the frozen damage contract did not fire;
it is not alpha evidence or permission to buy. No selector weight, target
book, cash policy, order, historical replay, fullrun, production, or live
trading state changed.

## Exact-close result

| State | Tickers | Required interpretation |
| --- | --- | --- |
| ALERT | STX | Freeze incremental buy and review manually |
| WATCH | AMAT, COHU | Review before any incremental buy |
| NORMAL | ARM, DELL, FTNT, PANW | No risk-contract signal; not a buy authorization |
| DATA_INSUFFICIENT | None | All seven had sufficient exact-close history |

STX fired on `opening_gap_shock` plus `drawdown_damage`. Its one-session return
was -5.46%, its one-session SPY excess return was -4.69%, and its 63-session
drawdown was -21.28%.

AMAT and COHU fired only the preregistered `volatility_spike` watch. Their
one-session returns were -4.50% and -5.98%, respectively. ARM fell -7.55% but
remained `NORMAL` because it did not satisfy the frozen past-quantile signal
definitions. That is an important operator caveat: the state is a narrow
contract result, not a complete fundamental, event, or discretionary review.

## Candidate and price provenance

The candidate set was derived mechanically from the hash-pinned selector
comparison: non-cash ticker, positive advisory weight, and zero marked weight.
The exact union was `AMAT`, `ARM`, `COHU`, `DELL`, `FTNT`, `PANW`, and `STX`.

For every candidate, the builder:

1. verified the immutable selector price-map manifest and each mapped long
   history file;
2. compared the current provider price file with the long history over 130
   overlapping sessions;
3. required maximum relative adjusted-close error no greater than `1e-5`;
4. appended only the 2026-07-13 provider row to the history ending 2026-07-10;
5. verified the exact SPY file through the macro manifest and market-component
   audit;
6. excluded rows after the valuation close and rechecked every source hash
   before and after output generation.

The largest observed overlap error was `1.1378592747990455e-07` for AMAT.
All seven candidates and SPY ended exactly on 2026-07-13. Network requests were
zero and `source_inputs_mutated=false`.

## Frozen classification contract

The candidate lane imports the held-security `price_features` and `classify`
functions directly. It therefore preserves the 756-session lookback, minimum
252 prior returns, strictly past-only quantile thresholds, exact-close rule,
and the five existing signals:

- one-session absolute and SPY-relative idiosyncratic shock;
- adjusted opening-gap shock;
- 21-session relative trend damage below MA20 and MA50;
- 63-session drawdown damage below MA50;
- 21-to-126-session realized-volatility ratio spike.

There is no candidate-specific threshold, no post-decline retuning, and no
stop, exit delay, partial resize, cluster cap, cash target, or replacement
grid.

## Determinism and append-only behavior

Two in-process evaluations matched exactly. The first output created seven
candidate/date events; a same-date rerun appended zero events and retained
exactly seven. A changed same-date payload fails closed through the shared
archive contract.

Canonical output hashes after the idempotent rerun:

- `candidate_risk_watch.csv`:
  `2555de769edc71beb859d9bb6fae55cce31e2e661f0b4c595a842dce30c5641a`
- `price_source_audit.csv`:
  `6ccbf9f03a7de59153935e460769f4d9f0757a779a7b3276edd1b2096e9ab305`
- `risk_history.jsonl`:
  `a697e97bac09dfcffc7878f3e5dd46712276c0df69117cc7996381c89ce8d41e`

## Remaining gate

The first selector/risk decision is now stored under the frozen append-only
decision observation archive. The one-date transition is still blocked by material turnover, existing-held
risk conflicts in Main, STX/AMAT/COHU candidate warnings, and lack of
multi-week selector stability. Continue the exact same selector scenarios and
risk contract across distinct completed decision weeks. Do not create a
turnover, cash, or risk-threshold grid after observing this date.

Historical CAGR/MDD controls remain unchanged:

- Main: CAGR 34.4032%, MDD -25.3619%.
- Concentrated: CAGR 49.0971%, MDD -22.9552%.

The historical improvement lane remains separately gated on genuine
timestamped PIT estimate/guidance evidence. This current candidate packet
cannot be promoted into seven-year CAGR/MDD evidence.

## Validation

- Candidate-risk synthetic and fail-closed smoke: pass.
- Local standard PR validation: `166/166` passed in `228.94` seconds.
- Direct fullrun guard, daily close gate, portfolio/cash, PIT, workflow, and
  public-dashboard contracts: pass within the same suite.
- Fullrun and historical backtest executed by this change: false.

## Evidence

- `docs/run287_candidate_risk_watch_contract.json`
- `tools/build_run287_candidate_risk_watch.py`
- `tests/run287_candidate_risk_watch_smoke.py`
- `outputs/run287_candidate_risk_watch_20260714_close_20260713/`
