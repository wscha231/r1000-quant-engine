# Run287 same-close selector and exact fundamental-break result (2026-07-17)

## Decision

The two prerequisites for a defensible `ROTATE` state are now automated and
fail closed.  The current 2026-07-16 evidence does not satisfy either gate, so
no replacement, weight, cash, target-book, or order change is allowed.

Historical CAGR/MDD is unchanged.  This work removes false freshness and false
fundamental-certainty before the first shadow hold/defend/rotate comparison.

## Same-close selector provenance

GitHub run `29554723038` completed successfully from `master` commit
`185ae879570dd87b69bd2b5abe04a40a094bbb84` and has exact prices through the
2026-07-16 close.  It is not a same-close selector rerun:

| Portfolio | Rows | Valuation close | Audited signal date | Recomputed ranks | Qualified candidates | Verdict |
|---|---:|---|---|---:|---:|---|
| Main | 17 | 2026-07-16 | missing | 0 | 0 | blocked |
| Concentrated | 3 | 2026-07-16 | 2026-05-08 | 0 | 0 | blocked |

The legacy workflow filled a missing Main `rebalance_date` with the latest
valuation close.  That field was being read as if it proved the ranking clock.
The workflow now emits separate `signal_source_date`, `valuation_close_date`,
`same_close_rank_recomputed`, `candidate_snapshot_role`, and
`rebalance_date_role` fields.  A legacy `rebalance_date` alone is never accepted
as signal provenance.

The daily artifact now carries a separate same-close readiness summary.  Its
blocked state does not prevent exact-close monitoring of the operating book; it
does prevent treating restored holdings as fresh challengers.

## Exact-accepted fundamental-break review

The sidecar read the frozen `115,185`-row exact filing-quality event archive,
excluded future rows, selected the latest comparable filing with at least three
observed components for each held ticker, and joined it only when
`available_from <= decision_time`.

Current result:

- source screen: `REJECT_SOURCE_SCREEN`;
- event archive maximum accepted date: `2026-07-09` versus required operating
  evidence through `2026-07-16`;
- confirmed exact fundamental breaks: `0`;
- negative exact comparable filings, review only: `2` (`GLW`, `PR`);
- portfolio A/B allowed from this source: `false`.

GLW's latest comparable filing was its 2026-Q1 10-Q accepted on 2026-05-01,
with 3 of 4 components worsening.  PR's 2026-Q1 10-Q accepted on 2026-05-07 had
4 of 4 worsening.  Both remain review-only because the exact source signal was
already rejected OOS and the archive is not current through the operating
close.  GOOG, CIEN, ON, WDC, and SNDK do not have a negative latest comparable
filing in this frozen archive.

## Dual-tempo recomputation

With both new sidecars supplied, the 2026-07-16 dual-tempo result remains:

| Portfolio | State | Defensive securities | Rotations |
|---|---|---:|---:|
| Main | `WATCH` | 3 | 0 |
| Concentrated | `DEFEND` | 3 | 0 |

All six defensive rows are explicitly blocked by both missing confirmation
gates.  The dual-tempo audit now requires the readiness file; matching a date
inside the selector ledger is no longer enough by itself.

## Automation and next gate

The daily continuous-learning path now:

1. audits restored target versus same-close selector provenance;
2. builds the exact filing-break review when frozen inputs are present;
3. supplies both fail-closed sidecars to the dual-tempo state machine;
4. publishes the gate statuses without mutating the operating portfolios.

The next engineering task is not a threshold grid.  It is a bounded,
decision-complete current cross-section selector run that writes explicit
same-close provenance for the full eligible universe.  In parallel, the SEC
accepted-time archive must catch up through the latest completed close.  A
single fixed shadow A/B remains blocked until a genuinely validated break
signal and same-close qualified challenger both exist.

## Evidence

- `docs/run287_same_close_selector_snapshot_contract_v1.json`
- `tools/audit_run287_same_close_selector_snapshot.py`
- `docs/run287_exact_fundamental_break_contract_v1.json`
- `tools/build_run287_exact_fundamental_breaks.py`
- `outputs/run287_same_close_selector_snapshot_20260717_close_20260716/`
- `outputs/run287_fundamental_breaks_20260717_close_20260716/`
- `outputs/run287_dual_tempo_policy_20260717_close_20260716_v3/`
