# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 742
- latest scored date: 2026-07-02
- historical candidate rows: 47435
- historical candidate tickers: 981
- historical months: 85
- historical candidate last date: 2026-05-29
- SEC-enriched candidate present: True
- SEC-enriched candidate rows: 47435

## Universe Source

- `current_constituents_proxy_static_seed`: 44581
- `adr_whitelist`: 1399
- `current_constituents_proxy_static_seed+strategic_global_hardware`: 1202
- `cycle_play_whitelist`: 253

## Evidence Utilization

- rows with SEC evidence: 5780
- rows with 13F evidence: 36920
- rows with ETF evidence: 0
- rows with smart-money evidence: 34732
- coverage ratio: 12.2%
- 13F coverage ratio: 77.8%

## Effective Market Cap Coverage

- `latest_scored` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`
- `historical_candidate_book` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`

## Largest Coverage Gaps

- `historical_candidate_book.market_cap_live` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.gross_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.operating_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.revenue_growth_final` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.op_income_growth_yoy` numeric=5.2%, nonzero=5.2%
- `historical_candidate_book.ocf_growth_yoy` numeric=5.8%, nonzero=5.8%
- `historical_candidate_book.roe_proxy` numeric=45.0%, nonzero=45.0%
- `historical_candidate_book.gross_profit_ttm` numeric=45.1%, nonzero=45.1%
- `historical_candidate_book.capex_ttm` numeric=47.1%, nonzero=47.0%
- `historical_candidate_book.ocf_ttm` numeric=56.7%, nonzero=56.7%
- `historical_candidate_book.op_income_ttm` numeric=57.0%, nonzero=57.0%
- `historical_candidate_book.revenues_ttm` numeric=57.9%, nonzero=57.9%

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

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=7.762730526967009
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=73; sleeve=`core_compounder`; score=6.7122917627381895
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=55; sleeve=`core_compounder`; score=1.8821034100511729
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.228807845158616
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.60759230098718
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=1.6138704467071985
- `CIEN`: selection_gate_or_rank_rejected; latest=True; hist_months=85; sleeve=`unassigned`; score=1.6519806090006173
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=23; sleeve=`unassigned`; score=3.430715922620676
- `DELL`: selection_gate_or_rank_rejected; latest=True; hist_months=7; sleeve=`unassigned`; score=4.843335640360889
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=11; sleeve=`core_compounder`; score=5.429786721706623
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=11; sleeve=`future_winner`; score=5.831199215480106
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=5.109756185371701
- `HPE`: selection_gate_or_rank_rejected; latest=True; hist_months=85; sleeve=`unassigned`; score=5.145105978065184
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=63; sleeve=``; score=None
- `KLAC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=82; sleeve=`early_scout`; score=6.930807032894233
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=73; sleeve=`unassigned`; score=3.124029325149297
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=7.489567507796243
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=51; sleeve=`future_winner`; score=5.895452890027092
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=85; sleeve=`core_compounder`; score=5.338680968494263
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=67; sleeve=`core_compounder`; score=4.314702310919683
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=29; sleeve=`core_compounder`; score=3.886166180693701
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=85; sleeve=`unassigned`; score=2.949663698257205
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=4; sleeve=`unassigned`; score=5.910867622413323
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.097403128767885
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.5304886554543495
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`core_compounder`; score=5.305708967237192
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=40; sleeve=`future_winner`; score=6.4744322825429785
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=25; sleeve=`core_compounder`; score=2.3202927393664905

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
