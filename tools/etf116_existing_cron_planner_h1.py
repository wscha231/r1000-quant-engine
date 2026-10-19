"""Pure schedule decision under the EXISTING GitHub Actions cron; NEVER schedules work.

This module must be inserted only by the approved owner in an isolated job,
separate from portfolio replay. No new cron, task, broker operation or Drive
writer. Official NYSE close/date/availability must be verified upstream.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from tools.etf116_research_metrics_h1 import d, ts, require


def plan_existing_trigger(*, session: str, close_utc: str, now_utc: str,
                          calendar_session_verified: bool,
                          provider_available_at_utc: str | None,
                          prior_eod_processed_session: str | None,
                          prior_holdings_refresh_session: str | None,
                          schedule_flag_enabled: bool = False) -> dict:
    day=d(session)
    now=ts(now_utc);close=ts(close_utc)
    require(close.date()==day, 'MARKET_CLOSE_DATE_INVALID')
    if prior_eod_processed_session:
        d(prior_eod_processed_session)
    if prior_holdings_refresh_session:
        d(prior_holdings_refresh_session)
        require(prior_holdings_refresh_session <= session, 'HOLDINGS_REFRESH_FUTURE_CHECKPOINT')
    base={'session':session,'job':'etf116_eod_research',
          'new_cron_created':False,'connected_to_broker_replay':False,
          'dispatch_performed':False,'economic_authority':False,
          'publish_enabled':False}
    if not schedule_flag_enabled:
        return {**base,'decision':'DISABLED_BY_DEFAULT','price_refresh_due':False,
                'holdings_refresh_due':False}
    if not calendar_session_verified:
        return {**base,'decision':'BLOCKED_NYSE_NOT_VERIFIED','price_refresh_due':False,'holdings_refresh_due':False}
    if now < close + timedelta(minutes=30):
        return {**base,'decision':'WAIT_EOD_COMPLETION_AND_DELAY','price_refresh_due':False,'holdings_refresh_due':False}
    if now > close + timedelta(hours=18):
        return {**base,'decision':'SKIP_STALE_CLOSE','price_refresh_due':False,'holdings_refresh_due':False}
    if provider_available_at_utc is None:
        return {**base,'decision':'BLOCKED_SOURCE_AVAILABILITY_UNKNOWN','price_refresh_due':False,'holdings_refresh_due':False}
    provider=ts(provider_available_at_utc)
    if provider < close or provider > now:
        return {**base,'decision':'BLOCKED_SOURCE_TIME_INCONSISTENT','price_refresh_due':False,'holdings_refresh_due':False}
    if prior_eod_processed_session and prior_eod_processed_session >= session:
        return {**base,'decision':'SKIP_UNCHANGED_OR_ROLLBACK','price_refresh_due':False,'holdings_refresh_due':False}
    current_week=day.isocalendar()[:2]
    previous_week=(d(prior_holdings_refresh_session).isocalendar()[:2]
                   if prior_holdings_refresh_session else None)
    weekly=previous_week is None or previous_week < current_week
    return {**base,'decision':'PREPARED_ONLY_NOT_DISPATCHED','price_refresh_due':True,
            'holdings_refresh_due':weekly,
            'weekly_membership_requires_source_release_clock':True,
            'note':'Only existing GH schedule can dispatch after A1/A6/T3; this is not approval.'}
