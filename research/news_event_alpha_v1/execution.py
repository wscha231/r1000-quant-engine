"""P0-2 exact-next-close event labels; no portfolio, fills, learning or orders.

Prices are USD total-return indices, NOT executable raw share prices. Results
are explicitly next-close, proportional-cost event-study proxies. They are not
real fills or an integer-share/cash portfolio backtest. The supplied calendar
must separately pass source/coverage review; weekdays are never synthesized.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date
from typing import Any, Iterable

from .runtime import (
    CHECKPOINTS, HORIZONS, ContractError, canonical_bytes, checkpoint_key,
    digest, strict_bool, unique_index, utc, validate_sessions,
)

LABEL_CONTRACT = "next-exact-close-cost-proxy-p0.2"
POLICY_SCHEMA = "news-next-close-policy-p0.2"


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ContractError(code)


def number(x: Any, name: str, *, low: float = 0) -> float:
    import math
    require(type(x) in (int, float) and math.isfinite(x) and x >= low,
            "INVALID_NUMBER:" + name)
    return float(x)


def validate_policy(raw: dict[str, Any]) -> dict[str, Any]:
    require(type(raw) is dict and raw.get("schema") == POLICY_SCHEMA, "POLICY_SCHEMA")
    require(raw.get("entry") == "NEXT_EXACT_SESSION_CLOSE", "POLICY_ENTRY")
    require(raw.get("missing_entry") == "NO_FILL_NO_FORWARD_SUBSTITUTION", "POLICY_MISSING_ENTRY")
    require(raw.get("cost_basis") == "PROPORTIONAL_NOTIONAL_EACH_SIDE", "POLICY_COST_BASIS")
    require(raw.get("currency") == "USD", "POLICY_CURRENCY")
    bps = raw.get("cost_bps_per_side")
    require(type(bps) is list and bps == [25, 50, 100], "POLICY_COST_SCENARIOS")
    require(all(type(v) is int for v in bps), "POLICY_COST_TYPES")
    require(raw.get("benchmark_security_id") not in (None, ""), "POLICY_BENCHMARK")
    require(raw.get("benchmark_symbol") == "SPY", "POLICY_BENCHMARK_SYMBOL")
    require(raw.get("return_convention") == "USD_TOTAL_RETURN_INDEX", "POLICY_RETURN_CONVENTION")
    for k in ("portfolio_authority", "orders_authority", "automatic_promotion_allowed"):
        require(strict_bool(raw.get(k), k) is False, "POLICY_AUTHORITY")
    require(type(raw.get("source_contract_sha256")) is str
            and len(raw["source_contract_sha256"]) == 64
            and all(c in '0123456789abcdef' for c in raw["source_contract_sha256"]),
            "POLICY_UPSTREAM_HASH")
    return dict(raw)


class ExecutionBook:
    """Stable-security keyed, availability-aware data. Missing rows never roll."""
    def __init__(self, prices: Iterable[dict], sessions: Iterable[dict], *, as_of: str):
        self.sessions = validate_sessions(sessions)
        self.dates = [s["session"] for s in self.sessions]
        self.pos = {s: i for i, s in enumerate(self.dates)}
        self.closes = [utc(s["market_close_utc"]) for s in self.sessions]
        self.as_of = utc(as_of)
        self.data: dict[tuple[str, str], dict] = {}
        self.terminal: dict[str, list[tuple[int, dict]]] = {}
        self.feeds: set[str] = set()
        for raw in prices:
            sid = raw.get("stable_security_id")
            require(type(sid) is str and bool(sid.strip()), "PRICE_STABLE_ID")
            session = raw.get("session")
            require(session in self.pos, "PRICE_SESSION_OUTSIDE_CALENDAR")
            key = (sid, session)
            require(key not in self.data, "DUPLICATE_PRICE")
            require(raw.get("currency") == "USD", "PRICE_CURRENCY")
            require(raw.get("return_convention") == "USD_TOTAL_RETURN_INDEX", "PRICE_ADJUSTMENT")
            feed = raw.get("feed")
            require(type(feed) is str and bool(feed), "PRICE_FEED")
            self.feeds.add(feed)
            available = utc(raw.get("available_at"))
            require(available >= self.closes[self.pos[session]], "PRICE_BEFORE_CLOSE")
            require(available <= self.as_of, "PRICE_AFTER_ASOF")
            status = raw.get("status")
            require(status in {"ACTIVE", "HALTED", "DELISTED_UNKNOWN", "TERMINAL_LOSS"}, "PRICE_STATUS")
            tradable = strict_bool(raw.get("tradable"), "price.tradable")
            tri = raw.get("total_return_index")
            if status == "TERMINAL_LOSS":
                require(number(tri, "tri") == 0 and tradable is False, "TERMINAL_LOSS_VALUE")
                require(type(raw.get("terminal_evidence_id")) is str
                        and bool(raw["terminal_evidence_id"]), "TERMINAL_EVIDENCE_REQUIRED")
                self.terminal.setdefault(sid, []).append((self.pos[session], raw))
            else:
                require(tradable is (status == "ACTIVE"), "TRADABILITY_STATUS_CONFLICT")
                if tri is not None:
                    require(number(tri, "tri") > 0, "NONTERMINAL_ZERO")
                require(status != "ACTIVE" or tri is not None, "ACTIVE_PRICE_MISSING")
            self.data[key] = dict(raw)
        require(len(self.feeds) <= 1, "MIXED_PRICE_FEED")
        for sid, terminals in self.terminal.items():
            require(len(terminals) == 1, "DUPLICATE_TERMINAL_EVENT")
            pos, _ = terminals[0]
            require(not any(s == sid and self.pos[d] > pos for s, d in self.data),
                    "PRICE_AFTER_TERMINAL_REQUIRES_NEW_SECURITY")

    def row(self, sid: str, session: str) -> dict | None:
        return self.data.get((sid, session))

    def shift(self, session: str, n: int) -> str | None:
        pos = self.pos[session] + n
        return self.dates[pos] if 0 <= pos < len(self.dates) else None

    def close(self, session: str):
        return self.closes[self.pos[session]]

    def endpoint(self, sid: str, entry: str, end: str) -> tuple[str, float | None, str | None]:
        p0 = self.row(sid, entry)
        require(p0 is not None and p0["status"] == "ACTIVE", "ENTRY_NOT_EXECUTABLE")
        losses = [(i, r) for i, r in self.terminal.get(sid, [])
                  if self.pos[entry] < i <= self.pos[end]]
        if losses:
            return "TERMINAL_LOSS", -1.0, losses[0][1]["available_at"]
        p1 = self.row(sid, end)
        if p1 is None:
            return "PENDING_EXIT_PRICE", None, None
        if p1["status"] != "ACTIVE":
            return "PENDING_EXIT_" + p1["status"], None, None
        return "RESOLVED", p1["total_return_index"] / p0["total_return_index"] - 1, p1["available_at"]

    def path(self, sid: str, entry: str, end: str) -> tuple[dict, list[dict]]:
        values = [1.0]
        missing = []
        known_rows = [self.row(sid, entry)]
        base = self.row(sid, entry)["total_return_index"]
        loss = self.terminal.get(sid, [])
        terminal_pos = loss[0][0] if loss else len(self.dates) + 1
        for i in range(self.pos[entry] + 1, self.pos[end] + 1):
            if i >= terminal_pos:
                values.append(0.0)
                continue
            row = self.row(sid, self.dates[i])
            if row is None or row["status"] != "ACTIVE":
                missing.append(self.dates[i])
                continue
            values.append(row["total_return_index"] / base)
            known_rows.append(row)
        result = {"path_status": "COMPLETE" if not missing else "INCOMPLETE",
                  "path_missing_sessions": missing,
                  "max_favorable_return": None, "max_adverse_return": None,
                  "path_max_drawdown": None}
        if not missing:
            peak, mdd = 1.0, 0.0
            for v in values:
                peak = max(peak, v)
                mdd = min(mdd, v / peak - 1.0)
            result.update(max_favorable_return=max(values) - 1,
                          max_adverse_return=min(values) - 1,
                          path_max_drawdown=mdd)
        return result, [r for r in known_rows if r is not None]


def attach_executable_outcomes(
    checkpoint_rows: Iterable[dict[str, Any]],
    price_rows: Iterable[dict[str, Any]],
    market_sessions: Iterable[dict[str, Any]],
    *, as_of: str, policy: dict[str, Any],
    horizons: tuple[int, ...] = HORIZONS,
) -> list[dict[str, Any]]:
    """Label at next exact close; missing/untradeable entry is a NO_FILL case.

    NO_FILL rows remain in the intent denominator. No-fill cash opportunity
    costs need the later portfolio ledger, not an invented zero here. Endpoint
    returns survive missing intermediate prices, but path risk stays unknown.
    """
    policy = validate_policy(policy)
    require(bool(horizons) and len(set(horizons)) == len(horizons)
            and all(type(h) is int and h in HORIZONS for h in horizons), "INVALID_HORIZONS")
    book = ExecutionBook(price_rows, market_sessions, as_of=as_of)
    rows = list(checkpoint_rows)
    unique_index(rows, checkpoint_key, "checkpoint")
    benchmark = policy["benchmark_security_id"]
    out = []
    for row in rows:
        checkpoint_key(row)
        cp = row["checkpoint_session"]
        require(cp in book.pos, "CHECKPOINT_CALENDAR")
        decision = utc(row["decision_at"])
        require(book.close(cp) <= decision <= book.as_of, "DECISION_TIME")
        require(utc(row["available_at"]) <= decision, "FUTURE_EVIDENCE")
        sid = row["stable_security_id"]
        require(sid != benchmark, "BENCHMARK_IS_CANDIDATE")
        entry = book.shift(cp, 1)
        entry_row = book.row(sid, entry) if entry else None
        b0 = book.row(benchmark, entry) if entry else None
        cp_id = digest(checkpoint_key(row))
        for h in horizons:
            end = book.shift(entry, h) if entry else None
            result = {
                "checkpoint_id": cp_id, "economic_event_id": row["economic_event_id"],
                "stable_security_id": sid, "security_id": row["security_id"],
                "issuer_id": row["issuer_id"], "event_version": row["event_version"],
                "sample_origin": row["sample_origin"], "checkpoint": row["checkpoint"],
                "checkpoint_session": cp, "decision_at": row["decision_at"],
                "entry_session": entry, "outcome_end_session": end,
                "horizon": h, "label_contract": LABEL_CONTRACT,
                "execution_policy_sha256": digest(policy),
                "return_kind": "NEXT_CLOSE_EVENT_PROXY_NOT_PORTFOLIO_OR_ACTUAL_FILL",
                "outcome_status": None, "absolute_gross_return": None,
                "benchmark_gross_return": None, "gross_excess_return": None,
                "label_available_at": None, "path_available_at": None,
                "cost_scenarios": [], "path_status": "NOT_EVALUATED",
                "path_missing_sessions": [], "max_favorable_return": None,
                "max_adverse_return": None, "path_max_drawdown": None,
            }
            if entry is None:
                result["outcome_status"] = "PENDING_ENTRY_CALENDAR"
            elif decision >= book.close(entry):
                result["outcome_status"] = "NO_FILL_MISSED_ENTRY_WINDOW"
            elif book.close(entry) > book.as_of:
                result["outcome_status"] = "PENDING_ENTRY_SESSION"
            elif entry_row is None:
                result["outcome_status"] = "NO_FILL_ENTRY_PRICE_MISSING"
            elif entry_row["status"] != "ACTIVE":
                result["outcome_status"] = "NO_FILL_ENTRY_" + entry_row["status"]
            elif b0 is None or b0["status"] != "ACTIVE":
                result["outcome_status"] = "PENDING_BENCHMARK_ENTRY"
            elif end is None:
                result["outcome_status"] = "PENDING_HORIZON_CALENDAR"
            elif book.close(end) > book.as_of:
                result["outcome_status"] = "PENDING_HORIZON"
            else:
                status, r, stock_at = book.endpoint(sid, entry, end)
                bs, br, benchmark_at = book.endpoint(benchmark, entry, end)
                require(bs != "TERMINAL_LOSS", "BENCHMARK_TERMINAL_UNSUPPORTED")
                if r is None:
                    result["outcome_status"] = status
                elif br is None:
                    result["outcome_status"] = "PENDING_BENCHMARK_EXIT"
                else:
                    result.update(outcome_status=status, absolute_gross_return=r,
                                  benchmark_gross_return=br, gross_excess_return=r-br)
                    label_at = max(utc(entry_row["available_at"]), utc(b0["available_at"]),
                                   utc(stock_at), utc(benchmark_at), book.close(end))
                    result["label_available_at"] = label_at.isoformat()
                    path, path_rows = book.path(sid, entry, end)
                    result.update(path)
                    result["path_available_at"] = max([label_at] + [utc(x["available_at"]) for x in path_rows]).isoformat()
                    for bps in policy["cost_bps_per_side"]:
                        cost = bps / 10000
                        net = (1 + r) * (1 - cost) / (1 + cost) - 1
                        benchmark_net = (1 + br) * (1 - cost) / (1 + cost) - 1
                        result["cost_scenarios"].append({
                            "bps_per_side": bps,
                            "absolute_net_return": net,
                            "benchmark_matched_cost_net_return": benchmark_net,
                            "net_excess_vs_gross_benchmark": net-br,
                            "net_excess_vs_matched_cost_benchmark": net-benchmark_net,
                            "cost_return_drag": r-net,
                        })
            result["outcome_id"] = digest((cp_id, h, LABEL_CONTRACT, result["execution_policy_sha256"]))
            result["outcome_sha256"] = digest(result)
            out.append(result)
    unique_index(out, lambda r: r["outcome_id"], "executable outcome")
    return out


def mature_training_rows(outcomes: Iterable[dict], decision_at: str) -> list[dict]:
    """For a later consumer: full labels must actually be available, not just end."""
    at = utc(decision_at)
    return [r for r in outcomes
            if r.get("outcome_status") in {"RESOLVED", "TERMINAL_LOSS"}
            and r.get("label_contract") == LABEL_CONTRACT
            and r.get("label_available_at")
            and utc(r["label_available_at"]) < at]
