from __future__ import annotations

import tempfile
import unittest
from unittest import mock
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run287_scored_latest_refresh import (
    PREFLIGHT_INPUT_LABELS,
    advance_feature_available_from,
    build_price_cache_input_audit,
    changed_preflight_inputs,
    changed_price_cache_inputs,
    drop_stale_prediction_columns,
    max_price_date_from_metadata,
    merge_current_vintage,
    lifecycle_download_start,
    normalize_price,
    nyse_session_close_utc,
    parse_provider_symbol_overrides,
    validate_preflight_input_hashes,
    validate_ticker_identity,
)
from tools import run_run287_scored_latest_refresh as refresh


def prices(start: str, periods: int, scale: float = 1.0) -> pd.DataFrame:
    index = pd.bdate_range(start, periods=periods)
    close = np.linspace(100.0, 120.0, periods)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Adj Close": close * scale,
            "Volume": np.full(periods, 1000),
        },
        index=index,
    )


class ScoredLatestRefreshSmoke(unittest.TestCase):
    def test_refreshed_features_cannot_keep_pre_close_availability(self) -> None:
        exact_close = nyse_session_close_utc(pd.Timestamp("2026-07-13"))
        self.assertEqual(exact_close, pd.Timestamp("2026-07-13T20:00:00Z"))
        frame = pd.DataFrame(
            {
                "ticker": ["OLD", "MISSING", "FUTURE"],
                "feature_available_from": [
                    "2026-07-10T20:00:00Z",
                    "",
                    "2026-07-14T12:00:00Z",
                ],
            }
        )
        refreshed = advance_feature_available_from(
            frame,
            refreshed_feature_available_at=exact_close,
        )
        available = pd.to_datetime(
            refreshed["feature_available_from"], utc=True
        )
        self.assertEqual(available.iloc[0], exact_close)
        self.assertEqual(available.iloc[1], exact_close)
        self.assertEqual(
            available.iloc[2], pd.Timestamp("2026-07-14T12:00:00Z")
        )
        self.assertTrue((available >= exact_close).all())

    def test_metadata_date_and_source_prefix_are_preserved(self) -> None:
        source = prices("2022-01-03", 800, scale=0.5)
        provider = prices(str(source.index[-20].date()), 25, scale=1.0)
        # Align raw close values across the overlap; only adjusted vintage differs.
        provider.loc[:, "Close"] = source.loc[provider.index.intersection(source.index), "Close"].tolist() + list(
            provider.loc[provider.index.difference(source.index), "Close"]
        )
        provider.loc[:, "Open"] = provider["Close"] - 0.5
        provider.loc[:, "High"] = provider["Close"] + 1.0
        provider.loc[:, "Low"] = provider["Close"] - 1.0
        provider.loc[:, "Adj Close"] = provider["Close"]
        session = provider.index[-1]
        merged, audit = merge_current_vintage(source, provider, session_date=session)
        self.assertEqual(merged.index.max(), session)
        self.assertTrue(audit["source_present"])
        self.assertGreaterEqual(audit["provider_overlap_row_count"], 5)
        prefix_date = provider.index.min() - pd.offsets.BDay(1)
        self.assertAlmostEqual(
            float(merged.loc[prefix_date, "Adj Close"]),
            float(source.loc[prefix_date, "Adj Close"]) * 2.0,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.parquet"
            normalize_price(merged).to_parquet(path)
            self.assertEqual(max_price_date_from_metadata(path), session.normalize())

    def test_missing_exact_session_fails_closed(self) -> None:
        source = prices("2022-01-03", 800)
        provider = source.tail(20)
        with self.assertRaisesRegex(ValueError, "exact_session_close_missing"):
            merge_current_vintage(
                source,
                provider,
                session_date=provider.index[-1] + pd.offsets.BDay(1),
            )

    def test_lifecycle_cutover_preserves_predecessor_prefix(self) -> None:
        source = prices("2022-01-03", 800)
        last_trade = source.index[-2]
        effective = source.index[-1]
        provider = prices(str(source.index[-10].date()), 12)
        provider.loc[provider.index < effective, "Close"] = 999.0
        provider.loc[provider.index < effective, "Adj Close"] = 999.0
        session = provider.index[-1]
        merged, audit = merge_current_vintage(
            source,
            provider,
            session_date=session,
            provider_symbol_link={
                "last_trading_date": last_trade.date().isoformat(),
                "effective_date": effective.date().isoformat(),
            },
        )
        self.assertEqual(float(merged.loc[last_trade, "Close"]), float(source.loc[last_trade, "Close"]))
        self.assertEqual(float(merged.loc[effective, "Close"]), float(provider.loc[effective, "Close"]))
        self.assertTrue(audit["lifecycle_cutover_applied"])

    def test_old_lifecycle_cutover_requires_continuous_successor_history(self) -> None:
        source = prices("2022-01-03", 800)
        last_trade = source.index[-2]
        effective = source.index[-1]
        provider = prices(str((effective + pd.Timedelta(days=30)).date()), 10)
        with self.assertRaisesRegex(ValueError, "successor_history_gap_after_cutover"):
            merge_current_vintage(
                source,
                provider,
                session_date=provider.index[-1],
                provider_symbol_link={
                    "last_trading_date": last_trade.date().isoformat(),
                    "effective_date": effective.date().isoformat(),
                },
            )
        self.assertEqual(
            lifecycle_download_start(
                "2026-01-02",
                ["OLD"],
                {"OLD": {"effective_date": effective.date().isoformat()}},
            ),
            effective.date().isoformat(),
        )

    def test_scorer_requires_external_pre_lifecycle_count(self) -> None:
        source = (ROOT / "tools" / "run_run287_scored_latest_refresh.py").read_text(
            encoding="utf-8"
        )
        upstream = (ROOT / "tools" / "run_run287_exact_packet_upstream.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("--expected-pre-lifecycle-context-count", source)
        self.assertIn("--expected-pre-lifecycle-context-count", upstream)
        self.assertIn("base_context_external_count_contract_failed", source)

    def test_same_count_ticker_substitution_fails_external_identity(self) -> None:
        expected = refresh.core_candidate_ticker_set_sha256(["AAA", "BBB"])
        ready = validate_ticker_identity(
            label="pre_lifecycle_context",
            tickers=["AAA", "BBB"],
            expected_count=2,
            expected_ticker_set_sha256=expected,
        )
        self.assertTrue(ready["matches"])
        with self.assertRaisesRegex(
            ValueError, "pre_lifecycle_context_ticker_identity_contract_failed"
        ):
            validate_ticker_identity(
                label="pre_lifecycle_context",
                tickers=["AAA", "CCC"],
                expected_count=2,
                expected_ticker_set_sha256=expected,
            )

    def test_model_or_base_input_change_is_detected_before_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_paths = {}
            expected = {}
            for label in PREFLIGHT_INPUT_LABELS:
                path = root / label
                path.write_text(f"{label}:frozen\n", encoding="utf-8")
                input_paths[label] = path
                expected[label] = refresh.checkpoint.sha256_file(path)
            audit = validate_preflight_input_hashes(input_paths, expected)
            self.assertEqual(changed_preflight_inputs(audit), [])

            input_paths["model_meta"].write_text(
                "model_meta:mutated\n", encoding="utf-8"
            )
            self.assertIn(
                "input_changed_before_scorer_ready:model_meta",
                changed_preflight_inputs(audit),
            )
            input_paths["base_selection_context"].write_text(
                "same-row-count:different-ticker\n", encoding="utf-8"
            )
            self.assertIn(
                "input_changed_before_scorer_ready:base_selection_context",
                changed_preflight_inputs(audit),
            )

    def test_consumed_price_cache_change_is_detected_before_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            source = cache / refresh.px_cache_name("AAA")
            source.write_bytes(b"frozen-price-history")
            audit = build_price_cache_input_audit(["AAA"], cache)
            self.assertEqual(changed_price_cache_inputs(audit), [])
            source.write_bytes(b"mutated-price-history")
            self.assertEqual(
                changed_price_cache_inputs(audit),
                ["price_cache_changed_before_scorer_ready:AAA"],
            )

    def test_provider_symbol_override_is_explicit(self) -> None:
        self.assertEqual(parse_provider_symbol_overrides(["OLD=NEW"]), {"OLD": "NEW"})
        with self.assertRaisesRegex(ValueError, "invalid provider symbol override"):
            parse_provider_symbol_overrides(["OLD"])

    def test_stale_predictions_are_removed_before_registered_merge(self) -> None:
        frame = pd.DataFrame(
            {
                "ticker": ["A"],
                "pred_lin_ret": [0.0],
                "pred_cat_p": [0.0],
                "score": [1.0],
            }
        )
        clean = drop_stale_prediction_columns(frame)
        self.assertEqual(clean.columns.tolist(), ["ticker", "score"])

    def test_blocked_manifest_returns_nonzero(self) -> None:
        with mock.patch.object(refresh, "parse_args", return_value=object()), mock.patch.object(
            refresh,
            "build",
            return_value={"status": "BLOCKED_CORE_CANDIDATE_COVERAGE"},
        ), mock.patch("builtins.print"):
            self.assertEqual(refresh.main(), 2)
        with mock.patch.object(refresh, "parse_args", return_value=object()), mock.patch.object(
            refresh,
            "build",
            return_value={"status": "READY_RESEARCH_SCORED_LATEST"},
        ), mock.patch("builtins.print"):
            self.assertEqual(refresh.main(), 0)


if __name__ == "__main__":
    unittest.main()
