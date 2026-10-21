#!/usr/bin/env python3
"""macro_daily_snapshot - Phase 17 v3 Layer 12 daily macro pulse.

Computes daily changes in macro inputs used by regime_state, including VIX,
SPY trend, SPY 3m return, high-yield OAS, and breadth. It can post a concise
Telegram digest when indicators cross regime boundaries.

Outputs
-------
    cloud_results/macro_daily/snapshot_YYYY-MM-DD.json
    cloud_results/macro_daily/latest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "cloud_results" / "macro_daily"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from tools import daily_crisis_report_clock as clock

SNAPSHOT_SCHEMA = "macro-daily-research-snapshot-v2"
REGIMES = frozenset({"bear", "deep_bear", "neutral", "bull", "strong_bull"})

VIX_TICKER = "^VIX"
SPY_TICKER = "SPY"

# Regime thresholds matching r1000_features.compute_regime_state_classifier
THRESHOLDS = {
    "vix_hot": 25.0,             # raw VIX level above this = caution
    "vix_extreme": 35.0,
    "spy_3m_bear": -0.03,
    "spy_3m_deep_bear": -0.10,
    "spy_3m_bull": 0.05,
    "spy_3m_strong_bull": 0.10,
    "ma200_breach_pct": 0.0,     # SPY/MA200 crossing
}


def fetch_yfinance_history(ticker: str, days: int = 260):
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        end = datetime.now()
        start = end - timedelta(days=int(days * 1.7))   # buffer for weekends
        df = yf.Ticker(ticker).history(start=start.strftime("%Y-%m-%d"),
                                       end=end.strftime("%Y-%m-%d"),
                                       auto_adjust=True)
        if df.empty:
            return None
        collected = clock.trusted_now().isoformat()
        df.attrs["macro_source_clock"] = dict(
            source_id="yfinance:"+ticker, observation_date=df.index[-1].date().isoformat(),
            collected_at_utc=collected, available_at_utc=collected,
            published_at_utc=None, availability_basis="COLLECTION_ONLY",
            unit="USD" if ticker == SPY_TICKER else "INDEX_POINTS",
            adjustment="AUTO_ADJUSTED", payload_kind="DERIVED_PROVIDER_FRAME",
            payload_sha256=hashlib.sha256(df.to_csv().encode("utf-8")).hexdigest())
        return df
    except Exception:
        return None


def fetch_fred_series(series_id: str, api_key: str | None) -> float | None:
    """Keep the existing scalar API; source metadata is available separately."""
    return fetch_fred_observation(series_id, api_key)["value"]


def fetch_fred_observation(series_id: str, api_key: str | None) -> dict:
    record = dict(series_id=series_id, value=None, observation_date=None,
                  realtime_start=None, realtime_end=None, collected_at_utc=None,
                  published_at_utc=None, availability_status="UNKNOWN",
                  vintage_kind="CURRENT_VINTAGE_NOT_HISTORICAL_PIT", status="UNAVAILABLE")
    if not api_key:
        return record
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={api_key}&file_type=json"
        f"&sort_order=desc&limit=1"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            raw = resp.read()
            record["collected_at_utc"] = datetime.now(timezone.utc).isoformat()
        data = json.loads(raw.decode())
        record["response_sha256"] = hashlib.sha256(raw).hexdigest()
        record["response_realtime_start"] = data.get("realtime_start")
        record["response_realtime_end"] = data.get("realtime_end")
        for obs in data.get("observations", []):
            v = obs.get("value")
            if v not in (".", "", None):
                record.update(value=float(v), observation_date=obs.get("date"),
                              realtime_start=obs.get("realtime_start"), realtime_end=obs.get("realtime_end"),
                              status="COLLECTED")
                return record
    except Exception:
        return record
    return record


def compute_snapshot() -> dict:
    # Obtain the decision clock AFTER retrieval; collection is never backdated
    # to observation/market close or claimed as original publication.
    spy = fetch_yfinance_history(SPY_TICKER)
    vix = fetch_yfinance_history(VIX_TICKER, days=120)
    decision = clock.trusted_now()
    snap = _empty_snapshot(decision)
    errors = []
    try:
        session = clock.completed_session_clock(decision.isoformat())
        snap.update(report_session=session["expected_session"],
                    session_close_utc=session["session_close_utc"])
        for ticker, frame, count in ((SPY_TICKER, spy, 200), (VIX_TICKER, vix, 63)):
            try:
                values, metadata = _validated_history(frame, ticker, count, decision, session)
                snap["source_clocks"][ticker] = metadata
                if ticker == SPY_TICKER:
                    last, ma200 = float(values.iloc[-1]), float(values.mean())
                    snap.update(spy_close=last, spy_ma200=ma200,
                        spy_above_ma200=bool(last > ma200), spy_dist_ma200_pct=last/ma200-1,
                        spy_ret_3m=last/float(values.iloc[-63])-1,
                        spy_ret_1m=last/float(values.iloc[-21])-1)
                else:
                    last, sd = float(values.iloc[-1]), float(values.std(ddof=1))
                    clock.need(math.isfinite(sd) and sd > 0, "VIX_VARIANCE_REQUIRED")
                    snap.update(vix=last, vix_z_63d=(last-float(values.mean()))/sd)
            except (clock.Blocked, ValueError, TypeError, KeyError, OverflowError, AttributeError):
                errors.append("INVALID_HISTORY_"+ticker.replace("^", ""))
    except (clock.Blocked, ValueError, TypeError, OverflowError):
        errors.append("COMPLETED_SESSION_UNAVAILABLE")

    # ---- FRED block (HY OAS, DGS10) - optional, only if FRED_API_KEY set
    api = os.getenv("FRED_API_KEY")
    if api:
        snap["fred_observations"] = {}
        for name, series_id in (("hy_oas", "BAMLH0A0HYM2"), ("dgs10", "DGS10"), ("unrate", "UNRATE")):
            record = fetch_fred_observation(series_id, api)
            snap[name] = record["value"]
            snap["fred_observations"][name] = record

    # ---- Regime classification (matches L1)
    refusal = sorted(set(errors+_snapshot_refusal_reasons(snap)))
    snap["input_quality"] = "BLOCKED_INPUT" if refusal else "OBSERVED_RESEARCH_PROXY"
    snap["input_quality_reasons"] = refusal
    snap["regime_state"] = None if refusal else classify_regime(snap)
    return snap


def _empty_snapshot(decision):
    return dict(schema=SNAPSHOT_SCHEMA, asof=decision.strftime("%Y-%m-%d %H:%M UTC"),
        asof_date=decision.date().isoformat(), decision_at_utc=decision.isoformat(),
        report_session=None, session_close_utc=None, source_clocks={}, regime_state=None,
        source_authenticated=False, historical_pit_certified=False,
        portfolio_mutation_allowed=False, orders_allowed=False, production_activation_allowed=False,
        input_quality="BLOCKED_INPUT", input_quality_reasons=["INPUT_NOT_VALIDATED"])


def _clock_reasons(metadata, ticker, decision, session):
    try:
        clock.need(type(metadata) is dict, "SOURCE_CLOCK_REQUIRED")
        clock.need(metadata.get("source_id") == "yfinance:"+ticker and
            metadata.get("unit") == ("USD" if ticker == SPY_TICKER else "INDEX_POINTS") and
            metadata.get("adjustment") == "AUTO_ADJUSTED" and
            metadata.get("payload_kind") == "DERIVED_PROVIDER_FRAME", "SOURCE_IDENTITY_OR_UNIT")
        clock.sha(metadata.get("payload_sha256"))
        clock.need(metadata.get("availability_basis") == "COLLECTION_ONLY" and
            metadata.get("published_at_utc") is None, "PUBLICATION_NOT_AUTHENTICATED")
        collected = clock.stamp(metadata.get("collected_at_utc"))
        available = clock.stamp(metadata.get("available_at_utc"))
        closing = clock.stamp(session["session_close_utc"])
        clock.need(closing <= collected == available <= decision, "SOURCE_CLOCK_ORDER")
        clock.need(metadata.get("observation_date") == session["expected_session"], "SOURCE_SESSION_MISMATCH")
        return []
    except (clock.Blocked, ValueError, TypeError, OverflowError):
        return ["INVALID_SOURCE_CLOCK_"+ticker.replace("^", "")]


def _validated_history(frame, ticker, count, decision, session):
    clock.need(frame is not None and count <= len(frame) <= 5000, "HISTORY_REQUIRED")
    clock.need(frame.index.is_unique and frame.index.is_monotonic_increasing, "HISTORY_ORDER")
    dates = [item.date().isoformat() for item in frame.index]
    clock.need(dates[-1] == session["expected_session"] and len(set(dates)) == len(dates), "HISTORY_SESSION")
    metadata = frame.attrs.get("macro_source_clock")
    clock.need(not _clock_reasons(metadata, ticker, decision, session), "HISTORY_SOURCE_CLOCK")
    clock.need(metadata["payload_sha256"] == hashlib.sha256(frame.to_csv().encode("utf-8")).hexdigest(),
               "HISTORY_PAYLOAD_CHANGED")
    values = frame["Close"].iloc[-count:]
    clock.need(getattr(values.dtype, "kind", "") in "fiu", "HISTORY_NUMERIC_UNIT")
    schedule = clock.mcal.get_calendar("NYSE").schedule(
        start_date=decision.date()-timedelta(days=500), end_date=session["expected_session"])
    expected = [item.date().isoformat() for item in schedule.index[-count:]]
    clock.need(len(expected) == count and dates[-count:] == expected, "HISTORY_SESSION_COVERAGE")
    maximum = 10_000_000 if ticker == SPY_TICKER else 1000
    clock.need(all(type(v) is not bool and math.isfinite(float(v)) and 0 < float(v) <= maximum for v in values),
               "HISTORY_CLOSE_REQUIRED")
    return values, dict(metadata)


def current_snapshot_reasons(snap, *, decision):
    """Shared CLI input contract. Hashes/clocks attest consistency, never Source/PIT."""
    errors = _snapshot_refusal_reasons(snap)
    if type(snap) is not dict:
        return errors
    try:
        clock.need(snap.get("schema") == SNAPSHOT_SCHEMA, "SNAPSHOT_SCHEMA")
        issued = clock.stamp(snap.get("decision_at_utc"))
        clock.need(issued <= decision, "FUTURE_SNAPSHOT")
        clock.need(snap.get("asof") == issued.strftime("%Y-%m-%d %H:%M UTC") and
                   snap.get("asof_date") == issued.date().isoformat(), "SNAPSHOT_CLOCK_CONFLICT")
        session = clock.completed_session_clock(decision.isoformat())
        clock.need(snap.get("report_session") == session["expected_session"] and
                   snap.get("session_close_utc") == session["session_close_utc"], "STALE_SNAPSHOT_SESSION")
        clock.need(type(snap.get("source_clocks")) is dict, "SOURCE_CLOCKS_REQUIRED")
        for ticker in (SPY_TICKER, VIX_TICKER):
            errors.extend(_clock_reasons(snap["source_clocks"].get(ticker), ticker, issued, session))
        clock.need(snap.get("input_quality") == "OBSERVED_RESEARCH_PROXY" and
                   snap.get("input_quality_reasons") == [], "INPUT_NOT_ACCEPTED")
        clock.need(snap.get("regime_state") in REGIMES and snap.get("regime_state") == classify_regime(snap),
                   "REGIME_CONFLICT")
        for key in ("source_authenticated", "historical_pit_certified", "portfolio_mutation_allowed",
                    "orders_allowed", "production_activation_allowed"):
            clock.need(snap.get(key) is False, "RESEARCH_AUTHORITY_CONFLICT")
    except (clock.Blocked, ValueError, TypeError, KeyError, OverflowError) as exc:
        errors.append(str(exc) if isinstance(exc, clock.Blocked) else "INVALID_SNAPSHOT_CONTRACT")
    return sorted(set(errors))


def _finite_snapshot_value(snap: dict, field: str) -> float | None:
    value = snap.get(field)
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _snapshot_refusal_reasons(snap: dict) -> list[str]:
    """Fail closed on essential SPY/VIX data before assigning any market label.

    The exchange calendar establishes session consistency, not authenticated
    provider/publication identity. Valid data remain a report-only research proxy.
    """
    if type(snap) is not dict:
        return ["INVALID_SNAPSHOT"]
    positive = ("spy_close", "spy_ma200", "vix")
    needed = (*positive, "spy_ret_3m", "vix_z_63d")
    values = {field: _finite_snapshot_value(snap, field) for field in needed}
    errors = ["INVALID_" + field.upper() for field, value in values.items() if value is None]
    for field in positive:
        if values[field] is not None and values[field] <= 0:
            errors.append("NONPOSITIVE_" + field.upper())
    # Data-domain bounds only; no change to any market classification threshold.
    for field, maximum in (("spy_close", 10_000_000), ("spy_ma200", 10_000_000), ("vix", 1000)):
        if values[field] is not None and values[field] > maximum:
            errors.append("INVALID_UNIT_SCALE_"+field.upper())
    ret = values["spy_ret_3m"]
    if ret is not None and not -1 < ret <= 10:
        errors.append("INVALID_SPY_RETURN_RANGE")
    z = values["vix_z_63d"]
    # A 63-observation sample z-score (ddof=1) cannot exceed this bound.
    if z is not None and abs(z) > 62 / math.sqrt(63) + 1e-10:
        errors.append("INVALID_VIX_Z_RANGE")
    above = snap.get("spy_above_ma200")
    if type(above) is not bool:
        errors.append("INVALID_SPY_ABOVE_MA200")
    elif values["spy_close"] is not None and values["spy_ma200"] is not None:
        if above != (values["spy_close"] > values["spy_ma200"]):
            errors.append("CONFLICTING_SPY_MA200")
    for field in ("spy_dist_ma200_pct", "spy_ret_1m"):
        if field in snap and _finite_snapshot_value(snap, field) is None:
            errors.append("INVALID_" + field.upper())
    return sorted(set(errors))


def _nonfinite_to_null(value):
    """Preserve explicit null and refusal; never serialize NaN/Infinity."""
    if type(value) is float and not math.isfinite(value):
        return None
    if type(value) is dict:
        return {key: _nonfinite_to_null(item) for key, item in value.items()}
    if type(value) is list:
        return [_nonfinite_to_null(item) for item in value]
    return value


def classify_regime(snap: dict) -> str | None:
    if _snapshot_refusal_reasons(snap):
        return None
    spy_above = snap["spy_above_ma200"]
    spy_3m = float(snap["spy_ret_3m"])
    vix_z = float(snap["vix_z_63d"])

    # Original five-state thresholds and priority order are unchanged.
    if (not spy_above) and spy_3m < THRESHOLDS["spy_3m_deep_bear"] and vix_z > 2.0:
        return "deep_bear"
    if (not spy_above) or (vix_z > 1.0 and spy_3m < THRESHOLDS["spy_3m_bear"]):
        return "bear"
    if spy_above and vix_z < -0.5 and spy_3m > THRESHOLDS["spy_3m_strong_bull"]:
        return "strong_bull"
    if spy_above and vix_z < 0.0 and spy_3m > THRESHOLDS["spy_3m_bull"]:
        return "bull"
    return "neutral"


def detect_transitions(today: dict, prev: dict | None) -> list[str]:
    if (type(today) is not dict or _snapshot_refusal_reasons(today) or
            today.get("input_quality") != "OBSERVED_RESEARCH_PROXY" or
            today.get("regime_state") != classify_regime(today)):
        return []
    if (type(prev) is not dict or _snapshot_refusal_reasons(prev) or
            prev.get("input_quality") != "OBSERVED_RESEARCH_PROXY" or
            prev.get("regime_state") != classify_regime(prev)):
        return []
    msgs: list[str] = []
    if today.get("regime_state") != prev.get("regime_state"):
        msgs.append(f"regime: {prev.get('regime_state')} -> {today.get('regime_state')}")
    # MA200 cross
    if (today.get("spy_above_ma200") is not None and
            prev.get("spy_above_ma200") is not None and
            today["spy_above_ma200"] != prev["spy_above_ma200"]):
        side = "above" if today["spy_above_ma200"] else "below"
        msgs.append(f"SPY crossed {side} MA200")
    # VIX spike
    if (today.get("vix") is not None and prev.get("vix") is not None and
            (today["vix"] - prev["vix"]) > 5.0):
        msgs.append(f"VIX +{today['vix'] - prev['vix']:.1f} ({prev['vix']:.1f} -> {today['vix']:.1f})")
    return msgs


def telegram_send(msg: str) -> None:
    tok = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15).read()
    except Exception:
        pass


def _write_snapshot(path: Path, serialized: str) -> None:
    """Replace a complete UTF-8 report within its existing output directory."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                dir=path.parent, prefix=".macro-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--telegram", action="store_true", help="post Telegram digest")
    p.add_argument("--out-dir", default=str(OUTPUT_DIR))
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        snap = _nonfinite_to_null(compute_snapshot())
    except (clock.Blocked, ValueError, TypeError, KeyError, OverflowError, AttributeError):
        snap = _empty_snapshot(clock.trusted_now())
        snap["input_quality_reasons"] = ["SNAPSHOT_COMPUTATION_FAILED"]

    # Compare against latest.json from the previous run
    latest_path = out_dir / "latest.json"
    prev = None
    if latest_path.exists():
        try:
            prev = clock.decode(clock.bounded(latest_path, limit=128*1024))
        except (clock.Blocked, OSError, ValueError, TypeError):
            prev = None

    transitions = detect_transitions(snap, prev)
    snap["transitions"] = transitions

    daily_path = out_dir / f"snapshot_{snap['asof_date']}.json"
    serialized = json.dumps(snap, indent=2, allow_nan=False)
    # Publish the current refusal before the independent archive. An archive
    # error must never preserve an earlier GREEN current pointer.
    _write_snapshot(latest_path, serialized)
    _write_snapshot(daily_path, serialized)

    print(f"[macro-daily] regime_state: {snap.get('regime_state')}")
    print(f"[macro-daily] spy_above_ma200: {snap.get('spy_above_ma200')}")
    print(f"[macro-daily] spy_ret_3m: {snap.get('spy_ret_3m')}")
    print(f"[macro-daily] vix: {snap.get('vix')}  vix_z_63d: {snap.get('vix_z_63d')}")
    if transitions:
        print(f"[macro-daily] transitions: {transitions}")
    print(f"[macro-daily] wrote {daily_path}")

    if args.telegram and transitions:
        body = "\n".join([f"[macro-daily {snap['asof_date']}]"] + transitions
                         + [f"regime: {snap.get('regime_state')}",
                            f"VIX: {snap.get('vix')} (z={snap.get('vix_z_63d')})",
                            f"SPY 3m: {snap.get('spy_ret_3m')}"])
        telegram_send(body)

    return 0 if snap["input_quality"] == "OBSERVED_RESEARCH_PROXY" else 2


if __name__ == "__main__":
    sys.exit(main())
