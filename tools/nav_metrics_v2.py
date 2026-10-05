"""Strict opt-in research NAV measurement; no accounting, prices or authority.

The supplied grid, anchor, RF and flow references bind explicit caller evidence.
Hash agreement is structural validation, not producer or historical PIT admission.
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
import stat
import inspect
from contextvars import ContextVar
from functools import wraps
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath
from zoneinfo import ZoneInfo

MODE = "nav_metrics_v2_research"
COMPLETE = "research_completed"
BLOCKED = "research_blocked"
NAMESPACE = "nav_metrics_v2_research"
CURVE_FILE = "equity_curve.research_v2.csv"
METRICS_FILE = "metrics.research_v2.json"
MAX_ROWS = 100000
MAX_BYTES = 32 * 1024 * 1024
MAX_DEPTH = 14
AUTHORITY = dict(research_only=True, valid_for_production=False,
                 production_activation_allowed=False, fullrun_allowed=False,
                 eligible_for_selector=False, historical_pit_certified=False)
METRIC_FIELDS = ("cagr", "max_dd", "total_return", "sharpe_raw", "sharpe_excess_rf",
                 "volatility_raw", "ending_capital_usd", "years")


class MetricError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise MetricError(reason)


def stamp(value):
    require(type(value) is str and len(value) <= 64, "TIMESTAMP_TYPE")
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MetricError("TIMESTAMP_FORMAT") from None
    require(out.tzinfo is not None and out.utcoffset() is not None, "TIMESTAMP_NAIVE")
    return out.astimezone(timezone.utc)


def real(value, positive=False):
    require(isinstance(value, numbers.Real) and not isinstance(value, bool), "NUMBER_TYPE")
    try:
        out = float(value)
    except (OverflowError, ValueError):
        raise MetricError("NUMBER_NONFINITE") from None
    require(math.isfinite(out), "NUMBER_NONFINITE")
    require(not positive or out > 0, "NAV_NONPOSITIVE_ZERO_UNSUPPORTED")
    return out


def encoded(value):
    nodes = 0
    byte_count = 0
    def charge(n):
        nonlocal byte_count
        byte_count += n
        require(byte_count <= MAX_BYTES, "RESOURCE_BYTES")
    def string(v):
        # At least one JSON byte per character; escape bounded chunks before allocation.
        require(len(v) <= MAX_BYTES, "RESOURCE_BYTES")
        charge(2)
        for start in range(0, len(v), 4096):
            charge(len(json.dumps(v[start:start+4096]).encode("utf-8")) - 2)
    def walk(v, depth):
        nonlocal nodes
        nodes += 1
        require(nodes <= MAX_ROWS * 20 and depth <= MAX_DEPTH, "RESOURCE_TREE")
        require(type(v) in (dict, list, str, int, float, bool, type(None)), "JSON_TYPE")
        if type(v) is dict:
            require(all(type(k) is str for k in v), "JSON_KEY")
            charge(2 + max(0, len(v)-1) + len(v))
            for key, item in v.items():
                string(key); walk(item, depth + 1)
        elif type(v) is list:
            charge(2 + max(0, len(v)-1))
            for item in v: walk(item, depth + 1)
        elif type(v) is str:
            string(v)
        elif type(v) is float:
            require(math.isfinite(v), "NUMBER_NONFINITE")
            charge(len(json.dumps(v)))
        else:
            if type(v) is int:
                require(v.bit_length() <= MAX_BYTES * 3, "RESOURCE_BYTES")
            try:
                charge(len(json.dumps(v)))
            except ValueError:
                raise MetricError("RESOURCE_INTEGER") from None
    walk(value, 0)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    require(len(raw) <= MAX_BYTES, "RESOURCE_BYTES")
    return raw


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def _windows_reserved(text):
    # Native path parsing and a small device-name fallback also work on Python3.12.
    path = PureWindowsPath(text)
    if text.startswith(("\\\\.\\", "\\\\?\\")):
        return True
    reserved = getattr(os.path, "isreserved", None)
    if reserved is not None:
        return reserved(text)
    names = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    names.update(prefix + digit for prefix in ("COM", "LPT") for digit in "123456789\u00b9\u00b2\u00b3")
    return any(part.endswith((".", " ")) or any(ord(ch)<32 or ch in ':*?"<>|' for ch in part)
               or part.partition(".")[0].rstrip(" ").upper() in names
               for part in path.parts if part != path.anchor)


def load_context(path):
    """Read only a stable regular file, bounded before open/read and JSON allocation."""
    path = Path(path)
    if os.name == "nt":
        text = str(path)
        require(not _windows_reserved(text), "CONTEXT_NOT_REGULAR")
    fd = None
    try:
        before = os.lstat(path)
        require(stat.S_ISREG(before.st_mode), "CONTEXT_NOT_REGULAR")
        require(before.st_size <= MAX_BYTES, "RESOURCE_BYTES")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        opened = os.fstat(fd)
        require(stat.S_ISREG(opened.st_mode), "CONTEXT_NOT_REGULAR")
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        require(identity(before) == identity(opened), "CONTEXT_FILE_CHANGED")
        require(opened.st_size <= MAX_BYTES, "RESOURCE_BYTES")
        chunks, length = [], 0
        while length <= MAX_BYTES:
            part = os.read(fd, min(65536, MAX_BYTES + 1 - length))
            if not part:
                break
            chunks.append(part); length += len(part)
        require(length <= MAX_BYTES, "RESOURCE_BYTES")
        require(length == opened.st_size and identity(os.fstat(fd)) == identity(opened), "CONTEXT_FILE_CHANGED")
        require(identity(os.lstat(path)) == identity(opened), "CONTEXT_FILE_CHANGED")
        raw = b"".join(chunks)
    except OSError:
        raise MetricError("CONTEXT_INPUT_IO") from None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                raise MetricError("CONTEXT_INPUT_IO") from None
    def unique(pairs):
        obj = {}
        for k, v in pairs:
            require(k not in obj, "JSON_DUPLICATE")
            obj[k] = v
        return obj
    # Match encoded's value/container budget before the native decoder allocates
    # any tree. Object keys consume bytes, but are not value nodes. This scanner
    # only bounds allocation; native JSON still decides syntax/duplicate keys.
    stack, nodes, quoted, escaped, atom, previous = [], 0, False, False, False, None
    for ch in raw:
        if quoted:
            if escaped: escaped = False
            elif ch == 92: escaped = True
            elif ch == 34: quoted = False; previous = ch
            continue
        if ch in (32, 9, 10, 13):
            atom = False
            continue
        if ch in (44, 58, 125, 93):
            atom = False
            if ch in (125, 93) and stack:
                stack.pop()
            previous = ch
            continue
        if ch == 34:
            key = bool(stack and stack[-1] == 123 and previous in (123, 44))
            if not key:
                nodes += 1
                require(len(stack) <= MAX_DEPTH, "RESOURCE_TREE")
            quoted = True; atom = False
        elif ch in (123, 91):
            nodes += 1
            require(len(stack) <= MAX_DEPTH, "RESOURCE_TREE")
            stack.append(ch); atom = False
            previous = ch
        elif not atom:
            nodes += 1
            require(len(stack) <= MAX_DEPTH, "RESOURCE_TREE")
            atom = True
        require(nodes <= MAX_ROWS * 20, "RESOURCE_TREE")
    try:
        obj = json.loads(raw, object_pairs_hook=unique,
                         parse_constant=lambda _: (_ for _ in ()).throw(MetricError("NUMBER_NONFINITE")))
        encoded(obj)
    except MetricError:
        raise
    except (UnicodeError, RecursionError, json.JSONDecodeError, ValueError):
        raise MetricError("CONTEXT_JSON") from None
    require(type(obj) is dict, "CONTEXT_TYPE")
    return obj


def reference(ref, value, cutoff):
    require(type(ref) is dict and set(ref) == {"identity", "sha256", "available_at"}, "REFERENCE_FIELDS")
    require(type(ref["identity"]) is str and 0 < len(ref["identity"]) <= 256, "REFERENCE_IDENTITY")
    require(ref["sha256"] == digest(value), "REFERENCE_HASH")
    require(stamp(ref["available_at"]) <= cutoff, "REFERENCE_FUTURE")


def blocked(reason, label="full", row_count=None):
    return dict(status=BLOCKED, reason=reason, metric_mode=MODE, label=label,
                input_row_count=row_count, metric_admission_complete=False,
                **{name: None for name in METRIC_FIELDS}, **AUTHORITY)


def artifact_name(name):
    """Every research export differs from names used by legacy account readers."""
    path = Path(name)
    return path.stem + ".research_v2" + path.suffix


_io_state = ContextVar("nav_research_io", default=None)


def research_io_active():
    return _io_state.get() is not None


def research_output_kind(path):
    """Only a real missing leaf is absent; permission/IO failures must propagate."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISREG(info.st_mode):
        return "file"
    if stat.S_ISLNK(info.st_mode):
        return "symlink"
    return "other"


def authorize_research_cleanup(directory, names, protected, price_cache):
    """Called only after the complete caller input-cone preflight has passed."""
    state = _io_state.get()
    if state is not None:
        state.update(directory=Path(directory), names=tuple(names), protected=set(protected),
                     price_cache=Path(price_cache), cleanup_authorized=True)


def observe_research_publication(directory, names, protected, price_cache):
    """Retain the known generation for disclosure before any cleanup is authorized."""
    state = _io_state.get()
    if state is not None:
        state.update(directory=Path(directory), names=tuple(names), protected=set(protected),
                     price_cache=Path(price_cache))


def refused_research_publication(reason, directory, names, protected=()):
    """Disclose retained/unknown leaves without mutating a refused input namespace."""
    remaining, errors, refused = [], [], []
    for name in names:
        path = Path(directory) / name
        try:
            if research_output_kind(path) is not None:
                remaining.append(name)
            if path.resolve() in protected:
                refused.append(name)
        except OSError as exc:
            if name not in remaining:
                remaining.append(name)
            errors.append(dict(name=name, error_type=type(exc).__name__, errno=exc.errno))
    result = blocked(reason)
    result.update(current_publication_complete=False, cleanup_complete=False,
                  uncleared_generated_outputs=remaining, cleanup_refused_inputs=refused,
                  retained_output_errors=errors)
    return result


def research_io_guard(context_argument):
    """Bound expected OS failures for opt-in callers; legacy/programming errors propagate."""
    def decorate(fn):
        signature = inspect.signature(fn)
        @wraps(fn)
        def call(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            if (bound.arguments.get(context_argument) is None
                    and not bound.arguments.get("load_measurement_context_from_path", False)):
                return fn(*args, **kwargs)
            state = {"cleanup_authorized": False}
            token = _io_state.set(state)
            try:
                return fn(*args, **kwargs)
            except OSError as exc:
                remaining, refused = [], []
                cleanup_complete = bool(state["cleanup_authorized"])
                if cleanup_complete:
                    try:
                        directory = state["directory"]
                        if directory.resolve().is_relative_to(state["price_cache"].resolve()):
                            cleanup_complete = False
                        else:
                            for name in state["names"]:
                                path = directory / name
                                try:
                                    if path.resolve() in state["protected"]:
                                        refused.append(name); cleanup_complete = False
                                    else:
                                        kind = research_output_kind(path)
                                        if kind in ("file", "symlink"):
                                            path.unlink()
                                        elif kind is not None:
                                            remaining.append(name); cleanup_complete = False
                                except OSError:
                                    remaining.append(name); cleanup_complete = False
                    except OSError:
                        cleanup_complete = False
                result = blocked("RESEARCH_IO_FAILURE")
                if not cleanup_complete and "directory" in state:
                    result = refused_research_publication("RESEARCH_IO_FAILURE", state["directory"],
                                                         state["names"], state["protected"])
                    remaining = list(dict.fromkeys(remaining + result["uncleared_generated_outputs"]))
                    refused = list(dict.fromkeys(refused + result["cleanup_refused_inputs"]))
                result.update(current_publication_complete=False, io_error_type=type(exc).__name__,
                              io_error_errno=exc.errno, cleanup_complete=cleanup_complete,
                              uncleared_generated_outputs=remaining, cleanup_refused_inputs=refused)
                # Reader-local admission attaches finite codes, never source text.
                formats = {
                    "CSV": {"UnicodeDecodeError", "ParserError", "EmptyDataError", "DateParseError"},
                    "JSON": {"UnicodeDecodeError", "JSONDecodeError", "JSONRootType", "JSONAuditType"},
                    "PARQUET": {"ArrowInvalid", "UnicodeDecodeError", "JSONDecodeError", "DateParseError", "PandasAttrsShape"},
                }
                reasons = {"SELECTED_INPUT_DECODE", "SELECTED_INPUT_DATE",
                           "SELECTED_INPUT_JSON_OBJECT", "SELECTED_INPUT_JSON_AUDIT_OBJECT", "SELECTED_INPUT_PARQUET_ATTRS"}
                input_format = getattr(exc, "selected_input_format", None)
                cause = getattr(exc, "selected_input_cause", None)
                reason = getattr(exc, "selected_input_reason", None)
                if (isinstance(input_format, str) and isinstance(cause, str) and isinstance(reason, str)
                        and cause in formats.get(input_format, ()) and reason in reasons):
                    result.update(selected_input_format=input_format, selected_input_cause=cause,
                                  selected_input_reason=reason)
                return result
            finally:
                _io_state.reset(token)
        return call
    return decorate


def _statistics(values, annualization):
    if len(values) < 2:
        return None, None, "INSUFFICIENT_SAMPLE"
    mean = math.fsum(values) / len(values)
    variance = math.fsum((x - mean) ** 2 for x in values) / (len(values) - 1)
    require(math.isfinite(mean) and math.isfinite(variance), "DERIVED_NONFINITE")
    if variance == 0:
        return None, 0.0, "ZERO_VARIANCE"
    sigma = math.sqrt(variance)
    sharpe = mean / sigma * math.sqrt(annualization)
    vol = sigma * math.sqrt(annualization)
    require(math.isfinite(sharpe) and math.isfinite(vol), "DERIVED_NONFINITE")
    return sharpe, vol, None


def calculate(rows, context, *, label="full"):
    """Measure untouched rows against an independently supplied exact grid."""
    try:
        return _calculate(rows, context, label)
    except MetricError as exc:
        return blocked(str(exc), label, len(rows) if type(rows) is list else None)
    except (ArithmeticError, RecursionError):
        return blocked("DERIVED_ARITHMETIC_OR_RESOURCE", label)
    except (KeyError, TypeError, ValueError):
        return blocked("CONTEXT_OR_ROW_SHAPE", label)


def _calculate(rows, c, label):
    require(type(c) is dict and set(c) == {"schema", "frequency", "cutoff", "grid", "anchor",
                                         "nav_ref", "risk_free", "external_flows"}, "CONTEXT_FIELDS")
    encoded(c); encoded(rows)
    require(c["schema"] == "nav-measurement-context-v2", "CONTEXT_SCHEMA")
    require(c["frequency"] in ("daily", "weekly"), "FREQUENCY")
    annualization = 252 if c["frequency"] == "daily" else 52
    cutoff = stamp(c["cutoff"])
    grid = c["grid"]
    require(type(grid) is dict and set(grid) == {"kind", "rows", "ref"}, "GRID_FIELDS")
    require(grid["kind"] == "INDEPENDENT_NYSE_REGULAR_CLOSE_GRID", "GRID_KIND")
    points = grid["rows"]
    require(type(points) is list and 0 < len(points) <= MAX_ROWS, "GRID_BUDGET")
    reference(grid["ref"], points, cutoff)
    times, sessions = [], set()
    for point in points:
        require(type(point) is dict and set(point) == {"session", "timestamp"}, "GRID_ROW_FIELDS")
        require(type(point["session"]) is str, "SESSION_TYPE")
        session = date.fromisoformat(point["session"])
        t = stamp(point["timestamp"])
        ny = t.astimezone(ZoneInfo("America/New_York"))
        require(ny.date() == session, "REGULAR_CLOSE_CLOCK")
        require(t <= cutoff, "GRID_FUTURE")
        require(not times or t > times[-1], "GRID_ORDER_OR_DUPLICATE")
        require(session not in sessions, "GRID_SESSION_DUPLICATE")
        times.append(t); sessions.add(session)
    require(stamp(grid["ref"]["available_at"]) <= times[0], "GRID_NOT_INDEPENDENTLY_AVAILABLE")
    # Compare the declared source grid with the native offline calendar, never prices.
    # Weekly observations may include a current partial week; each must be an actual close.
    import pandas_market_calendars as mcal
    require((times[-1] - times[0]).days <= 366 * 200, "GRID_TIME_BUDGET")
    schedule = mcal.get_calendar("NYSE").schedule(start_date=points[0]["session"], end_date=points[-1]["session"])
    closes = {d.date().isoformat(): t.to_pydatetime().astimezone(timezone.utc)
              for d, t in schedule["market_close"].items()}
    require(all(closes.get(p["session"]) == t for p, t in zip(points, times)), "CALENDAR_CLOSE_MISMATCH")
    if c["frequency"] == "daily":
        require(list(closes) == [p["session"] for p in points], "CALENDAR_SESSION_GAP")
    require(type(rows) is list and len(rows) == len(points), "ROW_GRID_LENGTH")
    values = []
    for row, point, t in zip(rows, points, times):
        require(type(row) is dict and set(row) == {"session", "timestamp", "nav"}, "NAV_ROW_FIELDS")
        require(row["session"] == point["session"] and stamp(row["timestamp"]) == t, "ROW_GRID_MISMATCH")
        values.append(real(row["nav"], positive=True))
    reference(c["nav_ref"], rows, cutoff)
    require(stamp(c["nav_ref"]["available_at"]) >= times[-1], "NAV_RECEIPT_PRECEDES_VALUATION")
    anchor = c["anchor"]
    require(type(anchor) is dict and set(anchor) == {"kind", "timestamp", "nav", "ref"}, "ANCHOR_FIELDS")
    require(anchor["kind"] in ("PREFILL", "OOS_PREDECESSOR"), "ANCHOR_KIND")
    anchor_t, anchor_nav = stamp(anchor["timestamp"]), real(anchor["nav"], positive=True)
    require(anchor_t < times[0], "ANCHOR_NOT_BEFORE_GRID")
    reference(anchor["ref"], {k:v for k,v in anchor.items() if k != "ref"}, cutoff)
    require(stamp(anchor["ref"]["available_at"]) <= anchor_t, "ANCHOR_NOT_INDEPENDENTLY_AVAILABLE")
    flows = c["external_flows"]
    require(type(flows) is dict and set(flows) == {"kind", "start", "end", "events", "ref"}, "FLOW_FIELDS")
    require(flows["kind"] == "ZERO_EXTERNAL_FLOW_ONLY", "FLOW_UNSUPPORTED")
    require(stamp(flows["start"]) == anchor_t and stamp(flows["end"]) == times[-1], "FLOW_SCOPE")
    require(type(flows["events"]) is list and len(flows["events"]) <= MAX_ROWS, "FLOW_BUDGET")
    for event in flows["events"]:
        require(type(event) is dict and set(event) == {"timestamp", "amount"}, "FLOW_EVENT_FIELDS")
        require(anchor_t <= stamp(event["timestamp"]) <= times[-1] and real(event["amount"]) == 0, "NONZERO_OR_UNTIMED_FLOW")
    reference(flows["ref"], {k:v for k,v in flows.items() if k != "ref"}, cutoff)
    require(stamp(flows["ref"]["available_at"]) >= times[-1], "FLOW_RECEIPT_PRECEDES_SCOPE_END")
    rf = c["risk_free"]
    require(type(rf) is dict and set(rf) == {"kind", "rows", "ref"}, "RF_FIELDS")
    require(rf["kind"] == "ACTUAL_INTERVAL_SIMPLE_RETURN", "RF_QUOTE_UNSUPPORTED")
    require(type(rf["rows"]) is list and len(rf["rows"]) == len(rows), "RF_ALIGNMENT")
    reference(rf["ref"], rf["rows"], cutoff)
    rf_available = stamp(rf["ref"]["available_at"])
    rf_values, previous_t = [], anchor_t
    for item, t in zip(rf["rows"], times):
        require(type(item) is dict and set(item) == {"start", "end", "value", "available_at"}, "RF_ROW_FIELDS")
        require(stamp(item["start"]) == previous_t and stamp(item["end"]) == t, "RF_ALIGNMENT")
        row_available = stamp(item["available_at"])
        require(row_available <= t, "RF_FUTURE")
        require(row_available <= rf_available, "RF_RECEIPT_PRECEDES_ROW_AVAILABILITY")
        value = real(item["value"])
        require(value > -1, "RF_RETURN_DOMAIN")
        rf_values.append(value); previous_t = t
    years = (times[-1] - anchor_t).total_seconds() / (365.25 * 86400)
    require(years > 0 and math.isfinite(years), "ELAPSED_TIME")
    previous, peak = anchor_nav, anchor_nav
    returns, drawdowns = [], []
    for value in values:
        ret = value / previous - 1
        peak = max(peak, value)
        drawdown = value / peak - 1
        require(math.isfinite(ret) and math.isfinite(drawdown), "DERIVED_NONFINITE")
        returns.append(ret); drawdowns.append(drawdown); previous = value
    ratio = values[-1] / anchor_nav
    require(ratio > 0 and math.isfinite(ratio), "DERIVED_NONFINITE_OR_UNDERFLOW")
    cagr = ratio ** (1 / years) - 1
    require(math.isfinite(ratio) and math.isfinite(cagr), "DERIVED_NONFINITE")
    raw_sharpe, raw_vol, raw_reason = _statistics(returns, annualization)
    excess = [r - f for r, f in zip(returns, rf_values)]
    excess_sharpe, _, excess_reason = _statistics(excess, annualization)
    out = dict(status=COMPLETE, metric_mode=MODE, metric_admission_complete=True, label=label,
               input_row_count=len(rows), days=len(rows), frequency=c["frequency"],
               start_date=points[0]["session"], end_date=points[-1]["session"],
               anchor_timestamp=anchor_t.isoformat(), ending_timestamp=times[-1].isoformat(),
               starting_capital_usd=anchor_nav, ending_capital_usd=values[-1],
               years=years, total_return=ratio - 1, cagr=cagr, max_dd=min(drawdowns),
               first_interval_return=returns[0], interval_returns=returns,
               sharpe_raw=raw_sharpe, sharpe_excess_rf=excess_sharpe, volatility_raw=raw_vol,
               statistic_reasons=dict(sharpe_raw=raw_reason, sharpe_excess_rf=excess_reason),
               annualization=annualization, standard_deviation_ddof=1, cost_basis="SUPPLIED_NET_NAV_NO_SECOND_FEE",
               measurement_context_sha256=digest(c), input_rows_sha256=digest(rows),
               producer_authentication="NOT_CERTIFIED_BY_HASH_AGREEMENT", **AUTHORITY)
    encoded(out)
    return out


def frame_rows(frame, *, date_column, nav_column, valuation_binding=None):
    """Bind actual caller sessions to a separate valuation-time receipt, never a price union."""
    require(len(frame) <= MAX_ROWS, "ROW_BUDGET")
    # The caller may carry arbitrarily wide auxiliary diagnostics. Consume only
    # these two/three columns, and admit their cells before allocating records.
    require(date_column != nav_column and nav_column != "valuation_time_utc", "FRAME_COLUMN_FIELDS")
    columns = [date_column, nav_column]
    if "valuation_time_utc" in frame.columns and date_column != "valuation_time_utc":
        columns.append("valuation_time_utc")
    require(all(sum(c == name for c in frame.columns) == 1 for name in columns), "FRAME_COLUMN_FIELDS")
    byte_count = 2
    for values in zip(*(frame[name] for name in columns)):
        session, value = values[:2]
        require(type(session) is str or isinstance(session, (date, datetime)), "SESSION_TYPE")
        if type(session) is str:
            require(len(session) <= 10, "SESSION_FORMAT")
        real(value, True)
        if len(values) == 3:
            stamp(values[2])
        # A bounded per-row canonical estimate avoids copying large cell values.
        byte_count += len(encoded([str(session), real(value, True), values[2] if len(values) == 3 else None])) + 1
        require(byte_count <= MAX_BYTES, "RESOURCE_BYTES")
    records = frame[columns].to_dict("records")
    bindings = None
    if valuation_binding is not None:
        require(type(valuation_binding) is dict and set(valuation_binding) == {"rows", "ref", "cutoff"}, "VALUATION_BINDING_FIELDS")
        bindings = valuation_binding["rows"]
        require(type(bindings) is list and len(bindings) == len(records), "VALUATION_BINDING_LENGTH")
        binding_cutoff = stamp(valuation_binding["cutoff"])
        reference(valuation_binding["ref"], bindings, binding_cutoff)
        receipt_available = stamp(valuation_binding["ref"]["available_at"])
        for point in bindings:
            require(type(point) is dict and set(point) == {"session", "timestamp"}, "VALUATION_BINDING_SESSION")
            require(stamp(point["timestamp"]) <= receipt_available <= binding_cutoff, "VALUATION_BINDING_POINT_FUTURE")
    rows = []
    for i, record in enumerate(records):
        session = record[date_column]
        if type(session) is not str:
            # Native generated date values carry only session identity, never an inferred close.
            require(isinstance(session, (date, datetime)), "SESSION_TYPE")
            session = session.date().isoformat() if isinstance(session, datetime) else session.isoformat()
        date.fromisoformat(session)
        if bindings is not None:
            point = bindings[i]
            require(type(point) is dict and set(point) == {"session", "timestamp"} and point["session"] == session,
                    "VALUATION_BINDING_SESSION")
            timestamp = point["timestamp"]
            if "valuation_time_utc" in record:
                require(stamp(record["valuation_time_utc"]) == stamp(timestamp), "VALUATION_CLOCK_CONFLICT")
        else:
            require("valuation_time_utc" in record, "VALUATION_TIME_UNBOUND")
            timestamp = record["valuation_time_utc"]
        nav = record[nav_column]
        rows.append(dict(session=session, timestamp=timestamp, nav=nav))
    return rows


def calculate_frame(frame, context, *, date_column="date", nav_column="equity_usd",
                    valuation_binding=None, date_range=None, label="full", expected_frequency="daily"):
    try:
        require(type(context) is dict and context.get("frequency") == expected_frequency, "CALLER_FREQUENCY")
        if valuation_binding is not None:
            require(stamp(valuation_binding["cutoff"]) <= stamp(context["cutoff"]), "VALUATION_BINDING_FUTURE")
        rows = frame_rows(frame, date_column=date_column, nav_column=nav_column, valuation_binding=valuation_binding)
        # Bind the entire admitted caller receipt before any window slicing.
        # Rows alone omit reference identity, availability and receipt cutoff.
        provenance = None if valuation_binding is None else dict(
            sha256=digest(valuation_binding), ref=dict(valuation_binding["ref"]),
            cutoff=valuation_binding["cutoff"])
        require(label not in ("oos", "oos2") or date_range is not None, "OOS_PREDECESSOR_MISSING")
        if date_range is not None:
            lo = date.fromisoformat(date_range[0]) if date_range[0] else None
            hi = date.fromisoformat(date_range[1]) if date_range[1] else None
            selected = [i for i,r in enumerate(rows) if (lo is None or date.fromisoformat(r["session"]) >= lo)
                        and (hi is None or date.fromisoformat(r["session"]) <= hi)]
            require(bool(selected), "WINDOW_EMPTY")
            first = selected[0]
            require(label not in ("oos", "oos2") or first > 0, "OOS_PREDECESSOR_MISSING")
            if first:
                predecessor = rows[first-1]
                anchor = context["anchor"]
                require(anchor["kind"] == "OOS_PREDECESSOR" and stamp(anchor["timestamp"]) == stamp(predecessor["timestamp"])
                        and real(anchor["nav"], True) == real(predecessor["nav"], True), "OOS_PREDECESSOR_MISMATCH")
            rows = [rows[i] for i in selected]
        result = calculate(rows, context, label=label)
        if result["status"] == COMPLETE and provenance is not None:
            result["valuation_binding_provenance"] = provenance
            encoded(result)
        return result
    except MetricError as exc:
        return blocked(str(exc), label)
    except (KeyError, TypeError, ValueError, ArithmeticError, RecursionError):
        return blocked("CALLER_CONTEXT_OR_ROW_SHAPE", label)

