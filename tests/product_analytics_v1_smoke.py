#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.aggregate_product_analytics as analytics  # noqa: E402
from tools.aggregate_product_analytics import (  # noqa: E402
    ContractError,
    aggregate,
    load_contract,
    read_events,
    strict_json_loads,
)

CONTRACT = (
    ROOT
    / "data_static"
    / "product_analytics_event_contract_v1.json"
)


def event(
    event_id: str,
    event_name: str,
    occurred: str,
    *,
    session: str = "session-A",
    data_state: str = "USABLE",
    surface: str = "site",
    internal: bool = False,
    bot: bool = False,
    entity_type: str | None = None,
    entity_id: str | None = None,
    market: str | None = None,
) -> dict:
    row = {
        "schema_version": "b5-product-analytics-event-v1",
        "event_name": event_name,
        "event_version": 1,
        "event_id": event_id,
        "occurred_at_utc": occurred,
        "received_at_utc": occurred,
        "session_id": session,
        "consent_status": "ACTIVE",
        "consent_version": "b6-analytics-consent-v1",
        "page": "home",
        "surface": surface,
        "data_state": data_state,
        "public_artifact_version": "artifact-20261007",
        "is_internal": internal,
        "is_bot": bot,
    }
    if entity_type is not None:
        row["entity_type"] = entity_type
    if entity_id is not None:
        row["entity_id"] = entity_id
    if market is not None:
        row["market"] = market
    return row


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_error(fn, expected: str) -> None:
    try:
        fn()
    except ContractError as exc:
        require(expected in str(exc), f"expected {expected}, got {exc}")
    else:
        raise AssertionError(
            f"expected ContractError containing {expected}"
        )


def test_contract_is_pretransmission_and_privacy_closed() -> None:
    contract = load_contract(CONTRACT)
    require(
        contract["status"] == "PREPARED_NOT_TRANSMITTING",
        "status",
    )
    require(
        contract["transmission_enabled"] is False,
        "transmission",
    )
    require(contract["collector_endpoint"] is None, "collector")
    require(
        contract["identity"][
            "persistent_anonymous_id_allowed"
        ]
        is False,
        "persistent anonymous id",
    )
    require(
        contract["identity"]["user_id_allowed"] is False,
        "user id",
    )
    require(
        contract["privacy"]["autocapture"] is False,
        "autocapture",
    )
    require(
        contract["privacy"]["session_replay"] is False,
        "session replay",
    )
    require(
        contract["privacy"]["raw_ip_storage"] is False,
        "raw ip",
    )


def test_qualified_session_requires_usable_search_and_depth_action() -> None:
    contract = load_contract(CONTRACT)
    rows = [
        event(
            "e1",
            "site_viewed",
            "2026-10-07T10:00:00Z",
        ),
        event(
            "e2",
            "research_search_succeeded",
            "2026-10-07T10:01:00Z",
            surface="research_results",
            entity_type="ticker",
            entity_id="NVDA",
            market="US",
        ),
        event(
            "e3",
            "research_source_opened",
            "2026-10-07T10:02:00Z",
            surface="research_source",
            entity_type="source",
            entity_id="sec",
            market="US",
        ),
        event(
            "e4",
            "research_search_succeeded",
            "2026-10-07T11:00:00Z",
            session="session-B",
            data_state="RESEARCH_DEGRADED",
            surface="research_results",
        ),
        event(
            "e5",
            "trade_ledger_opened",
            "2026-10-07T11:01:00Z",
            session="session-B",
            data_state="RESEARCH_DEGRADED",
            surface="trade_ledger",
            entity_type="portfolio",
            entity_id="main",
            market="US",
        ),
    ]
    result = aggregate(rows, contract)
    require(result["session_count"] == 2, "session count")
    day = result["daily"][0]
    require(day["usable_sessions"] == 1, "usable")
    require(day["degraded_sessions"] == 1, "degraded")
    require(
        day["qualified_value_sessions"] == 1,
        "qualified",
    )
    require(
        day["anonymous_qualified_value_session_rate"] == 1.0,
        "rate",
    )
    require(
        result["primary_kpi"]["status"] == "NOT_AVAILABLE",
        "primary KPI",
    )
    require(
        result["retention"][
            "d7_qualified_retention"
        ]["status"]
        == "NOT_AVAILABLE",
        "D7",
    )


def test_exact_duplicate_dedupes_but_conflict_fails() -> None:
    contract = load_contract(CONTRACT)
    row = event(
        "same",
        "site_viewed",
        "2026-10-07T10:00:00Z",
    )
    result = aggregate([row, deepcopy(row)], contract)
    require(result["unique_event_count"] == 1, "unique count")
    require(
        result["duplicate_event_count"] == 1,
        "duplicate count",
    )
    conflict = deepcopy(row)
    conflict["surface"] = "research_results"
    require_error(
        lambda: aggregate([row, conflict], contract),
        "conflicting_duplicate_event_id",
    )


def test_unknown_free_text_and_inactive_consent_fail_closed() -> None:
    contract = load_contract(CONTRACT)
    free_text = event(
        "free",
        "site_viewed",
        "2026-10-07T10:00:00Z",
    )
    free_text["search_query"] = "secret free text"
    require_error(
        lambda: aggregate([free_text], contract),
        "unknown_fields",
    )
    inactive = event(
        "declined",
        "site_viewed",
        "2026-10-07T10:00:00Z",
    )
    inactive["consent_status"] = "DECLINED"
    require_error(
        lambda: aggregate([inactive], contract),
        "analytics_consent_not_active",
    )


def test_mixed_state_session_cannot_qualify() -> None:
    contract = load_contract(CONTRACT)
    rows = [
        event("mixed-search", "research_search_succeeded", "2026-10-07T10:00:00Z", surface="research_results"),
        event("mixed-source", "research_source_opened", "2026-10-07T10:01:00Z", surface="research_source"),
        event("mixed-degraded", "site_viewed", "2026-10-07T10:02:00Z", data_state="RESEARCH_DEGRADED"),
    ]
    result = aggregate(rows, contract)
    day = result["daily"][0]
    require(day["usable_sessions"] == 0, "mixed session usable")
    require(day["degraded_sessions"] == 1, "mixed session degraded")
    require(day["qualified_value_sessions"] == 0, "mixed session must not qualify")
    require(day["anonymous_qualified_value_session_rate"] is None, "mixed session rate")


def test_custom_contract_cannot_weaken_privacy_boundary() -> None:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "contract.json"
        weakened_identity = deepcopy(payload)
        weakened_identity["identity"]["user_id_allowed"] = True
        path.write_text(json.dumps(weakened_identity), encoding="utf-8")
        require_error(lambda: load_contract(path), "user_id_must_remain_disabled")
        weakened_fields = deepcopy(payload)
        weakened_fields["optional_fields"].append("user_id")
        weakened_fields["forbidden_fields"].remove("user_id")
        path.write_text(json.dumps(weakened_fields), encoding="utf-8")
        require_error(lambda: load_contract(path), "optional_field_contract_mismatch")

        direct_contract = deepcopy(payload)
        direct_contract["identity"]["user_id_allowed"] = True
        require_error(
            lambda: aggregate(
                [event("direct-privacy", "site_viewed", "2026-10-07T10:00:00Z")],
                direct_contract,
            ),
            "user_id_must_remain_disabled",
        )


def test_input_resource_limits_fail_closed() -> None:
    require_error(
        lambda: strict_json_loads("[" * (analytics.MAX_JSON_DEPTH + 1) + "0" + "]" * (analytics.MAX_JSON_DEPTH + 1)),
        "json_depth_limit",
    )
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.json"
        path.write_text(json.dumps([
            event("limit-a", "site_viewed", "2026-10-07T10:00:00Z"),
            event("limit-b", "site_viewed", "2026-10-07T10:01:00Z"),
        ]), encoding="utf-8")
        old_event_limit = analytics.MAX_EVENTS
        analytics.MAX_EVENTS = 1
        try:
            require_error(lambda: read_events(path), "event_count_limit")
            contract = load_contract(CONTRACT)
            require_error(
                lambda: aggregate(
                    [
                        event("direct-a", "site_viewed", "2026-10-07T10:00:00Z"),
                        event("direct-b", "site_viewed", "2026-10-07T10:01:00Z"),
                    ],
                    contract,
                ),
                "event_count_limit",
            )
        finally:
            analytics.MAX_EVENTS = old_event_limit
        old_byte_limit = analytics.MAX_EVENT_INPUT_BYTES
        analytics.MAX_EVENT_INPUT_BYTES = 8
        try:
            require_error(lambda: read_events(path), "events_byte_limit")
        finally:
            analytics.MAX_EVENT_INPUT_BYTES = old_byte_limit

        jsonl_path = Path(tmp) / "events.jsonl"
        jsonl_path.write_text(
            "\n".join(
                json.dumps(row)
                for row in [
                    event("nodes-a", "site_viewed", "2026-10-07T10:00:00Z"),
                    event("nodes-b", "site_viewed", "2026-10-07T10:01:00Z"),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        old_node_limit = analytics.MAX_JSON_NODES
        analytics.MAX_JSON_NODES = 20
        try:
            require_error(
                lambda: read_events(jsonl_path),
                "json_node_limit",
            )
        finally:
            analytics.MAX_JSON_NODES = old_node_limit


def test_kst_timestamp_overflow_fails_closed() -> None:
    contract = load_contract(CONTRACT)
    require_error(
        lambda: aggregate(
            [
                event(
                    "overflow",
                    "site_viewed",
                    "9999-12-31T23:59:59Z",
                )
            ],
            contract,
        ),
        "occurred_at_utc_kst_range",
    )


def test_internal_and_bot_events_are_excluded() -> None:
    contract = load_contract(CONTRACT)
    result = aggregate(
        [
            event(
                "normal",
                "site_viewed",
                "2026-10-07T10:00:00Z",
            ),
            event(
                "internal",
                "site_viewed",
                "2026-10-07T10:01:00Z",
                internal=True,
            ),
            event(
                "bot",
                "site_viewed",
                "2026-10-07T10:02:00Z",
                bot=True,
            ),
        ],
        contract,
    )
    require(
        result["excluded_internal_event_count"] == 1,
        "internal count",
    )
    require(
        result["excluded_bot_event_count"] == 1,
        "bot count",
    )
    require(result["eligible_event_count"] == 1, "eligible count")


def test_session_timeout_and_kst_day_boundary_are_deterministic() -> None:
    contract = load_contract(CONTRACT)
    rows = [
        event(
            "a",
            "site_viewed",
            "2026-10-07T14:59:59Z",
            session="same",
        ),
        event(
            "b",
            "site_viewed",
            "2026-10-07T15:00:00Z",
            session="same",
        ),
        event(
            "c",
            "site_viewed",
            "2026-10-07T15:31:01Z",
            session="same",
        ),
    ]
    forward = aggregate(rows, contract)
    reverse = aggregate(list(reversed(rows)), contract)
    require(
        forward == reverse,
        "input order must not change output",
    )
    require(forward["session_count"] == 2, "30-minute split")
    require(
        [row["date_kst"] for row in forward["daily"]]
        == ["2026-10-07", "2026-10-08"],
        "KST boundary",
    )


def test_optimized_python_keeps_contract_checks() -> None:
    with TemporaryDirectory() as tmp:
        event_path = Path(tmp) / "events.json"
        bad = event(
            "bad",
            "site_viewed",
            "2026-10-07T10:00:00Z",
        )
        bad["consent_status"] = "DECLINED"
        event_path.write_text(
            json.dumps([bad]),
            encoding="utf-8",
        )
        command = [sys.executable, "-O", str(ROOT / "tools" / "aggregate_product_analytics.py"), "--events", str(event_path)]
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        require(proc.returncode != 0, "-O must not disable validation")
        require("analytics_consent_not_active" in (proc.stderr + proc.stdout), "-O validation reason")
        contract_path = Path(tmp) / "contract.json"
        weakened = json.loads(CONTRACT.read_text(encoding="utf-8"))
        weakened["identity"]["user_id_allowed"] = True
        contract_path.write_text(json.dumps(weakened), encoding="utf-8")
        event_path.write_text(json.dumps([event("good", "site_viewed", "2026-10-07T10:00:00Z")]), encoding="utf-8")
        contract_proc = subprocess.run(command + ["--contract", str(contract_path)], cwd=ROOT, capture_output=True, text=True)
        require(contract_proc.returncode != 0, "-O must keep contract privacy validation")
        require("user_id_must_remain_disabled" in (contract_proc.stderr + contract_proc.stdout), "-O contract privacy reason")


def main() -> int:
    tests = [
        test_contract_is_pretransmission_and_privacy_closed,
        test_qualified_session_requires_usable_search_and_depth_action,
        test_exact_duplicate_dedupes_but_conflict_fails,
        test_unknown_free_text_and_inactive_consent_fail_closed,
        test_mixed_state_session_cannot_qualify,
        test_custom_contract_cannot_weaken_privacy_boundary,
        test_input_resource_limits_fail_closed,
        test_kst_timestamp_overflow_fails_closed,
        test_internal_and_bot_events_are_excluded,
        test_session_timeout_and_kst_day_boundary_are_deterministic,
        test_optimized_python_keeps_contract_checks,
    ]
    for test in tests:
        test()
    print(
        f"product_analytics_v1_smoke: PASS ({len(tests)} tests)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
