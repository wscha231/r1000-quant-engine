#!/usr/bin/env python3
"""H1 adapter for the existing vendor collector, deliberately not scheduled.

Reuses the legacy network coordinator only on explicit main() invocation. Missing
instrument/provider/unit context keeps revisions unavailable, not equal to zero.
This adapter does not certify provider entitlements, historical PIT or returns.
"""
from __future__ import annotations
import copy
from datetime import timedelta
from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import pandas as pd
from tools.earnings_consensus_h1 import (
    CONTEXT_KEYS, _admissible_time, _dt, _valid_context, build_snapshot,
    iso_utc, optional_float, pct_change, period_value,
)


def parse_snapshot_row(ticker: str, *, fetch_date: Any, eps_payload: Any,
                       revenue_payload: Any, earnings_payload: Any,
                       recommendation_payload: Any,
                       eps_estimate_access: bool = True,
                       revenue_estimate_access: bool = True,
                       fetch_source: str = 'finnhub',
                       identity_context: dict[str, Any] | None = None) -> dict[str, Any]:
    # An actual collector clock must supply an aware observation timestamp.
    # Do not relabel a date-only legacy snapshot as intraday evidence.
    stamp = iso_utc(fetch_date)
    row = build_snapshot(ticker, eps_payload=eps_payload, revenue_payload=revenue_payload,
                         recommendation_payload=recommendation_payload, observed_at=stamp,
                         collected_at=stamp, first_seen_at=stamp, fetch_source=fetch_source,
                         eps_estimate_access=eps_estimate_access,
                         revenue_estimate_access=revenue_estimate_access,
                         identity_context=identity_context)
    row.update(as_of_date=stamp[:10] if stamp else None, available_from=row['available_at'],
               est_eps_fy1=row['eps_fy1_avg'], est_eps_fy2=row['eps_fy2_avg'],
               est_rev_fy1=row['rev_fy1_avg'], est_dispersion=row['eps_fy1_dispersion'])
    counts = [row[k] for k in ('eps_fy1_analyst_count','rev_fy1_analyst_count') if row[k] is not None]
    row['n_analysts'] = max(counts) if counts else None
    # Actuals are a separate channel: do not confuse fiscal-period end with
    # announcement date, or absolute surprise with percentage surprise.
    actuals = [x for x in earnings_payload if isinstance(x, dict)] if isinstance(earnings_payload, list) else []
    actuals = [x for x in actuals if period_value(x)]
    latest = max(actuals, key=lambda x: period_value(x)) if actuals else {}
    row.update(actual_eps_last=optional_float(latest.get('actual')),
               actual_fiscal_period_end=period_value(latest), actual_report_date=None,
               actual_available_at=None, earnings_surprise_last=None,
               provider_surprise_absolute=optional_float(latest.get('surprise')),
               provider_surprise_percent=optional_float(latest.get('surprisePercent')),
               surprise_streak=None, actual_evidence_status='OBSERVED_NOT_RELEASE_TIME_VERIFIED')
    return row


def _same_context(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _valid_context(a) and _valid_context(b) and all(a[k] == b[k] for k in CONTEXT_KEYS)


def _value(row: dict[str, Any], metric: str, period: str, field: str = 'avg') -> float | None:
    values = [optional_float(row.get(f'{metric}_fy{n}_{field}')) for n in (1,2)
              if row.get(f'{metric}_fy{n}_period_end') == period]
    values = [v for v in values if v is not None]
    return values[0] if len(set(values)) == 1 else None


def _prior(rows: list[dict[str, Any]], current: dict[str, Any], metric: str,
           days: int) -> tuple[dict[str, Any] | None, str]:
    now = _admissible_time(current)
    period = current.get(f'{metric}_fy1_period_end')
    if now is None or not period or not _valid_context(current):
        return None, 'IDENTITY_OR_TIME_INCOMPLETE'
    anchor = now - timedelta(days=days)
    eligible = []
    for r in rows:
        ts = _admissible_time(r)
        if ts is None or ts > anchor or ts >= now or not _same_context(r,current) or r.get('validation_errors'):
            continue
        if _value(r,metric,period) is not None:
            eligible.append((ts,r))
    if not eligible:
        return None, 'NO_SAME_PERIOD_LOOKBACK'
    latest = max(t for t,r in eligible)
    tied = [r for t,r in eligible if t == latest]
    signatures = {(_value(r,metric,period),_value(r,metric,period,'dispersion')) for r in tied}
    if len(signatures) != 1:
        return None, 'CONFLICTING_LOOKBACK'
    # The last observation may be much older than requested. Report its age;
    # no silently fabricated 30-day/90-day precision.
    return tied[0], 'SAME_PERIOD_COMPARABLE'


def compute_estimate_revision_features(snapshots: pd.DataFrame, *,
                                      as_of_date: Any = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    cutoff = _dt(as_of_date)
    if cutoff is None:
        return pd.DataFrame(), {'status':'blocked','reason':'EXACT_AWARE_DECISION_CUTOFF_REQUIRED'}
    if snapshots.empty:
        return pd.DataFrame(), {'status':'blocked','reason':'NO_SNAPSHOT_ROWS'}
    original = snapshots.to_dict('records')
    eligible, exclusions = [], []
    for r in original:
        ts = _admissible_time(r)
        if ts is None or ts > cutoff or r.get('validation_errors'):
            exclusions.append({'ticker':r.get('ticker'), 'reason':'INVALID_FUTURE_OR_BLOCKED_SNAPSHOT'})
        else:
            eligible.append(r)
    # Stable, content-based traversal. Insertion order never chooses between
    # same-time conflicting estimates.
    eligible.sort(key=lambda r: (str(r.get('ticker')),str(r.get('security_id')),iso_utc(r.get('available_at'))))
    out = []
    for r in eligible:
        x = copy.deepcopy(r)
        statuses=[]
        for metric, days, column in (('eps',30,'est_eps_revision_30d'),('eps',90,'est_eps_revision_90d'),('rev',30,'est_rev_revision_30d')):
            previous, state = _prior(eligible,r,metric,days)
            statuses.append(state)
            period = r.get(f'{metric}_fy1_period_end')
            x[column] = pct_change(_value(r,metric,period), _value(previous,metric,period)) if previous else None
            x[column+'_anchor_available_at'] = previous.get('available_at') if previous else None
            x[column+'_observed_age_days'] = ((_admissible_time(r)-_admissible_time(previous)).total_seconds()/86400) if previous else None
        prior_eps,state = _prior(eligible,r,'eps',30)
        p = r.get('eps_fy1_period_end')
        cdisp,pdisp = _value(r,'eps',p,'dispersion'), _value(prior_eps,'eps',p,'dispersion') if prior_eps else None
        x['est_dispersion_change_30d'] = cdisp-pdisp if cdisp is not None and pdisp is not None else None
        x['revision_period_status'] = 'SAME_PERIOD_COMPARABLE' if any(x[k] is not None for k in ('est_eps_revision_30d','est_eps_revision_90d','est_rev_revision_30d')) else '|'.join(sorted(set(statuses)))
        x['est_eps_revision_breadth'] = None
        positive=any(x[k] is not None and x[k]>0 for k in ('est_eps_revision_30d','est_eps_revision_90d','est_rev_revision_30d'))
        x['estimate_revision_confirmed']=int(positive and x['est_dispersion_change_30d'] is not None and x['est_dispersion_change_30d']<=0)
        # H1 can describe a revision; it may not grant replacement/alpha authority.
        x['estimate_revision_replacement_gate_pass']=0
        x['estimate_revision_future_winner_multiplier']=1.0
        out.append(x)
    return pd.DataFrame(out), {
        'status':'completed' if out else 'blocked','schema_version':'forward-earnings-estimates-h1-v2',
        'input_rows':len(original),'output_rows':len(out),'excluded_rows':len(exclusions),
        'exclusions':exclusions,'forward_only':True,'backtest_acceptance_allowed':False,
        'production_activation_allowed':False,'live_trading_enabled':False,
    }


def run_legacy(legacy: Any, identity_resolver: Callable[[str], dict[str, Any] | None] | None = None) -> Any:
    """Scoped single-process adapter injection; restore callbacks even on failure.

    No resolver means observation-only context. This is not a concurrent runner;
    a future coordinator should pass callbacks explicitly instead of module patching.
    """
    original_parse,original_compute = legacy.parse_snapshot_row,legacy.compute_estimate_revision_features
    def parse(ticker: str, **kwargs: Any) -> dict[str, Any]:
        context = identity_resolver(ticker) if identity_resolver else None
        return parse_snapshot_row(ticker,identity_context=context,**kwargs)
    try:
        legacy.parse_snapshot_row=parse
        legacy.compute_estimate_revision_features=compute_estimate_revision_features
        return legacy.main()
    finally:
        legacy.parse_snapshot_row=original_parse
        legacy.compute_estimate_revision_features=original_compute


def main() -> Any:
    import tools.collect_earnings_estimates_finnhub as legacy
    return run_legacy(legacy)

if __name__=='__main__':
    main()
