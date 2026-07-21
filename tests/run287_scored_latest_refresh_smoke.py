from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_run287_scored_latest_refresh import (
    drop_stale_prediction_columns,
    max_price_date_from_metadata,
    merge_current_vintage,
    lifecycle_download_start,
    normalize_price,
    parse_provider_symbol_overrides,
)


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


if __name__ == "__main__":
    unittest.main()
