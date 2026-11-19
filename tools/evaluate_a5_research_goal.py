"""Assess one registered A5 research portfolio against a matched SPY total-return curve."""
import argparse
import json
from datetime import date
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import nav_metrics_v2 as nav


def assess(packet, *, portfolio_kind, expected_manifest_sha256, end_session):
    """The external pin must come from the review of the named historical inputs."""
    base = dict(portfolio_kind=portfolio_kind, research_only=True, promotion_allowed=False)
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
                    report["cash_rate_future_use_count"] == 0 and report["execution_cost_mode"] == "fixed_bps", "GOAL_EXECUTION_POLICY")
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
        passed_return = book["cagr"] >= .40
        passed_drawdown = abs(book["max_dd"]) <= abs(spy["max_dd"])
        return dict(base, status="PASS" if passed_return and passed_drawdown else "MISS",
                    total_return=book["total_return"], cagr=book["cagr"], max_dd=book["max_dd"],
                    spy_total_return=spy["total_return"], spy_cagr=spy["cagr"], spy_max_dd=spy["max_dd"],
                    start_session=book["start_date"], end_session=book["end_date"],
                    cost_bps_per_side=25, return_goal_met=passed_return, drawdown_goal_met=passed_drawdown,
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
        result = dict(portfolio_kind=args.portfolio_kind, status="DATA_BLOCKED", reason=str(error))
    print(json.dumps(result, allow_nan=False))
    return 2 if result["status"] == "DATA_BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
