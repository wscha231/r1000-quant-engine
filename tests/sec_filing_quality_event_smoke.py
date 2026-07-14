#!/usr/bin/env python3
"""Focused offline smoke checks for the SEC filing quality event sidecar."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_sec_filing_quality_event as quality  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


CIK = "0000000123"


def accession(year: int, quarter: int, suffix: int = 1) -> str:
    return f"0000000123-{str(year)[-2:]}-{quarter:03d}{suffix:02d}"


def filing_rows() -> pd.DataFrame:
    records = []
    values = [
        (2023, 1, "2023-03-31", "2023-04-20T20:00:00Z", "10-Q", 1),
        (2023, 2, "2023-06-30", "2023-07-20T20:00:00Z", "10-Q", 1),
        (2023, 3, "2023-09-30", "2023-10-20T20:00:00Z", "10-Q", 1),
        (2024, 1, "2024-03-31", "2024-04-20T20:00:00Z", "10-Q", 1),
        (2024, 2, "2024-06-30", "2024-07-20T20:00:00Z", "10-Q", 1),
        # Amendment is a new timestamped state, not a replacement at the
        # original filing's acceptance time.
        (2024, 2, "2024-06-30", "2024-07-22T20:00:00Z", "10-Q/A", 2),
        (2024, 3, "2024-09-30", "2024-10-20T20:00:00Z", "10-Q", 1),
    ]
    for year, quarter, period, accepted, form, suffix in values:
        records.append(
            {
                "ticker": "TEST",
                "cik10": CIK,
                "accession_number": accession(year, quarter, suffix),
                "form_type": form,
                "period_of_report": period,
                "filing_date": accepted[:10],
                "accepted_at": accepted,
                "available_from": accepted,
            }
        )
    # A filed-only row must not become an event.
    records.append(
        {
            "ticker": "TEST",
            "cik10": CIK,
            "accession_number": accession(2024, 4),
            "form_type": "10-K",
            "period_of_report": "2024-12-31",
            "filing_date": "2025-02-20",
            "accepted_at": "",
            "available_from": "",
        }
    )
    return pd.DataFrame(records)


def companyfacts_payload() -> dict:
    # Q2 2024 accelerates on every component; its amendment reverses most of
    # that improvement.  Q3 2024 then deteriorates versus the amended state.
    observations = {
        (2023, 1, 1): (100.0, 10.0, 8.0),
        (2023, 2, 1): (100.0, 10.0, 8.0),
        (2023, 3, 1): (100.0, 10.0, 8.0),
        (2024, 1, 1): (110.0, 11.0, 8.8),
        (2024, 2, 1): (130.0, 19.5, 12.0),
        (2024, 2, 2): (120.0, 12.0, 9.0),
        (2024, 3, 1): (105.0, 8.0, 7.0),
    }
    periods = {
        (2023, 1): ("2023-01-01", "2023-03-31"),
        (2023, 2): ("2023-04-01", "2023-06-30"),
        (2023, 3): ("2023-07-01", "2023-09-30"),
        (2024, 1): ("2024-01-01", "2024-03-31"),
        (2024, 2): ("2024-04-01", "2024-06-30"),
        (2024, 3): ("2024-07-01", "2024-09-30"),
    }
    tag_values: dict[str, list[dict]] = {
        "Revenues": [],
        "OperatingIncomeLoss": [],
        "NetCashProvidedByUsedInOperatingActivities": [],
    }
    tags = list(tag_values)
    for (year, quarter, suffix), values in observations.items():
        start, end = periods[(year, quarter)]
        form = "10-Q/A" if suffix == 2 else "10-Q"
        for tag, value in zip(tags, values):
            tag_values[tag].append(
                {
                    "start": start,
                    "end": end,
                    "val": value,
                    "accn": accession(year, quarter, suffix),
                    "fy": year,
                    "fp": f"Q{quarter}",
                    "form": form,
                    "filed": "1900-01-01",  # Must be ignored for PIT.
                }
            )
    return {
        "cik": int(CIK),
        "facts": {
            "us-gaap": {
                tag: {"units": {"USD": values}}
                for tag, values in tag_values.items()
            }
        },
    }


def build_fixture_events() -> tuple[pd.DataFrame, dict]:
    raw = json.dumps(companyfacts_payload(), sort_keys=True).encode("utf-8")
    item = quality.CompanyfactsPayload(
        cik10=CIK,
        payload=json.loads(raw),
        sha256=quality.sha256_bytes(raw),
        source_member=f"CIK{CIK}.json",
    )
    facts = quality.extract_companyfacts_flow_records(item)
    assert set(facts["accession_number"]) == {
        accession(year, quarter, suffix)
        for year, quarter, suffix in [
            (2023, 1, 1),
            (2023, 2, 1),
            (2023, 3, 1),
            (2024, 1, 1),
            (2024, 2, 1),
            (2024, 2, 2),
            (2024, 3, 1),
        ]
    }
    return quality.build_filing_quality_events(
        facts,
        filing_rows(),
        companyfacts_sources={
            CIK: {
                "companyfacts_sha256": item.sha256,
                "companyfacts_member": item.source_member,
            }
        },
        submissions_sha256="submissions-fixture-sha",
    )


def test_exact_acceptance_join_and_predeclared_event() -> None:
    events, diagnostics = build_fixture_events()
    indexed = events.set_index("accession_number")
    q2 = indexed.loc[accession(2024, 2)]
    amendment = indexed.loc[accession(2024, 2, 2)]
    q3 = indexed.loc[accession(2024, 3)]

    assert q2["sec_filing_quality_event"] == "positive", q2.to_dict()
    assert int(q2["component_coverage"]) == 4
    assert all(float(q2[column]) > 0 for column in quality.COMPONENT_COLUMNS)
    assert amendment["sec_filing_quality_event"] == "negative", amendment.to_dict()
    assert q3["sec_filing_quality_event"] == "negative", q3.to_dict()
    assert pd.Timestamp(q2["accepted_at"]) < pd.Timestamp(amendment["accepted_at"])
    assert q2["accepted_at"] == q2["available_from"]
    assert bool(q2["exact_acceptance"])
    source_hashes = json.loads(q2["source_hashes"])
    assert "companyfacts_sha256" in source_hashes
    assert source_hashes["submissions_index_sha256"] == "submissions-fixture-sha"
    assert diagnostics["missing_exact_acceptance_count"] == 1
    assert diagnostics["filed_date_fallback_used"] is False
    assert accession(2024, 4) not in set(events["accession_number"])


def test_missing_components_are_neutral() -> None:
    events, _ = build_fixture_events()
    first = events.sort_values("accepted_at").iloc[0]
    assert first["sec_filing_quality_event"] == "neutral"
    assert int(first["component_coverage"]) == 0


def test_multi_share_class_cik_replicates_event_deterministically() -> None:
    raw = json.dumps(companyfacts_payload(), sort_keys=True).encode("utf-8")
    item = quality.CompanyfactsPayload(CIK, json.loads(raw), quality.sha256_bytes(raw), f"CIK{CIK}.json")
    facts = quality.extract_companyfacts_flow_records(item)
    filings = filing_rows()
    second_class = filings.copy()
    second_class["ticker"] = "TEST.B"
    events, diagnostics = quality.build_filing_quality_events(
        facts,
        pd.concat([filings, second_class], ignore_index=True),
        companyfacts_sources={CIK: {"companyfacts_sha256": item.sha256, "companyfacts_member": item.source_member}},
        submissions_sha256="fixture",
    )
    per_accession = events.groupby("accession_number")["ticker"].agg(lambda values: sorted(values.tolist()))
    assert per_accession.map(lambda values: values == ["TEST", "TEST.B"]).all()
    compared = events.pivot(index="accession_number", columns="ticker", values="sec_filing_quality_event")
    assert compared["TEST"].equals(compared["TEST.B"])
    component_columns = list(quality.COMPONENT_COLUMNS) + ["component_coverage"]
    for column in component_columns:
        compared_component = events.pivot(index="accession_number", columns="ticker", values=column)
        assert np.allclose(compared_component["TEST"], compared_component["TEST.B"], equal_nan=True)
    assert diagnostics["multi_ticker_issuer_cik_count"] == 1
    assert diagnostics["source_screen_issuer_independence"] is True


def test_report_period_mismatch_does_not_select_another_period() -> None:
    raw = json.dumps(companyfacts_payload(), sort_keys=True).encode("utf-8")
    item = quality.CompanyfactsPayload(
        cik10=CIK,
        payload=json.loads(raw),
        sha256=quality.sha256_bytes(raw),
        source_member=f"CIK{CIK}.json",
    )
    facts = quality.extract_companyfacts_flow_records(item)
    prepared, _ = quality.prepare_filings(filing_rows().head(1))
    filing = prepared.iloc[0].copy()
    filing["period"] = pd.Timestamp("2099-12-31")
    assert quality._select_current_facts(filing, facts).empty


def test_operating_margin_requires_matched_revenue_and_income_periods() -> None:
    raw = json.dumps(companyfacts_payload(), sort_keys=True).encode("utf-8")
    item = quality.CompanyfactsPayload(CIK, json.loads(raw), quality.sha256_bytes(raw), f"CIK{CIK}.json")
    facts = quality.extract_companyfacts_flow_records(item)
    mismatch = facts["accession_number"].eq(accession(2024, 2)) & facts["field_name"].eq("op_income")
    facts.loc[mismatch, "start"] = pd.Timestamp("2024-04-15")
    events, _ = quality.build_filing_quality_events(
        facts,
        filing_rows(),
        companyfacts_sources={CIK: {"companyfacts_sha256": item.sha256, "companyfacts_member": item.source_member}},
        submissions_sha256="fixture",
    )
    row = events.set_index("accession_number").loc[accession(2024, 2)]
    assert pd.isna(row["operating_margin_yoy_change"])
    assert pd.isna(row["operating_margin_yoy_change_change"])


def test_future_availability_fails_closed() -> None:
    events, _ = build_fixture_events()
    checked = events.head(1).copy()
    checked["decision_time"] = "2020-01-01T00:00:00Z"
    try:
        quality.assert_no_future_availability(checked)
    except quality.DataContractError as exc:
        assert "future or missing availability" in str(exc)
    else:
        raise AssertionError("future SEC event was not rejected")


def test_string_false_exact_acceptance_fails_closed() -> None:
    events, _ = build_fixture_events()
    checked = events.head(1).copy().astype({"exact_acceptance": "object"})
    checked.loc[checked.index[0], "exact_acceptance"] = "False"
    try:
        quality.assert_event_contract(checked)
    except quality.DataContractError as exc:
        assert "exact-acceptance contract violation" in str(exc)
    else:
        raise AssertionError("string False exact_acceptance passed")


def test_source_screen_uses_first_close_after_exact_acceptance_and_is_underpowered() -> None:
    events, _ = build_fixture_events()
    dates = pd.bdate_range("2023-01-02", periods=650)
    prices = pd.DataFrame(
        {
            "ticker": "TEST",
            "date": dates,
            "adjusted_close": np.linspace(100.0, 200.0, len(dates)),
        }
    )
    labeled, summary = quality.source_screen(
        events,
        prices,
        oos_start=quality.DEFAULT_OOS_START,
        oos2_start=quality.DEFAULT_OOS2_START,
        bootstrap_iterations=20,
    )
    accepted_dates = pd.to_datetime(labeled["accepted_at"], utc=True).dt.tz_convert(None).dt.normalize()
    entry_dates = pd.to_datetime(labeled["entry_date"], errors="coerce")
    assert (entry_dates.dropna().reset_index(drop=True) > accepted_dates[entry_dates.notna()].reset_index(drop=True)).all()
    assert summary["verdict"] == "UNDERPOWERED"
    assert summary["labels_are_not_features"] is True
    assert summary["segments"]["oos2"]["event_count"] >= summary["segments"]["oos"]["event_count"]


def test_event_time_entry_uses_same_day_preclose_and_next_day_after_close() -> None:
    template = build_fixture_events()[0].iloc[0].to_dict()
    events = pd.DataFrame(
        [
            {
                **template,
                "accession_number": "pre",
                "accepted_at": "2024-07-01T19:00:00Z",
                "available_from": "2024-07-01T19:00:00Z",
            },
            {
                **template,
                "accession_number": "post",
                "accepted_at": "2024-07-01T21:00:00Z",
                "available_from": "2024-07-01T21:00:00Z",
            },
        ]
    )
    prices = pd.DataFrame(
        {
            "ticker": ["TEST", "TEST", "TEST"],
            "date": pd.to_datetime(["2024-07-01", "2024-07-02", "2024-07-03"]),
            "adjusted_close": [100.0, 101.0, 102.0],
        }
    )
    labeled = quality.label_forward_returns(events, prices).set_index("accession_number")
    assert labeled.loc["pre", "entry_date"] == "2024-07-01"
    assert labeled.loc["post", "entry_date"] == "2024-07-02"


def test_event_time_entry_respects_nyse_early_close() -> None:
    template = build_fixture_events()[0].iloc[0].to_dict()
    events = pd.DataFrame(
        [
            {
                **template,
                "accession_number": "half-day-post-close",
                "accepted_at": "2024-07-03T18:00:00Z",
                "available_from": "2024-07-03T18:00:00Z",
            }
        ]
    )
    prices = pd.DataFrame(
        {
            "ticker": ["TEST", "TEST"],
            "date": pd.to_datetime(["2024-07-03", "2024-07-05"]),
            "adjusted_close": [100.0, 101.0],
        }
    )
    labeled = quality.label_forward_returns(events, prices)
    assert labeled.iloc[0]["entry_date"] == "2024-07-05"


def test_event_before_price_cache_does_not_shift_to_first_cached_close() -> None:
    template = build_fixture_events()[0].iloc[0].to_dict()
    events = pd.DataFrame(
        [
            {
                **template,
                "accession_number": "before-cache",
                "accepted_at": "2020-01-02T15:00:00Z",
                "available_from": "2020-01-02T15:00:00Z",
            }
        ]
    )
    dates = pd.bdate_range("2021-01-04", periods=150)
    prices = pd.DataFrame(
        {
            "ticker": "TEST",
            "date": dates,
            "adjusted_close": np.linspace(100.0, 130.0, len(dates)),
        }
    )
    labeled = quality.label_forward_returns(events, prices)
    assert labeled.iloc[0]["entry_date"] == ""
    assert pd.isna(labeled.iloc[0]["forward_return_21d"])


def test_hashed_broker_price_cache_resolves_ticker_identity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp)
        pd.DataFrame(
            {"Close": [100.0, 101.0], "Adj Close": [99.0, 100.0]},
            index=pd.to_datetime(["2024-07-01", "2024-07-02"]),
        ).to_parquet(cache / px_cache_name("TEST"))
        loaded = quality.load_prices(cache, wanted_tickers=["TEST"])
        assert loaded["ticker"].unique().tolist() == ["TEST"]
        assert loaded["adjusted_close"].tolist() == [99.0, 100.0]


def test_source_screen_power_and_sign_boundaries() -> None:
    def metrics(count: int = 100, weeks: int = 12, spread: float = 0.01, lower: float = 0.0) -> dict:
        row = {
            "positive_count": count,
            "negative_count": count,
            "filing_week_count": weeks,
            "positive_minus_negative": spread,
            "filing_week_cluster_bootstrap_95_lower": lower,
        }
        return {name: {"horizon_63": dict(row)} for name in ("full", "oos", "oos2")}

    assert quality.classify_source_screen(metrics(count=99)) == "UNDERPOWERED"
    assert quality.classify_source_screen(metrics(weeks=11)) == "UNDERPOWERED"
    assert quality.classify_source_screen(metrics()) == "PASS_SOURCE_SCREEN"
    assert quality.classify_source_screen(metrics(spread=-0.001)) == "REJECT_SOURCE_SCREEN"
    assert quality.classify_source_screen(metrics(lower=-0.0001)) == "REJECT_SOURCE_SCREEN"


def test_source_screen_counts_multi_share_class_accession_once() -> None:
    labeled = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "cik10": "0000000001",
                "accession_number": "0000000001-26-000001",
                "accepted_at": "2026-01-05T21:00:00Z",
                "available_from": "2026-01-05T21:00:00Z",
                "sec_filing_quality_event": "positive",
                "filing_week": "2026-01-05",
                "entry_date": "2026-01-06",
                "forward_return_21d": value,
                "forward_return_63d": value,
                "forward_return_126d": value,
            }
            for ticker, value in (("GOOG", 0.10), ("GOOGL", 0.20))
        ]
    )
    collapsed = quality.issuer_independent_source_rows(labeled)
    assert len(collapsed) == 1
    assert collapsed.iloc[0]["share_class_ticker_count"] == 2
    assert np.isclose(collapsed.iloc[0]["forward_return_63d"], 0.15)


def test_vectorized_week_bootstrap_matches_naive_cluster_resampling() -> None:
    frame = pd.DataFrame(
        [
            {"filing_week": week, "sec_filing_quality_event": event, "ret": value}
            for week, values in {
                "2026-01-05": (0.10, -0.02),
                "2026-01-12": (0.04, -0.01),
                "2026-01-19": (-0.01, 0.02),
                "2026-01-26": (0.08, 0.00),
            }.items()
            for event, value in zip(("positive", "negative"), values)
        ]
    )
    iterations = 200
    seed = 99
    actual = quality.cluster_bootstrap_spread(frame, "ret", iterations=iterations, seed=seed)
    weeks = sorted(frame["filing_week"].unique())
    sampled = np.random.default_rng(seed).integers(0, len(weeks), size=(iterations, len(weeks)))
    naive = []
    for draw in sampled:
        selected = pd.concat([frame[frame["filing_week"].eq(weeks[index])] for index in draw], ignore_index=True)
        positive = selected.loc[selected["sec_filing_quality_event"].eq("positive"), "ret"]
        negative = selected.loc[selected["sec_filing_quality_event"].eq("negative"), "ret"]
        naive.append(float(positive.mean() - negative.mean()))
    expected = (float(np.quantile(naive, 0.025)), float(np.quantile(naive, 0.975)))
    assert np.allclose(actual, expected)


def test_missing_exact_horizon_session_does_not_shift_label() -> None:
    template = build_fixture_events()[0].iloc[0].to_dict()
    event = pd.DataFrame(
        [
            {
                **template,
                "accepted_at": "2024-07-01T19:00:00Z",
                "available_from": "2024-07-01T19:00:00Z",
            }
        ]
    )
    schedule = quality.mcal.get_calendar("NYSE").schedule("2024-07-01", "2025-03-31")
    dates = pd.DatetimeIndex(schedule.index[:140]).tz_localize(None)
    missing_21d_date = dates[21]
    available_dates = dates[dates != missing_21d_date]
    prices = pd.DataFrame(
        {"ticker": "TEST", "date": available_dates, "adjusted_close": np.arange(len(available_dates)) + 100.0}
    )
    labeled = quality.label_forward_returns(event, prices)
    assert pd.isna(labeled.iloc[0]["forward_return_21d"])
    assert pd.notna(labeled.iloc[0]["forward_return_63d"])


def test_raw_close_only_price_input_is_rejected() -> None:
    try:
        quality._normalize_prices(
            pd.DataFrame({"ticker": ["TEST"], "date": ["2024-07-01"], "close": [100.0]})
        )
    except quality.DataContractError as exc:
        assert "adjusted-close" in str(exc)
    else:
        raise AssertionError("raw close-only source-screen input was accepted")


def test_append_only_rejects_conflicting_event() -> None:
    events, _ = build_fixture_events()
    changed = events.copy()
    changed.loc[0, "sec_filing_quality_event"] = "positive"
    try:
        quality.merge_append_only(events, changed)
    except quality.DataContractError as exc:
        assert "append-only conflict" in str(exc)
    else:
        raise AssertionError("append-only conflict was silently overwritten")


def test_cli_writes_only_to_explicit_temp_output() -> None:
    # Exercise the append-only writer without touching repository outputs.
    events, diagnostics = build_fixture_events()
    events = events.copy()
    if len(events) >= 2:
        events.loc[events.index[0], "fiscal_year"] = np.float64(2024.0)
        events.loc[events.index[1], "fiscal_year"] = ""
    with tempfile.TemporaryDirectory() as tmp:
        paths = quality.write_outputs(events, diagnostics, Path(tmp))
        saved = pd.read_parquet(paths["events_parquet"])
        assert len(saved) == len(events)
        assert set(quality.EVENT_COLUMNS).issubset(saved.columns)
        assert saved["fiscal_year"].map(type).eq(str).all()
        second = quality.write_outputs(events, diagnostics, Path(tmp))
        assert len(pd.read_parquet(second["events_parquet"])) == len(events)
        screened = quality.write_outputs(
            events,
            diagnostics,
            Path(tmp),
            labeled=events.copy(),
            screen_summary={"verdict": "UNDERPOWERED"},
            screen_provenance={"price_input_path": "fixture", "price_input_sha256": "fixture-hash"},
        )
        screen = json.loads(Path(screened["source_screen_summary"]).read_text(encoding="utf-8"))
        assert screen["source_screen_rows_sha256"] == quality.sha256_file(Path(screened["source_screen_rows"]))
        assert screen["source_screen_producer_sha256"] == quality.source_screen_producer_fingerprint()[0]
        assert screen["price_input_sha256"] == "fixture-hash"


if __name__ == "__main__":
    test_exact_acceptance_join_and_predeclared_event()
    test_missing_components_are_neutral()
    test_multi_share_class_cik_replicates_event_deterministically()
    test_report_period_mismatch_does_not_select_another_period()
    test_operating_margin_requires_matched_revenue_and_income_periods()
    test_future_availability_fails_closed()
    test_string_false_exact_acceptance_fails_closed()
    test_source_screen_uses_first_close_after_exact_acceptance_and_is_underpowered()
    test_event_time_entry_uses_same_day_preclose_and_next_day_after_close()
    test_event_time_entry_respects_nyse_early_close()
    test_event_before_price_cache_does_not_shift_to_first_cached_close()
    test_hashed_broker_price_cache_resolves_ticker_identity()
    test_source_screen_power_and_sign_boundaries()
    test_source_screen_counts_multi_share_class_accession_once()
    test_vectorized_week_bootstrap_matches_naive_cluster_resampling()
    test_missing_exact_horizon_session_does_not_shift_label()
    test_raw_close_only_price_input_is_rejected()
    test_append_only_rejects_conflicting_event()
    test_cli_writes_only_to_explicit_temp_output()
    print("sec_filing_quality_event_smoke: PASS")
