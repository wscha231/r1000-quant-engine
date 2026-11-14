"""Explicit forecast units shared by A3 and A5; no fit or admission authority."""
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from functools import lru_cache

SESSION_ER_SCHEMA = "validated-er-nyse-sessions-v1"
SESSION_PROFILE_SCHEMA = "stock-cash-research-v2"
SESSION_HORIZON = "63_NYSE_SESSIONS"
SESSION_ER_KEY = "63s"


def _need(ok, reason):
    if not ok:
        raise ValueError(reason)


@lru_cache(maxsize=128)
def _exposure(session):
    import pandas_market_calendars as mcal
    day = date.fromisoformat(session)
    _need(day.isoformat() == session, "er63_decision_session")
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=day, end_date=day + timedelta(days=200))
    _need(len(schedule) >= 65 and schedule.index[0].date() == day,
          "er63_decision_not_nyse_session")
    # Same clock as the incumbent learner: future[0] -> future[63].
    # The decision-to-entry gap is not one of the 63 held price intervals.
    entry, mark = schedule.iloc[1]["market_close"], schedule.iloc[64]["market_close"]
    return (entry.isoformat(), mark.isoformat(),
            (mark.date() - entry.date()).days, (entry.date() - day).days)


def session63_exposure(session):
    _need(type(session) is str, "er63_decision_session")
    entry, mark, days, gap = _exposure(session)
    return dict(decision_session=session, entry_at=entry, mark_at=mark,
                held_intervals=63, carry_calendar_days=days,
                pre_entry_calendar_days=gap)


def validate_session63_er(value, *, decision_session=None):
    """Validate units and ex-ante calendar only; this does not validate a model."""
    _need(isinstance(value, Mapping) and value.get("schema") == SESSION_ER_SCHEMA,
          "er63_schema")
    _need(value.get("horizon") == SESSION_HORIZON and
          value.get("horizon_unit") == "NYSE_PRICE_INTERVALS" and
          type(value.get("horizon_count")) is int and value["horizon_count"] == 63,
          "er63_horizon")
    _need(value.get("downside_horizon") == SESSION_HORIZON and
          value.get("cost_horizon") == SESSION_HORIZON, "er63_risk_or_cost_horizon")
    supplied = value.get("forecast_clock")
    _need(isinstance(supplied, Mapping), "er63_original_forecast_clock")
    expected = session63_exposure(supplied.get("decision_session"))
    _need(decision_session is None or decision_session == expected["decision_session"],
          "er63_market_session_mismatch")
    _need(set(supplied) == set(expected), "er63_forecast_clock_fields")
    for key in ("entry_at", "mark_at"):
        try:
            observed = datetime.fromisoformat(supplied[key].replace("Z", "+00:00"))
            canonical = datetime.fromisoformat(expected[key])
        except (TypeError, ValueError, AttributeError):
            raise ValueError("er63_forecast_clock_time") from None
        _need(observed.tzinfo is not None and observed == canonical,
              "er63_forecast_clock_time")
    _need(all(type(supplied[k]) is int and supplied[k] == expected[k] for k in
              ("held_intervals", "carry_calendar_days", "pre_entry_calendar_days")),
          "er63_forecast_clock_exposure")
    return expected
