"""Assess one registered A5 research portfolio against a matched SPY total-return curve."""
import argparse
import calendar
import json
import math
from datetime import date, timedelta
from itertools import groupby
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from mission_contract import mission_identity
from r1000_config import PORTFOLIO_MISSION_TARGETS
from tools import nav_metrics_v2 as nav
from tools.execution_cost_model import EXECUTION_COST_MODE_FIXED


GOAL_POLICY = "matched_spy_diagnostics_constrained_compounding_v3"
CASH_BASIS = "MODELED_TRADE_DATE_LEDGER_CASH_OVER_CLOSING_NAV"


def goal_outcome(kind, book, spy):
    """Keep the matched-SPY diagnostic separate from risk limits and admission."""
    # On the authenticated common window and capital, terminal NAV strictly orders
    # CAGR even when annualizing two adjacent representable values rounds them equal.
    beats_spy = book["ending_capital_usd"] > spy["ending_capital_usd"]
    drawdown_ok = abs(book["max_dd"]) <= abs(spy["max_dd"])
    base_met = beats_spy and drawdown_ok
    return dict(status="PASS" if base_met else "MISS", return_goal_met=beats_spy,
                drawdown_goal_met=drawdown_ok,
                stretch_status="RETIRED_FIXED_CAGR_TARGET" if kind == "concentrated" else "NOT_APPLICABLE")


def compounding_objective(kind, book, spy):
    """Continuous research objective; no fixed CAGR threshold or promotion power.

    Supplied NAV is already net of costs. Terminal wealth orders CAGR only on
    the authenticated common window, capital, and cash-flow basis in assess().
    The existing drawdown limit is reported independently of SPY's drawdown.
    """
    identity = mission_identity(PORTFOLIO_MISSION_TARGETS)
    drawdown_limit = identity["mission_contract_values"][kind]["max_dd_min"]
    return dict(
        policy="MAXIMIZE_NET_COMPOUNDING_WITHIN_EXISTING_RISK_CONSTRAINTS_V1",
        status="MEASURED", fixed_cagr_target=None,
        primary_measure="NET_TERMINAL_WEALTH_ON_AUTHENTICATED_MATCHED_WINDOW",
        ending_capital_usd=book["ending_capital_usd"], cagr=book["cagr"],
        net_wealth_difference_vs_spy_usd=book["ending_capital_usd"]-spy["ending_capital_usd"],
        excess_cagr_vs_spy=book["cagr"]-spy["cagr"],
        drawdown_constraint=dict(
            status="MET" if book["max_dd"] >= drawdown_limit else "BREACHED",
            max_dd_min=drawdown_limit, observed_max_dd=book["max_dd"],
            source="PORTFOLIO_MISSION_TARGETS.max_dd",
            mission_contract_sha256=identity["mission_contract_sha256"]),
        recovery_policy="REPORT_PEAK_TO_RECOVERY_AND_RIGHT_CENSORED_ONGOING_EPISODES",
        evidence_scope="RESEARCH_WINDOW_ONLY_NOT_FORWARD_ALPHA",
        other_admission_gates_evaluated=False, promotion_allowed=False)


def _project_mission(kind, book):
    """Preserve the configured historical scorecard as a compatibility diagnostic."""
    identity = mission_identity(PORTFOLIO_MISSION_TARGETS)
    target = identity["mission_contract_values"][kind]
    cagr_met = book["cagr"] >= target["cagr_min"]
    drawdown_met = book["max_dd"] >= target["max_dd_min"]
    return dict(status="PASS" if cagr_met and drawdown_met else "MISS",
                role="LEGACY_FIXED_TARGET_DIAGNOSTIC_NOT_RESEARCH_ACCEPTANCE",
                basis="MATCHED_RESEARCH_WINDOW_NET_NAV",
                mission_contract_id=identity["mission_contract_id"],
                mission_contract_sha256=identity["mission_contract_sha256"],
                cagr_min=target["cagr_min"], max_dd_min=target["max_dd_min"],
                cagr_met=cagr_met, drawdown_met=drawdown_met)


def _cash_at_close(packet, nav_rows):
    """Optional original daily equity curve, pinned by the same external manifest."""
    try:
        rows = packet["equity_curve"]
        nav.require(packet["manifest"].get("equity_curve_cash_basis") == CASH_BASIS and
                    type(rows) is list and len(rows) == len(nav_rows) and
                    nav.digest(rows) == packet["manifest"]["equity_curve_sha256"], "GOAL_CASH_ORIGINAL")
        cash = {}
        for row, mark in zip(rows, nav_rows):
            amount = nav.real(row["cash_usd"])
            nav.require(row["date"] == mark["session"] and
                        nav.real(row["equity_usd"], positive=True) == mark["nav"] and
                        0 <= amount <= mark["nav"], "GOAL_CASH_GRID")
            cash[row["date"]] = amount / mark["nav"]
        return cash, "MEASURED"
    except (KeyError, TypeError, ValueError, OverflowError):
        return {}, "DATA_BLOCKED"


def monthly_diagnostics(packet):
    """Use complete NYSE months on the already verified, identical daily grids."""
    import pandas_market_calendars as mcal

    book, spy = packet["portfolio"], packet["spy"]
    rows = book["rows"]
    first = date.fromisoformat(rows[0]["session"])
    last = date.fromisoformat(rows[-1]["session"])
    first_of_month = first.replace(day=1)
    last_of_month = last.replace(day=calendar.monthrange(last.year, last.month)[1])
    nyse = mcal.get_calendar("NYSE")
    prior_month_end = first_of_month - timedelta(days=1)
    prior = nyse.schedule(start_date=prior_month_end.replace(day=1), end_date=prior_month_end)
    first_anchor_ok = nav.stamp(book["context"]["anchor"]["timestamp"]) == prior.market_close.iloc[-1]
    first_session = nyse.valid_days(first_of_month, first)[0].date()
    last_session = nyse.valid_days(last, last_of_month)[-1].date()
    cash, cash_status = _cash_at_close(packet, rows)
    prev_nav = book["context"]["anchor"]["nav"]
    prev_spy = spy["context"]["anchor"]["nav"]
    prev_day = None
    previous_spy_down = False
    months = []
    for month, pairs in groupby(zip(rows, spy["rows"]), key=lambda pair: pair[0]["session"][:7]):
        mark, benchmark = list(pairs)[-1]
        complete = (prev_day is not None or (first_session == first and first_anchor_ok)) and (
            mark["session"] != rows[-1]["session"] or last_session == last)
        if complete:
            book_return = nav.real(mark["nav"] / prev_nav - 1)
            spy_return = nav.real(benchmark["nav"] / prev_spy - 1)
            months.append(dict(month=month, portfolio_return=book_return, spy_return=spy_return,
                               excess_return=book_return-spy_return, spy_down=spy_return < 0,
                               immediate_rebound=previous_spy_down and spy_return > 0,
                               prior_close_cash_weight=cash.get(prev_day)))
            previous_spy_down = spy_return < 0
        prev_day, prev_nav, prev_spy = mark["session"], mark["nav"], benchmark["nav"]
    groups = {}
    for label in ("spy_down", "immediate_rebound"):
        subset = [row for row in months if row[label]]
        available_cash = [row["prior_close_cash_weight"] for row in subset
                          if row["prior_close_cash_weight"] is not None]
        groups[label] = dict(count=len(subset), prior_cash_count=len(available_cash),
                             mean_prior_cash_weight=(math.fsum(available_cash)/len(available_cash)
                                                     if available_cash else None))
        for key in ("portfolio_return", "spy_return"):
            groups[label][key] = nav.real(math.prod(1 + row[key] for row in subset)-1) if subset else None
    return dict(basis="EX_POST_COMPLETE_NYSE_MONTHS", cash_status=cash_status,
                cash_basis=CASH_BASIS if cash_status == "MEASURED" else None, groups=groups, months=months)


def _recovery(rows, anchor):
    """Calendar days from the deepest trough to the next close at its previous peak."""
    peak = anchor["nav"]
    worst = 0.0
    trough = None
    recovery_level = peak
    for i, row in enumerate(rows):
        peak = max(peak, row["nav"])
        drawdown = row["nav"] / peak - 1
        if drawdown < worst:
            worst, trough, recovery_level = drawdown, i, peak
    if trough is None:
        return dict(status="NO_DRAWDOWN", days=0, sessions=0)
    low = date.fromisoformat(rows[trough]["session"])
    for i in range(trough + 1, len(rows)):
        if rows[i]["nav"] >= recovery_level:
            return dict(status="RECOVERED", days=(date.fromisoformat(rows[i]["session"])-low).days,
                        sessions=i-trough)
    return dict(status="UNRECOVERED_AT_END", days=None, sessions=None,
                observed_days=(date.fromisoformat(rows[-1]["session"])-low).days)


def drawdown_durations(rows, anchor):
    """Peak-to-recovery duration on an already validated daily NAV grid.

    Equal highs reset the peak date, so flat time is not counted as underwater.
    Within the daily grid, one interval is one NYSE close. From a pre-grid
    anchor, count the actual closes after its timestamp.
    A still-open episode has a lower bound, never a fabricated recovery time.
    """
    anchor_time = nav.stamp(anchor["timestamp"])
    anchor_date = anchor_time.astimezone(ZoneInfo("America/New_York")).date()
    points = [dict(session=anchor_date.isoformat(), nav=anchor["nav"])] + rows
    peak = 0
    active = None
    episodes = []

    def finish(episode, endpoint, recovered):
        first, low = episode["peak_index"], episode["trough_index"]
        days = (date.fromisoformat(points[endpoint]["session"]) -
                date.fromisoformat(points[first]["session"])).days
        sessions = endpoint - first
        if first == 0:
            import pandas_market_calendars as mcal

            leading_schedule = mcal.get_calendar("NYSE").schedule(anchor_date, rows[0]["session"])
            # Replace the single anchor-to-first-row interval with actual closes.
            sessions += int((leading_schedule["market_close"] > anchor_time).sum()) - 1
        return dict(
            status="RECOVERED" if recovered else "UNRECOVERED_AT_END",
            peak_session=points[first]["session"], trough_session=points[low]["session"],
            recovery_session=points[endpoint]["session"] if recovered else None,
            observed_end_session=points[endpoint]["session"],
            max_dd=points[low]["nav"] / points[first]["nav"] - 1,
            days=days if recovered else None, sessions=sessions if recovered else None,
            observed_days=days, observed_sessions=sessions,
            right_censored=not recovered)

    for i, row in enumerate(points[1:], 1):
        if row["nav"] >= points[peak]["nav"]:
            if active is not None:
                episodes.append(finish(active, i, True))
                active = None
            peak = i
        elif active is None:
            active = dict(peak_index=peak, trough_index=i)
        elif row["nav"] < points[active["trough_index"]]["nav"]:
            active["trough_index"] = i
    ongoing = finish(active, len(points)-1, False) if active is not None else None
    completed = list(episodes)
    if ongoing is not None:
        episodes.append(ongoing)
    return dict(
        status="MEASURED", basis="PEAK_TO_RECOVERY_WITHIN_OBSERVED_WINDOW",
        session_basis="NYSE_CLOSES_AFTER_PEAK_THROUGH_OBSERVED_END",
        max_drawdown_tie_policy="FIRST_DEEPEST_EPISODE_ONGOING_REPORTED_SEPARATELY",
        max_drawdown_episode=min(episodes, key=lambda x: x["max_dd"]) if episodes else
            dict(status="NO_DRAWDOWN", days=0, sessions=0, right_censored=False),
        longest_completed_episode=max(completed, key=lambda x: x["days"]) if completed else None,
        ongoing_episode=ongoing, completed_episode_count=len(completed))


def _turnover(packet, book):
    """Gross buys plus sells divided by mean daily closing NAV, before fees."""
    try:
        trades = packet["trades"]
        nav.require(type(trades) is list and nav.digest(trades) == packet["manifest"]["trades_sha256"] and
                    type(packet["portfolio_report"]["trade_count"]) is int and
                    len(trades) == packet["portfolio_report"]["trade_count"], "GOAL_TRADES_ORIGINAL")
        rows = packet["portfolio"]["rows"]
        dates = {row["session"] for row in rows}
        gross = 0.0
        for trade in trades:
            value = nav.real(trade["gross_value"], positive=True)
            nav.require(trade["date"] in dates and trade["side"] in ("BUY", "SELL") and
                        math.isclose(value, nav.real(trade["quantity"], positive=True) *
                                     nav.real(trade["fill_price"], positive=True), rel_tol=1e-10), "GOAL_TRADE_FILL")
            gross += value
        mean_nav = math.fsum(row["nav"] / len(rows) for row in rows)
        ratio = nav.real(nav.real(gross) / nav.real(mean_nav, positive=True))
        return dict(status="MEASURED", gross_over_mean_daily_nav=ratio, annualized=nav.real(ratio/book["years"]))
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        return dict(status="DATA_BLOCKED", reason=str(error))


def _qqq_comparison(packet, book):
    try:
        original = packet["originals"]["qqq_total_return"]
        qqq = packet["qqq"]
        manifest = packet["manifest"]
        nav.require(nav.digest(original) == manifest["qqq_total_return_original_sha256"] and
                    original["symbol"] == "QQQ" and original["status"] == "VERIFIED" and
                    original["return_basis"] == "TOTAL_RETURN" and original["dividends_reinvested"] is True and
                    original["start_session"] == book["start_date"] and original["end_session"] == book["end_date"]
                    and original["nav_rows_sha256"] == nav.digest(qqq["rows"]), "GOAL_QQQ_ORIGINAL")
        nav.require(nav.digest(qqq["context"]) == manifest["qqq_context_sha256"] and
                    qqq["context"]["frequency"] == "daily" and qqq["context"]["grid"]["rows"] ==
                    packet["portfolio"]["context"]["grid"]["rows"], "GOAL_QQQ_GRID")
        measured = nav.calculate(qqq["rows"], qqq["context"])
        nav.require(measured["status"] == nav.COMPLETE and measured["anchor_timestamp"] == book["anchor_timestamp"]
                    and measured["starting_capital_usd"] == book["starting_capital_usd"], "GOAL_QQQ_NAV")
        return dict(status="MEASURED", total_return=measured["total_return"], cagr=measured["cagr"],
                    max_dd=measured["max_dd"], excess_cagr=book["cagr"]-measured["cagr"])
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        return dict(status="DATA_BLOCKED", reason=str(error))


def assess(packet, *, portfolio_kind, expected_manifest_sha256, end_session):
    """The external pin must come from the review of the named historical inputs."""
    base = dict(portfolio_kind=portfolio_kind, goal_policy=GOAL_POLICY,
                status_basis="MATCHED_SPY_COMPARISON_ONLY_NOT_ADMISSION",
                research_only=True, promotion_allowed=False, project_mission=None,
                research_objective=None)
    try:
        manifest = packet["manifest"]
        nav.require(nav.digest(manifest) == expected_manifest_sha256, "GOAL_MANIFEST_PIN")
        nav.require(portfolio_kind in ("main", "concentrated") and
                    manifest["portfolio_kind"] == portfolio_kind and
                    manifest["schema"] == "a5-matched-spy-goal-v1", "GOAL_PORTFOLIO")
        nav.require(manifest["benchmark"] == "SPY" and manifest["benchmark_policy"] ==
                    "BUY_AND_HOLD_DIVIDENDS_REINVESTED", "GOAL_SPY_TOTAL_RETURN")
        nav.require(manifest["start_session"] == "2021-10-01", "GOAL_REGISTERED_START")
        nav.require(manifest["end_session"] == end_session and
                    date.fromisoformat(end_session) >= date(2026, 11, 6), "GOAL_REGISTERED_END")
        portfolio_context = manifest["portfolio_context_sha256"]
        spy_context = manifest["spy_context_sha256"]
        for role, scope in (
            ("source_pit", dict(portfolio_context_sha256=portfolio_context, spy_context_sha256=spy_context,
                                point_in_time_verified=True, corporate_actions_verified=True)),
            ("closed_loop", dict(portfolio_kind=portfolio_kind, portfolio_context_sha256=portfolio_context,
                                 portfolio_report_sha256=manifest["portfolio_report_sha256"],
                                 producer="tools/run_broker_ledger_replay.py", own_fills_verified=True)),
            ("spy_total_return", dict(symbol="SPY", benchmark_policy=manifest["benchmark_policy"],
                                      spy_context_sha256=spy_context, dividends_reinvested=True)),
        ):
            key = role + "_receipt_sha256"
            receipt = packet["receipts"][key]
            required = dict(kind=role, status="VERIFIED", start_session=manifest["start_session"],
                            end_session=end_session, **scope)
            nav.require(isinstance(receipt, dict) and nav.digest(receipt) == manifest[key] and
                        all(type(receipt.get(k)) is type(v) and receipt[k] == v for k, v in required.items()),
                        "GOAL_RECEIPT_SCOPE:" + role)
            original = packet["originals"][role]
            nav.require(isinstance(original, dict) and bool(original) and
                        nav.digest(original) == receipt.get("original_sha256"), "GOAL_RECEIPT_ORIGINAL:" + role)
            if role != "closed_loop":
                nav.require(original.get("kind") == role and
                            original.get("start_session") == manifest["start_session"] and
                            original.get("end_session") == end_session, "GOAL_ORIGINAL_SCOPE:" + role)
            if role == "closed_loop":
                nav.require(nav.digest(original) == manifest["portfolio_report_sha256"], "GOAL_NATIVE_PUBLICATION")
            elif role == "spy_total_return":
                nav.require(original.get("symbol") == "SPY" and original.get("return_basis") == "TOTAL_RETURN" and
                            original.get("dividends_reinvested") is True and original.get("status") == "VERIFIED" and
                            original.get("nav_rows_sha256") == packet["spy"]["context"]["nav_ref"]["sha256"],
                            "GOAL_SPY_ORIGINAL_SERIES")
            else:
                nav.require(original.get("status") == "VERIFIED" and original.get("historical_pit_verified") is True
                            and original.get("corporate_actions_verified") is True and
                            original.get("portfolio_context_sha256") == portfolio_context and
                            original.get("spy_context_sha256") == spy_context, "GOAL_HISTORICAL_INPUTS")
        report = packet["portfolio_report"]
        for k in ("cost_bps_per_side", "cash_rate_lag_days", "cash_carry_haircut_bps", "cash_carry_day_count",
                  "cash_rate_future_use_count"):
            nav.real(report[k])
        nav.require(nav.digest(report) == manifest["portfolio_report_sha256"] and
                    report["portfolio_kind"] == portfolio_kind and report["status"] == nav.COMPLETE and
                    report["execution_status"] == "completed" and report["metric_admission_complete"] is True and
                    report["cost_basis"] == "SUPPLIED_NET_NAV_NO_SECOND_FEE" and
                    report["integer_shares"] is True and report["fill_mode"] == "next_close" and
                    report["cost_bps_per_side"] == 25 and report["cash_carry_mode"] == "risk_free_rate" and
                    report["cash_rate_source"] == "DGS3MO" and report["cash_rate_lag_days"] == 1 and
                    report["cash_carry_haircut_bps"] == 0 and report["cash_carry_day_count"] == 365 and
                    report["cash_rate_future_use_count"] == 0, "GOAL_EXECUTION_POLICY")
        # The native fixed-bps producer omits optional variable-model metadata.
        config = report.get("execution_cost_config")
        nav.require(report.get("execution_cost_mode", EXECUTION_COST_MODE_FIXED) == EXECUTION_COST_MODE_FIXED and
                    (config is None or (type(config) is dict and config.get("enabled") is False and
                                        config.get("mode") == EXECUTION_COST_MODE_FIXED)), "GOAL_VARIABLE_COST")
        coverage = report.get("target_fill_coverage")
        nav.require(type(coverage) is dict and coverage.get("execution_clock_contract") ==
                    "explicit_cutoff_exact_next_close_v1" and coverage.get("coverage_complete") is True and
                    coverage.get("chronology_safe") is True and report.get("metric_mode") == nav.MODE and
                    all(report.get(k) is v for k, v in nav.AUTHORITY.items()), "GOAL_EXACT_CLOSE_E2")
        results = {}
        for name in ("portfolio", "spy"):
            context = packet[name]["context"]
            rows = packet[name]["rows"]
            nav.require(nav.digest(context) == manifest[name + "_context_sha256"], "GOAL_CONTEXT_PIN")
            metric = nav.calculate(rows, context)
            nav.require(metric["status"] == nav.COMPLETE and metric["frequency"] == "daily" and
                        metric["starting_capital_usd"] == 100000 and
                        metric["start_date"] == manifest["start_session"] and
                        metric["end_date"] == manifest["end_session"], "GOAL_NAV_OR_WINDOW:" + name)
            results[name] = metric
        book, spy = results["portfolio"], results["spy"]
        nav.require(packet["portfolio"]["context"]["grid"]["rows"] == packet["spy"]["context"]["grid"]["rows"] and
                    book["anchor_timestamp"] == spy["anchor_timestamp"], "GOAL_UNMATCHED_GRID")
        for key in ("measurement_context_sha256", "input_rows_sha256", "total_return", "cagr", "max_dd"):
            nav.require(report[key] == book[key], "GOAL_ORIGINAL_E2_MISMATCH:" + key)
        outcome = goal_outcome(portfolio_kind, book, spy)
        try:
            monthly = monthly_diagnostics(packet)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            monthly = dict(status="DATA_BLOCKED", reason=str(error))
        return dict(base, **outcome,
                    research_objective=compounding_objective(portfolio_kind, book, spy),
                    project_mission=_project_mission(portfolio_kind, book),
                    total_return=book["total_return"], cagr=book["cagr"], max_dd=book["max_dd"],
                    spy_total_return=spy["total_return"], spy_cagr=spy["cagr"], spy_max_dd=spy["max_dd"],
                    start_session=book["start_date"], end_session=book["end_date"],
                    cost_bps_per_side=25, monthly_diagnostics=monthly,
                    spy_excess_cagr=book["cagr"]-spy["cagr"],
                    recovery_from_worst_trough=_recovery(packet["portfolio"]["rows"],
                                                         packet["portfolio"]["context"]["anchor"]),
                    spy_recovery_from_worst_trough=_recovery(packet["spy"]["rows"], packet["spy"]["context"]["anchor"]),
                    drawdown_durations=drawdown_durations(packet["portfolio"]["rows"],
                                                         packet["portfolio"]["context"]["anchor"]),
                    spy_drawdown_durations=drawdown_durations(packet["spy"]["rows"],
                                                             packet["spy"]["context"]["anchor"]),
                    turnover=_turnover(packet, book), qqq=_qqq_comparison(packet, book),
                    reviewed_manifest_sha256=expected_manifest_sha256)
    except (TypeError, KeyError, ValueError, OverflowError) as error:
        return dict(base, status="DATA_BLOCKED", reason=str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("--portfolio-kind", choices=("main", "concentrated"), required=True)
    parser.add_argument("--reviewed-manifest-sha256", required=True)
    parser.add_argument("--end-session", required=True, help="NYSE end session fixed at preflight")
    args = parser.parse_args()
    try:
        packet = nav.load_context(args.packet)
        result = assess(packet, portfolio_kind=args.portfolio_kind, end_session=args.end_session,
                        expected_manifest_sha256=args.reviewed_manifest_sha256)
    except (ValueError, OSError) as error:
        result = dict(portfolio_kind=args.portfolio_kind, status="DATA_BLOCKED", reason=str(error),
                      project_mission=None)
    print(json.dumps(result, allow_nan=False))
    return 2 if result["status"] == "DATA_BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
