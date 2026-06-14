# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 736
- latest scored date: 2026-06-12
- historical candidate rows: 46480
- historical candidate tickers: 968
- historical months: 84
- historical candidate last date: 2026-04-30
- SEC-enriched candidate present: False
- SEC-enriched candidate rows: 0

## Universe Source

- `current_constituents_proxy_static_seed`: 43744
- `adr_whitelist`: 1308
- `current_constituents_proxy_static_seed+strategic_global_hardware`: 1180
- `cycle_play_whitelist`: 248

## Evidence Utilization

- rows with SEC evidence: None
- rows with 13F evidence: None
- rows with ETF evidence: None
- rows with smart-money evidence: None
- coverage ratio: 0.0%
- 13F coverage ratio: 0.0%

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
- `historical_candidate_book.roe_proxy` numeric=44.8%, nonzero=44.8%
- `historical_candidate_book.gross_profit_ttm` numeric=45.0%, nonzero=45.0%
- `historical_candidate_book.capex_ttm` numeric=46.9%, nonzero=46.8%
- `historical_candidate_book.ocf_ttm` numeric=56.5%, nonzero=56.5%
- `historical_candidate_book.op_income_ttm` numeric=56.8%, nonzero=56.8%
- `historical_candidate_book.revenues_ttm` numeric=57.7%, nonzero=57.7%

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

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=7.57411418146033
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=72; sleeve=`core_compounder`; score=6.839821795233787
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=54; sleeve=`core_compounder`; score=3.063526231243269
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.439993606666095
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.794101394053048
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=1.8963748225022348
- `CIEN`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=1.768409624877887
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=22; sleeve=`unassigned`; score=4.36427854809802
- `DELL`: selection_gate_or_rank_rejected; latest=True; hist_months=3; sleeve=`unassigned`; score=5.487261683543912
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`core_compounder`; score=3.461880532113681
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=4.854867363826274
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.320377071609615
- `HPE`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=7.680906191515048
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=63; sleeve=``; score=None
- `KLAC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=81; sleeve=`early_scout`; score=7.051746739133809
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=72; sleeve=`unassigned`; score=4.952984198154199
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=8.013182979473909
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`future_winner`; score=5.743996026579021
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.482115750254359
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=66; sleeve=`core_compounder`; score=4.452503625164694
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=28; sleeve=`core_compounder`; score=2.055592450206849
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=4.610182356615581
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=3; sleeve=`unassigned`; score=4.16112698339568
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=6.0455792012497644
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=3.9127931715331385
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`core_compounder`; score=3.4783249897137063
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=39; sleeve=`future_winner`; score=7.022933130379912
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=24; sleeve=`core_compounder`; score=2.533794953824596

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
