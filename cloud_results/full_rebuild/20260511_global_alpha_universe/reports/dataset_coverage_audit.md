# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 731
- latest scored date: 2026-05-11
- historical candidate rows: 56982
- historical months: 107
- historical candidate last date: 2026-03-31

## Effective Market Cap Coverage

- `latest_scored` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`
- `historical_candidate_book` effective cap numeric=100.0%, inputs=`market_cap_live,mktcap`

## Largest Coverage Gaps

- `historical_candidate_book.market_cap_live` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.gross_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.operating_margins` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.revenue_growth_final` numeric=0.0%, nonzero=0.0%
- `historical_candidate_book.op_income_growth_yoy` numeric=5.4%, nonzero=5.4%
- `historical_candidate_book.ocf_growth_yoy` numeric=6.0%, nonzero=6.0%
- `historical_candidate_book.roe_proxy` numeric=44.3%, nonzero=44.3%
- `historical_candidate_book.gross_profit_ttm` numeric=44.7%, nonzero=44.7%
- `historical_candidate_book.capex_ttm` numeric=46.6%, nonzero=46.5%
- `historical_candidate_book.ocf_ttm` numeric=56.3%, nonzero=56.3%
- `historical_candidate_book.op_income_ttm` numeric=56.8%, nonzero=56.8%
- `historical_candidate_book.revenues_ttm` numeric=57.8%, nonzero=57.8%

## Missing Audit Columns

- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `latest_scored.eps_revision_proxy`
- `latest_scored.revision_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=107; sleeve=`core_compounder`; score=6.035150757409228
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=95; sleeve=`core_compounder`; score=3.5317114283704663
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=53; sleeve=`core_compounder`; score=3.477312207171908
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.687566325298693
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.4862263691172775
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=94; sleeve=`core_compounder`; score=4.652670299673774
- `CIEN`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=107; sleeve=`future_winner`; score=5.137888430410628
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=21; sleeve=`unassigned`; score=4.6868018654261
- `DELL`: historical_only_not_current_latest_universe; latest=False; hist_months=20; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=9; sleeve=`core_compounder`; score=6.096779208117591
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=6.570468448896666
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=107; sleeve=`core_compounder`; score=6.862492888951413
- `HPE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=104; sleeve=`early_scout`; score=3.3495591027143465
- `INTC`: historical_only_not_current_latest_universe; latest=False; hist_months=87; sleeve=``; score=None
- `KLAC`: selection_gate_or_rank_rejected; latest=True; hist_months=107; sleeve=`unassigned`; score=5.074715315549228
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=95; sleeve=`unassigned`; score=5.443414579154126
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=105; sleeve=`core_compounder`; score=7.046661446316107
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`future_winner`; score=5.54371098299089
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=105; sleeve=`core_compounder`; score=4.188949099195408
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=76; sleeve=`core_compounder`; score=5.166027341669649
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=27; sleeve=`core_compounder`; score=6.157598442196655
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=107; sleeve=`unassigned`; score=4.632048543300469
- `SMCI`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=2; sleeve=`unassigned`; score=2.5480038772742777
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.119211150249065
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=5.945718017487335
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=48; sleeve=`core_compounder`; score=6.476757213580488
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=57; sleeve=`future_winner`; score=5.625405961848186
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=25; sleeve=`core_compounder`; score=4.51325656911437

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
