from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_sec_institutional_signals import (  # noqa: E402
    add_13f_position_deltas,
    append_13f_exit_tombstones,
    build_13f_signal,
    prepare_13f_holdings,
)


def row(
    *,
    manager: str = "1",
    ticker: str = "XYZ",
    period: str = "2026-03-31",
    available: str = "2026-05-15T20:00:00Z",
    accession: str = "base-q1",
    shares: object = 100.0,
    value: object = 1_000.0,
    cusip: str = "123456789",
    title: str = "COM",
    put_call: str = "",
    share_type: str = "SH",
    discretion: str = "SOLE",
    other_manager: str = "",
    form_type: str = "13F-HR",
    amendment_type: str = "",
) -> dict[str, object]:
    return {
        "manager_cik": manager,
        "manager_name": f"MGR-{manager}",
        "ticker_mapped": ticker,
        "report_period": period,
        "available_from": available,
        "accepted_at": available,
        "source_accession": accession,
        "form_type": form_type,
        "amendment_type": amendment_type,
        "shares": shares,
        "market_value_usd": value,
        "cusip": cusip,
        "title_of_class": title,
        "put_call": put_call,
        "share_type": share_type,
        "investment_discretion": discretion,
        "other_manager": other_manager,
    }


def q2(**kwargs) -> dict[str, object]:
    defaults = {
        "period": "2026-06-30",
        "available": "2026-08-14T20:00:00Z",
        "accession": "base-q2",
    }
    defaults.update(kwargs)
    return row(**defaults)


class SecurityIdentityPreservationTests(unittest.TestCase):
    def test_cash_and_call_same_ticker_are_both_preserved(self) -> None:
        frame = pd.DataFrame([
            row(),
            row(put_call="CALL", shares=500, value=9_000),
        ])
        prepared = prepare_13f_holdings(frame)
        self.assertEqual(len(prepared), 2)
        self.assertEqual(set(prepared["put_call"]), {"", "CALL"})
        self.assertEqual(prepared["security_identity"].nunique(), 2)

    def test_cash_put_call_stock_signal_uses_cash_only(self) -> None:
        frame = pd.DataFrame([
            row(shares=100, value=1_000),
            row(put_call="CALL", shares=900, value=50_000),
            row(put_call="PUT", shares=800, value=40_000),
        ])
        signal = build_13f_signal(frame).set_index("ticker")
        self.assertEqual(int(signal.loc["XYZ", "sec_13f_manager_count"]), 1)
        self.assertEqual(float(signal.loc["XYZ", "sec_13f_total_value_usd"]), 1_000.0)
        self.assertEqual(float(signal.loc["XYZ", "sec_13f_shares_delta"]), 100.0)

    def test_call_change_does_not_change_cash_stock_delta(self) -> None:
        frame = pd.DataFrame([
            row(shares=100, value=1_000),
            row(put_call="CALL", shares=100, value=3_000),
            q2(shares=100, value=1_100),
            q2(put_call="CALL", shares=1_000, value=30_000),
        ])
        signal = build_13f_signal(frame).set_index("ticker")
        self.assertEqual(float(signal.loc["XYZ", "sec_13f_shares_delta"]), 0.0)
        self.assertEqual(int(signal.loc["XYZ", "sec_13f_buying_manager_count"]), 0)

    def test_cash_increase_measured_on_exact_security_identity(self) -> None:
        frame = pd.DataFrame([row(shares=100), q2(shares=140, value=1_500)])
        deltas = add_13f_position_deltas(frame)
        latest = deltas.sort_values("report_period_ts").iloc[-1]
        self.assertEqual(float(latest["shares_delta"]), 40.0)
        self.assertTrue(bool(latest["added_position"]))

    def test_share_classes_and_cusips_do_not_keep_last_collapse(self) -> None:
        frame = pd.DataFrame([
            row(cusip="123456789", title="COM CLASS A", shares=100),
            row(cusip="12345678A", title="COM CLASS B", shares=200),
        ])
        prepared = prepare_13f_holdings(frame)
        self.assertEqual(len(prepared), 2)
        self.assertEqual(prepared["security_identity"].nunique(), 2)

    def test_exact_duplicate_identity_fails_closed(self) -> None:
        frame = pd.DataFrame([row(accession="a"), row(accession="b")])
        with self.assertRaisesRegex(ValueError, "duplicate_security_identity"):
            prepare_13f_holdings(frame)

    def test_exit_tombstone_preserves_prior_security_identity(self) -> None:
        prepared = prepare_13f_holdings(pd.DataFrame([
            row(cusip="123456789", title="COM", shares=100),
            q2(ticker="ABC", cusip="987654321", title="COM", shares=50),
        ]))
        with_exits = append_13f_exit_tombstones(prepared)
        xyz = with_exits[(with_exits["ticker"] == "XYZ") & with_exits["synthetic_exit"]]
        self.assertEqual(len(xyz), 1)
        exit_row = xyz.iloc[0]
        self.assertEqual(exit_row["cusip"], "123456789")
        self.assertEqual(exit_row["put_call"], "")
        self.assertEqual(exit_row["title_of_class"], "COM")
        self.assertTrue(str(exit_row["security_identity"]).startswith("123456789|COM||SH|"))

    def test_cash_exit_does_not_convert_call_identity_into_cash(self) -> None:
        frame = pd.DataFrame([
            row(shares=100),
            row(put_call="CALL", shares=200, value=5_000),
            q2(put_call="CALL", shares=200, value=5_500),
        ])
        deltas = add_13f_position_deltas(frame)
        cash_exit = deltas[(deltas["ticker"] == "XYZ") & deltas["cash_equity_eligible"] & deltas["synthetic_exit"]]
        call_rows = deltas[(deltas["ticker"] == "XYZ") & (deltas["put_call"] == "CALL")]
        self.assertEqual(len(cash_exit), 1)
        self.assertFalse(call_rows["cash_equity_eligible"].any())

    def test_new_holdings_only_period_emits_no_false_security_exits(self) -> None:
        incremental = q2(
            ticker="ABC", cusip="987654321", shares=50, value=500,
            form_type="13F-HR/A", amendment_type="NEW HOLDINGS",
            accession="q2-new-only",
        )
        deltas = add_13f_position_deltas(pd.DataFrame([row(), incremental]))
        self.assertFalse(deltas["synthetic_exit"].astype(bool).any())

    def test_cash_security_rollover_is_neither_pure_buy_nor_pure_sell(self) -> None:
        frame = pd.DataFrame([
            row(cusip="123456789", title="CLASS A", shares=100, value=1_000),
            q2(cusip="12345678A", title="CLASS B", shares=100, value=1_100),
        ])
        signal = build_13f_signal(frame).set_index("ticker")
        self.assertEqual(int(signal.loc["XYZ", "sec_13f_buying_manager_count"]), 0)
        self.assertEqual(int(signal.loc["XYZ", "sec_13f_selling_manager_count"]), 0)

    def test_option_only_ticker_produces_no_stock_signal(self) -> None:
        signal = build_13f_signal(pd.DataFrame([row(put_call="CALL")]))
        self.assertTrue(signal.empty)

    def test_prn_only_ticker_produces_no_stock_signal(self) -> None:
        signal = build_13f_signal(pd.DataFrame([row(share_type="PRN")]))
        self.assertTrue(signal.empty)

    def test_missing_required_identity_fields_fail_closed(self) -> None:
        for field in ["cusip", "title_of_class", "share_type", "investment_discretion"]:
            bad = row()
            bad[field] = ""
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "required_field_missing"):
                prepare_13f_holdings(pd.DataFrame([bad]))

    def test_invalid_put_call_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_put_call"):
            prepare_13f_holdings(pd.DataFrame([row(put_call="WARR")]))

    def test_invalid_required_numeric_fails_closed(self) -> None:
        for field, value in [("shares", None), ("shares", "bad"), ("shares", -1),
                             ("market_value_usd", None), ("market_value_usd", "bad"), ("market_value_usd", -1)]:
            bad = row()
            bad[field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "required_numeric_invalid"):
                prepare_13f_holdings(pd.DataFrame([bad]))

    def test_cash_conviction_denominator_excludes_option_value(self) -> None:
        frame = pd.DataFrame([
            row(ticker="XYZ", cusip="123456789", value=1_000),
            row(ticker="ABC", cusip="987654321", value=3_000),
            row(ticker="XYZ", cusip="123456789", put_call="CALL", value=96_000),
        ])
        prepared = prepare_13f_holdings(frame)
        cash = prepared[prepared["cash_equity_eligible"]].set_index("ticker")
        self.assertAlmostEqual(float(cash.loc["XYZ", "manager_cash_position_weight"]), 0.25)
        self.assertAlmostEqual(float(cash.loc["ABC", "manager_cash_position_weight"]), 0.75)

    def test_pit_as_of_excludes_future_filing(self) -> None:
        frame = pd.DataFrame([row(), q2(shares=200)])
        prepared = prepare_13f_holdings(frame, as_of="2026-05-16T00:00:00Z")
        self.assertEqual(set(prepared["report_period"].astype(str)), {"2026-03-31"})

    def test_restatement_replaces_base_at_security_identity_level(self) -> None:
        base = q2(shares=100, value=1_000)
        restated = q2(
            shares=150, value=1_500, accession="q2-restated",
            available="2026-08-17T20:00:00Z", form_type="13F-HR/A",
            amendment_type="RESTATEMENT",
        )
        prepared = prepare_13f_holdings(pd.DataFrame([row(), base, restated]))
        current = prepared[prepared["report_period"].eq("2026-06-30")]
        self.assertEqual(len(current), 1)
        self.assertEqual(float(current.iloc[0]["shares"]), 150.0)

    def test_same_ticker_two_managers_counts_two(self) -> None:
        frame = pd.DataFrame([
            row(manager="1", shares=100, value=1_000),
            row(manager="2", shares=50, value=500),
        ])
        signal = build_13f_signal(frame).set_index("ticker")
        self.assertEqual(int(signal.loc["XYZ", "sec_13f_manager_count"]), 2)

    def test_input_row_order_does_not_change_stock_signal(self) -> None:
        frame = pd.DataFrame([
            row(manager="1", shares=100, value=1_000),
            row(manager="1", put_call="CALL", shares=200, value=5_000),
            row(manager="2", shares=50, value=500),
        ])
        a = build_13f_signal(frame).reset_index(drop=True)
        b = build_13f_signal(frame.sample(frac=1.0, random_state=7)).reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)

    def test_late_prior_restatement_delays_inferred_exit_without_resurrecting_security(self) -> None:
        prior = row(ticker="XYZ", period="2026-03-31", available="2026-05-15T20:00:00Z", accession="q1", shares=100)
        current = q2(ticker="ABC", cusip="987654321", accession="q2", shares=50)
        late_prior = row(
            ticker="XYZ", period="2026-03-31", available="2026-09-01T20:00:00Z",
            accession="q1-restated", shares=120, value=1_200, form_type="13F-HR/A",
            amendment_type="RESTATEMENT",
        )
        deltas = add_13f_position_deltas(pd.DataFrame([prior, current, late_prior]), as_of="2026-09-02T00:00:00Z")
        xyz = deltas[deltas["ticker"].eq("XYZ")].sort_values(["available_from_ts", "report_period_ts"])
        latest = xyz.iloc[-1]
        self.assertTrue(bool(latest["synthetic_exit"]))
        self.assertTrue(bool(latest["exited_position"]))
        self.assertEqual(latest["report_period_ts"], pd.Timestamp("2026-06-30"))
        self.assertEqual(latest["available_from_ts"], pd.Timestamp("2026-09-01T20:00:00Z"))


class CLIContractTests(unittest.TestCase):
    def test_cli_summary_labels_cash_equity_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "holdings.csv"
            out = root / "out"
            pd.DataFrame([row()]).to_csv(src, index=False)
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/run_sec_institutional_signals.py"),
                 "--holdings", str(src), "--output-dir", str(out), "--require-nonempty"],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads((out / "institutional_signal_summary.json").read_text())
            self.assertTrue(summary["security_identity_preserved"])
            self.assertEqual(
                summary["stock_signal_scope"],
                "CASH_EQUITY_ONLY_OPTIONS_AND_PRN_EXCLUDED_FROM_STOCK_SCORE",
            )

    def test_cli_rejects_malformed_identity_without_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "holdings.csv"
            out = root / "out"
            bad = row()
            bad["cusip"] = ""
            pd.DataFrame([bad]).to_csv(src, index=False)
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/run_sec_institutional_signals.py"),
                 "--holdings", str(src), "--output-dir", str(out), "--require-nonempty"],
                cwd=ROOT, check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
