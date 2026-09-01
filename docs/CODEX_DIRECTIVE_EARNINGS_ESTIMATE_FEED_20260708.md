# Codex Directive — Forward Earnings-Estimate Revision Feed (build + wire into selection)

> Author: Claude Code (web reviewer), 2026-07-08. Concrete build order for a
> daily per-ticker analyst-estimate + revision + surprise feed, wired as a
> **default-OFF confirmation signal into live stock selection**. This fills the
> exact path the W4 inventory found missing
> (`data_pit/events/earnings_revision_signals.parquet`).

## 0. The one hard rule (read first)

This feed is **forward-only PIT**: the archive starts the day we turn it on, so
it has **no history**. Therefore it must be wired into the **latest-month
scoring path only**, never into the walk-forward `feature_store`.

Consequences, non-negotiable:
- It is **neutral (absent) for every historical backtest rebalance date** → it
  **cannot change backtest CAGR/MDD** and **cannot be validated by a historical
  A/B or the acceptance gate**.
- Its **only** effect is the **latest live month's pick** (the operating book /
  `user_current`).
- Validation is a **forward paper ledger** (audit-only), never a backtest claim.
- **No retro-fill.** Applying today's estimate snapshot to a past date = the
  look-ahead we forbid. `available_from = fetch date`, always.

This is why it needs **no FULL rebuild / no fullrun**: it never enters
walk-forward training. That is the whole point of the latest-scoring wiring.

## Non-negotiables

No fullrun. No production promotion / live trading / public "estimate-driven
outperformance" wording while `pit_universe_label_clean=false`. Forward returns
audit-only. Default OFF. Missing estimate = neutral, never a penalty.

---

## 1. Data layer — collector + PIT archive (reuse existing Finnhub infra)

`FINNHUB_API_KEY` is already wired (`r1000_insider_analyst_impact.py`,
`aggressive/finnhub_cache_loader.py`, advisors v1–v3). Reuse the per-ticker
cache pattern from `collect_analyst_events` (`r1000_insider_analyst_impact.py:187`).

New tool `tools/collect_earnings_estimates_finnhub.py`:
- Per-ticker daily pull, rate-limit aware (free tier 60/min; 981 tickers ≈ a few min).
- Finnhub endpoints: `/stock/eps-estimate`, `/stock/revenue-estimate`,
  `/stock/earnings` (actual-vs-estimate surprise), `/stock/recommendation`
  (up/down revision breadth proxy).
- Track a `coverage_ratio` (Finnhub free coverage is partial) — WARN-only, never fail.

Storage (creates `data_pit/events/`):
- daily snapshot: `data_pit/events/earnings_estimates/estimates_YYYYMMDD.parquet`
- rolling signals: `data_pit/events/earnings_revision_signals.parquet` ← the W4-inventory missing path
- schema: `ticker, as_of_date (== available_from), est_eps_fy1, est_eps_fy2,
  est_rev_fy1, n_analysts, est_dispersion, actual_eps_last, actual_report_date,
  surprise_last, fetch_source="finnhub"`. Deltas are computed by diffing
  consecutive daily snapshots (see §2) — never provided as a single snapshot.

Daily workflow `.github/workflows/earnings_estimates_daily.yml` (backend-only):
runs the collector, appends the snapshot, updates the rolling signals parquet,
commits to the data path. Empty/rate-limited pull → `blocked_partial_coverage`
summary, never a crash.

## 2. Signal layer — the exact columns (maps to your request)

Compute in a new `compute_estimate_revision_features(df, signals_parquet, as_of_date)`;
constant `PHASE18_ESTIMATE_REVISION_COLUMNS` in `r1000_config.py` (mirror
`PHASE17_EXPLOSION_COLUMNS` at `r1000_config.py:304`):

| Column | Meaning (your ask) |
|---|---|
| `est_eps_fy1`, `est_eps_fy2` | 어닝 전망치 (consensus, FY1/FY2) |
| `est_eps_revision_30d`, `_90d` | 전망치 변경폭 (up/down, `(now − prior)/|prior|`) |
| `est_eps_revision_breadth` | 상향/하향 breadth `(up−down)/(up+down)` — 몇 명이 올렸나 |
| `est_rev_revision_30d` | 매출 전망 변경폭 |
| `est_dispersion`, `est_dispersion_change_30d` | 전망 **축소폭/증가폭** (좁혀지면 conviction↑) |
| `earnings_surprise_last` | **현재 실적 대비** `(actual − estimate)/|estimate|` |
| `surprise_streak` | 연속 beat/miss |

All computed **as-of** the latest snapshot with `as_of_date ≤ decision_date`.

## 3. Selection wiring — HOW / WHERE it picks stocks (latest-scoring path ONLY)

Do **not** touch `build_feature_store` / `keep_cols` (`r1000_pipeline.py:8395`) /
walk-forward. Instead attach in the **latest-month scoring path** where Phase-1
columns are already recomputed outside the cached store
(`prepare_latest_scored_data` / `score_latest_month` /
`compute_strategy_blueprint_columns` — confirm exact call site). Two uses, both
**confirmation, not a new primary factor**, behind
`phase_is_enabled("ESTIMATE_REVISION_CONFIRM")` /
`PHASE_ESTIMATE_REVISION_CONFIRM_ENABLED` (default OFF):

**A. Concentrated replacement-quality gate** (the miss-set fix; ties to the 13F
directive). Extend the replacement-quality logic
(`tools/run_concentrated_cap_replacement_audit.py` + the hook): a leader may be
**swapped in only when** `est_eps_revision_breadth > 0` **AND**
`est_dispersion_change_30d ≤ 0` (revisions rising and estimates narrowing),
with `available_from ≤ decision_date`. This is the orthogonal confirmation the
miss-set needs — a **gate, not a universe tilt** (universe tilt is exactly how
the SEC arm died OOS).

**B. Main `future_winner` sleeve tilt.** Apply `est_eps_revision_breadth` as a
**bounded** multiplier on the existing future_winner score (cap e.g. ±5% so it
confirms momentum, never dominates it). Core/early sleeves untouched.

## 4. Forward-only guarantees (prove no leakage / no backtest contamination)

- `available_from = fetch date` only; the estimate's fiscal-period date is never
  used as availability. `audit_data_readiness` (`available_from ≤ rebalance_date`)
  applies unchanged.
- Because the signal lives only in latest-month scoring, **historical rebalance
  dates never see it** → walk-forward training/backtest is byte-identical
  feed-ON vs feed-OFF. This must be **proven by smoke** (§5), not asserted.
- `data_coverage_gate`: add the estimates feed as **WARN-only** (partial Finnhub
  coverage); missing ticker estimate = neutral.

## 5. Acceptance / smokes (all required)

- `tests/collect_earnings_estimates_smoke.py`: fixture pull → archive schema
  correct; `as_of_date == fetch_date`; **assert no fiscal-period date leaks into
  `available_from`**.
- `tests/estimate_revision_features_smoke.py`: the 8 columns compute; a rising-
  revision fixture yields `breadth > 0` and `dispersion_change ≤ 0`.
- **`tests/estimate_feed_backtest_neutrality_smoke.py` (the leakage guard):**
  run the historical backtest path with feed ON and feed OFF → **identical
  metrics** (proves the feed cannot touch the backtest / no look-ahead).
- `tests/estimate_confirm_selection_smoke.py`: with feed ON, a latest-month swap
  occurs **only** when revision-breadth confirms; with an empty archive
  (historical), **zero** selection change.
- `tools/run_pr_validation.py` registers all four.

## 6. Validation = forward paper ledger (not a backtest number)

Wire the estimate-confirmed picks into the forward paper ledger
(`update_forward_service_ledger` from the sustainment layer): each month, record
which picks the confirmation gate changed and track their forward (audit-only)
excess vs SPY over N months. **This is the only honest way to judge the feed.**
No backtest CAGR/MDD delta may ever be attributed to it.

## 7. Build order (WIP ≤ 2)

1. Data layer (§1) + daily workflow — start the archive **now** (compounding PIT
   history for the future paid-free backtest path).
2. Signal + latest-scoring wiring (§2–3), default OFF.
3. Smokes (§5) — especially the **backtest-neutrality** guard.
4. Turn ON for the latest operating book only; seed the forward ledger (§6).

No fullrun at any step (forward-only ⇒ no feature_store schema change is needed
in the walk-forward path). If someone later wants this signal **inside the
backtest**, that requires **paid PIT estimate history** (I/B/E/S / FactSet /
Zacks) — the D2 decision — and a separate directive; do not fake it from a
current snapshot.

## Verdict gates Claude will check

- §1: `available_from == fetch_date`; `data_pit/events/earnings_revision_signals.parquet` materialized; coverage WARN-only.
- §3: wired in latest-scoring path only; `keep_cols`/`build_feature_store` untouched; default OFF; Concentrated = gate (not tilt), Main = bounded multiplier.
- §5: **backtest-neutrality smoke passes** (feed ON == feed OFF on history) — this is the leakage gate.
- §6: forward ledger records estimate-changed picks; no backtest metric attributed to the feed.
