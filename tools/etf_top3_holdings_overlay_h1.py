"""Research-only ETF look-through: deterministic dedupe and identity admission guard.

Integration route: existing tools/run_etf_holdings_refresh.py normalizer and A2
candidate registry. Do not mutate fixed 1009 seed, target portfolio or rankings.
Always keep issuer/security identity, ETF holding *as-of* and actual publication
availability timestamps separate. The ETFIQ quote is research only.
"""
from __future__ import annotations
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

TOP3 = ('GARP','QUAL','SPMO')
TICKER = re.compile(r'^[A-Z][A-Z0-9.-]{0,10}$')

class OverlayError(ValueError): pass


def require(ok,code):
    if not ok: raise OverlayError(code)


def parse_date(s):
    require(type(s) is str, 'MISSING_ASOF')
    try: d = date.fromisoformat(s)
    except ValueError as exc: raise OverlayError('BAD_ASOF_DATE') from exc
    require(s==d.isoformat(),'ASOF_NOT_ISO')
    return d


def parse_timestamp(s):
    require(type(s) is str,'PUBLISHED_TIMESTAMP_REQUIRED')
    try: dt=datetime.fromisoformat(s.replace('Z','+00:00'))
    except ValueError as exc: raise OverlayError('PUBLISHED_TIMESTAMP_INVALID') from exc
    require(dt.tzinfo is not None and dt.utcoffset() is not None,'PUBLISHED_TIMESTAMP_OFFSET_MISSING')
    return dt.astimezone(timezone.utc)


def build_lookthrough(records: list[dict[str, Any]], seed_symbols: list[str], *,
                     reviewed_at_utc: str, expected_top_n: int=10) -> dict[str, Any]:
    """Only accepts real dated ETF holding *snapshots*; cannot invent as-of.

    `published_at_utc` is a provider-observed publication/availability clock,
    not merely when a research sheet was exported. Missing = blocked for PIT.
    Currently recorded ETFIQ holdings have NO verified published timestamp.
    """
    review=parse_timestamp(reviewed_at_utc)
    require(type(expected_top_n) is int and expected_top_n > 0, 'TOP_N_INVALID')
    require(isinstance(records,list) and len(records)==len(TOP3)*expected_top_n,'TOP3_NUMBER_WRONG')
    require(isinstance(seed_symbols,list) and len(seed_symbols)==len(set(seed_symbols)), 'SEED_DUPLICATE')
    seed=set(seed_symbols)
    byfund: dict[str, dict[int, dict]]={t:{} for t in TOP3}
    tick_byfund={f:set() for f in TOP3}
    for rec in records:
        require(isinstance(rec,dict),'HOLDINGS_ROW_NOT_OBJECT')
        fund=rec.get('etf')
        require(fund in TOP3,'UNEXPECTED_ETF')
        ticker=rec.get('ticker')
        require(type(ticker) is str and bool(TICKER.fullmatch(ticker)), 'MALFORMED_SECURITY_TICKER')
        rank=rec.get('rank')
        require(type(rank) is int and 1 <= rank <= expected_top_n, 'INVALID_ETF_RANK')
        require(rank not in byfund[fund] and ticker not in tick_byfund[fund], 'DUPLICATE_RANK_OR_HOLDING')
        w=rec.get('weight_pct')
        require(type(w) in (float,int) and 0 < w <= 100,'BAD_HOLDING_WEIGHT')
        asof=parse_date(rec.get('holdings_asof'))
        require(asof <= review.date(),'HOLDINGS_FUTURE_ASOF')
        url=rec.get('source_url')
        require(type(url) is str and url.startswith('https://'),'SOURCE_URL_NOT_AUTHENTICATED')
        available=rec.get('published_at_utc')
        if available:
            stamp=parse_timestamp(available)
            require(stamp.date()>=asof and stamp <= review,'PUBLISHED_CLOCK_CONFLICT')
        byfund[fund][rank]=rec
        tick_byfund[fund].add(ticker)
    require(all(set(ranks)==set(range(1,expected_top_n+1)) for ranks in byfund.values()),'ETF_TOP10_INCOMPLETE')
    for ranks in byfund.values():
        require(len({r['holdings_asof'] for r in ranks.values()}) == 1, 'ETF_SNAPSHOT_MIXED_ASOF')
        require(sum(r['weight_pct'] for r in ranks.values()) <= 100.0,
                'ETF_TOP_HOLDINGS_WEIGHT_EXCEEDS_FUND')
    result=[]
    for ticker in sorted(set().union(*tick_byfund.values())):
        placements=[]
        for fund in TOP3:
            for rank,rec in byfund[fund].items():
                if rec['ticker']==ticker:
                    placements.append({'etf':fund,'rank':rank,'weight_pct':rec['weight_pct'],
                                       'holdings_asof':rec['holdings_asof'],'source_url':rec['source_url'],
                                       'published_at_utc':rec.get('published_at_utc')})
        if ticker in seed: admission='ALREADY_IN_FROZEN_SEED__RESEARCH_TAG_ONLY'
        else: admission='DISCOVERED_NOT_IN_SEED__IDENTITY_REVIEW'
        result.append({'ticker':ticker,'etf_membership_count':len(placements),
                       'placements':sorted(placements,key=lambda r:TOP3.index(r['etf'])),
                       'seed_membership':ticker in seed,'registry_state':admission,
                       'issuer_economic_identity': 'SAME_COMPANY_MULTICLASS__REVIEW' if ticker in {'GOOG','GOOGL'} else 'NOT_INFERRED',
                       'eligible_for_buy':False, 'eligible_for_portfolio':False, 'a2_candidate_approved':False})
    return {'status':'RESEARCH_TAGS_PREPARED_ONLY','universe_seed_modified':False,
            'etfs':list(TOP3),'holding_slots':len(records),'unique_securities':len(result),
            'count_already_in_seed':sum(x['seed_membership'] for x in result),
            'requires_identity_review':sum(not x['seed_membership'] for x in result),
            'historical_membership_backfill':False, 'provenance_time_complete':all(bool(r.get('published_at_utc')) for r in records),
            'eligible_for_pit':False,'results':result}
