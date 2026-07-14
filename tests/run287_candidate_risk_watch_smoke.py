#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_candidate_risk_watch import (  # noqa: E402
    build_isolated_cache,
    candidate_metadata,
    deterministic_rows,
    evaluate_candidates,
    render_report,
    sha256_file,
    source_audits_unchanged,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


ASOF = pd.Timestamp("2026-07-13")


def price_frame(close: np.ndarray, end: pd.Timestamp) -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=len(close))
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Adj Close": close,
            "Volume": 1_000_000,
        },
        index=dates,
    )


def main() -> None:
    comparison = pd.DataFrame(
        [
            {
                "ticker": "normal",
                "scenario": "main_strict",
                "portfolio_kind": "main",
                "advisory_weight": 0.04,
                "marked_weight": 0.0,
                "delta_vs_marked": 0.04,
            },
            {
                "ticker": "NORMAL",
                "scenario": "main_bridge",
                "portfolio_kind": "main",
                "advisory_weight": 0.03,
                "marked_weight": 0.0,
                "delta_vs_marked": 0.03,
            },
            {
                "ticker": "SHOCK",
                "scenario": "concentrated",
                "portfolio_kind": "concentrated",
                "advisory_weight": 0.05,
                "marked_weight": 0.0,
                "delta_vs_marked": 0.05,
            },
            {
                "ticker": "EXISTING",
                "scenario": "main_strict",
                "portfolio_kind": "main",
                "advisory_weight": 0.05,
                "marked_weight": 0.02,
                "delta_vs_marked": 0.03,
            },
        ]
    )
    candidates = candidate_metadata(comparison)
    assert set(candidates["ticker"]) == {"NORMAL", "SHOCK"}
    normal = candidates.set_index("ticker").loc["NORMAL"]
    assert int(normal["scenario_count"]) == 2
    assert normal["scenarios"] == "main_bridge|main_strict"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source_cache = root / "source"
        macro_cache = root / "macro"
        isolated = root / "isolated"
        source_cache.mkdir()
        macro_cache.mkdir()

        sessions = 340
        phase = np.arange(sessions)
        full_normal = 80.0 * np.cumprod(1.0 + 0.001 + 0.003 * np.sin(phase))
        full_normal[-1] = full_normal[-2] * 1.01
        full_shock = 90.0 * np.cumprod(1.0 + 0.001 + 0.003 * np.sin(phase + 0.5))
        full_shock[-1] = 75.0
        full_spy = 100.0 * np.cumprod(1.0 + 0.0007 + 0.002 * np.sin(phase + 1.0))

        price_rows = []
        provider_frames = []
        for ticker, close in (("NORMAL", full_normal), ("SHOCK", full_shock)):
            full = price_frame(close, ASOF)
            base = full.iloc[:-1].copy()
            source = source_cache / px_cache_name(ticker)
            base.to_parquet(source)
            price_rows.append(
                {"ticker": ticker.lower(), "path": str(source), "sha256": sha256_file(source)}
            )
            provider = full.iloc[-130:].reset_index(names="Date")
            future = provider.iloc[-1:].copy()
            future["Date"] = pd.Timestamp("2026-07-14", tz="UTC")
            provider_frames.append(
                pd.concat([provider.assign(ticker=ticker), future.assign(ticker=ticker)], ignore_index=True)
            )

        spy_source = macro_cache / px_cache_name("SPY")
        price_frame(full_spy, ASOF).to_parquet(spy_source)
        spy_hash = sha256_file(spy_source)
        provider = pd.concat(provider_frames, ignore_index=True)
        price_map = pd.DataFrame(price_rows)
        source_hashes_before = {row["ticker"]: sha256_file(Path(row["path"])) for row in price_rows}

        audit, failures = build_isolated_cache(
            candidates=candidates,
            price_map=price_map,
            provider=provider,
            macro_cache=macro_cache,
            expected_spy_sha256=spy_hash,
            isolated_cache=isolated,
            valuation=ASOF,
            minimum_overlap=20,
            maximum_relative_error=1e-5,
        )
        assert failures == [], failures
        candidate_audit = audit[audit["role"].eq("proposed_new_entry")]
        assert candidate_audit["provider_overlap_count"].ge(20).all()
        assert candidate_audit["provider_future_rows_excluded"].eq(1).all()
        assert candidate_audit["isolated_date_max"].eq("2026-07-13").all()
        assert source_hashes_before == {
            row["ticker"]: sha256_file(Path(row["path"])) for row in price_rows
        }

        base_contract = json.loads(
            (ROOT / "docs" / "run287_holding_risk_watch_contract.json").read_text(
                encoding="utf-8"
            )
        )
        candidate_contract = json.loads(
            (ROOT / "docs" / "run287_candidate_risk_watch_contract.json").read_text(
                encoding="utf-8"
            )
        )
        first = evaluate_candidates(
            candidates,
            isolated,
            base_contract,
            candidate_contract,
            ASOF,
            "2026-07-13T20:30:00Z",
        )
        second = evaluate_candidates(
            candidates,
            isolated,
            base_contract,
            candidate_contract,
            ASOF,
            "2026-07-13T20:30:00Z",
        )
        assert deterministic_rows(first, second)
        indexed = first.set_index("ticker")
        assert indexed.loc["SHOCK", "risk_state"] == "ALERT"
        assert bool(indexed.loc["SHOCK", "idiosyncratic_shock"]) is True
        assert indexed.loc["NORMAL", "risk_state"] == "NORMAL", indexed.loc[
            "NORMAL"
        ].to_dict()
        assert first["price_exact_asof"].eq(True).all()
        assert first["portfolio_transition_allowed"].eq(False).all()
        assert first["orders_generated"].eq(False).all()
        assert first["selector_weights_changed"].eq(False).all()
        report = render_report(
            {
                "status": "READY_CANDIDATE_RISK_REVIEW_ONLY",
                "as_of_date": "2026-07-13",
                "candidate_count": 2,
                "alert_count": 1,
                "watch_count": 0,
                "data_insufficient_count": 0,
                "normal_count": 1,
            },
            first,
        )
        assert "idiosyncratic_shock<br>opening_gap_shock" in report

        source_audits = {
            row["ticker"]: {"path": row["path"], "sha256": source_hashes_before[row["ticker"]]}
            for row in price_rows
        }
        assert source_audits_unchanged(source_audits)
        changed = dict(source_audits)
        changed["normal"] = dict(changed["normal"], sha256="0" * 64)
        assert not source_audits_unchanged(changed)

        bad_provider = provider.copy()
        provider_dates = pd.to_datetime(bad_provider["Date"], errors="coerce", utc=True).dt.tz_convert(None)
        mask = bad_provider["ticker"].eq("NORMAL") & provider_dates.lt(ASOF)
        bad_provider.loc[mask, ["Close", "Adj Close"]] *= 1.02
        _, bad_failures = build_isolated_cache(
            candidates=candidates,
            price_map=price_map,
            provider=bad_provider,
            macro_cache=macro_cache,
            expected_spy_sha256=spy_hash,
            isolated_cache=root / "bad_isolated",
            valuation=ASOF,
            minimum_overlap=20,
            maximum_relative_error=1e-5,
        )
        assert any(item.startswith("overlap_mismatch:NORMAL:") for item in bad_failures)

        _, spy_failures = build_isolated_cache(
            candidates=candidates,
            price_map=price_map,
            provider=provider,
            macro_cache=macro_cache,
            expected_spy_sha256="0" * 64,
            isolated_cache=root / "bad_spy",
            valuation=ASOF,
            minimum_overlap=20,
            maximum_relative_error=1e-5,
        )
        assert "spy_source_hash" in spy_failures

    print("run287_candidate_risk_watch_smoke: PASS")


if __name__ == "__main__":
    main()
