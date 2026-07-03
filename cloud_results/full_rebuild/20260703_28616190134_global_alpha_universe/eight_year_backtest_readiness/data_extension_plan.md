# Data Extension Plan

- window: `8-year`
- target start: `2018-07-02`
- target end: `2026-07-02`
- selected target-book tickers: `392`
- hard blockers: `6`

| Task | Scope | Status | Hard Blocker | Action |
| --- | --- | --- | :---: | --- |
| price_cache_window | prices | needs_extension | true | Run free_data_lake_bootstrap.yml with price_mode=target_books and max_price_tickers=0. |
| price_cache_ticker_count | prices | ready | false | none |
| main_target_book_window | target_books | needs_extension | true | Run full_rebuild_manual.yml with backtest_years=8 after price readiness so main target books extend across the full 8-year window. |
| concentrated_target_book_window | target_books | needs_extension | true | Run full_rebuild_manual.yml with backtest_years=8 after price readiness so concentrated target books extend across the full 8-year window. |
| main_broker_replay_window | broker_replay | needs_extension | true | Rerun broker-ledger replay/account evaluation after target books cover the full 8-year window. |
| concentrated_broker_replay_window | broker_replay | needs_extension | true | Rerun broker-ledger replay/account evaluation after target books cover the full 8-year window. |
| sec_companyfacts_archive | macro_sec_fundamentals | ready | false | none |
| pit_universe_label | universe | needs_extension | true | Keep the run labeled proxy until historical membership, delistings, ADR eligibility, and ticker changes are PIT-safe. |

## Sample Target-Book Tickers

AAPL, ABT, ACI, ACLS, ACN, ADBE, ADC, ADI, AEE, AEM, AEP, AIT, AIZ, AJG, AKAM, ALGM, ALGN, ALNY, ALSN, AM, AMAT, AMD, AMGN, AMP, AMT, AMZN, AN, ANET, APH, APO, APP, APPF, ATI, ATO, AVGO, AVT, AXON, AXP, AZO, BABA, BAC, BAH, BEN, BIIB, BIO, BJ, BKNG, BLD, BLDR, BR
