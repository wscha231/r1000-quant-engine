# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 661
- latest scored date: 2026-04-30
- historical candidate rows: 41226
- historical candidate tickers: 956
- historical months: 73
- historical candidate last date: 2026-04-30
- SEC-enriched candidate present: True
- SEC-enriched candidate rows: 41226

## Universe Source

- `current_constituents_proxy_static_seed`: 38754
- `adr_whitelist`: 1186
- `current_constituents_proxy_static_seed+strategic_global_hardware`: 1048
- `cycle_play_whitelist`: 238

## Evidence Utilization

- rows with SEC evidence: 5538
- rows with 13F evidence: 32281
- rows with ETF evidence: 0
- rows with smart-money evidence: 30220
- coverage ratio: 13.4%
- 13F coverage ratio: 78.3%

## Effective Market Cap Coverage

- `latest_scored` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`
- `historical_candidate_book` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`

## Largest Coverage Gaps

- `historical_candidate_book.market_cap_live` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.gross_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.operating_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.revenue_growth_final` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.op_income_growth_yoy` numeric=5.1%, nonzero=5.1%
- `historical_candidate_book.ocf_growth_yoy` numeric=5.8%, nonzero=5.8%
- `historical_candidate_book.roe_proxy` numeric=44.5%, nonzero=44.5%
- `historical_candidate_book.gross_profit_ttm` numeric=44.9%, nonzero=44.9%
- `historical_candidate_book.capex_ttm` numeric=47.1%, nonzero=46.9%
- `historical_candidate_book.ocf_ttm` numeric=56.5%, nonzero=56.5%
- `historical_candidate_book.op_income_ttm` numeric=56.7%, nonzero=56.7%
- `historical_candidate_book.revenues_ttm` numeric=57.5%, nonzero=57.5%

## Missing Audit Columns

- `historical_candidate_book.available_from`
- `historical_candidate_book.early_evidence_score`
- `historical_candidate_book.etf_holdings_score`
- `historical_candidate_book.etf_theme_leadership_score`
- `historical_candidate_book.evidence_fusion_score`
- `historical_candidate_book.institutional_evidence_score`
- `historical_candidate_book.latest_13f_available_from`
- `historical_candidate_book.latest_available_from`
- `historical_candidate_book.latest_etf_available_from`
- `historical_candidate_book.leader_onset_sec_v3_score`
- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `historical_candidate_book.sec_13f_score`
- `historical_candidate_book.sec_13f_smart_money_score`
- `historical_candidate_book.sec_combined_evidence_score`
- `historical_candidate_book.sec_form4_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`core_compounder`; score=3.411606906568898
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=61; sleeve=`core_compounder`; score=6.166531169135241
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=54; sleeve=`core_compounder`; score=4.108527270945584
- `ARM`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `ASML`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`core_compounder`; score=4.960411250132691
- `CIEN`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`future_winner`; score=3.802023453308229
- `COHR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=22; sleeve=`future_winner`; score=3.7756442211005807
- `DELL`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`core_compounder`; score=6.717911964808316
- `GLW`: historical_only_not_current_latest_universe; latest=False; hist_months=7; sleeve=``; score=None
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`core_compounder`; score=7.520963243584132
- `HPE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`future_winner`; score=1.2539003310825385
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=52; sleeve=``; score=None
- `KLAC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`early_scout`; score=3.8500436456852976
- `LITE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=61; sleeve=`future_winner`; score=4.570188977432026
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`core_compounder`; score=3.310489010398829
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`future_winner`; score=4.764799708179312
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`core_compounder`; score=2.5359060676778302
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=61; sleeve=`core_compounder`; score=4.215080636687826
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=28; sleeve=`core_compounder`; score=2.119323307255014
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=73; sleeve=`unassigned`; score=4.218581767004616
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=3; sleeve=`unassigned`; score=3.01124962950562
- `STX`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `TSM`: not_in_latest_universe; latest=False; hist_months=0; sleeve=``; score=None
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=48; sleeve=`core_compounder`; score=5.656261545265634
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=37; sleeve=`future_winner`; score=5.442912453171378
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=24; sleeve=`core_compounder`; score=3.9046555951887134

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
