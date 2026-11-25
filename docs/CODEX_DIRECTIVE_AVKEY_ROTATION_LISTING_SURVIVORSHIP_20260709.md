# Codex Directive — AV Key Rotation + LISTING_STATUS Survivorship Bound

> Author: Claude Code (web reviewer), 2026-07-09. Follow-up to the API review of
> PR #249/#250 and the forward-estimate feed. Two work items: (a) close the one
> open security item (rotate the Alpha Vantage key that appeared in a vendor
> error body), and (b) use the newly available Alpha Vantage `LISTING_STATUS`
> endpoint to bound the survivorship `delisted_exclusion` component that R2 left
> unmeasured. Sequencing: **A (rotation) → then 13F fixed-book A/B (existing
> directive) → then B (LISTING_STATUS).** Research/security only; no fullrun, no
> production, no threshold tuning, no raw keys in any artifact.

## Non-negotiables

No fullrun. No production promotion / live trading. No raw API key values in
docs/PR/issues/logs/artifacts/chat — secret names only. Forward-only snapshots
never enter the 2019–2026 replay. Every failure/caveat gets a
`docs/AGENT_SHARED_LESSONS_LEDGER.md` entry.

---

## A. Alpha Vantage key rotation (do FIRST — the one open security item)

**Why.** Ledger entry `2026-07-09 - Vendor error messages can leak API keys`:
Alpha Vantage echoed the key in a rate-limit response body; redaction was
hardened and affected runs (`28987731184`, `28988568483`) were deleted, final
run `28989287304` verified clean. But the "rotate any key that may have
appeared" next-action is **not confirmed done**. Deleting GitHub runs purges
GitHub-side logs/artifacts; it does not purge the vendor's server logs or any
local/chat transit. The exposed key must be rotated.

**Checklist (Codex executes; user performs the secret update):**
1. **Generate a new Alpha Vantage key** (user, in the AV account — never pasted
   into repo/chat).
2. **Update the GitHub secret `ALPHAVANTAGE_API_KEY`** to the new value (user,
   via GitHub Settings → Secrets; not through a committed file).
3. **Verify with the one-ticker safe smoke** (`ALPHAVANTAGE`-only vendor order):
   `earnings_estimates_daily.yml -f tickers='AAPL' -f ticker_limit=1`, and after
   it runs, **scan `summary.json` AND `collector.log` for any key pattern**
   (reuse `sanitize_error_message`); require `available_from=fetch_date`,
   `backtest_acceptance_allowed=false`.
4. **Confirm the old key is dead**: a call with the old key should now fail auth.
5. **Ledger entry** `key rotation completed`: agent, run id, `rotated=true`,
   `old_key_invalidated_confirmed`, `no_raw_key_in_artifacts`, no value.

**Acceptance.** Ledger shows `rotated=true` + old-key-dead confirmation; the
safe smoke passes with clean artifacts. **Until this lands, pause further Alpha
Vantage calls** (FMP/Finnhub base may continue).

**Anti-leakage.** The new key value appears only in the GitHub secret store and
the user's AV account — never in a file, PR, log, or this ledger.

---

## B. LISTING_STATUS → delisted universe → survivorship bound (after 13F A/B)

**Why.** R2 (`outputs/run287_survivorship/`) measured only the one-sided
late-inclusion component (`0.0pp`) and left the **dominant** component
`delisted_exclusion` **unmeasured** — the current-constituents proxy silently
drops names that left the R1000 mid-window, inflating absolute CAGR. Alpha
Vantage `LISTING_STATUS` returns delisted securities **with delisting dates**,
which is the free source that can finally bound that component. This is higher
leverage than any Concentrated alpha hook: it gates the honesty of **every**
acceptance number.

**Work items.**
1. **Collector** `tools/collect_listing_status_alphavantage.py`: pull
   `function=LISTING_STATUS&state=delisted` (and `state=active` for cross-check).
   Store `data_pit/universe/listing_status/listing_status_YYYYMMDD.parquet` +
   rolling `data_pit/universe/delisted_securities.parquet`. Schema: `symbol,
   name, exchange, ipo_date, delisting_date, status, as_of_fetch_date,
   fetch_source`. Rate-limit aware (free tier); coverage caveat, not failure.
2. **PIT membership reconstruction (proxy).** Join delisted names into the
   historical membership proxy the engine already consumes
   (`load_historical_universe_membership` / `apply_historical_membership_filter`,
   `r1000_pipeline.py:2870/2921`): a delisted name is **eligible for every
   rebalance date in `[ipo_date … delisting_date]`** and excluded afterward.
   This is still a `proxy` (AV lacks R1000 index membership per se — it gives
   listing lifecycle, not index constituency), so **label `proxy`**; it improves
   the delisted side but does not make PIT membership clean.
3. **Survivorship bound upgrade.** Extend
   `tools/run287_survivorship_bound.py` to a **two-sided** estimate: current
   proxy (survivor-only) vs a stricter arm that also admits the delisted names
   alive at each rebalance date, on a price basis (delisted-name prices where
   available; neutral where not). Emit
   `survivorship_inflation_estimate_cagr_pp_two_sided`,
   `delisted_names_admitted_count`, `delisted_component_measured=true|partial`,
   and the **deflated Main/Conc gap range**.

**Files.**
- `tools/collect_listing_status_alphavantage.py`, `tests/collect_listing_status_smoke.py`
- `tools/run287_survivorship_bound.py` (extend), `tests/run287_survivorship_bound_smoke.py` (extend)
- `outputs/run287_survivorship/` (two-sided summary + `delisted_admitted.csv`)

**Acceptance.**
- `delisted_securities.parquet` materialized with `delisting_date` populated;
  coverage ratio reported (WARN-only).
- Survivorship summary emits the two-sided bound and states the **deflated**
  Main/Conc gap (e.g. "Conc real gap ≥ X pp after delisted admission").
- `survivorship_unmeasured_component` shrinks from `delisted_exclusion` to
  `delisted_exclusion_partial` (or `measured` if price coverage is adequate),
  and the `label` stays `proxy`.

**Anti-leakage.**
- Delisted admission keyed on `ipo_date`/`delisting_date` only — a name is never
  admitted after its `delisting_date`, never before `ipo_date`.
- `LISTING_STATUS` is reference/lifecycle data (not forward-return) → **this one
  MAY inform the historical backtest** (it de-biases the universe), unlike the
  forward estimate feed. Keep the two strictly separate: estimates = forward-
  only; listing lifecycle = historical de-biasing.
- Still `pit_universe_label_clean=false` (AV listing ≠ R1000 index membership);
  production promotion stays blocked. This narrows survivorship, it does not
  clear the production gate.

---

## Sequencing (recommended)

1. **A — Alpha Vantage key rotation** (security; unblocks safe AV usage incl. B).
2. **13F single-source fixed-book A/B** (`CODEX_DIRECTIVE_13F_FIXEDBOOK_AB_20260708.md`, G0→G3) — the near-term historical alpha test.
3. **B — LISTING_STATUS survivorship bound** — de-biases every acceptance number; run once AV key is rotated so the calls are on a clean key.

Forward estimate archive (Concentrated watchlist) continues in parallel as
forward-ledger evidence, default OFF, per `CODEX_DIRECTIVE_API_DATA_ALPHA_WORKPLAN_20260709.md`.

## Verdict gates Claude will check

- A: ledger `rotated=true` + old-key-dead + clean smoke artifacts; AV calls paused until then.
- B: `delisted_securities.parquet` with delisting dates; two-sided survivorship bound + deflated gap; admission keyed on lifecycle dates only; `proxy` label kept; production still blocked.
