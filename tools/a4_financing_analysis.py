"""Supplementary financing context; never allocation or native risk authority."""
from collections import defaultdict
from statistics import mean
from tools import a4_primary_sources as p


def analyze(rows,*,cutoff):
    now=p.clock(cutoff);eligible=[]
    for row in rows:
        p.check(p.clock(row['available_at'])<=now and p.day(row['observation_date'])<=now.date(),
                'FINANCING_FUTURE_ANALYSIS')
        eligible.append(row)
    auction_groups=defaultdict(list)
    for row in eligible:
        if row['kind']=='TREASURY_AUCTION':
            auction_groups[(row['security_type'],row['original_term_years'])].append(row)
    auctions=[]
    for key,group in sorted(auction_groups.items()):
        ordered=sorted(group,key=lambda r:(r['observation_date'],r['cusip']))
        latest=ordered[-1]
        # Same-original-term cohorts preserve new issue/reopening distinctions.
        prior=[r for r in ordered if r['observation_date']<latest['observation_date']]
        same=[r for r in prior if r['reopening']==latest['reopening']]
        all6=prior[-6:];same6=same[-6:]
        baseline=mean(r['bid_to_cover'] for r in all6) if len(all6)==6 else None
        same_baseline=mean(r['bid_to_cover'] for r in same6) if len(same6)==6 else None
        def comparison(value):
            return 'INSUFFICIENT_EVIDENCE' if value is None else (
                'BELOW_PRIOR_SIX_BTC' if latest['bid_to_cover']<value else 'AT_OR_ABOVE_PRIOR_SIX_BTC')
        all_comparison=comparison(baseline);same_comparison=comparison(same_baseline)
        age=(now.date()-p.day(latest['observation_date'])).days
        auctions.append(dict(latest=latest,status='OBSERVED' if age<=45 else 'STALE',
            prior_six_same_original_term_btc_mean=baseline,
            prior_six_same_original_term_dates=[r['observation_date'] for r in all6],
            prior_six_same_original_term_reopening_flags=[r['reopening'] for r in all6],
            prior_six_same_issuance_type_btc_mean=same_baseline,
            prior_six_same_issuance_type_dates=[r['observation_date'] for r in same6],
            latest_minus_same_original_term_mean=None if baseline is None else latest['bid_to_cover']-baseline,
            comparison=all_comparison,same_issuance_type_comparison=same_comparison,
            cohort_comparison='INSUFFICIENT_EVIDENCE' if baseline is None or same_baseline is None else (
                'SAME_DIRECTION' if all_comparison==same_comparison else 'MIXED_COHORT_COMPARISONS'),
            tail_bp=None,tail_blocker='VERIFIED_AUCTION_TIME_WHEN_ISSUED_QUOTE_REQUIRED',
            comparison_caveat='All-term peer mean mixes new issues/reopenings; same-issuance cohort is separate.',
            independent_signal_group='TREASURY_AUCTION_DEMAND'))
    surveys=[r for r in eligible if r['kind']=='SLOOS']
    period=max((r['survey_period'] for r in surveys),default=None)
    surveys=[r for r in surveys if r['survey_period']==period]
    ndfi=[r for r in surveys if r['sector'].startswith('ndfi_')]
    credit=dict(status='OBSERVED' if surveys and (now.date()-p.day(surveys[0]['observation_date'])).days<=150
        else 'STALE' if surveys else 'DATA_BLOCKED',survey_period=period,series=surveys,
        ndfi_status='OBSERVED' if ndfi else 'NOT_ASKED_OR_NOT_VERIFIED_THIS_RELEASE',
        interpretation='Positive net tightening means more respondents tightened than eased; demand is separate.',
        population_caveat='Question-specific respondent counts; SLOOS groups are not H8 bank aggregates.',
        independent_signal_group='BANK_CREDIT_SUPPLY')
    acm=sorted([r for r in eligible if r['kind']=='ACM_MONTHLY'],key=lambda r:r['observation_date'])
    term=dict(status=('MONTHLY_CONTEXT_ONLY' if (now.date()-p.day(acm[-1]['observation_date'])).days<=62
        else 'STALE_MONTHLY_CONTEXT') if acm else 'DATA_BLOCKED',latest=acm[-1] if acm else None,
        daily_status='DAILY_ORIGINAL_ADAPTER_NOT_VERIFIED',
        caveat='ACM is an estimated, revised model premium; chart CSV is monthly, not independent daily evidence.',
        independent_signal_group='TREASURY_DURATION_COMPENSATION')
    daily=sorted([r for r in eligible if r['kind']=='ACM_DAILY'],key=lambda r:r['observation_date'])
    if daily:
        latest=daily[-1]
        status=('MISSING_LATEST_MODEL_VALUE' if latest['native_value_status']!='OBSERVED' else
            'OBSERVED_DAILY_MODEL_ESTIMATE' if (now.date()-p.day(latest['observation_date'])).days<=7 else 'STALE_DAILY_MODEL_ESTIMATE')
        term.update(status=status,daily_status=status,latest=latest,monthly_context_latest=acm[-1] if acm else None,
            caveat='ACM is a revised model decomposition of fitted zero-coupon yields, not a measured premium or the Treasury par curve; monthly and daily data are the same signal family.')
    observed=any(r['kind'] in {'TREASURY_AUCTION','SLOOS','ACM_DAILY','ACM_MONTHLY'} for r in eligible)
    return dict(schema='a4-financing-conditions-v1',status='PARTIAL_EVIDENCE' if observed else 'DATA_BLOCKED',
        treasury_auctions=auctions,lending_standards=credit,
        cross_tenor_counter_evidence=[dict(security_type=r['latest']['security_type'],
            original_term_years=r['latest']['original_term_years'],observation_date=r['latest']['observation_date'],
            bid_to_cover=r['latest']['bid_to_cover'],baseline=r['prior_six_same_original_term_btc_mean'],
            **{key:r['latest'][key] for key in ('original_sha256','source_uri','available_at')})
            for r in auctions if r['status']=='OBSERVED' and r['comparison']=='AT_OR_ABOVE_PRIOR_SIX_BTC'],
        term_premium=term,credit_fragility=dict(status='RIGHTS_EVIDENCE_REQUIRED',
            required=['CCC_AND_LOWER_OAS','BROAD_HY_OAS'],
            caveat='Different index constituents; spread differences are descriptive, not a causal crisis estimate.',
            source_uri='https://fred.stlouisfed.org/series/BAMLH0A3HYC',
            independent_signal_group='CORPORATE_CREDIT'),
        fund_flows=dict(status='RIGHTS_EVIDENCE_REQUIRED',
            required=['ICI_DOMESTIC_EQUITY_ETF_NET_ISSUANCE','ICI_MMF_ASSETS_BY_TYPE'],
            source_uri='https://www.ici.org/copyright-and-linking-policies',
            caveats=['ETF net issuance is creations minus redemptions, not secondary-market net buying.',
                'MMF asset changes are balance changes, not an identified equity-to-MMF transfer.',
                'Simultaneous ETF issuance and MMF asset growth do not identify the same investors.']),
        leverage=dict(status='RIGHTS_AND_ORIGINAL_ADAPTER_REQUIRED',series='FINRA_MARGIN_DEBT'),
        conditional_scenarios=dict(status='INSUFFICIENT_EVIDENCE',
            improving=['DECLINING_LONG_AND_REAL_YIELDS','NARROWING_HY_AND_CCC_SPREADS','BROADENING_EQUITY_PARTICIPATION'],
            deteriorating=['RISING_DURATION_COMPENSATION','CREDIT_STRESS_PROPAGATION','WEAK_FUND_FLOWS_AND_CREDIT_SUPPLY'],
            classification_status='NOT_CALIBRATED_AS_A_NATIVE_A4_RISK_STATE'),
        readiness=dict(treasury_auction_context=any(r['status']=='OBSERVED' for r in auctions),sloos_context=credit['status']=='OBSERVED',
            sloos_ndfi_context=credit['status']=='OBSERVED' and credit['ndfi_status']=='OBSERVED',
            ccc_licensed=False,ici_licensed=False,daily_term_premium=term['daily_status']=='OBSERVED_DAILY_MODEL_ESTIMATE',finra_leverage=False),
        learning_status='INDEPENDENT_FEATURE_RECIPE_AND_INPUT_POLICY_REVIEW_REQUIRED',
        native_risk_axes_changed=False,portfolio_weights_allowed=False,automatic_winner_exit_allowed=False)
