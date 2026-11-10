"""Synthetic component isolation; no credentials, provider or Drive transport."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import date, timedelta
import gzip
import io
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import alpaca_sip_managed_refresh as runtime


cap = runtime.capture
FULL = ["2026-10-21", "2026-10-22", "2026-10-23"]
HELD = "BASELINE_COVERAGE_OR_LIFECYCLE_REVIEW_REQUIRED"


def bar(day):
    return dict(t=day + "T04:00:00Z", o=10, h=11, l=9, c=10.5, v=100)


def asset(symbol):
    return dict(symbol=symbol, id="00000000-0000-0000-0000-000000000001",
                exchange="NASDAQ", status="active", **{"class": "us_equity"})


class Reply:
    status = 200

    def __init__(self, body):
        self.body = body
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda _: None)))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read1(self, n):
        result, self.body = self.body[:n], self.body[n:]
        return result


class Opener:
    def __init__(self):
        self.urls = []
        self.asset_ids = {}

    def open(self, request, **_):
        self.urls.append(request.full_url)
        url = urlsplit(request.full_url)
        if "/assets/" in url.path:
            record = asset(url.path.rsplit("/", 1)[1])
            record["id"] = self.asset_ids.get(record["symbol"], record["id"])
            return Reply(runtime.encoded(record))
        query = parse_qs(url.query)
        end = (date.fromisoformat(query["end"][0][:10]) + timedelta(days=1)).isoformat()
        days = sorted(runtime.expected_sessions(query["start"][0][:10], end))
        return Reply(runtime.encoded(dict(bars={t: [bar(d) for d in days]
            for t in query["symbols"][0].split(",")}, next_page_token=None)))


class MemoryDrive:
    root_id, owner, token, free = "fixture-root-123", "fixture-owner", "fixture-token", 2 * 1024**3

    def __init__(self, meter):
        self.meter = meter
        self.objects, self.parents, self.names, self.checked = {}, {}, {}, []

    def seed(self, folder, body, ext=".json"):
        fid = "fixture-object-" + str(len(self.objects) + 1).zfill(6)
        self.objects[fid], self.parents[fid], self.names[fid] = body, folder, runtime.digest(body) + ext
        return dict(file_id=fid, sha256=runtime.digest(body), bytes=len(body))

    def cost(self):
        self.meter.debit(dict(drive_requests=1, drive_bytes=100))

    def check(self, fid, parent=None, folder=False):
        self.cost()
        if fid in {"fixture-data-123", "fixture-journal-123", "fixture-evidence-123"} and parent == self.root_id:
            return
        self.checked.append(fid)
        runtime.require(fid in self.objects and self.parents[fid] == parent, "FIXTURE_OWNER")

    def read(self, fid, limit=16_000_000):
        self.cost()
        body = self.objects[fid]
        runtime.require(len(body) <= limit, "FIXTURE_LIMIT")
        return body

    def request(self, url, **_):
        self.cost()
        query = parse_qs(urlsplit(url).query)["q"][0]
        parent = re.search(r"'([^']+)' in parents", query).group(1)
        name = re.search(r"name = '([^']+)'", query)
        return runtime.encoded(dict(files=[dict(id=fid, name=self.names[fid], size=str(len(body)))
            for fid, body in self.objects.items() if self.parents[fid] == parent
            and (name is None or self.names[fid] == name.group(1))]))

    def write(self, folder, body, ext):
        self.cost()
        self.meter.reserve_storage(len(body))
        return self.seed(folder, body, ext)


class ComponentHoldTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        # Refuse default transports or child collectors if a fixture regresses.
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("network")))
        stack.enter_context(patch.object(runtime.subprocess, "run", side_effect=AssertionError("child")))
        stack.enter_context(patch.object(cap.time, "sleep", return_value=None))
        stack.enter_context(patch.dict("os.environ", {
            "GITHUB_SHA": "2" * 40, "ALPACA_API_KEY": "fixture-key",
            "ALPACA_API_SECRET": "fixture-secret"}, clear=True))
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.now = runtime.campaign.utc("2026-10-24T00:30:00Z")
        allowance = dict(provider_gets=20, drive_requests=200, drive_bytes=100_000_000, storage_bytes=2_000_000)
        identity = dict(run_id=1, run_attempt=1, source_sha="2" * 40,
                        parent_checkpoint_sha256=None, examined_before=0)
        self.opener = Opener()
        self.meter = runtime.campaign.RuntimeMeter(allowance, self.root / "meter.json",
            (self.now + timedelta(seconds=300)).isoformat(), identity,
            clock=lambda: self.now, opener=self.opener)
        self.drive = MemoryDrive(self.meter)
        self.control = dict(task_key="R1000-SYNTHETIC-COMPONENT-HOLD-ONLY", max_symbols_per_run=4,
            private_root_folder_id=self.drive.root_id, private_data_folder_id="fixture-data-123",
            journal_folder_id="fixture-journal-123", evidence_folder_id="fixture-evidence-123",
            authorized_tickers=["AAPL", "MSFT"], backfill_tickers=[], max_runs=2,
            per_run_allowance=allowance, inventory_sha256="a" * 64,
            owner_sha256=runtime.digest(self.drive.owner.encode()),
            credential_binding=runtime.digest(b"fixture-key\0fixture-secret"),
            expires_at=(self.now + timedelta(seconds=300)).isoformat(), max_active_seconds_per_run=300)
        self.identities = {t: self.drive.seed(self.control["evidence_folder_id"], runtime.encoded(asset(t)))
                           for t in self.control["authorized_tickers"]}

    def baseline(self, dates, *, split=None, start="2026-10-21", end="2026-10-24",
                 scope=None, evidence=None):
        """Construct original response pages and matching normalized bytes."""
        names, members, pages, normalized = sorted(dates), {}, [], []
        for basis, grid in (("raw", dates), ("split", split if split is not None else dates)):
            payload = runtime.encoded(dict(bars={t: [bar(d) for d in grid[t]] for t in names},
                                           next_page_token=None, adjustment=basis))
            h = runtime.digest(payload)
            members[h + ".json"] = payload
            pages.append(dict(symbols=names, adjustment=basis, page=0, bytes=len(payload),
                              sha256=h, member=h + ".json"))
        for t in names:
            for basis, grid in (("raw", dates), ("split", split if split is not None else dates)):
                normalized.extend(cap.normalize([bar(d) for d in grid[t]], t, basis, start, end))
        meta = dict(schema=cap.SCHEMA, source=cap.SOURCE, symbols=names,
            collected=[t for t in names if dates[t]], no_bars=[t for t in names if not dates[t]],
            start=start, end=end, asof=cap.mapping_asof(end), seed_sha256="a" * 64,
            source_sha="2" * 40, pages=pages, raw_adjustments=["raw", "split"],
            historical_identity_verified=False, pit_verified=False,
            source_admission=False, commercial_use_authorized=False)
        if scope is not None or evidence is not None:
            meta.update(cohort_scope=scope, asset_precheck=evidence)
        members["capture.json"] = runtime.encoded(meta)
        folder = self.control["private_data_folder_id"]
        raw = self.drive.seed(folder, cap.zip_bytes(members), ".zip")
        norm = self.drive.seed(folder, gzip.compress(b"".join(runtime.encoded(r) for r in normalized), mtime=0), ".jsonl.gz")
        receipt = dict(meta, pages=len(pages), rows=len(normalized), raw_object=raw, normalized_object=norm)
        ref = self.drive.seed(folder, runtime.encoded(receipt))
        return dict(provider="alpaca_sip", symbols=names, receipt=ref)

    def scoped_baseline(self, dates, **kwargs):
        evidence = []
        for ticker in sorted(dates):
            raw = runtime.encoded(asset(ticker))
            evidence.append(dict(symbol=ticker,
                url="https://paper-api.alpaca.markets/v2/assets/" + ticker,
                collected_at_utc="2026-10-24T00:00:00Z", http_status=200,
                response_utf8=raw.decode(), sha256=runtime.digest(raw)))
        scope = dict(task_key="R1000-SYNTHETIC-ARCHIVED-ASSET-ONLY",
                     namespace="fixture-managed-source", input_sha256="a" * 64)
        return self.baseline(dates, scope=kwargs.pop("scope", scope),
                             evidence=kwargs.pop("evidence", evidence), **kwargs)

    def collect(self, groups, tracked=("AAPL", "MSFT"), prior=None, held=None,
                session="2026-10-23"):
        return runtime.collect_groups(self.drive, self.meter, self.control,
            dict(groups=groups, asset_identity_refs=self.identities), set(tracked), prior or {}, held or {},
            session, "fixture-key", "fixture-secret", lambda: self.now)

    def execute(self, groups, tracked=("AAPL", "MSFT")):
        gate = runtime.managed.evaluate_market_session(now_utc=self.now, min_close_age_minutes=120)
        return runtime.execute(self.control, "b" * 64,
            dict(active_tickers=list(tracked[:1]), watch_tickers=list(tracked[1:])),
            dict(groups=groups, asset_identity_refs=self.identities), [dict(id=1, head_sha="2" * 40)],
            self.drive, self.meter, dict(run_id=1, head="2" * 40), "fixture-key", "fixture-secret",
            lambda: self.now, market_preflight=gate)

    def test_strict_bootstrap_still_refuses_incomplete_partition(self):
        group = self.baseline(dict(AAPL=FULL, MSFT=FULL[1:]))
        with self.assertRaisesRegex(runtime.IncompleteBootstrapCoverage, "^MANAGED_BOOTSTRAP_INCOMPLETE_GRID$") as caught:
            runtime.bootstrap_coverage(self.drive, self.control, dict(groups=[group]), {"AAPL", "MSFT"})
        self.assertEqual(caught.exception.coverage, {"AAPL": FULL[-1]})
        self.assertEqual(caught.exception.held, {"MSFT": HELD})

    def test_mixed_reuse_and_prefix_hold_no_identity_or_provider_for_held(self):
        result = self.execute([self.baseline(dict(AAPL=FULL, MSFT=FULL[1:]))])
        self.assertEqual((result["valid_updated"], result["reused"], result["held"], result["rows"]), (0, 1, 1, 0))
        self.assertEqual(result["session_coverage"], dict(policy_tracked=2, execution_scoped=2,
            current=1, held=1, pending=0, outside_scope=0, all_tracked_same_session=False))
        self.assertFalse(any(result[k] for k in ("source_admission", "pit_verified", "economic_authority")))
        self.assertEqual(self.opener.urls, [])
        self.assertNotIn(self.identities["MSFT"]["file_id"], self.drive.checked)
        terminal = next(row for _, row in runtime.journal_rows(self.drive, self.control) if row["state"] == "COMPLETE")
        self.assertEqual(terminal["coverage_updates"], {"AAPL": FULL[-1]})
        self.assertEqual(terminal["held"], {"MSFT": HELD})
        self.assertEqual(terminal["reused"], ["AAPL"])
        self.assertNotIn("session_coverage", terminal)

    def test_execution_subset_keeps_excluded_spy_outside_scope(self):
        self.control["authorized_tickers"].append("SPY")
        self.control["execution_tickers"] = ["AAPL", "MSFT"]
        result = self.execute([self.baseline(dict(AAPL=FULL, MSFT=FULL))],
                              tracked=("AAPL", "MSFT", "SPY"))
        self.assertEqual(result["session_coverage"], dict(policy_tracked=3, execution_scoped=2,
            current=2, held=0, pending=0, outside_scope=1, all_tracked_same_session=False))
        self.assertEqual(self.opener.urls, [])

    def test_bounded_batch_counts_same_session_prior_and_leaves_stale_spy_pending(self):
        self.control["authorized_tickers"].append("SPY")
        self.control["max_symbols_per_run"] = 1
        prior = {"MSFT": FULL[-1], "SPY": FULL[-2]}
        with patch.object(runtime, "restore_journal", return_value=("c" * 64, prior, {})):
            result = self.execute([self.baseline(dict(AAPL=FULL[:2]), end=FULL[-1])],
                                  tracked=("AAPL", "MSFT", "SPY"))
        self.assertEqual(result["valid_updated"], 1)
        self.assertEqual(result["session_coverage"], dict(policy_tracked=3, execution_scoped=3,
            current=2, held=0, pending=1, outside_scope=0, all_tracked_same_session=False))
        self.assertEqual(len(self.opener.urls), 3)

    def test_full_same_session_reuse_reports_all_tracked(self):
        result = self.execute([self.baseline(dict(AAPL=FULL, MSFT=FULL))])
        self.assertEqual(result["reused"], 2)
        self.assertEqual(result["session_coverage"], dict(policy_tracked=2, execution_scoped=2,
            current=2, held=0, pending=0, outside_scope=0, all_tracked_same_session=True))
        self.assertEqual(self.opener.urls, [])

    def test_verified_embedded_identity_updates_without_standalone_copy(self):
        self.identities = {}
        group = self.scoped_baseline(dict(AAPL=FULL[:2]), end=FULL[-1])
        values = self.collect([group], tracked=("AAPL",))
        self.assertEqual(values[:3], ({"AAPL": FULL[-1]}, {}, []))
        self.assertEqual(self.meter.used["provider_gets"], 3)
        self.assertIn("/assets/AAPL", self.opener.urls[0])
        self.assertTrue(all("start=2026-10-23" in url for url in self.opener.urls[1:]))
        self.assertTrue(all(r["public_available_at"] is None and not r["pit_verified"]
                            and not r["historical_identity_verified"] for r in values[3]))

    def test_embedded_matching_standalone_is_still_read_and_validated(self):
        group = self.scoped_baseline(dict(AAPL=FULL[:2]), end=FULL[-1])
        values = self.collect([group], tracked=("AAPL",))
        self.assertEqual(values[0], {"AAPL": FULL[-1]})
        self.assertIn(self.identities["AAPL"]["file_id"], self.drive.checked)
        self.assertEqual(self.meter.used["provider_gets"], 3)

    def test_embedded_conflicting_standalone_refuses_before_provider(self):
        group = self.scoped_baseline(dict(AAPL=FULL[:2]), end=FULL[-1])
        record = dict(asset("AAPL"), id="00000000-0000-0000-0000-000000000002")
        self.identities["AAPL"] = self.drive.seed(self.control["evidence_folder_id"], runtime.encoded(record))
        with self.assertRaisesRegex(runtime.Refused, "^MANAGED_IDENTITY_CONFLICT$"):
            self.collect([group], tracked=("AAPL",))
        self.assertEqual(self.opener.urls, [])

    def test_embedded_does_not_bypass_explicit_none_or_bad_standalone(self):
        group = self.scoped_baseline(dict(AAPL=FULL), end="2026-10-24")
        self.identities = {"AAPL": None}
        values = self.collect([group], tracked=("AAPL",))
        self.assertEqual(values[:3], ({}, {"AAPL": "MISSING_STABLE_PROVIDER_IDENTITY_PROOF"}, []))
        good = self.drive.seed(self.control["evidence_folder_id"], runtime.encoded(asset("AAPL")))
        for ref in ({}, dict(good, sha256="0" * 64)):
            with self.subTest(ref=ref):
                self.identities = {"AAPL": ref}
                with self.assertRaises(runtime.Refused):
                    self.collect([group], tracked=("AAPL",))
        self.assertEqual(self.opener.urls, [])

    def test_legacy_embedded_fields_are_not_identity_proof(self):
        scoped = self.scoped_baseline(dict(AAPL=FULL))
        receipt = runtime.decode(self.drive.objects[scoped["receipt"]["file_id"]])
        group = self.baseline(dict(AAPL=FULL), evidence=receipt["asset_precheck"])
        self.identities = {}
        self.assertEqual(self.collect([group], tracked=("AAPL",))[:3],
                         ({}, {"AAPL": "MISSING_STABLE_PROVIDER_IDENTITY_PROOF"}, []))
        # The legacy standalone fallback still supports an actual missing interval.
        self.identities = {"AAPL": self.drive.seed(self.control["evidence_folder_id"], runtime.encoded(asset("AAPL")))}
        legacy = self.baseline(dict(AAPL=FULL[:2]), end=FULL[-1])
        self.assertEqual(self.collect([legacy], tracked=("AAPL",))[0], {"AAPL": FULL[-1]})
        self.assertEqual(self.meter.used["provider_gets"], 3)

    def test_invalid_embedded_evidence_or_cohort_never_reaches_provider(self):
        self.identities = {}
        for case in ("hash", "clock", "symbol", "url", "http", "inactive", "scope", "manifest"):
            with self.subTest(case=case):
                original = self.scoped_baseline(dict(AAPL=FULL))
                receipt = runtime.decode(self.drive.objects[original["receipt"]["file_id"]])
                evidence, scope = receipt["asset_precheck"], receipt["cohort_scope"]
                row = evidence[0]
                if case == "hash":
                    row["sha256"] = "0" * 64
                elif case == "clock":
                    row["collected_at_utc"] = "unknown"
                elif case == "symbol":
                    row["symbol"] = "MSFT"
                elif case == "url":
                    row["url"] += "?unverified"
                elif case == "http":
                    row["http_status"] = 403
                elif case == "inactive":
                    raw = runtime.encoded(dict(asset("AAPL"), status="inactive"))
                    row.update(response_utf8=raw.decode(), sha256=runtime.digest(raw))
                elif case == "scope":
                    scope = {}
                group = self.baseline(dict(AAPL=FULL), scope=scope, evidence=evidence)
                if case == "manifest":
                    def mutate(members):
                        meta = runtime.decode(members["capture.json"])
                        meta["asset_precheck"][0]["sha256"] = "0" * 64
                        members["capture.json"] = runtime.encoded(meta)
                    self.repack(group, mutate)
                with self.assertRaises(runtime.Refused) as caught:
                    self.collect([group], tracked=("AAPL",))
                self.assertNotIsInstance(caught.exception, runtime.IncompleteBootstrapCoverage)
        self.assertEqual(self.opener.urls, [])

    def test_embedded_complete_partition_keeps_prefix_held(self):
        self.identities = {}
        group = self.scoped_baseline(dict(AAPL=FULL[:2], MSFT=FULL[1:2]), end=FULL[-1])
        identities = {}
        with self.assertRaises(runtime.IncompleteBootstrapCoverage) as caught:
            runtime.bootstrap_coverage(self.drive, self.control, dict(groups=[group]),
                                       {"AAPL", "MSFT"}, asset_identities=identities)
        self.assertEqual(identities, {"AAPL": asset("AAPL")["id"]})
        self.assertEqual(caught.exception.held, {"MSFT": HELD})
        values = self.collect([group])
        self.assertEqual(values[:3], ({"AAPL": FULL[-1]}, {"MSFT": HELD}, []))
        self.assertEqual(self.meter.used["provider_gets"], 3)
        self.assertTrue(all("MSFT" not in url for url in self.opener.urls))

    def test_late_corrupt_archive_leaves_identity_sink_unpublished(self):
        self.identities = {}
        first = self.scoped_baseline(dict(AAPL=FULL))
        second = self.scoped_baseline(dict(MSFT=FULL))
        receipt = runtime.decode(self.drive.objects[second["receipt"]["file_id"]])
        receipt["raw_object"]["sha256"] = "0" * 64
        second["receipt"] = self.drive.seed(self.control["private_data_folder_id"], runtime.encoded(receipt))
        identities = {}
        with self.assertRaisesRegex(runtime.Refused, "^MANAGED_OBJECT_HASH$"):
            runtime.bootstrap_coverage(self.drive, self.control, dict(groups=[first, second]),
                                       {"AAPL", "MSFT"}, asset_identities=identities)
        self.assertEqual(identities, {})
        with self.assertRaisesRegex(runtime.Refused, "^MANAGED_OBJECT_HASH$"):
            self.collect([first, second])
        self.assertEqual(self.opener.urls, [])

    def test_embedded_identity_still_requires_matching_fresh_provider_id(self):
        self.identities = {}
        group = self.scoped_baseline(dict(AAPL=FULL[:2]), end=FULL[-1])
        self.opener.asset_ids["AAPL"] = "00000000-0000-0000-0000-000000000002"
        values = self.collect([group], tracked=("AAPL",))
        self.assertEqual(values[:3], ({}, {"AAPL": "PROVIDER_SECURITY_ID_CHANGED"}, []))
        self.assertEqual(self.meter.used["provider_gets"], 1)
        self.assertEqual(len(self.opener.urls), 1)

    def test_restored_coverage_cannot_replace_archive_identity_validation(self):
        self.identities = {}
        group = self.scoped_baseline(dict(AAPL=FULL))
        group["receipt"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(runtime.Refused, "^MANAGED_OBJECT_HASH$"):
            self.collect([group], tracked=("AAPL",), prior={"AAPL": FULL[-1]})
        self.assertEqual(self.opener.urls, [])

    def test_identity_only_targets_do_not_gain_new_coverage_or_holds(self):
        group = self.scoped_baseline(dict(AAPL=FULL, MSFT=FULL[1:]))
        identities = {}
        coverage = runtime.bootstrap_coverage(self.drive, self.control, dict(groups=[group]),
            {"AAPL"}, asset_identities=identities, identity_targets={"AAPL", "MSFT"})
        self.assertEqual(coverage, {"AAPL": FULL[-1]})
        self.assertEqual(set(identities), {"AAPL", "MSFT"})
        self.assertEqual(self.opener.urls, [])

    def test_same_control_two_complete_sessions_then_current_reuse(self):
        self.identities = {}
        self.control.update(max_runs=3, expires_at="2026-10-28T00:30:00Z")
        group = self.scoped_baseline(dict(AAPL=FULL[:2]), end=FULL[-1])
        bootstrap = dict(groups=[group], asset_identity_refs={})
        history, meters, results = [], {}, []

        def verify_meter(run, checkpoint):
            return runtime.verify_final_meter(meters[run["id"]], run, checkpoint,
                "b" * 64, self.control["per_run_allowance"])

        for run_id, observed in enumerate(("2026-10-24T00:30:00Z",
                "2026-10-27T00:30:00Z", "2026-10-27T00:31:00Z"), 1):
            self.now = runtime.campaign.utc(observed)
            if run_id > 1:
                self.meter = runtime.campaign.RuntimeMeter(self.control["per_run_allowance"],
                    self.root / ("meter" + str(run_id) + ".json"),
                    (self.now + timedelta(seconds=300)).isoformat(),
                    dict(run_id=run_id, run_attempt=1, source_sha="2" * 40,
                         parent_checkpoint_sha256=None, examined_before=0),
                    clock=lambda: self.now, opener=self.opener)
                self.drive.meter = self.meter
            self.meter.identity["managed_control_sha256"] = "b" * 64
            history.append(dict(id=run_id, head_sha="2" * 40))
            gate = runtime.managed.evaluate_market_session(now_utc=self.now, min_close_age_minutes=120)
            result = runtime.execute(self.control, "b" * 64,
                dict(active_tickers=["AAPL"], watch_tickers=[]), bootstrap, history,
                self.drive, self.meter, dict(run_id=run_id, head="2" * 40),
                "fixture-key", "fixture-secret", lambda: self.now,
                meter_verifier=verify_meter, market_preflight=gate)
            self.meter.finish("COMPLETE")
            meters[run_id] = json.loads(self.meter.journal.read_text(encoding="utf-8"))
            self.assertEqual(verify_meter(history[-1], result["checkpoint_sha256"])["provider_gets"],
                             3 if run_id < 3 else 0)
            self.assertTrue(result["session_coverage"]["all_tracked_same_session"])
            results.append(result)
        self.assertEqual([r["session"] for r in results], ["2026-10-23", "2026-10-26", "2026-10-26"])
        self.assertEqual([r["valid_updated"] for r in results], [1, 1, 0])
        self.assertEqual([r["reused"] for r in results], [0, 0, 1])
        rows = runtime.journal_rows(self.drive, self.control)
        self.assertEqual(sum(r["state"] == "COMPLETE" for _, r in rows), 3)
        _, coverage, held = runtime.restore_journal(rows, history + [dict(id=4)], "b" * 64, verify_meter)
        self.assertEqual((coverage, held), ({"AAPL": "2026-10-26"}, {}))
        self.assertEqual(len(self.opener.urls), 6)

    def test_internal_hole_held_even_when_explicit_backfill_lists_it(self):
        self.control["backfill_tickers"] = ["MSFT"]
        values = self.collect([self.baseline(dict(AAPL=FULL, MSFT=FULL[::2]))])
        self.assertEqual(values[:3], ({"AAPL": FULL[-1]}, {"MSFT": HELD}, ["AAPL"]))
        self.assertEqual(self.opener.urls, [])

    def test_complete_sibling_updates_while_prefix_held_is_not_backfilled(self):
        self.control["backfill_tickers"] = ["MSFT"]
        group = self.baseline(dict(AAPL=FULL[:2], MSFT=FULL[1:2]), end="2026-10-23")
        result = self.execute([group])
        self.assertEqual((result["valid_updated"], result["reused"], result["held"], result["rows"]), (1, 0, 1, 2))
        self.assertEqual(self.meter.used["provider_gets"], 3)
        self.assertEqual(len(self.opener.urls), 3)
        self.assertTrue(all("MSFT" not in u for u in self.opener.urls))
        self.assertNotIn(self.identities["MSFT"]["file_id"], self.drive.checked)

    def test_absent_bootstrap_requires_explicit_backfill(self):
        values = self.collect([], tracked=("AAPL",))
        self.assertEqual(values[:3], ({}, {"AAPL": "MISSING_VERIFIED_ALPACA_COVERAGE"}, []))
        self.assertEqual(self.opener.urls, [])
        self.control["backfill_tickers"] = ["AAPL"]
        values = self.collect([], tracked=("AAPL",))
        self.assertEqual(values[0], {"AAPL": FULL[-1]})
        self.assertEqual(values[1:3], ({}, []))
        self.assertEqual(self.meter.used["provider_gets"], 3)
        self.assertTrue(any("start=" + cap.MIN_START in url for url in self.opener.urls))

    def test_prior_held_stays_visible_and_is_not_retried(self):
        values = self.collect([], prior={"AAPL": FULL[-1], "MSFT": FULL[-1]}, held={"MSFT": "PRIOR_REVIEW"})
        self.assertEqual(values[:3], ({"AAPL": FULL[-1]}, {"MSFT": "PRIOR_REVIEW"}, ["AAPL"]))
        self.assertEqual(self.opener.urls, [])
        self.assertNotIn(self.identities["MSFT"]["file_id"], self.drive.checked)
        prior = {"AAPL": "PRIOR_REVIEW", "MSFT": "PRIOR_REVIEW"}
        self.assertEqual(self.collect([], held=prior)[:3], ({}, prior, []))
        self.assertEqual(self.opener.urls, [])

    def test_all_held_real_run_blocks_journal_meter_and_caller(self):
        group = self.baseline(dict(AAPL=FULL[1:], MSFT=FULL[1:]))
        self.assert_all_held_run([group], {"AAPL": HELD, "MSFT": HELD})

    def test_no_coverage_or_backfill_is_not_a_successful_empty_run(self):
        self.assert_all_held_run([], {t: "MISSING_VERIFIED_ALPACA_COVERAGE" for t in ("AAPL", "MSFT")})

    def assert_all_held_run(self, groups, expected_held):
        policy = dict(automatic_capture_enabled=True, active_tickers=["AAPL"], watch_tickers=["MSFT"])
        args = SimpleNamespace(policy=self.root / "policy.json", inventory=self.root / "inventory.json",
                               output=self.root / "result.json", meter=self.root / "meter.json")
        with ExitStack() as stack:
            for name, value in (("validate_control", "b" * 64), ("deployed_source", self.now),
                    ("owner_grant", self.now), ("source_history_fence", []),
                    ("run_history", [dict(id=1, head_sha="2" * 40)]),
                    ("context_from_env", dict(run_id=1, attempt=1, head="2" * 40)),
                    ("rights_and_bootstrap", dict(groups=groups, asset_identity_refs=self.identities)),
                    ("final_meter_reader", None)):
                stack.enter_context(patch.object(runtime, name, return_value=value))
            stack.enter_context(patch.object(runtime.managed, "load", side_effect=[(policy, "c" * 64), ({}, "a" * 64)]))
            for name in ("inventory_rows", "policy_rows", "transition"):
                stack.enter_context(patch.object(runtime.managed, name))
            stack.enter_context(patch.object(runtime.campaign, "RuntimeMeter", return_value=self.meter))
            stack.enter_context(patch.dict("os.environ", {"A1_MANAGED_OHLCV_CONTROL": json.dumps(self.control)}))
            with self.assertRaisesRegex(runtime.Refused, "^MANAGED_ALL_COMPONENTS_HELD$"):
                runtime.run(args, gh=lambda _: self.fail("metadata"),
                            drive_factory=lambda *a, **k: self.drive, clock=lambda: self.now)
        self.assertEqual(self.opener.urls, [])
        rows = runtime.journal_rows(self.drive, self.control)
        self.assertEqual({r["state"] for _, r in rows}, {"RESERVED", "BLOCKED"})
        terminal = next(r for _, r in rows if r["state"] == "BLOCKED")
        self.assertEqual(terminal["reason"], "MANAGED_ALL_COMPONENTS_HELD")
        self.assertEqual(terminal["held"], expected_held)
        self.assertEqual((terminal["coverage_updates"], terminal["reused"], terminal["receipts"], terminal["rows"]), ({}, [], [], 0))
        meter = json.loads(args.meter.read_text(encoding="utf-8"))
        self.assertEqual((meter["status"], meter["finalized"], meter["usage"]["provider_gets"]), ("BLOCKED", True, 0))
        self.assertEqual(meter["reason"], "MANAGED_RUN_BLOCKED")
        self.assertTrue(all(meter[k] is False for k in ("source_admission", "pit_verified", "economic_authority")))
        with self.assertRaisesRegex(runtime.Refused, "MANAGED_PRIOR_FAILURE_REQUIRES_RECONCILIATION"):
            runtime.restore_journal(rows, [dict(id=1, head_sha="2" * 40), dict(id=2)], "b" * 64)

    def repack(self, group, mutate):
        receipt = runtime.decode(self.drive.objects[group["receipt"]["file_id"]])
        with zipfile.ZipFile(io.BytesIO(self.drive.objects[receipt["raw_object"]["file_id"]])) as archive:
            members = {n: archive.read(n) for n in archive.namelist()}
        mutate(members)
        receipt["raw_object"] = self.drive.seed(self.control["private_data_folder_id"], cap.zip_bytes(members), ".zip")
        group["receipt"] = self.drive.seed(self.control["private_data_folder_id"], runtime.encoded(receipt))

    def test_integrity_failures_after_a_held_group_remain_global(self):
        for case in ("receipt_hash", "raw_hash", "norm_hash", "raw_bytes", "norm_bytes", "schema", "malformed", "norm_row", "basis"):
            with self.subTest(case=case):
                held = self.baseline(dict(MSFT=FULL[1:]))
                good = self.baseline(dict(AAPL=FULL), split=dict(AAPL=FULL[:2]) if case == "basis" else None)
                receipt = runtime.decode(self.drive.objects[good["receipt"]["file_id"]])
                if case == "receipt_hash":
                    good["receipt"]["sha256"] = "0" * 64
                elif case in ("raw_hash", "norm_hash", "raw_bytes", "norm_bytes", "norm_row"):
                    key = "raw_object" if case.startswith("raw") else "normalized_object"
                    if case.endswith("hash"):
                        receipt[key]["sha256"] = "0" * 64
                    elif case.endswith("bytes"):
                        receipt[key]["bytes"] += 1
                    else:
                        receipt[key] = self.drive.seed(self.control["private_data_folder_id"], gzip.compress(b'{}\n', mtime=0), ".jsonl.gz")
                    good["receipt"] = self.drive.seed(self.control["private_data_folder_id"], runtime.encoded(receipt))
                elif case in ("schema", "malformed"):
                    def mutate(members):
                        meta = runtime.decode(members["capture.json"])
                        if case == "schema":
                            meta["schema"] = "invalid"
                        else:
                            page = meta["pages"][0]
                            body = runtime.decode(members.pop(page["member"]))
                            body["bars"]["AAPL"][0]["c"] = None
                            raw = runtime.encoded(body)
                            h = runtime.digest(raw)
                            page.update(member=h + ".json", sha256=h, bytes=len(raw))
                            members[page["member"]] = raw
                        members["capture.json"] = runtime.encoded(meta)
                    self.repack(good, mutate)
                reason = {"schema": "RESUME_ARCHIVE", "malformed": "BAR_VALUE",
                          "norm_row": "RESUME_NORMALIZED_MISMATCH", "basis": "RESUME_BASIS_GRID"}.get(
                              case, "MANAGED_OBJECT_HASH")
                with self.assertRaisesRegex(runtime.Refused, "^" + reason + "$") as caught:
                    self.collect([held, good])
                self.assertNotIsInstance(caught.exception, runtime.IncompleteBootstrapCoverage)
                self.assertEqual(self.opener.urls, [])

    def test_unexpected_exchange_holiday_is_not_a_recoverable_gap(self):
        group = self.baseline(dict(AAPL=["2026-11-25", "2026-11-26", "2026-11-27"]),
                              start="2026-11-25", end="2026-11-28")
        with self.assertRaisesRegex(runtime.Refused, "^MANAGED_BOOTSTRAP_UNEXPECTED_SESSION$") as caught:
            self.collect([group], tracked=("AAPL",))
        self.assertNotIsInstance(caught.exception, runtime.IncompleteBootstrapCoverage)
        self.assertEqual(self.opener.urls, [])


class TieredCadenceTests(unittest.TestCase):
    """Synthetic role/control evidence, never actual holdings or market rights."""

    def setUp(self):
        self.enterContext(patch.object(socket, "create_connection", side_effect=AssertionError("network")))
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network")))
        self.now = runtime.campaign.utc("2026-10-24T00:30:00Z")
        self.monitor = (runtime.ROOT / runtime.managed.MONITOR_CONTRACT).read_bytes()
        self.monitor_sha = runtime.digest(self.monitor)
        self.helper_path = runtime.ROOT / runtime.managed.MONITOR_HELPER
        self.helper_raw = self.helper_path.read_bytes()
        self.helper_sha = runtime.digest(self.helper_raw.replace(b"\r\n", b"\n"))
        from tools import run287_etf_rotation as helper
        self.etf_sha = runtime.digest(runtime.managed.encode(sorted(helper.universe(
            helper.policy(json.loads(self.monitor))[0]))))
        self.proof = b'{"fixture_only":"independent Source review; not actual portfolio evidence"}'
        self.proof_sha = runtime.digest(self.proof)
        self.proofs = {self.proof_sha: self.proof}

    def evidence(self):
        return dict(scope="RESEARCH_ONLY", source_sha256=self.proof_sha,
            source_reference="https://github.com/wscha231/r1000-quant-engine/issues/448#issuecomment-12345678",
            as_of="2026-10-23T20:00:00Z", available_at="2026-10-23T20:01:00Z",
            expires_at="2026-11-01T00:00:00Z")

    def packet(self):
        return dict(schema="a1-managed-priority-roster-v1", usage="RESEARCH_ONLY",
            as_of="2026-10-23T20:00:00Z", available_at="2026-10-23T20:01:00Z",
            expires_at="2026-11-01T00:00:00Z",
            source_reference=runtime.managed.A0 + "#issuecomment-12345678",
            holdings=dict(status="UNKNOWN", portfolio_mode="ACTUAL", tickers=None),
            roles=[dict(self.evidence(), ticker="AAPL", role="PRIORITY")])

    def parse(self, packet=None, *, binding=None, expected=None, monitor_sha=None, limit=60):
        raw = runtime.encoded(self.packet() if packet is None else packet)
        return runtime.managed.priority_roster(raw,
            expected_sha256=runtime.digest(raw) if expected is None else expected,
            monitor_raw=self.monitor, monitor_sha256=self.monitor_sha if monitor_sha is None else monitor_sha,
            monitor_helper_sha256=self.helper_sha, etf_universe_sha256=self.etf_sha,
            proof_objects=self.proofs, max_priority_candidates=limit, holdings_binding=binding,
            now_utc=self.now)

    def holding(self, *, status="VERIFIED", mode="ACTUAL", kind="ACTUAL_ACCEPTED", names=None):
        value = dict(self.evidence(), status=status, portfolio_mode=mode, portfolio_kind=kind,
                     tickers=["AAPL"] if names is None else names, scope=mode,
                     positions_sha256=self.proof_sha)
        keys = ("portfolio_mode", "portfolio_kind", "status", "positions_sha256", "tickers", "as_of",
                "available_at", "expires_at", "source_reference")
        return value, {k: value[k] for k in keys}

    def cadence(self, *, extra=None):
        ref = dict(file_id="fixture-proof-123", sha256=self.proof_sha, bytes=len(self.proof))
        return dict(schema=runtime.managed.CADENCE_SCHEMA, roster_ref=ref, source_refs=[ref],
                    monitor_contract_sha256=self.monitor_sha, max_priority_candidates=60,
                    monitor_helper_sha256=self.helper_sha, etf_universe_sha256=self.etf_sha,
                    holdings_binding=None, weekly_catchup=extra)

    def test_unknown_holdings_preserves_independent_etfs_and_candidate(self):
        roster = self.parse()
        self.assertEqual(roster["etf_count"], 42)
        self.assertEqual(len(roster["daily"]), 43)
        self.assertEqual(roster["daily"]["SPY"], ["ETF"])
        self.assertEqual(roster["daily"]["AAPL"], ["PRIORITY"])
        self.assertEqual((roster["holdings_status"], roster["holdings_completeness"],
                          roster["overall_status"]), ("UNKNOWN", "UNKNOWN", "PARTIAL_HOLDINGS"))

    def test_helper_drift_refuses_before_import_or_provider(self):
        original_open = Path.open
        def changed(path, *args, **kwargs):
            if path.resolve() == self.helper_path.resolve():
                return io.BytesIO(self.helper_raw + b"\n# changed policy code\n")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", changed), self.assertRaisesRegex(ValueError, "CADENCE_HELPER_CODE_CHANGED"):
            self.parse()

    def test_imported_helper_replacement_cannot_add_or_swap_same_count_basket(self):
        from tools import run287_etf_rotation as helper
        original = helper.universe
        for swap in (False, True):
            def substituted(config):
                result = original(config)
                if swap:
                    result.pop("SPY")
                result["AAPL"] = dict(kind="THEME", group="changed", label="unreviewed")
                return result
            with self.subTest(swap=swap), patch.object(helper, "universe", substituted), \
                    self.assertRaisesRegex(ValueError, "CADENCE_HELPER_EXECUTION_CHANGED"):
                self.parse()

    def test_monitor_and_external_same_count_basket_pins_both_refuse_drift(self):
        monitor = json.loads(self.monitor)
        rotation = monitor["etf_rotation"]
        used = set(rotation["watch_reference"].values())
        group = next(g for g in rotation["themes"].values() if set(g) - used)
        old = next(t for t in group if t not in used)
        group["AAPL"] = group.pop(old)
        changed = runtime.encoded(monitor)
        with self.assertRaisesRegex(ValueError, "CADENCE_MONITOR_HASH"):
            runtime.managed.priority_roster(runtime.encoded(self.packet()),
                expected_sha256=runtime.digest(runtime.encoded(self.packet())), monitor_raw=changed,
                monitor_sha256=self.monitor_sha, monitor_helper_sha256=self.helper_sha,
                etf_universe_sha256=self.etf_sha, proof_objects=self.proofs,
                max_priority_candidates=60, holdings_binding=None, now_utc=self.now)
        with self.assertRaisesRegex(ValueError, "CADENCE_ETF_UNIVERSE_CHANGED"):
            runtime.managed.priority_roster(runtime.encoded(self.packet()),
                expected_sha256=runtime.digest(runtime.encoded(self.packet())), monitor_raw=changed,
                monitor_sha256=runtime.digest(changed), monitor_helper_sha256=self.helper_sha,
                etf_universe_sha256=self.etf_sha, proof_objects=self.proofs,
                max_priority_candidates=60, holdings_binding=None, now_utc=self.now)

    def test_helper_git_lf_binding_preserves_observed_windows_crlf_hash(self):
        canonical = self.helper_raw.replace(b"\r\n", b"\n")
        crlf = canonical.replace(b"\n", b"\r\n")
        original_open = Path.open
        def windows_file(path, *args, **kwargs):
            if path.resolve() == self.helper_path.resolve():
                return io.BytesIO(crlf)
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", windows_file):
            roster = self.parse()
        self.assertEqual(roster["etf_helper_binding"], dict(expected_GitLF_sha256=self.helper_sha,
            observed_file_sha256=runtime.digest(crlf), normalization="CRLF_TO_LF_EXACT_MATCH"))
        self.assertNotEqual(runtime.digest(crlf), self.helper_sha)

    def test_wrong_helper_origin_and_legacy_no_cadence_compatibility(self):
        from tools import run287_etf_rotation as helper
        with patch.object(helper, "__file__", "other/helper.py"), \
                self.assertRaisesRegex(ValueError, "CADENCE_HELPER_BINDING"):
            self.parse()
        with patch.object(runtime.managed, "verified_etf_helper", side_effect=AssertionError("legacy helper I/O")):
            self.assertEqual(runtime.select_candidates({"AAPL", "MSFT"}, {}, {}, FULL[-1], 1), ["AAPL"])
            self.assertTrue(runtime.managed.cadence_market_gate(now_utc=self.now)["ready"])

    def test_unknown_is_not_an_empty_portfolio(self):
        value = self.packet(); value["holdings"]["tickers"] = []
        with self.assertRaisesRegex(ValueError, "CADENCE_UNKNOWN_NOT_EMPTY"):
            self.parse(value)

    def test_actual_holdings_requires_external_original_positions_binding(self):
        value = self.packet(); value["holdings"], binding = self.holding()
        with self.assertRaisesRegex(ValueError, "CADENCE_HOLDINGS_EXTERNAL_BINDING"):
            self.parse(value)
        roster = self.parse(value, binding=binding)
        self.assertEqual(set(roster["daily"]["AAPL"]), {"HOLDING", "PRIORITY"})
        self.assertEqual(roster["holdings_completeness"], "VERIFIED")
        changed = deepcopy(value); changed["holdings"]["positions_sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "CADENCE_HOLDINGS_EXTERNAL_BINDING"):
            self.parse(changed, binding=binding)
        changed = deepcopy(value); changed["holdings"]["tickers"] = ["AAPM"]
        with self.assertRaisesRegex(ValueError, "CADENCE_HOLDINGS_EXTERNAL_BINDING"):
            self.parse(changed, binding=binding)

    def test_model_empty_and_csv_path_do_not_authenticate_actual_empty(self):
        value = self.packet()
        value["holdings"], binding = self.holding(status="NO_POSITIONS", kind="RESEARCH_MODEL", names=[])
        with self.assertRaisesRegex(ValueError, "CADENCE_HOLDINGS_KIND"):
            self.parse(value, binding=binding)
        value["holdings"] = dict(status="VERIFIED", portfolio_mode="ACTUAL", tickers=[], csv="old-paper.csv")
        with self.assertRaisesRegex(ValueError, "CADENCE_HOLDINGS_EXTERNAL_BINDING"):
            self.parse(value)

    def test_explicit_research_no_positions_and_notconfigured_keep_their_meaning(self):
        for status in ("NO_POSITIONS", "NOT_CONFIGURED"):
            with self.subTest(status=status):
                value = self.packet()
                value["holdings"], binding = self.holding(status=status, mode="RESEARCH_ONLY",
                    kind="RESEARCH_" + status, names=[])
                roster = self.parse(value, binding=binding)
                self.assertEqual(roster["holdings_status"], status)
                self.assertIn("SPY", roster["daily"])
                if status == "NOT_CONFIGURED":
                    self.assertEqual(roster["overall_status"], "PARTIAL_HOLDINGS")

    def test_external_hashes_and_roster_schema_cannot_self_authorize(self):
        for kwargs, reason in ((dict(expected="f" * 64), "CADENCE_ROSTER_HASH"),
                               (dict(monitor_sha="f" * 64), "CADENCE_MONITOR_HASH")):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.parse(**kwargs)
        value = self.packet(); value["owner_approved"] = True
        with self.assertRaisesRegex(ValueError, "CADENCE_ROSTER_SCHEMA"):
            self.parse(value)

    def test_sources_clocks_duplicates_v0_and_candidate_cap(self):
        cases = []
        value = self.packet(); value["roles"][0]["source_sha256"] = "f" * 64
        cases.append((value, "CADENCE_ROLE_SOURCE"))
        value = self.packet(); value["roles"][0]["scope"] = "ACTUAL"
        cases.append((value, "CADENCE_CANDIDATE_RESEARCH_SCOPE"))
        value = self.packet(); value["available_at"] = "2026-10-25T00:00:00Z"
        cases.append((value, "CADENCE_ROSTER_STALE_OR_FUTURE"))
        value = self.packet(); value["expires_at"] = "2026-10-23T00:00:00Z"
        cases.append((value, "CADENCE_ROSTER_STALE_OR_FUTURE"))
        value = self.packet(); value["roles"] *= 2
        cases.append((value, "CADENCE_ROLE_DUPLICATE"))
        value = self.packet(); value["roles"][0].update(role="OPPORTUNITY", verification="V0", event_id="event-fixture-1")
        cases.append((value, "CADENCE_EVENT_UNVERIFIED"))
        for value, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.parse(value)
        with self.assertRaisesRegex(ValueError, "CADENCE_CANDIDATE_BOUND"):
            self.parse(limit=0)

    def test_stale_role_is_preserved_without_becoming_daily(self):
        value = self.packet(); value["roles"][0]["expires_at"] = "2026-10-23T23:59:00Z"
        roster = self.parse(value)
        self.assertNotIn("AAPL", roster["daily"])
        self.assertEqual(roster["stale_roles"]["AAPL"], ["STALE_PRIORITY_EVIDENCE"])
        self.assertIn("SPY", roster["daily"])

    def test_verified_opportunity_has_one_event_and_never_creates_sixty_candidates(self):
        value = self.packet(); value["roles"][0].update(role="OPPORTUNITY", verification="V2", event_id="event-fixture-1")
        roster = self.parse(value)
        self.assertEqual(roster["daily"]["AAPL"], ["OPPORTUNITY"])
        self.assertEqual(len(roster["daily"]), 43)
        value["roles"].append(dict(value["roles"][0], ticker="MSFT"))
        with self.assertRaisesRegex(ValueError, "CADENCE_EVENT_UNVERIFIED"):
            self.parse(value)

    def test_role_rank_precedes_age_and_duplicate_role_uses_highest_priority(self):
        value = self.packet(); value["holdings"], binding = self.holding(names=["SPY"])
        value["roles"].append(dict(self.evidence(), ticker="MSFT", role="OPPORTUNITY",
                                   event_id="event-fixture-2", verification="V1"))
        roster = self.parse(value, binding=binding)
        schedule = runtime.managed.tier_schedule(roster, {"SPY", "QQQ", "AAPL", "MSFT", "ZZZ"}, "2026-10-23")
        coverage = {"SPY": "2026-10-22", "QQQ": "2020-01-02", "AAPL": "2019-01-02"}
        self.assertEqual(runtime.select_candidates(set(coverage) | {"MSFT", "ZZZ"}, coverage, {},
            "2026-10-23", 5, schedule), ["SPY", "QQQ", "AAPL", "MSFT", "ZZZ"])
        coverage["SPY"] = "2026-10-23"
        self.assertEqual(runtime.select_candidates(set(coverage) | {"MSFT", "ZZZ"}, coverage, {},
            "2026-10-23", 1, schedule), ["QQQ"])

    def test_weekday_watch_not_due_and_weekly_pending_is_not_removed(self):
        roster = self.parse()
        schedule = runtime.managed.tier_schedule(roster, {"AAPL", "MSFT"}, "2026-10-21")
        self.assertFalse(schedule["weekly_due"])
        self.assertEqual(schedule["weekly_target_session"], "2026-10-16")
        self.assertEqual(runtime.select_candidates({"AAPL", "MSFT"}, {}, {}, "2026-10-21", 2, schedule), ["AAPL"])
        progress = runtime.managed.tier_progress(schedule, {"AAPL", "MSFT"}, {}, {}, "2026-10-21")
        self.assertEqual(progress["pending_weekly"], ["MSFT"])
        self.assertEqual(progress["holdings_completeness"], "UNKNOWN")

    def test_ordinary_saturday_earlyclose_and_dst_use_actual_session_closes(self):
        for now, close in (("2026-10-24T00:30:00Z", "2026-10-23T20:00:00Z"),
                           ("2026-11-07T00:30:00Z", "2026-11-06T21:00:00Z"),
                           ("2026-11-28T00:30:00Z", "2026-11-27T18:00:00Z")):
            with self.subTest(now=now):
                gate = runtime.managed.cadence_market_gate(now_utc=now, cadence=self.cadence())
                self.assertTrue(gate["ready"])
                self.assertEqual(runtime.campaign.utc(gate["market_close_utc"]), runtime.campaign.utc(close))

    def friday_holiday(self):
        return dict(mode="WEEKLY_CATCHUP", week_start="2026-03-30", session="2026-04-02",
                    not_before="2026-04-03T00:30:00Z", expires_at="2026-04-06T00:00:00Z")

    def test_friday_holiday_requires_explicit_week_and_preserves_old_session(self):
        now = "2026-04-04T00:30:00Z"
        self.assertFalse(runtime.managed.cadence_market_gate(now_utc=now)["ready"])
        cadence = self.cadence(extra=self.friday_holiday())
        runtime.managed.cadence_contract(cadence, not_before="2026-04-01T00:00:00Z",
                                         expires_at="2026-04-06T00:00:00Z")
        for at in (now, "2026-04-05T00:30:00Z"):
            gate = runtime.managed.cadence_market_gate(now_utc=at, cadence=cadence)
            self.assertTrue(gate["ready"])
            self.assertEqual(gate["session_date"], "2026-04-02")
            self.assertTrue(gate["catchup_mode"])
            self.assertFalse(gate["forced"])
        self.assertFalse(runtime.managed.cadence_market_gate(now_utc="2026-04-06T00:30:00Z", cadence=cadence)["ready"])

    def test_weekly_wrong_week_non_session_or_unbounded_expiry_refuses(self):
        for key, bad, reason in (("session", "2026-04-03", "CADENCE_WEEK_END_SESSION"),
                                 ("week_start", "2026-03-23", "CADENCE_WEEK_END_SESSION"),
                                 ("expires_at", "2026-04-07T00:00:00Z", "CADENCE_WEEKLY_WINDOW")):
            extra = self.friday_holiday(); extra[key] = bad
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason):
                runtime.managed.cadence_contract(self.cadence(extra=extra),
                    not_before="2026-04-01T00:00:00Z", expires_at="2026-04-08T00:00:00Z")

    def test_journal_roster_swap_and_new_control_cannot_reset_prior_usage(self):
        base = dict(schema="a1-managed-run-checkpoint-v1", control_sha256="b" * 64,
                    cadence_binding_sha256="c" * 64, run_id=1, slot=1, source_sha="2" * 40)
        rows = [("a" * 64, dict(base, state="RESERVED", parent_sha256=None)),
                ("d" * 64, dict(base, state="COMPLETE", parent_sha256="a" * 64,
                    coverage_updates={"AAPL": "2026-10-23"}, held={}))]
        history = [dict(id=1, head_sha="2" * 40), dict(id=2)]
        result = runtime.restore_journal(rows, history, "b" * 64, lambda *_: {}, cadence_binding="c" * 64)
        self.assertEqual(result[1], {"AAPL": "2026-10-23"})
        with self.assertRaisesRegex(runtime.Refused, "CADENCE_JOURNAL_BINDING_CHANGED"):
            runtime.restore_journal(rows, history, "b" * 64, lambda *_: {}, cadence_binding="e" * 64)
        with self.assertRaisesRegex(runtime.Refused, "MANAGED_STATE_CHAIN"):
            runtime.restore_journal(rows, history, "e" * 64, lambda *_: {}, cadence_binding="c" * 64)

    def fixture(self):
        f = ComponentHoldTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        return f

    def test_collector_preserves_role_order_across_different_missing_windows(self):
        f = self.fixture()
        groups = [f.baseline({t: days}, end=(date.fromisoformat(max(days)) + timedelta(days=1)).isoformat())
                  for t, days in dict(AAPL=FULL[:1], MSFT=FULL[:2]).items()]
        schedule = dict(daily=["MSFT"], role_rank={"MSFT": 0}, weekly_due=True)
        result = runtime.collect_groups(f.drive, f.meter, f.control,
            dict(groups=groups, asset_identity_refs=f.identities), {"AAPL", "MSFT"},
            {"AAPL": FULL[0], "MSFT": FULL[1]}, {}, FULL[-1], "fixture-key", "fixture-secret",
            lambda: f.now, scheduling=schedule)
        queries = [parse_qs(urlsplit(url).query) for url in f.opener.urls if "/bars" in url]
        self.assertEqual([q["symbols"][0] for q in queries], ["MSFT", "MSFT", "AAPL", "AAPL"])
        self.assertEqual(result[0], {"AAPL": FULL[-1], "MSFT": FULL[-1]})

    def role_fixture(self):
        f = self.fixture()
        f.control["authorized_tickers"] = ["AAPL", "MSFT", "SPY"]
        f.identities["SPY"] = f.drive.seed(f.control["evidence_folder_id"], runtime.encoded(asset("SPY")))
        schedule = dict(daily=["MSFT", "SPY"], role_rank={"MSFT": 0, "SPY": 1}, weekly_due=True)
        return f, schedule

    def collect_roles(self, f, schedule, dates):
        groups = [f.baseline({t: days}, end=(date.fromisoformat(max(days)) + timedelta(days=1)).isoformat())
                  for t, days in dates.items()]
        prior = {t: max(days) for t, days in dates.items()}
        return runtime.collect_groups(f.drive, f.meter, f.control,
            dict(groups=groups, asset_identity_refs=f.identities), set(dates), prior, {}, FULL[-1],
            "fixture-key", "fixture-secret", lambda: f.now, scheduling=schedule)

    def test_same_window_mixed_roles_preserve_actual_provider_order(self):
        f, schedule = self.role_fixture()
        self.collect_roles(f, schedule, dict(AAPL=FULL[:2], MSFT=FULL[:2], SPY=FULL[:2]))
        queries = [parse_qs(urlsplit(url).query) for url in f.opener.urls if "/bars" in url]
        self.assertEqual([q["symbols"][0] for q in queries],
                         ["MSFT", "MSFT", "SPY", "SPY", "AAPL", "AAPL"])

    def test_holding_window_cannot_pull_watch_ahead_of_another_etf_window(self):
        f, schedule = self.role_fixture()
        self.collect_roles(f, schedule, dict(AAPL=FULL[:1], MSFT=FULL[:1], SPY=FULL[:2]))
        queries = [parse_qs(urlsplit(url).query) for url in f.opener.urls if "/bars" in url]
        self.assertEqual([q["symbols"][0] for q in queries],
                         ["MSFT", "MSFT", "SPY", "SPY", "AAPL", "AAPL"])

    def test_mid_group_budget_stop_never_starts_lower_role_or_refunds_completed_io(self):
        f, schedule = self.role_fixture()
        f.meter.allowance["provider_gets"] = 3
        with self.assertRaises(runtime.Refused):
            self.collect_roles(f, schedule, dict(AAPL=FULL[:1], MSFT=FULL[:1], SPY=FULL[:2]))
        queries = [parse_qs(urlsplit(url).query) for url in f.opener.urls if "/bars" in url]
        self.assertEqual([q["symbols"][0] for q in queries], ["MSFT", "MSFT"])
        self.assertEqual(f.meter.used["provider_gets"], 3)
        self.assertFalse(any("/assets/SPY" in u or "/assets/AAPL" in u for u in f.opener.urls))

    def install_roster(self, f):
        value = self.packet(); value["roles"][0]["ticker"] = "MSFT"
        cadence = self.cadence()
        cadence["roster_ref"] = f.drive.seed(f.control["evidence_folder_id"], runtime.encoded(value))
        cadence["source_refs"] = [f.drive.seed(f.control["evidence_folder_id"], self.proof)]
        f.control["cadence"] = cadence
        return cadence

    def test_bounded_execution_keeps_daily_first_weekly_pending_and_outside_names_uncaptured(self):
        f = self.fixture(); self.install_roster(f); f.control["max_symbols_per_run"] = 1
        group = f.baseline(dict(AAPL=FULL[:2], MSFT=FULL[:2]), end="2026-10-23")
        result = f.execute([group])
        self.assertEqual(result["valid_updated"], 1)
        self.assertEqual(result["tier_progress"]["pending_weekly"], ["AAPL"])
        self.assertIn("SPY", result["tier_progress"]["outside_scope"])
        self.assertEqual(result["overall_status"], "PARTIAL_HOLDINGS")
        self.assertFalse(any("SPY" in url or "AAPL" in url for url in f.opener.urls))
        rows = runtime.journal_rows(f.drive, f.control)
        binding = runtime.sha(f.control["cadence"])
        _, coverage, held = runtime.restore_journal(rows,
            [dict(id=1, head_sha="2" * 40), dict(id=2)], "b" * 64, lambda *_: {}, cadence_binding=binding)
        roster = runtime.load_cadence_roster(f.control, f.drive, f.now)
        schedule = runtime.managed.tier_schedule(roster, {"AAPL", "MSFT"}, FULL[-1])
        self.assertEqual(runtime.select_candidates({"AAPL", "MSFT"}, coverage, held,
            FULL[-1], 1, schedule), ["AAPL"])
        self.assertLess(len(runtime.encoded(result)), 65536)

    def test_empty_provider_response_is_held_without_deleting_original_bytes(self):
        f = self.fixture()
        group = f.baseline(dict(AAPL=FULL[:2]), end="2026-10-23")
        originals = set(f.drive.objects)
        original_open = f.opener.open
        def empty_bars(request, **kwargs):
            if "/bars" in request.full_url:
                f.opener.urls.append(request.full_url)
                return Reply(runtime.encoded(dict(bars={}, next_page_token=None)))
            return original_open(request, **kwargs)
        schedule = dict(daily=["AAPL"], role_rank={"AAPL": 0}, weekly_due=False)
        with patch.object(f.opener, "open", side_effect=empty_bars):
            updates, held, _, _, _ = runtime.collect_groups(f.drive, f.meter, f.control,
                dict(groups=[group], asset_identity_refs=f.identities), {"AAPL"}, {}, {},
                FULL[-1], "fixture-key", "fixture-secret", lambda: f.now, scheduling=schedule)
        self.assertEqual(updates, {})
        self.assertEqual(held["AAPL"], "VERIFIED_NO_DATA_FOR_REQUESTED_WINDOW")
        self.assertTrue(originals <= set(f.drive.objects))

    def test_budget_failure_keeps_meter_cost_and_source_history(self):
        f = self.fixture(); group = f.baseline(dict(AAPL=FULL[:2]), end="2026-10-23")
        before = set(f.drive.objects)
        f.meter.used["provider_gets"] = f.meter.allowance["provider_gets"]
        used = dict(f.meter.used)
        with self.assertRaises(runtime.Refused):
            runtime.collect_groups(f.drive, f.meter, f.control,
                dict(groups=[group], asset_identity_refs=f.identities), {"AAPL"}, {}, {},
                FULL[-1], "fixture-key", "fixture-secret", lambda: f.now,
                scheduling=dict(daily=["AAPL"], role_rank={"AAPL": 0}, weekly_due=False))
        self.assertGreaterEqual(f.meter.used["provider_gets"], used["provider_gets"])
        self.assertTrue(before <= set(f.drive.objects))


if __name__ == "__main__":
    unittest.main()
