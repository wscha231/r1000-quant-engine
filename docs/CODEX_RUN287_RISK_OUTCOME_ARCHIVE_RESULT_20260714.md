# Run287 risk outcome archive result - 2026-07-14

## Decision

The missing forward evidence link between the exact-close security-risk watch
and any future risk mechanism is implemented.  Frozen held-security and
proposed-candidate warnings now receive append-only 1, 5, 21, 63, and
126-trading-day outcomes without changing a holding, weight, cash balance,
order, target book, historical backtest, fullrun, production, or live trading.

This is performance-strengthening infrastructure, not a claimed CAGR/MDD
improvement.  The frozen historical controls remain:

- Main: CAGR `34.4032%`, MDD `-25.3619%`;
- Concentrated: CAGR `49.0971%`, MDD `-22.9552%`.

Main therefore still needs about `0.5968` percentage point of CAGR and `0.3619`
percentage point of MDD recovery.  Concentrated still needs about `0.9029`
percentage point of CAGR; its MDD already passes the `-25%` gate.

## How the current work can strengthen CAGR and MDD

There are two independent evidence paths.

| Evidence path | Later fixed mechanism | Primary benefit | Current status |
| --- | --- | --- | --- |
| Exact historical PIT estimate/guidance revisions | Main: cancel only the incremental growth-weight transfer into a confirmed negative name | Recover MDD without changing baseline gross, cash, cadence, or caps | Blocked until a timestamped source with delisted/ADR identity passes |
| Exact historical PIT estimate/guidance revisions | Concentrated: confirm an already selector-qualified replacement only when the challenger has positive evidence | Improve CAGR without allowing the event to create a new buy | Blocked at the same source gate |
| Current held/candidate risk outcomes | Determine whether `ALERT/WATCH` names experience worse subsequent excess return and drawdown than frozen `NORMAL` controls | Avoid bad incremental buys and identify a single future downside mechanism without sacrificing rebounds | Collection and automatic resolution now active; underpowered |

The new outcome archive measures both sides of the CAGR/MDD trade-off:

- future total return and SPY excess return show whether a warning identifies
  persistent weakness;
- maximum additional drawdown shows potential MDD protection;
- maximum gain and recovery from trough show the CAGR cost of selling or
  freezing too aggressively;
- metrics beginning at the next close separate a tradable counterfactual from
  the immediate move that occurred before an operator could act.

This distinction matters for the 2026-07-13 semiconductor decline.  The watch
was created after that completed close, so it cannot claim that it would have
avoided the already-observed loss.  It can test only whether those warnings
predict additional weakness or recovery from the following sessions.

## Frozen outcome contract

`docs/run287_risk_outcome_archive_contract.json` fixes:

- adjusted close and SPY as the benchmark;
- horizons `1/5/21/63/126` sessions;
- signal-close and next-close-actionable metrics as separate fields;
- missing/delisted price paths as pending, never zero-filled;
- one candidate observation per date/ticker;
- one held observation per date/portfolio/ticker with positive marked weight;
- no threshold retuning and no automatic stop, exit, resize, or cash rule.

Mechanism review cannot open before all of the following are present at 63D:

- 12 distinct decision weeks;
- 50 resolved `ALERT/WATCH` observations;
- 50 resolved `NORMAL` observations;
- 30 distinct tickers;
- eight paired warning/control decision-week blocks.

Even that gate opens review only.  It cannot promote a portfolio mechanism.

## Actual local connection

The first resolver run used the immutable 2026-07-13 decision archive.

- status: `READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY`;
- signal observations: `26`;
- held observations: `19`;
- candidate observations: `7`;
- states: `ALERT 6`, `WATCH 9`, `NORMAL 11`;
- unresolved price universe: `22` securities plus SPY, `23` total;
- resolved forward outcomes: `0`;
- distinct decision weeks: `1`;
- mechanism review ready: `false`.

Zero outcomes is correct because the resolver as-of date is the same
2026-07-13 signal close.  Under the NYSE calendar, the first observation can
reach the fixed endpoints no earlier than:

| Horizon | Earliest close |
| ---: | --- |
| 1D | 2026-07-14 |
| 5D | 2026-07-20 |
| 21D | 2026-08-11 |
| 63D | 2026-10-09 |
| 126D | 2027-01-11 |

## Sustainable daily automation

After each completed-close decision archive attempt, the daily workflow now:

1. captures new held and candidate observations idempotently;
2. retains previously captured observations even when the current exact packet
   safely skips;
3. builds a price queue from unresolved observations plus SPY;
4. blocks rather than silently truncates above 150 unique tickers;
5. refreshes only that bounded cache;
6. reruns the resolver and appends newly elapsed outcomes;
7. persists the event log, derived status, queue, and cache through GitHub
   cache/artifacts and Google Drive when configured.

The append-only event log is the source of truth.  `current_status.csv` and the
human report are rebuildable views.

## Next performance gate

Continue daily exact-close observations.  The 1D result becomes the first
diagnostic after the 2026-07-14 US close, but no rule changes from one day.
At 21D, compare warning versus normal direction and recovery.  At 63D and only
after the frozen sample gate is powered, decide whether there is evidence for
one preregistered mechanism.  Do not create a stop/exit grid or count this
forward archive as seven-year CAGR/MDD proof.

## Evidence

- `docs/run287_risk_outcome_archive_contract.json`
- `tools/resolve_run287_risk_outcomes.py`
- `tests/run287_risk_outcome_archive_smoke.py`
- `.github/workflows/daily_operating_selection_refresh.yml`
- `outputs/run287_risk_outcome_archive_20260714_local/`

The complete local PR validation passed `171/171` test files in `216.25`
seconds.  No fullrun was executed.
