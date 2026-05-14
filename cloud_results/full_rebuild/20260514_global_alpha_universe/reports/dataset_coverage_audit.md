# Dataset Coverage Audit

- latest run: `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs`
- scored latest rows: 745
- latest scored date: 2026-05-15
- historical candidate rows: 46789
- historical months: 84
- historical candidate last date: 2026-03-31

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
- `historical_candidate_book.roe_proxy` numeric=44.9%, nonzero=44.9%
- `historical_candidate_book.gross_profit_ttm` numeric=45.1%, nonzero=45.1%
- `historical_candidate_book.capex_ttm` numeric=47.1%, nonzero=47.0%
- `historical_candidate_book.ocf_ttm` numeric=56.5%, nonzero=56.5%
- `historical_candidate_book.op_income_ttm` numeric=56.8%, nonzero=56.8%
- `historical_candidate_book.revenues_ttm` numeric=57.7%, nonzero=57.7%

## Missing Audit Columns

- `historical_candidate_book.r_12m`
- `historical_candidate_book.r_6m`
- `latest_scored.eps_revision_proxy`
- `latest_scored.revision_score`

## Watchlist Gaps

- `AMAT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.157993193694372
- `AMD`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.5985409436156575
- `ANET`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=53; sleeve=`core_compounder`; score=1.9076775878781544
- `ARM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=5.534376129586626
- `ASML`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=4.336876915791095
- `AVGO`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=3.1817569585467864
- `CIEN`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`future_winner`; score=5.197595532821808
- `COHR`: selection_gate_or_rank_rejected; latest=True; hist_months=25; sleeve=`unassigned`; score=5.013772557804236
- `DELL`: historical_only_not_current_latest_universe; latest=False; hist_months=8; sleeve=``; score=None
- `GEV`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=9; sleeve=`core_compounder`; score=6.360709978393288
- `GLW`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=10; sleeve=`future_winner`; score=5.20088512673857
- `GOOGL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=7.528157807284011
- `HPE`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`early_scout`; score=4.339003352507328
- `INTC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.006122907960484
- `KLAC`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=5.2483553803419705
- `LITE`: selection_gate_or_rank_rejected; latest=True; hist_months=72; sleeve=`unassigned`; score=5.88753163558683
- `LRCX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=6.836432742864006
- `MRVL`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=49; sleeve=`future_winner`; score=6.487140467771663
- `MU`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=84; sleeve=`core_compounder`; score=5.361399518299064
- `NVDA`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=77; sleeve=`core_compounder`; score=4.785049682800269
- `OKLO`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `PLTR`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=27; sleeve=`core_compounder`; score=6.11508667978894
- `QCOM`: selection_gate_or_rank_rejected; latest=True; hist_months=84; sleeve=`unassigned`; score=5.150116303330285
- `SMCI`: selection_gate_or_rank_rejected; latest=True; hist_months=22; sleeve=`unassigned`; score=-0.9602622703257546
- `SMR`: historical_only_not_current_latest_universe; latest=False; hist_months=6; sleeve=``; score=None
- `SNDK`: selection_gate_or_rank_rejected; latest=True; hist_months=2; sleeve=`unassigned`; score=3.341684148986322
- `STX`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`future_winner`; score=6.006900078331334
- `TSM`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=0; sleeve=`core_compounder`; score=3.871055284230574
- `VRT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=50; sleeve=`core_compounder`; score=6.557581473445141
- `WDC`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=66; sleeve=`future_winner`; score=6.55052194408848
- `WMT`: selected_candidate_not_portfolio_ranked_high_enough; latest=True; hist_months=23; sleeve=`core_compounder`; score=4.825206051945219

## Files

- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit.json`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_coverage.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_watchlist.csv`
- `/home/runner/work/r1000-quant-engine/r1000-quant-engine/outputs/reports/dataset_coverage_audit_distributions.csv`
