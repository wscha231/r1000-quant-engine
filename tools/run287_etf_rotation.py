"""Exact-session relative strength and private A3 review proposals for Run287.

Daily observations are research triage. A watch symbol is a review locator,
not a verified security ID or an assertion that an ETF holds the company.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone

WINDOWS = (1, 5, 20)
POINTS = max(WINDOWS) + 2
MARGIN = 0.0025
SCHEMA = "run287-etf-rotation-v1"
RECEIPT_SCHEMA = "run287-etf-rotation-receipt-v1"
PRIVATE_PREFIX = "etf-rotation-v1/objects/"
A3_SLICES = ("RS_PATH", "TIMING", "VALUATION", "EXPECTED_RETURN")
A3_REQUIREMENTS = ("SECURITY_IDENTITY_VERIFIED", "A1_CURRENT_VERIFIED", "RELEVANT_A2_A4_EVIDENCE_VERIFIED")
SAFETY = dict(source_admitted=False, historical_pit_verified=False, formal_a3_evaluated=False,
              registry_write_allowed=False, economic_authority=False, auto_trade_allowed=False)
COUNTS = ("etfs_expected", "etf_price_windows", "etfs_compared", "stocks_expected",
          "stock_price_windows", "stocks_compared", "etf_changes", "a3_review_requests")
HEX = re.compile(r"[0-9a-f]{64}")


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def policy(contract: dict) -> tuple[dict, tuple[str, ...], str]:
    config = contract["etf_rotation"]
    references, sectors, themes = (config[k] for k in ("references", "sectors", "themes"))
    theme_symbols = [ticker for group in themes.values() for ticker in group]
    symbols = [*references, *sectors, *theme_symbols]
    watch = tuple(sorted(contract["watchlist"]["US"]))
    if (set(references) != {"SPY", "QQQ", "RSP"} or config["benchmark"] != "SPY"
            or len(sectors) != 11 or len(theme_symbols) != 28 or len(set(symbols)) != 42
            or len(watch) != len(set(watch)) or not watch or len(watch) > 100
            or set(watch).intersection(symbols)
            or any(not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", ticker) for ticker in (*symbols, *watch))
            or not set(config["watch_reference"]).issubset(watch)
            or not set(config["watch_reference"].values()).issubset(set(sectors) | set(theme_symbols))):
        raise ValueError("rotation_policy_invalid")
    return config, watch, sha256(canonical({"schema": SCHEMA, "rotation": config, "watch": watch,
        "horizons": WINDOWS, "points": POINTS, "rs5_crossing_margin": MARGIN,
        "rank_order": ["RS5", "RS20"], "leader_bucket": "TOP_FIFTH_POSITIVE_RS5"}))


def universe(config: dict) -> dict:
    rows = {ticker: {"kind": "REFERENCE", "group": None, "label": label}
            for ticker, label in config["references"].items()}
    rows.update({ticker: {"kind": "SECTOR", "group": "GICS", "label": label}
                 for ticker, label in config["sectors"].items()})
    rows.update({ticker: {"kind": "THEME", "group": group, "label": label}
                 for group, members in config["themes"].items() for ticker, label in members.items()})
    return rows


def session_window(now: datetime) -> tuple[tuple[str, ...], datetime]:
    import pandas_market_calendars as mcal

    if now.utcoffset() is None:
        raise ValueError("rotation_timezone_required")
    now = now.astimezone(timezone.utc)
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=(now - timedelta(days=70)).date(), end_date=now.date())
    settled = schedule[schedule["market_close"] <= now - timedelta(minutes=90)].tail(POINTS)
    if len(settled) != POINTS:
        raise ValueError("rotation_settled_window_unavailable")
    return (tuple(day.date().isoformat() for day in settled.index),
            settled["market_close"].iloc[-1].to_pydatetime() + timedelta(minutes=90))


def exact_closes(rows, sessions: tuple[str, ...]) -> tuple[list[float] | None, str | None]:
    expected = set(sessions)
    selected = {}
    for session, close in rows:
        if session not in expected:
            continue
        if session in selected:
            return None, "DUPLICATE_SESSION"
        if isinstance(close, bool):
            return None, "INVALID_CLOSE"
        try:
            close = float(close)
        except (ValueError, TypeError, OverflowError):
            return None, "INVALID_CLOSE"
        if not math.isfinite(close) or not 1e-8 <= close <= 1e10:
            return None, "INVALID_CLOSE"
        selected[session] = close
    if sessions[-1] not in selected:
        return None, "EXACT_SESSION_MISSING"
    if expected != set(selected):
        return None, "WINDOW_GAP"
    return [selected[session] for session in sessions], None


def relative(prices: list[float], baseline: list[float], *, previous: bool = False) -> dict:
    end = len(prices) - 1 - int(previous)
    return {str(days): round((prices[end] / prices[end - days]) /
                             (baseline[end] / baseline[end - days]) - 1, 10) for days in WINDOWS}


def crossings(before: float, after: float) -> list[str]:
    if before < MARGIN <= after:
        return ["RS5_OUTPERFORMANCE_ENTERED"]
    if after <= -MARGIN < before:
        return ["RS5_UNDERPERFORMANCE_ENTERED"]
    return []


def ranks(members, rows) -> None:
    # Compare within a fixed, fully observed cohort. A missing peer cannot
    # manufacture a top-bucket entry for a remaining name.
    if any(rows[ticker]["relative_strength"] is None for ticker in members):
        return
    def score(ticker, key):
        rs = rows[ticker][key]
        return rs["5"], rs["20"]
    previous = sorted((score(t, "previous_relative_strength") for t in members), reverse=True)
    current = sorted((score(t, "relative_strength") for t in members), reverse=True)
    bucket = math.ceil(len(members) / 5)
    for ticker in members:
        row = rows[ticker]
        before = score(ticker, "previous_relative_strength")
        after = score(ticker, "relative_strength")
        rank_before, rank_after = previous.index(before) + 1, current.index(after) + 1
        row["rank5"] = {"prior": rank_before, "current": rank_after, "cohort": len(members)}
        led, leads = before[0] > 0 and rank_before <= bucket, after[0] > 0 and rank_after <= bucket
        if leads != led:
            row["changes"].append("TOP_BUCKET_ENTERED" if leads else "TOP_BUCKET_EXITED")


def a3_request_id(session: str, subject: dict) -> str:
    return sha256(canonical({"purpose": "A3_LEADERSHIP_REVIEW", "session": session, "subject": subject}))


def analyze(histories: dict, contract: dict, *, now: datetime, price_basis: str) -> dict:
    config, watch, policy_sha = policy(contract)
    sessions, settled_at = session_window(now)
    etfs = universe(config)
    symbols = (*etfs, *watch)
    windows, gaps = {}, {}
    for ticker in symbols:
        closes, reason = exact_closes(histories.get(ticker, ()), sessions)
        if closes is None:
            gaps[ticker] = reason
        else:
            windows[ticker] = closes
    benchmark = config["benchmark"]
    rows = {}
    for ticker in symbols:
        metadata = etfs[ticker] if ticker in etfs else {"kind": "STOCK", "group": "US_WATCHLIST", "label": ticker}
        row = {**metadata, "relative_strength": None, "previous_relative_strength": None,
               "rank5": None, "changes": [], "gap": gaps.get(ticker)}
        if ticker in windows and benchmark in windows:
            row["relative_strength"] = relative(windows[ticker], windows[benchmark])
            row["previous_relative_strength"] = relative(windows[ticker], windows[benchmark], previous=True)
            row["changes"] = crossings(row["previous_relative_strength"]["5"], row["relative_strength"]["5"])
        elif ticker in windows:
            row["gap"] = "BENCHMARK_WINDOW_UNAVAILABLE"
        rows[ticker] = row
    ranks(tuple(config["sectors"]), rows)
    ranks(tuple(t for t in etfs if etfs[t]["kind"] == "THEME"), rows)
    ranks(watch, rows)
    # Theme peer ranks are supplemental; they never replace the 28-theme rank.
    theme_peer_ranks = {}
    for group, members in config["themes"].items():
        if len(members) < 2:
            continue
        group_rows = {t: {**rows[t], "changes": []} for t in members}
        ranks(tuple(members), group_rows)
        theme_peer_ranks[group] = {t: row["rank5"] for t, row in group_rows.items()}
        for ticker, row in group_rows.items():
            rows[ticker]["changes"].extend("THEME_FAMILY_" + change for change in row["changes"])

    peer_groups = {}
    for ticker in watch:
        row = rows[ticker]
        peer = config["watch_reference"].get(ticker)
        peer_metrics = None
        if row["relative_strength"] is not None and peer in windows:
            after = relative(windows[ticker], windows[peer])
            before = relative(windows[ticker], windows[peer], previous=True)
            peer_metrics = {"reference": peer, "current": after, "prior": before,
                            "changes": crossings(before["5"], after["5"])}
        row["peer_relative_strength"] = peer_metrics
        if peer is not None:
            peer_groups.setdefault(peer, []).append(ticker)

    for members in peer_groups.values():
        if len(members) < 2 or any(rows[t]["peer_relative_strength"] is None for t in members):
            continue
        group_rows = {t: {"relative_strength": rows[t]["peer_relative_strength"]["current"],
                          "previous_relative_strength": rows[t]["peer_relative_strength"]["prior"],
                          "changes": []} for t in members}
        ranks(members, group_rows)
        for ticker, row in group_rows.items():
            peer_metrics = rows[ticker]["peer_relative_strength"]
            peer_metrics["rank5"] = row["rank5"]
            peer_metrics["changes"].extend("STOCK_PEER_" + change for change in row["changes"])

    requests = []
    for ticker in watch:
        row = rows[ticker]
        peer = config["watch_reference"].get(ticker)
        peer_metrics = row["peer_relative_strength"]
        if row["relative_strength"] is None:
            continue
        triggers = [{"scope": "STOCK_VS_SPY", "symbol": ticker, "changes": row["changes"]}] if row["changes"] else []
        if peer_metrics and peer_metrics["changes"]:
            triggers.append({"scope": "STOCK_VS_REFERENCE", "symbol": peer, "changes": peer_metrics["changes"]})
        if peer and rows[peer]["changes"]:
            triggers.append({"scope": "REFERENCE_ETF_ROTATION", "symbol": peer, "changes": rows[peer]["changes"]})
        if triggers:
            subject = {"market": "US", "ticker": ticker}
            request_id = a3_request_id(sessions[-1], subject)
            requests.append({"request_id": request_id, "agent": "A3", "subject": subject,
                             "status": "REVIEW_REQUIRED", "event_family": "LEADERSHIP",
                             "requested_slices": A3_SLICES, "requires": A3_REQUIREMENTS,
                             "triggers": triggers, "execute": False})
    compared = lambda cohort: sum(rows[t]["relative_strength"] is not None for t in cohort)
    counts = dict(etfs_expected=len(etfs), etf_price_windows=sum(t in windows for t in etfs),
                  etfs_compared=compared(etfs), stocks_expected=len(watch),
                  stock_price_windows=sum(t in windows for t in watch), stocks_compared=compared(watch),
                  etf_changes=sum(bool(rows[t]["changes"]) for t in etfs),
                  a3_review_requests=len(requests))
    status = ("DATA_BLOCKED" if benchmark not in windows else
              "CURRENT" if len(windows) == len(symbols) else "PARTIAL")
    return {"schema": SCHEMA, "session": sessions[-1], "previous_session": sessions[-2],
            "observation_started_at_utc": now.astimezone(timezone.utc).isoformat(),
            "settled_at_utc": settled_at.isoformat(), "status": status, "policy_sha256": policy_sha,
            "normalized_price_input_sha256": sha256(canonical(
                {"price_basis": price_basis, "sessions": sessions, "closes": windows})),
            "price_basis": price_basis, "counts": counts, "rows": rows, "theme_peer_ranks": theme_peer_ranks,
            "a3_review_requests": requests, "safety": SAFETY}


def public_receipt(result: dict, producer: dict, observed_at: datetime, payload_sha: str | None) -> dict:
    count = result["counts"]["a3_review_requests"]
    handoff = ("PRIVATE_HANDOFF_BLOCKED" if payload_sha is None else
               "REVIEW_REQUESTS_READY" if count else "DATA_BLOCKED" if result["status"] == "DATA_BLOCKED" else
               "NO_NEW_REVIEW_REQUESTS" if result["status"] == "CURRENT" else "NO_REQUESTS_IN_OBSERVED_SCOPE")
    return {"schema": RECEIPT_SCHEMA, "session": result["session"], "observed_at_utc": observed_at.isoformat(),
            "producer": producer, "policy_sha256": result["policy_sha256"], "counts": result["counts"],
            "price_status": result["status"], "a3_handoff_status": handoff,
            "private_payload_sha256": payload_sha, "safety": SAFETY}


def frame_rows(frame, column: str) -> list:
    if frame is None or column not in frame:
        return []
    return [(stamp.date().isoformat(), value) for stamp, value in frame[column].items()]


class ScheduledRotation:
    """Share the legacy ETF fetches; use the existing batch helper for gaps."""

    def __init__(self, contract: dict, now: datetime):
        self.contract = contract
        self.now = now
        self.sessions, _ = session_window(now)
        self.config, self.watch, _ = policy(contract)
        self.etfs = universe(self.config)
        self.histories = {}

    def legacy_history(self, fetch, ticker):
        frame = fetch(ticker)  # preserve the legacy request and its output
        if ticker in self.etfs:
            self.histories[ticker] = frame_rows(frame, "Close")  # legacy auto_adjust=True
        return frame

    def finish(self, download=None) -> dict:
        from tools.build_replay_price_cache import run_download_batches

        if download is None:
            from tools.build_replay_price_cache import download_yfinance as download

        symbols = sorted((*self.etfs, *self.watch))
        end = (datetime.fromisoformat(self.sessions[-1]).date() + timedelta(days=1)).isoformat()
        for attempt, batch_size in enumerate((20, 5), start=1):
            gaps = [t for t in symbols
                    if exact_closes(self.histories.get(t, ()), self.sessions)[1] is not None]
            if not gaps:
                break
            frames, _ = run_download_batches(
                gaps, start=self.sessions[0], end=end, batch_size=batch_size,
                attempt=attempt, download_fn=download,
            )
            for ticker in gaps:
                rows = frame_rows(frames.get(ticker), "Adj Close")
                if exact_closes(rows, self.sessions)[1] is None or not self.histories.get(ticker):
                    self.histories[ticker] = rows
        return analyze(self.histories, self.contract, now=self.now, price_basis="YAHOO_ADJUSTED_DAILY_CLOSE_USD")


def publish_private(result: dict, producer: dict, observed_at: datetime, remote=None) -> dict:
    import os

    raw = canonical({**result, "producer": producer, "observed_at_utc": observed_at.isoformat()})
    digest = sha256(raw)
    try:
        if remote is None:
            from tools.macro_research_checkpoint import RcloneTransport
            namespace = os.environ.get("MACRO_RESEARCH_REMOTE", "")
            if not namespace.endswith("/scheduled"):
                raise ValueError("scheduled_private_namespace_required")
            remote = RcloneTransport(namespace)
        remote.write(PRIVATE_PREFIX + digest, raw)  # immutable + byte-for-byte readback
    except (ValueError, OSError):
        return public_receipt(result, producer, observed_at, None)
    return public_receipt(result, producer, observed_at, digest)


def receipt_observation(receipt, run: dict, artifact: dict, session: str, now: datetime, contract: dict) -> dict:
    """Verify before projecting a public-safe view; the parent can still fail."""
    missing = {"status": "MISSING_RECEIPT"}
    invalid = {"status": "UNVERIFIED_RECEIPT"}
    if receipt is None:
        return missing
    try:
        _, watch, policy_sha = policy(contract)
        producer = {"run_id": run["id"], "run_attempt": run["run_attempt"], "head_sha": run["head_sha"]}
        if (run.get("event") != "schedule" or not isinstance(receipt, dict)
                or receipt.get("schema") != RECEIPT_SCHEMA
                or receipt.get("producer") != producer
                or any(type(producer[k]) is not int or producer[k] < 1
                       or type(receipt["producer"][k]) is not int for k in ("run_id", "run_attempt"))
                or not re.fullmatch(r"[0-9a-f]{40}", producer["head_sha"])
                or receipt.get("policy_sha256") != policy_sha or receipt.get("safety") != SAFETY
                or any(receipt["safety"][k] is not False for k in SAFETY)):
            return invalid
        if receipt.get("session") != session:
            return {"status": "SESSION_MISMATCH"}
        def clock(value):
            t = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if t.utcoffset() is None:
                raise ValueError("rotation_timestamp_timezone")
            return t
        observed = clock(receipt["observed_at_utc"])
        close_sessions, settled = session_window(observed)
        if (close_sessions[-1] != session
                or not (clock(run["created_at"]) <= observed <= clock(artifact["created_at"]) <= now)
                or observed < settled):
            return invalid
        counts = receipt["counts"]
        if (not isinstance(counts, dict) or set(counts) != set(COUNTS)
                or any(type(n) is not int or n < 0 for n in counts.values())
                or counts["etfs_expected"] != 42 or counts["stocks_expected"] != len(watch)
                or not counts["etf_changes"] <= counts["etfs_compared"] <= counts["etf_price_windows"] <= 42
                or not counts["a3_review_requests"] <= counts["stocks_compared"] <= counts["stock_price_windows"] <= len(watch)):
            return invalid
        status = ("DATA_BLOCKED" if counts["etfs_compared"] == 0 else
                  "CURRENT" if counts["etfs_compared"] == 42 and counts["stocks_compared"] == len(watch) else "PARTIAL")
        if (receipt.get("price_status") != status or
                (status == "DATA_BLOCKED" and counts["stocks_compared"] != 0)):
            return invalid
        digest = receipt["private_payload_sha256"]
        if digest is not None and (not isinstance(digest, str) or not HEX.fullmatch(digest)):
            return invalid
        expected = public_receipt({"session": session, "counts": counts, "status": status, "policy_sha256": policy_sha},
                                  producer, observed, digest)
        if receipt["a3_handoff_status"] != expected["a3_handoff_status"]:
            return invalid
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return invalid
    return {"status": status, "session": session, "observed_at_utc": observed.isoformat(),
            "counts": counts, "a3_handoff_status": expected["a3_handoff_status"],
            "private_payload_sha256": digest, "producer": producer, "policy_sha256": policy_sha, "safety": SAFETY}


def decode_a3_review_requests(observation: dict, raw: bytes, contract: dict) -> list[dict]:
    """A3 reads exact private bytes by the verified monitor observation's hash."""
    if (observation.get("a3_handoff_status") != "REVIEW_REQUESTS_READY"
            or len(raw) > 1_000_000 or sha256(raw) != observation.get("private_payload_sha256")):
        raise ValueError("rotation_private_binding")
    payload = json.loads(raw)
    _, watch, policy_sha = policy(contract)
    if (not isinstance(payload, dict) or payload.get("schema") != SCHEMA or payload.get("safety") != SAFETY
            or any(payload["safety"][key] is not False for key in SAFETY)
            or payload.get("policy_sha256") != policy_sha
            or any(payload.get(k) != observation.get(k)
                   for k in ("session", "observed_at_utc", "producer", "counts", "policy_sha256", "status"))):
        raise ValueError("rotation_private_identity")
    requests = payload.get("a3_review_requests")
    if not isinstance(requests, list) or len(requests) != observation["counts"]["a3_review_requests"]:
        raise ValueError("rotation_private_count")
    seen = set()
    for request in requests:
        subject = request.get("subject") if isinstance(request, dict) else None
        ticker = subject.get("ticker") if isinstance(subject, dict) else None
        if (subject != {"market": "US", "ticker": ticker} or ticker not in watch or ticker in seen
                or request.get("request_id") != a3_request_id(observation["session"], subject)
                or request.get("agent") != "A3" or request.get("status") != "REVIEW_REQUIRED"
                or request.get("event_family") != "LEADERSHIP" or request.get("execute") is not False
                or request.get("requires") != list(A3_REQUIREMENTS)
                or request.get("requested_slices") != list(A3_SLICES)):
            raise ValueError("rotation_a3_request")
        seen.add(ticker)
    return requests
