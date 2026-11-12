#!/usr/bin/env python3
"""Offline regressions: publication leakage, revised data, labels and inference."""
from __future__ import annotations

import argparse
from datetime import timezone
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import macro_history_sources as source
from tools import macro_technical_study as study


def alfred_page(rows):
    return source.encoded(dict(units="lin", output_type=1, count=len(rows), offset=0, observations=rows))


def current_payload():
    vintage = "2026-09-11"
    rows = [dict(date=day, value=value, realtime_start=vintage, realtime_end=vintage)
            for day, value in (("2020-01-01", "3.5"), ("2020-02-01", "."), ("2020-03-01", None))]
    return dict(file_type="json", units="lin", output_type=1, offset=0,
                limit=source.CURRENT_API_ROW_LIMIT, count=len(rows), observations=rows,
                observation_start="2020-01-01", observation_end="2020-03-31",
                realtime_start=vintage, realtime_end=vintage)


class EvidenceTests(unittest.TestCase):
    def test_keyed_current_collect_keeps_exact_api_bytes_and_current_only_clocks(self):
        raw = source.encoded(current_payload())
        retrieved = "2026-09-11T12:00:00Z"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"FRED_API_KEY": "fixture-secret"}), \
             patch.object(source, "utc_now", return_value=retrieved), \
             patch.object(source, "request_bytes", return_value=raw) as request:
            receipt, path = source.collect(tmp, ["UNRATE"], "2020-01-01", "2020-03-31")
            request.assert_called_once()
            self.assertEqual(request.call_args.kwargs, {"secret": "fixture-secret"})
            endpoint = urlparse(request.call_args.args[0])
            self.assertEqual((endpoint.netloc, endpoint.path),
                             ("api.stlouisfed.org", "/fred/series/observations"))
            self.assertEqual(parse_qs(endpoint.query), dict(series_id=["UNRATE"], api_key=["fixture-secret"],
                file_type=["json"], units=["lin"], output_type=["1"], offset=["0"],
                limit=[str(source.CURRENT_API_ROW_LIMIT)], observation_start=["2020-01-01"],
                observation_end=["2020-03-31"]))
            item = receipt["sources"][0]
            self.assertEqual(item["status"], "COLLECTED")
            self.assertEqual(item["raw_sha256"], [source.digest(raw)])
            self.assertEqual((Path(tmp) / "objects" / item["raw_sha256"][0]).read_bytes(), raw)
            self.assertEqual(item["missing_observation_dates"], ["2020-02-01", "2020-03-01"])
            rows = source.load_bundle(tmp, path)[1]["UNRATE"]
            self.assertEqual(rows, source.parse_graph(
                b"DATE,UNRATE\n2020-01-01,3.5\n", "UNRATE", "2020-01-01", "2020-03-31", retrieved)[0])
            self.assertNotIn(b"fixture-secret", path.read_bytes())

    def test_current_without_key_uses_graph_and_keyed_errors_are_redacted(self):
        csv_raw = b"DATE,UNRATE\n2020-01-01,3.5\n"
        with patch.dict(os.environ, {"FRED_API_KEY": ""}), \
             patch.object(source, "request_bytes", return_value=csv_raw) as request:
            pages, retrieved = source.fetch("UNRATE", "2020-01-01", "2020-03-31", "current")
            request.assert_called_once_with(
                "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE&cosd=2020-01-01&coed=2020-03-31")
            self.assertEqual(source.parse_current(pages, "UNRATE", "2020-01-01", "2020-03-31", retrieved)[0][0]["value"], 3.5)
        for failure in (HTTPError("https://example.com/?api_key=fixture-secret", 403, "fixture-secret", {}, None),
                        URLError("fixture-secret"), TimeoutError("fixture-secret"), OSError("fixture-secret")):
            with self.subTest(kind=type(failure)), patch.dict(os.environ, {"FRED_API_KEY": "fixture-secret"}), \
                 patch.object(source, "request_bytes", side_effect=failure) as request:
                with self.assertRaises(type(failure)) as caught:
                    source.fetch("UNRATE", "2020-01-01", "2020-03-31", "current")
                request.assert_called_once()
                self.assertNotIn("fixture-secret", repr(caught.exception))
                self.assertFalse(getattr(caught.exception, "url", ""))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_current_api_rejects_http_success_csv_before_legacy_parser(self):
        csv_raw = b"DATE,UNRATE\n2020-01-01,3.5\n"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"FRED_API_KEY": "fixture-secret"}), \
             patch.object(source, "request_bytes", return_value=csv_raw) as request:
            receipt, _ = source.collect(tmp, ["UNRATE"], "2020-01-01", "2020-03-31")
            request.assert_called_once()
            self.assertEqual(receipt["sources"], [
                dict(series="UNRATE", status="BLOCKED", reason="current_api_json")])
            self.assertFalse((Path(tmp) / "objects" / source.digest(csv_raw)).exists())
        self.assertEqual(source.parse_current([csv_raw], "UNRATE", "2020-01-01",
            "2020-03-31", "2026-09-11T12:00:00Z")[0][0]["value"], 3.5)

    def test_current_api_contract_rejects_truncation_wrong_scope_and_invalid_observations(self):
        args = ("UNRATE", "2020-01-01", "2020-03-31", "2026-09-11T12:00:00Z")
        for field, bad in (("count", 4), ("count", True), ("offset", 1), ("limit", 2),
                           ("units", "chg"), ("output_type", True), ("series_id", "PAYEMS"),
                           ("observation_start", "2019-01-01"), ("observation_end", "2020-03-30"),
                           ("realtime_end", "2026-09-12"), ("realtime_start", "2026-09-10")):
            payload = current_payload()
            payload[field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaisesRegex(ValueError, "current_api_"):
                source.parse_current([source.encoded(payload)], *args)
        for field, bad in (("date", "2019-12-01"), ("date", "2020-04-01"), ("date", "20200101"),
                           ("date", "2020-01-01"), ("value", True), ("value", "inf"),
                           ("realtime_end", "2026-09-12")):
            payload = current_payload()
            payload["observations"][1][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                source.parse_current([source.encoded(payload)], *args)
        with self.assertRaisesRegex(ValueError, "current_page_count"):
            source.parse_current([source.encoded(current_payload())] * 2, *args)

    def test_current_api_rejects_duplicate_json_keys_and_nonstandard_constants(self):
        raw = source.encoded(current_payload())
        bad_payloads = (
            raw.replace(b'"count":3', b'"count":0,"count":3', 1),
            raw.replace(b'"value":"3.5"', b'"value":"9.9","value":"3.5"', 1),
            raw.replace(b'"value":"3.5"', b'"extra":NaN,"value":"3.5"', 1),
        )
        for index, bad in enumerate(bad_payloads):
            with self.subTest(case=index), self.assertRaisesRegex(ValueError, "^current_api_json$"):
                source.parse_current([bad], "UNRATE", "2020-01-01", "2020-03-31",
                                     "2026-09-11T12:00:00Z")

    def test_a4_exact_fred_series_have_distinct_registered_units_and_frequencies(self):
        import json
        specs = {row['id']: row for row in source.registry()['series']}
        contract = json.loads((ROOT/'docs/run287_chameleon_macro_inputs_contract.json').read_bytes())
        self.assertTrue({row['series_id'] for row in contract['fred'].values()} <= set(specs))
        expected = {'BAMLC0A0CM': ('daily', 'percent'), 'DGS3MO': ('daily', 'percent'),
                    'WDTGAL': ('weekly', 'millions_usd'), 'RRPTSYD': ('daily', 'billions_usd')}
        for sid, (frequency, unit) in expected.items():
            self.assertEqual((specs[sid]['frequency'], specs[sid]['unit']), (frequency, unit))
            self.assertEqual(specs[sid]['source_url'], 'https://fred.stlouisfed.org/series/'+sid)
            self.assertEqual(specs[sid]['initial_inference'], 'SHADOW_ONLY')
        self.assertIn('WTREGEN', specs)  # Weekly average is not Wednesday WDTGAL.
        self.assertIn('RRPONTSYD', specs)  # Overnight-only is not total RRPTSYD.

    def test_held_four_series_use_existing_bundle_and_preserve_original_clocks(self):
        series = ['BAMLC0A0CM', 'DGS3MO', 'WDTGAL', 'RRPTSYD']
        calls = []
        def held(sid, start, through, mode):
            calls.append((sid, mode))
            return ([('observation_date,'+sid+'\n2026-10-21,1.25\n').encode()],
                    '2026-10-27T07:00:00Z')
        with tempfile.TemporaryDirectory() as tmp:
            receipt, path = source.collect(tmp, series, '2026-10-01', '2026-10-26', fetcher=held)
            _, records = source.load_bundle(tmp, path)
            self.assertEqual(calls, [(sid, 'current') for sid in series])
            self.assertEqual(set(records), set(series))
            self.assertFalse(receipt['durable_remote_verified'])
            self.assertFalse(receipt['historical_price_pit_verified'])
            snapshot = Path(tmp)/'objects'/receipt['registry_sha256']
            self.assertEqual(snapshot.read_bytes(), source.REGISTRY.read_bytes())
            for rows in records.values():
                self.assertEqual(rows[0]['available_at'], '2026-10-27T07:00:00Z')
                self.assertIsNone(rows[0]['published_at'])
                self.assertEqual(rows[0]['evidence'], 'current_only')

    def test_registry_version_change_needs_explicit_original_bytes_for_read_only_reuse(self):
        import json
        original = source.REGISTRY.read_bytes()
        changed = json.loads(original)
        changed['series'][0]['unit'] = 'SYNTHETIC_DIFFERENT_UNIT'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt, path = source.collect(root, ['UNRATE'], '2020-01-01', '2020-01-31',
                fetcher=lambda *args: ([b'DATE,UNRATE\n2020-01-01,3.5\n'], '2026-10-27T07:00:00Z'))
            replacement = root/'new-registry.json'
            replacement.write_bytes(source.encoded(changed))
            with patch.object(source, 'REGISTRY', replacement):
                with self.assertRaisesRegex(ValueError, 'registry_changed'):
                    source.load_bundle(root, path)  # Default analysis guard stays strict.
                self.assertEqual(source.load_bundle(root, path, registry_raw=original)[1]['UNRATE'][0]['value'], 3.5)
                (root/'objects'/receipt['registry_sha256']).unlink()  # Legacy bundle without snapshot.
                with self.assertRaisesRegex(ValueError, 'registry_changed'):
                    source.load_bundle(root, path)
                self.assertIn('UNRATE', source.load_bundle(root, path, registry_raw=original)[1])
                with self.assertRaisesRegex(ValueError, 'registry_changed'):
                    source.load_bundle(root, path, registry_raw=replacement.read_bytes())
            (root/'objects'/receipt['registry_sha256']).write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError, 'registry_snapshot_hash'):
                source.load_bundle(root, path, registry_raw=original)

    def test_registry_is_pinned_before_fetch_and_cannot_escape_its_source_scope(self):
        import copy
        original = source.REGISTRY.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); selected = root/'registry.json'; selected.write_bytes(original)
            def held(*args):
                selected.write_bytes(b'{"schema":"changed-during-fetch"}')
                return ([b'DATE,UNRATE\n2020-01-01,3.5\n'], '2026-10-27T07:00:00Z')
            with patch.object(source, 'REGISTRY', selected):
                receipt, path = source.collect(root, ['UNRATE'], '2020-01-01', '2020-01-31', fetcher=held)
            self.assertEqual(receipt['registry_sha256'], source.digest(original))
            self.assertIn('UNRATE', source.load_bundle(root, path)[1])
            for change in ('unknown', 'duplicate', 'path'):
                bad = copy.deepcopy(receipt)
                if change == 'unknown': bad['sources'][0]['series'] = 'UNREGISTERED_SERIES'
                elif change == 'duplicate': bad['sources'].append(copy.deepcopy(bad['sources'][0]))
                else: bad['registry_sha256'] = '../registry.json'
                raw = source.encoded(bad); other = root/'receipts'/(source.digest(raw)+'.json')
                other.write_bytes(raw)
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'registry_source_scope|registry_identity'):
                    source.load_bundle(root, other)

    def test_alfred_fetch_paginates_beyond_legacy_200k_cap(self):
        total = 225_001
        offsets = []
        def fake_request(url, *, secret=None):
            query = parse_qs(urlparse(url).query)
            limit = int(query["limit"][0])
            offset = int(query["offset"][0])
            offsets.append(offset)
            size = min(limit, total - offset)
            return source.encoded(dict(
                units="lin", output_type=1, count=total, offset=offset,
                observations=[{}] * size,
            ))
        with patch.dict(os.environ, {"FRED_API_KEY": "fixture-secret"}), \
             patch("tools.macro_history_sources.request_bytes", side_effect=fake_request):
            pages, _ = source.fetch("NFCI", "1996-01-01", "2026-09-22", "alfred")
        self.assertEqual(offsets, [0, 50_000, 100_000, 150_000, 200_000])
        self.assertEqual(len(pages), 5)

    def test_alfred_fetch_keeps_hard_bounded_row_cap(self):
        def fake_request(url, *, secret=None):
            query = parse_qs(urlparse(url).query)
            offset = int(query["offset"][0])
            return source.encoded(dict(
                units="lin", output_type=1,
                count=source.ALFRED_MAX_ROWS + 1,
                offset=offset, observations=[{}],
            ))
        with patch.dict(os.environ, {"FRED_API_KEY": "fixture-secret"}), \
             patch("tools.macro_history_sources.request_bytes", side_effect=fake_request):
            with self.assertRaisesRegex(ValueError, "alfred_count"):
                source.fetch("NFCI", "1996-01-01", "2026-09-22", "alfred")

    def test_current_history_is_not_backdated(self):
        rows, missing = source.parse_graph(b"observation_date,UNRATE\n2020-01-01,3.5\n2020-02-01,.\n", "UNRATE", "2020-01-01", "2020-02-28", "2026-09-11T12:00:00Z")
        self.assertEqual(rows[0]["available_at"], "2026-09-11T12:00:00Z")
        self.assertEqual(rows[0]["evidence"], "current_only")
        self.assertIsNone(rows[0]["published_at"])
        self.assertEqual(missing, ["2020-02-01"])
        with self.assertRaisesRegex(ValueError, "historical_vintage"):
            study.archive_release_changes(rows, [], [], "monthly")

    def test_bad_graph_schema_duplicate_and_nonfinite(self):
        for raw in (b"DATE,PAYEMS\n2020-01-01,1\n", b"DATE,UNRATE\n2020-01-01,1\n2020-01-01,2\n", b"DATE,UNRATE\n2020-01-01,inf\n", b"DATE,UNRATE\n2030-01-01,1\n"):
            with self.assertRaises(ValueError):
                source.parse_graph(raw, "UNRATE", "2020-01-01", "2020-12-31", "2026-09-11T12:00:00Z")

    def test_vintages_keep_revisions_and_conservative_dst(self):
        rows=[dict(date="2020-01-01", value="3.5", realtime_start="2020-02-07", realtime_end="2020-03-05"),
              dict(date="2020-01-01", value="3.6", realtime_start="2020-03-06", realtime_end="9999-12-31"),
              dict(date="2020-02-01", value="3.7", realtime_start="2020-03-06", realtime_end="9999-12-31")]
        parsed=source.parse_alfred([alfred_page(rows)], "UNRATE", "2020-01-01", "2020-03-31", "2026-09-11T00:00:00Z")
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["available_at"], "2020-02-08T05:00:00+00:00")
        dates=pd.bdate_range("2020-02-06", "2020-03-10")
        closes=[d.to_pydatetime().replace(hour=21,tzinfo=timezone.utc) for d in dates]
        changes=study.archive_release_changes(parsed, dates, closes, "monthly")
        self.assertEqual(changes.dropna().index.tolist(), [pd.Timestamp("2020-03-09")])
        self.assertAlmostEqual(changes.dropna().iloc[0], .1)
        summer=[dict(date="2020-06-01",value="5",realtime_start="2020-07-02",realtime_end="9999-12-31")]
        summer_row=source.parse_alfred([alfred_page(summer)], "UNRATE", "2020-01-01", "2020-07-31", "2026-09-11T00:00:00Z")[0]
        self.assertEqual(summer_row["available_at"], "2020-07-03T04:00:00+00:00")

    def test_alfred_rejects_incomplete_and_overlapping_pages(self):
        row=dict(date="2020-01-01",value="3.5",realtime_start="2020-02-07",realtime_end="9999-12-31")
        for payload in [dict(units="lin",output_type=1,count=2,offset=0,observations=[row]),
                        dict(units="lin",output_type=1,count=2,offset=0,observations=[row,dict(row,realtime_start="2020-03-06")])]:
            with self.assertRaises(ValueError):
                source.parse_alfred([source.encoded(payload)],"UNRATE","2020-01-01","2020-03-31","2026-09-11T00:00:00Z")

    def test_missing_month_does_not_become_monthly_change(self):
        records=[]
        for period, available, value in [("2020-01-01","2020-02-08T05:00:00Z",3), ("2020-03-01","2020-04-04T04:00:00Z",4)]:
            records.append(dict(observation_date=period,available_at=available,value=value,realtime_end="9999-12-31",evidence="alfred_date_archive"))
        days=pd.bdate_range("2020-02-01","2020-04-10")
        closes=[d.to_pydatetime().replace(hour=21,tzinfo=timezone.utc) for d in days]
        self.assertTrue(study.archive_release_changes(records,days,closes,"monthly").isna().all())

    def test_unavailable_revision_does_not_expire_prior_value_early(self):
        rows=[dict(date='2020-01-01',value='3.5',realtime_start='2020-02-07',realtime_end='2020-03-08'),
              dict(date='2020-01-01',value='3.6',realtime_start='2020-03-09',realtime_end='9999-12-31'),
              dict(date='2020-02-01',value='3.7',realtime_start='2020-03-06',realtime_end='9999-12-31')]
        parsed=source.parse_alfred([alfred_page(rows)],'UNRATE','2020-01-01','2020-03-31','2026-09-11T00:00:00Z')
        dates=pd.bdate_range('2020-02-01','2020-03-11')
        closes=[d.to_pydatetime().replace(hour=21,tzinfo=timezone.utc) for d in dates]
        changes=study.archive_release_changes(parsed,dates,closes,'monthly')
        self.assertAlmostEqual(changes.loc['2020-03-09'],.2)
        self.assertEqual(len(changes.dropna()),1)

    def test_objects_receipts_idempotency_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher=lambda *args: ([b"DATE,UNRATE\n2020-01-01,3.5\n2020-02-01,3.6\n"], "2026-09-11T00:00:00Z")
            receipt, path=source.collect(tmp,["UNRATE"],"2020-01-01","2020-02-29",fetcher=fetcher)
            _, loaded=source.load_bundle(tmp,path)
            self.assertEqual(len(loaded["UNRATE"]),2)
            count=len(list((Path(tmp)/"objects").iterdir()))
            source.collect(tmp,["UNRATE"],"2020-01-01","2020-02-29",fetcher=fetcher)
            self.assertEqual(len(list((Path(tmp)/"objects").iterdir())),count)
            obj=Path(tmp)/"objects"/receipt["sources"][0]["records_sha256"]
            obj.write_text("[]")
            with self.assertRaisesRegex(ValueError,"object_hash"):
                source.load_bundle(tmp,path)

    def test_label_entry_maturity_and_gap(self):
        prices=pd.Series(np.arange(100.,115.),index=pd.bdate_range("2020-01-01",periods=15))
        result=study.labels(prices,5)
        self.assertAlmostEqual(result.iloc[0],106/101-1)
        self.assertTrue(result.iloc[-6:].isna().all())
        prices.iloc[3]=np.nan
        self.assertTrue(study.labels(prices,5).iloc[:4].isna().all())

    def test_features_have_no_future_dependency_and_single_cross(self):
        dates=pd.bdate_range("2000-01-01",periods=650)
        close=pd.Series(np.r_[np.linspace(200,80,300),np.linspace(80,240,350)],index=dates)
        features,_=study.technical_features(close,close)
        self.assertEqual(features["golden_cross_50_200"].sum(),1)
        self.assertEqual(features["relative_strength_60"].dropna().abs().max(),0)
        modified=close.copy(); modified.iloc[450:]*=20
        other,_=study.technical_features(modified,modified)
        for name in features:
            pd.testing.assert_series_equal(features[name].iloc[:450],other[name].iloc[:450])

    def test_walk_forward_purges_unmatured_labels(self):
        rng=np.random.default_rng(75)
        index=pd.bdate_range("2000-01-01",periods=1500)
        x=pd.Series(rng.normal(size=len(index)),index=index)
        y=pd.Series(.05*x+rng.normal(0,.02,len(index)),index=index)
        result=study.evaluate(x,y,63,initial=400,min_train=200,fold_size=200)
        self.assertGreater(result["oos_mse_improvement"],0)
        for fold in result["folds"]:
            self.assertLess(fold["last_training_label_position"],fold["first_test_position"])
        self.assertEqual(result["status"],"INSUFFICIENT_INDEPENDENT_EVIDENCE")
        changed=y.copy(); changed.iloc[350:400]=999
        other=study.evaluate(x,changed,63,initial=400,min_train=200,fold_size=200)
        self.assertEqual(result['folds'][0]['coefficient_per_train_sd'],other['folds'][0]['coefficient_per_train_sd'])

    def test_dependence_and_rare_events_do_not_pass(self):
        self.assertEqual(study.independent_windows(np.arange(1000),252),4)
        dates=pd.bdate_range("2000-01-01",periods=2000)
        x=pd.Series((np.arange(2000)%200==0).astype(float),index=dates)
        y=x*.1+.01
        result=study.evaluate(x,y,5,kind="event",initial=400,min_train=200)
        self.assertLess(result["event_count"],20)
        self.assertIsNone(result["p_value"])

    def test_multiple_testing_counts_unavailable_tests(self):
        results=[dict(p_value=.01,status="TESTED_SHADOW",oos_mse_improvement=.01,folds=[dict(mse_improvement=.01)]*3)]
        results += [dict(p_value=None,status="INSUFFICIENT_DATA") for _ in range(99)]
        study.adjust_family(results)
        self.assertEqual(results[0]["status"],"NO_INCREMENTAL_EVIDENCE")
        self.assertEqual(results[0]["family_q_value"],1)

    def test_due_plan_requires_actual_calendar(self):
        before={"UNRATE":dict(retrieved_at="2026-09-01T00:00:00Z")}
        events=[dict(series="UNRATE",release_at="2026-09-04T12:30:00Z")]
        plan={r["series"]:r for r in source.update_plan("2026-09-11T00:00:00Z",before,events)}
        self.assertEqual(plan["UNRATE"]["status"],"RELEASE_DUE")
        self.assertEqual(plan["PAYEMS"]["status"],"BACKFILL_REQUIRED")
        no_calendar={r["series"]:r for r in source.update_plan("2026-09-11T00:00:00Z",before,[])}
        self.assertEqual(no_calendar["UNRATE"]["status"],"CALENDAR_REFRESH_REQUIRED")

    def test_calendar_uses_official_dates_and_shared_release(self):
        calls=[]
        def fake(url, secret=None):
            calls.append(urlparse(url).path)
            query=parse_qs(urlparse(url).query)
            if urlparse(url).path.endswith('/series/release'):
                return source.encoded(dict(releases=[dict(id=50)]))
            self.assertEqual(query['include_release_dates_with_no_data'],['true'])
            return source.encoded(dict(count=1,release_dates=[dict(release_id=50,date='2026-10-02')]))
        with patch.dict(os.environ,{'FRED_API_KEY':'synthetic-test-key'}), patch.object(source,'request_bytes',fake):
            calendar=source.fetch_calendar(['UNRATE','PAYEMS'],'2026-09-01','2026-12-31')
        self.assertEqual(calls.count('/fred/release/dates'),1)
        self.assertEqual(len(calendar['events']),2)
        self.assertEqual(calendar['events'][0]['release_at'],'2026-10-03T04:00:00+00:00')
        self.assertNotIn('synthetic-test-key',source.encoded(calendar).decode())


def run_tests(*, portable=False):
    classes=[EvidenceTests]
    if not portable:
        from a4_macro_bridge_smoke import BridgeTests
        from a4_liquidity_analysis_smoke import LiquidityTests
        from a4_macro_learning_smoke import LearningTests
        from a4_cloud_cycle_smoke import CloudTests
        from a5_model_portfolio_smoke import ModelTests
        from a4_primary_sources_smoke import PrimaryTests
        from a4_primary_macro_sources_smoke import EconomicTests
        from a4_financing_sources_smoke import FinancingTests
        from a4_data_center_smoke import DataCenterTests
        from a4_macro_diagnosis_smoke import DiagnosisTests
        from a4_native_inputs_smoke import NativeHandoffTests
        classes.extend((BridgeTests,LiquidityTests,LearningTests,CloudTests,ModelTests,PrimaryTests,EconomicTests,FinancingTests,DataCenterTests,DiagnosisTests,NativeHandoffTests))
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in classes])
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("macro_technical_evidence_smoke_failed")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portable',action='store_true',
        help='Run the incumbent Source-only cases in the declared collector sparse checkout; PR validation defaults to all A4 cases.')
    run_tests(portable=parser.parse_args().portable)
