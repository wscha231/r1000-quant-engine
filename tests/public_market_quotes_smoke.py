"""Exact-session quotes never imply a completed account or a synthetic close."""
from __future__ import annotations
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from tools.refresh_public_market_quotes import collect, exact_close, fetch_json, preserve_deployed, public_tickers, yahoo_close


def fixture():
    return {"schema_version": "run287-public-dashboard-v1", "as_of_close": "2026-07-10",
            "status": {"review_only": True, "live_trading_enabled": False},
            "portfolios": {p: {"holdings": [{"ticker": t, "weight": 0.8, "price": 80}],
                                "cash_weight": 0.2, "metrics": {"cagr": 0.3}, "trades": []}
                           for p, t in [("main", "AAA"), ("concentrated", "BBB")]}}


def rejected(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("unsafe input accepted")


def main():
    stamp = lambda day: datetime.fromisoformat(day + "T13:30:00+00:00").timestamp()
    reached_sink = []
    class RedirectServer(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/sink":
                reached_sink.append(True)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
            else:
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}/sink")
                self.end_headers()
        def log_message(self, *_): pass
    with HTTPServer(("127.0.0.1", 0), RedirectServer) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            try:
                fetch_json(f"http://127.0.0.1:{server.server_port}/redirect",
                           {"APCA-API-KEY-ID": "test-only", "APCA-API-SECRET-KEY": "test-only"})
                raise AssertionError("redirect followed")
            except HTTPError as exc:
                assert exc.code == 302
            assert reached_sink == []
        finally:
            server.shutdown()
            thread.join(timeout=2)
    provider_payload = {"chart": {"result": [{"meta": {"symbol": "BRK-B", "currency": "USD"},
                        "timestamp": [stamp("2026-09-11")], "indicators": {"quote": [{"close": [450]}]}}]}}
    with patch("tools.refresh_public_market_quotes.fetch_json", return_value=(provider_payload, "a" * 64)) as request:
        assert yahoo_close("BRK.B", "2026-09-11") == (450, "a" * 64)
        assert "/BRK-B?" in request.call_args.args[0]
    assert exact_close([(stamp("2026-09-10"), 10), (stamp("2026-09-11"), 11),
                        (stamp("2026-09-14"), 14)], "2026-09-11") == 11
    for rows in [[(stamp("2026-09-10"), 10)], [(stamp("2026-09-11"), None)],
                 [(stamp("2026-09-11"), float("nan"))], [(stamp("2026-09-11"), 0)],
                 [(stamp("2026-09-11"), 11)] * 2]:
        rejected(lambda: exact_close(rows, "2026-09-11"))
    # UTC midnight is still the preceding New York date.
    rejected(lambda: exact_close([(datetime(2026, 9, 11, tzinfo=timezone.utc).timestamp(), 11)], "2026-09-11"))
    data = fixture()
    before = copy.deepcopy(data)
    def good(ticker, session):
        assert session == "2026-09-11"
        return 123.45, "a" * 64
    with patch.dict(os.environ, {"ALPACA_API_KEY": "", "ALPACA_API_SECRET": ""}):
        complete = collect(data, now="2026-09-12T03:00:00Z", yahoo=good)
        assert complete["status"] == "COMPLETE" and complete["as_of_close"] == "2026-09-11"
        assert complete["portfolio_as_of_close"] == "2026-07-10" and complete["portfolio_revalued"] is False
        assert data == before
        def partial(ticker, session):
            if ticker == "BBB": raise ValueError("missing")
            return good(ticker, session)
        result = collect(data, now="2026-09-12T03:00:00Z", yahoo=partial)
        assert result["status"] == "PARTIAL" and result["as_of_close"] is None
        assert result["missing_tickers"] == ["BBB"] and len(result["quotes"]) == 1
        waiting = collect(data, now="2026-09-11T20:10:00Z", yahoo=lambda *_: (_ for _ in ()).throw(AssertionError()))
        assert waiting["status"] == "WAITING_FOR_COMPLETED_CLOSE" and waiting["quotes"] == []
        # Labor Day selects the real preceding Friday, not a weekday guess.
        holiday = collect(data, now="2026-09-07T23:00:00Z", yahoo=lambda t, s: (100, "a" * 64))
        assert holiday["expected_session_date"] == "2026-09-04"
    with patch.dict(os.environ, {"ALPACA_API_KEY": "test-only", "ALPACA_API_SECRET": "test-only"}):
        def fail(*_): raise ValueError("provider rejected request")
        unavailable = collect(data, now="2026-09-12T03:00:00Z", alpaca=fail,
                              yahoo=lambda *_: (_ for _ in ()).throw(AssertionError()))
        assert unavailable["status"] == "PROVIDER_UNAVAILABLE" and unavailable["quotes"] == []
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "dashboard.json"
        path.write_text(json.dumps(data))
        deployed = copy.deepcopy(data)
        deployed["as_of_close"] = "2026-07-24"
        preserve_deployed(path, deployed)
        assert json.loads(path.read_text()) == deployed
        preserve_deployed(path, data)
        assert json.loads(path.read_text()) == deployed
        corrected = copy.deepcopy(deployed)
        corrected["portfolios"]["main"]["metrics"]["cagr"] = 0.25
        path.write_text(json.dumps(corrected))
        preserve_deployed(path, deployed)
        assert json.loads(path.read_text()) == corrected
        unsafe = copy.deepcopy(deployed)
        unsafe["status"]["review_only"] = False
        rejected(lambda: preserve_deployed(path, unsafe))
    unsafe = copy.deepcopy(data)
    unsafe["portfolios"]["main"]["holdings"][0]["ticker"] = "../../unsafe"
    rejected(lambda: public_tickers(unsafe))
    print("public_market_quotes_smoke: PASS")


if __name__ == "__main__":
    main()
