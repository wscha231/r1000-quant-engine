#!/usr/bin/env python3
"""Smoke checks for the bounded, secret-safe ZACKS/EEH sample probe."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "probe_run287_nasdaq_zeeh_sample.py"
SPEC = importlib.util.spec_from_file_location("probe_run287_nasdaq_zeeh_sample", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = json.dumps(self._payload, sort_keys=True).encode("utf-8") if payload is not None else text.encode("utf-8")

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def metadata_payload() -> dict[str, Any]:
    return {
        "datatable": {
            "vendor_code": "ZACKS",
            "datatable_code": "EEH",
            "name": "Zacks Consensus Earnings Estimates History",
            "premium": True,
            "primary_key": ["m_ticker", "per_end_date", "obs_date", "per_type"],
        }
    }


def sample_payload(count: int = 50, *, future: bool = False) -> dict[str, Any]:
    columns = [
        {"name": "m_ticker", "type": "text"},
        {"name": "per_end_date", "type": "Date"},
        {"name": "obs_date", "type": "Date"},
        {"name": "per_type", "type": "text"},
        {"name": "eps_mean_est", "type": "double"},
    ]
    rows = []
    for index in range(count):
        obs = "2099-01-01" if future and index == 0 else f"2026-06-{(index % 28) + 1:02d}"
        rows.append([f"T{index:03d}", "2026-12-31", obs, "A", 1.0 + index / 100])
    return {"datatable": {"columns": columns, "data": rows}, "meta": {"next_cursor_id": "bounded-next"}}


def artifact_text(path: Path) -> str:
    return "\n".join(item.read_text(encoding="utf-8", errors="replace") for item in path.rglob("*") if item.is_file())


def test_missing_key_makes_zero_requests() -> None:
    with tempfile.TemporaryDirectory() as td:
        session = FakeSession([])
        result = MOD.probe(api_key="", output_dir=Path(td), as_of_date=date(2026, 7, 14), session=session)
        assert result["status"] == "BLOCKED_CREDENTIAL_MISSING"
        assert result["request_count"] == 0
        assert session.calls == []


def test_entitlement_failure_is_bounded_and_secret_safe() -> None:
    secret = "secret-value-123"
    with tempfile.TemporaryDirectory() as td:
        session = FakeSession(
            [
                FakeResponse(200, metadata_payload()),
                FakeResponse(403, {"error": f"api_key={secret}"}, text=f"url?api_key={secret}"),
            ]
        )
        result = MOD.probe(api_key=secret, output_dir=Path(td), as_of_date=date(2026, 7, 14), session=session)
        assert result["status"] == "BLOCKED_PROVIDER_ENTITLEMENT"
        assert result["request_count"] == 2
        assert len(session.calls) == 2
        assert secret not in artifact_text(Path(td))


def test_50_date_only_rows_are_schema_ready_but_not_pit_ready() -> None:
    secret = "sample-secret"
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        session = FakeSession([FakeResponse(200, metadata_payload()), FakeResponse(200, sample_payload())])
        result = MOD.probe(api_key=secret, output_dir=out, as_of_date=date(2026, 7, 14), session=session)
        assert result["status"] == "READY_50_ROW_SCHEMA_REVIEW"
        assert result["row_count"] == 50
        assert result["request_count"] == 2
        assert result["exact_timestamp_ratio"] == 0.0
        assert result["source_gate_status"] == "BLOCKED_PIT_IDENTITY_GAPS"
        assert "date_only_obs_date_not_exact_timestamp" in result["source_gate_blockers"]
        assert result["return_join_allowed"] is False
        assert result["portfolio_ab_allowed"] is False
        assert (out / "raw" / "sample.json").exists()
        assert secret not in artifact_text(out)


def test_row_limit_and_future_rows_fail_closed() -> None:
    for count, future, expected in [(51, False, "row_limit_exceeded"), (50, True, "future_obs_date_rows")]:
        with tempfile.TemporaryDirectory() as td:
            session = FakeSession([FakeResponse(200, metadata_payload()), FakeResponse(200, sample_payload(count, future=future))])
            result = MOD.probe(api_key="key", output_dir=Path(td), as_of_date=date(2026, 7, 14), session=session)
            assert result["status"] == "BLOCKED_SCHEMA"
            assert expected in result["reason"]


def test_raw_evidence_is_immutable_and_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        first = FakeSession([FakeResponse(200, metadata_payload()), FakeResponse(200, sample_payload())])
        result1 = MOD.probe(api_key="key", output_dir=out, as_of_date=date(2026, 7, 14), session=first)
        assert result1["status"] == "READY_50_ROW_SCHEMA_REVIEW"
        second = FakeSession([FakeResponse(200, metadata_payload()), FakeResponse(200, sample_payload())])
        result2 = MOD.probe(api_key="key", output_dir=out, as_of_date=date(2026, 7, 14), session=second)
        assert result2["status"] == "READY_50_ROW_SCHEMA_REVIEW"
        assert result2["sample_write"] == "existing_same"
        changed = FakeSession([FakeResponse(200, metadata_payload()), FakeResponse(200, sample_payload(49))])
        result3 = MOD.probe(api_key="key", output_dir=out, as_of_date=date(2026, 7, 14), session=changed)
        assert result3["status"] == "BLOCKED_IMMUTABLE_COLLISION"


def main() -> int:
    test_missing_key_makes_zero_requests()
    test_entitlement_failure_is_bounded_and_secret_safe()
    test_50_date_only_rows_are_schema_ready_but_not_pit_ready()
    test_row_limit_and_future_rows_fail_closed()
    test_raw_evidence_is_immutable_and_idempotent()
    print("run287_nasdaq_zeeh_sample_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
