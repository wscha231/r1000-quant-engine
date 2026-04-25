# ADR Universe Playbook

How to monitor, validate, and add ADRs to the universe over time.

## Current state (2026-04-25)

- **26 ADRs** in `adr_universe.yaml` (mcap >= $30B, NYSE/NASDAQ-listed)
- **3 watchlist** entries (SK Hynix, Samsung, Reliance — pending listings)
- Loadable via `aggressive.universe.load_universe("r1000+adr")` → R1000 ∪ ADR set
- Stage 2 breakout overextension penalty (`6fd6afe`) applies equally to ADRs

## File structure

| File | Role | Update cadence |
|---|---|---|
| `adr_universe.yaml` | Canonical whitelist with mcap, country, theme tags | Quarterly |
| `themes.yaml` | Cross-cutting taxonomy; ADRs added to relevant themes | Per addition |
| `tests/check_adr_data.py` | Source + runtime data availability check | Run after each addition |
| `tests/smoke_test.py` | Regression guards (4 ADR-related, including SK Hynix watchlist) | Auto |

## Adding a new ADR (general process)

```bash
# 1. Verify the ticker trades on NYSE/NASDAQ (not foreign exchange — Alpaca req)
#    Confirm Alpaca paper supports it: https://app.alpaca.markets/paper/dashboard

# 2. Edit adr_universe.yaml — append to adr_universe: list
- ticker: NEW_TICKER
  name: "Full Company Name"
  country: XX                # ISO 2-letter (CN, KR, JP, ...)
  sector: Semiconductors     # Match existing convention
  sub_sector: Memory
  mcap_usd_b: 100            # Approximate global mcap
  listed_since: "2026-10"    # YYYY-MM
  themes: [semi_memory]      # From themes.yaml available themes
  notes: "Why included; risk/regulatory caveats"

# 3. Edit themes.yaml — add ticker to each listed theme
   themes:
     semi_memory:
       tickers: [MU, WDC, STX, NEW_TICKER]    # ← add here

# 4. Verify data path:
   py -3 tests/check_adr_data.py --ticker NEW_TICKER
   # PASS: 5+ years of daily bars + Finnhub fundamentals
   # FAIL: short history → wait 6-12 months OR exclude from initial backtest

# 5. Run smoke tests:
   py -3 tests/smoke_test.py
   # 44/44 PASS (or 45/45 if you added a new guard)

# 6. Commit + push to claude/analyze-updated-code-OfEbu (or new branch)

# 7. Optional: trigger paper_executor_dryrun.yml to verify scanner sees it
```

## Watchlist monitoring

`adr_universe.yaml` has an `adr_watchlist:` section for confirmed-but-unlisted ADRs.

### SK Hynix (Korean memory chipmaker)
- **Expected**: Oct 2026 NYSE/NASDAQ listing per 2026-04 reporting
- **Proposed symbol**: TBD (likely `SKHY` or `SKHX` — confirm at filing)
- **Significance**: World #2 DRAM, #1 HBM3e supplier (NVDA H100/H200/B200 partner)
- **Themes to add to**: `semi_memory`, `semi_design_memory`, `ai_compute`
- **Action when listed**:
  ```bash
  # On listing day:
  # 1. Confirm symbol via Alpaca asset lookup
  py -3 -c "from aggressive.executor import _get_trading_client; \
            c = _get_trading_client(); \
            print(c.get_asset('SKHY'))"
  # 2. Move from adr_watchlist to adr_universe (with mcap_usd_b)
  # 3. Add to themes.yaml: semi_memory, semi_design_memory, ai_compute
  # 4. Initial mcap_usd_b ≈ $100B (KOSPI cap × ADR ratio); update after first month
  # 5. py -3 tests/check_adr_data.py --ticker SKHY (require 1y+ for backtest;
  #    until then synthetic-row scoring via Finnhub only)
  ```

### Samsung Electronics
- **Status**: OTC pink-sheet (`SSNLF`) only. No firm ADR conversion timeline.
- **Action**: Monitor; add only when full NYSE/NASDAQ listing confirmed.

### Reliance Industries
- **Status**: Periodic rumors, no firm SEC F-1 filing.
- **Action**: Monitor; defer until concrete filing.

## Data path expectations per ADR

| Data | ASML | TSM | BABA | NVO | New ADR (template) |
|---|---|---|---|---|---|
| Alpaca daily bars | ✅ | ✅ | ✅ | ✅ | Verify with `check_adr_data.py` |
| Finnhub fundamentals | ✅ | ✅ | ✅ | ✅ | Should be available for top-mcap |
| SEC EDGAR companyfacts | ⚠️ 20-F | ⚠️ 20-F | ⚠️ 20-F | ⚠️ 20-F | Often partial parse — fall back to synthetic-row |

If SEC EDGAR doesn't yield clean XBRL, the ticker auto-falls into
`r1000_unified_universe.py` `finnhub_synthetic` path (composite score from
`0.30·RS + 0.25·PEG + 0.20·growth + 0.15·margin + 0.10·analyst`). This is
the same path used for the 402 R1000 names without 정석 ML coverage — no
new infrastructure needed.

## Risk caveats specific to ADRs

| Country | Risk | Macro feature alignment |
|---|---|---|
| China (BABA, PDD, JD, BIDU, NTES) | PBOC, regulation, delisting risk | US macro features partially decorrelated |
| Korea (SK Hynix watchlist) | KOSPI flow, Won FX exposure | Semi cycle aligned with US |
| Japan (TM, SONY, HMC) | Yen FX, BoJ policy | Tech/auto cycle aligned |
| Europe (ASML, NVO, AZN, ...) | EUR FX, ECB policy | Generally well-correlated |
| UK (HSBC, SHEL, BP, ...) | GBP FX, BoE policy | Energy/finance aligned |

For now, all ADRs use the same macro features (CPI, VIX, SPY) as US-domestic.
Future improvement: country-specific FX/policy features for ADRs in non-US/EU
home markets (China especially). Track via IC measurements after 6 months
of inclusion data.

## Sourcing future ADR additions

1. **Top-mcap screen**: Companies with >$30B global mcap that list ADRs on US exchanges
2. **Theme-driven discovery**: New tech/biotech ADRs that fit existing themes
3. **Phase 18A clustering**: `theme_discovery.py` may surface foreign tickers in correlated clusters
4. **User-mandated**: Direct addition request (like SK Hynix Oct 2026)

## Cleanup process

If an ADR delists, suspends trading, or fails data availability:

```bash
# 1. Move from adr_universe: to a new adr_archive: section in adr_universe.yaml
#    (preserves history for backtests)
# 2. Remove from themes.yaml themes
# 3. Add note: delisted_date + reason
# 4. py -3 tests/smoke_test.py → verify guards still pass (may need to reduce required: set)
```
