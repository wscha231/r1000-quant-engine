# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 741
- latest scored date: 2026-06-22
- historical candidate rows: 46276
- historical candidate tickers: 968
- historical months: 83
- historical candidate last date: 2026-04-30
- SEC-enriched candidate present: True
- SEC-enriched candidate rows: 46276

## Universe Source

- `current_constituents_proxy_static_seed`: 43501
- `adr_whitelist`: 1355
- `current_constituents_proxy_static_seed+strategic_global_hardware`: 1173
- `cycle_play_whitelist`: 247

## Evidence Utilization

- rows with SEC evidence: 5613
- rows with 13F evidence: 36036
- rows with ETF evidence: 0
- rows with smart-money evidence: 33900
- coverage ratio: 12.1%
- 13F coverage ratio: 77.9%

## Effective Market Cap Coverage

- `latest_scored` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`
- `historical_candidate_book` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`

## Largest Coverage Gaps

- `historical_candidate_book.market_cap_live` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.gross_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.operating_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.revenue_growth_final` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.op_income_growth_yoy` numeric=5.2%, nonzero=5.2%
- `historical_candidate_book.ocf_growth_yoy` numeric=5.9%, nonzero=5.9%
- `historical_candidate_book.roe_proxy` numeric=44.6%, nonzero=44.6%
- `historical_candidate_book.gross_profit_ttm` numeric=44.8%, nonzero=44.8%
- `historical_candidate_book.capex_ttm` numeric=46.8%, nonzero=46.6%
- `historical_candidate_book.ocf_ttm` numeric=56.2%, nonzero=56.2%
- `historical_candidate_book.op_income_ttm` numeric=56.6%, nonzero=56.6%
- `historical_candidate_book.revenues_ttm` numeric=57.4%, nonzero=57.4%

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

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=7.748905119352026
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=71; sleeve=`core_compounder`; score=6.4611053408219545
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=54; sleeve=`core_compounder`; score=2.9448557458217106
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.855004270657878
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=6.8198335051511245
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=2.7483551186352058
- `CIEN`: selection_gate_or_rank_rejected; latest=True; hist_months=83; sleeve=`unassigned`; score=1.719255760072777
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=22; sleeve=`unassigned`; score=4.818632496882844
- `DELL`: selection_gate_or_rank_rejected; latest=True; hist_months=6; sleeve=`unassigned`; score=5.389108404389743
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`core_compounder`; score=4.905804857937345
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=5.868430871413898
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=5.342992073964446
- `HPE`: selection_gate_or_rank_rejected; latest=True; hist_months=83; sleeve=`unassigned`; score=7.444591092139814
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=62; sleeve=``; score=None
- `KLAC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=81; sleeve=`early_scout`; score=7.2468980218509875
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=71; sleeve=`unassigned`; score=4.445563096001484
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=8.042715575268758
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`future_winner`; score=5.514246278864031
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=83; sleeve=`core_compounder`; score=6.862493131186584
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=66; sleeve=`core_compounder`; score=4.545721096216686
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=28; sleeve=`core_compounder`; score=2.934959495676653
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=83; sleeve=`unassigned`; score=6.001404331752376
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=3; sleeve=`core_compounder`; score=4.145802676300309
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=6.312915612805002
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.616664434735789
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`core_compounder`; score=6.266608880979224
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=39; sleeve=`future_winner`; score=7.394130130612207
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=24; sleeve=`core_compounder`; score=2.7468477697605724

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
