# Run287 dual-tempo Buffett/Chameleon policy audit (2026-07-17)

## Decision

The review-only dual-tempo state machine is implemented and wired into the daily continuous-learning sidecar. It separates broad-market, factor, security, durable-quality, exact fundamental-break, and challenger-freshness clocks.

No portfolio weight, cash, score, rank, selector, model, target book, or order changed. Historical CAGR/MDD is unchanged.

## Fixed states

| State | Meaning | Review speed |
|---|---|---|
| `COMPOUND_HOLD` | Exact-close risk is normal and durable-quality evidence is complete in a benign market | Monitor daily; do not exit for rank alone |
| `WATCH` | Warning or incomplete evidence without a sell-quality break | Review after each completed close |
| `DEFEND` | Security alert or fresh factor-residual alert | Same after-close manual review before the next actionable close |
| `ROTATE` | Defend evidence plus exact-accepted fundamental break plus fresh superior selector challenger | Scheduled next-close shadow review only |
| `REBUILD` | Two clear observations after a recent defensive state with durable quality intact | Staged re-entry review |
| `DATA_INSUFFICIENT` | Exact-close risk or quality identity missing | Missing-neutral, no action |

State labels are advisory. Every row fixes `portfolio_action_authorized=false`, `sell_or_rotate_authorized=false`, `orders_generated=false`, and `target_books_mutated=false`.

## 2026-07-16 completed-close result

The broad market and semiconductor factor disagree:

- broad regime: `BENIGN` (`normal`, SPY above 200-day average, VIX 16.73);
- pinned crisis state: `GREEN`, last exact decision date 2026-07-13;
- SOXX factor: `WATCH`, 21-day SPY excess -15.30%, 63-day drawdown -19.01%;
- factor and holding-risk data are exact through the 2026-07-16 close.

That disagreement is the reason a single broad-market regime is insufficient.

### Portfolio state

| Portfolio | State | Security composition | Defend/rotate weight |
|---|---|---|---:|
| Main | `WATCH` | 3 `DEFEND`, 14 `WATCH` | 27.66% |
| Concentrated | `DEFEND` | 3 `DEFEND` | 99.16% |

Concentrated is `DEFEND` because CIEN and WDC are `ALERT`, while SNDK has a fresh SOXX-residual alert. Main's defensive names are GLW, GOOG, and ON. Main does not escalate to portfolio `DEFEND` because only 3 of 17 positions are defensive; Concentrated has all three positions defensive.

GOOG illustrates the Buffett/Chameleon separation: it passes the strict quantitative durable-quality gate but is currently an exact-close `ALERT`. The correct state is therefore `DEFEND`, not an automatic exit and not an automatic add.

## Why no rotation was authorized

All six defensive security rows are blocked from `ROTATE` for both required reasons:

1. no `CONFIRMED_EXACT_ACCEPTED_BREAK` sidecar row exists;
2. the latest frozen selector decision is 2026-07-13, older than the 2026-07-16 risk close.

The old selector identifies MU as the best non-held challenger, but that is stale diagnostic context. It cannot justify replacing CIEN, SNDK, WDC, GLW, GOOG, or ON after the 2026-07-16 close.

There are no `COMPOUND_HOLD` holdings in this first strict snapshot. This does not mean all holdings lack a moat. It means no name simultaneously has complete exact debt/quality evidence, normal price risk, benign applicable factor state, and no missing textual-moat evidence. The system fails closed instead of manufacturing certainty.

## What is now automated

The daily causal-ledger orchestrator now runs:

1. exact SEC debt refresh;
2. durable-quality review queue and checklist;
3. dual-tempo security and portfolio states;
4. append-only state history;
5. fixed 21/63-day decision outcomes.

Same-date state-history payload conflicts fail closed. `REBUILD` requires two clear observations after a recent defensive state, preventing one-day rebound chasing.

## Next gate

The next bottlenecks are evidence, not another threshold grid:

1. produce a same-close selector/challenger snapshot after every completed session;
2. build a conservative exact-accepted fundamental-break sidecar from comparable filing periods and amendments;
3. append dual-tempo states until 21/63-day outcomes mature;
4. only then run one fixed review-only hold/defend/rotate shadow comparison.

No portfolio A/B should start while either the fundamental-break input or same-close challenger is missing. Fullrun and production/live activation remain prohibited.

## Evidence

- `docs/run287_dual_tempo_policy_contract_v1.json`
- `tools/audit_run287_dual_tempo_policy.py`
- `tests/run287_dual_tempo_policy_smoke.py`
- `tools/run_run287_continuous_learning_daily.py`
- `outputs/run287_dual_tempo_policy_20260717_close_20260716_v2/`
