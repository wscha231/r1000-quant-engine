#!/usr/bin/env python3
"""No-network regressions for daily research provenance and stale inputs."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import run_run287_daily_research_monitor as monitor
from tools import run287_etf_rotation as rotation
from tools import run287_research_score_handoff as handoff
from tools.run287_code_identity import IDENTITY_FILES, identity_sha256

CONTRACT = json.loads(monitor.CONTRACT.read_text(encoding="utf-8"))
NOW = monitor.timestamp("2026-09-05T08:30:00Z")
TACTICAL_EVENTS = CONTRACT["sources"]["tactical"]["allowed_events"]


def sample_run(run_id=2, conclusion="success"):
    return {"id": run_id, "run_attempt": 1, "head_sha": "a" * 40,
            "head_branch": "master", "head_repository": {"full_name": CONTRACT["repository"]},
            "created_at": f"2026-09-0{run_id}T05:00:00Z", "event": "schedule",
            "path": ".github/workflows/after_close_daily.yml", "status": "completed",
            "conclusion": conclusion}


def evidence():
    sources = {key: {"status": "VERIFIED_ARTIFACT", "artifact_hash_verified": True,
                     "run": sample_run(), "data": {}} for key in CONTRACT["sources"]}
    sources["tactical"]["data"]["summary"] = {
        "data_as_of": "2026-09-04", "latest_scored_rebalance_date": "2026-07-13"}
    sources["estimates"]["data"]["summary"] = {
        "fetch_date": "2026-09-05", "collector_status": "blocked_partial_coverage",
        "request_estimate_coverage_ratio": 1 / 6, "coverage_ratio": 1.0}
    sources["ownership"]["data"] = {
        "summary": {"13f_freshness": {"as_of_date": "2026-09-05", "freshness_ready": True,
                                     "required_due_period_end": "2026-06-30"}},
        "ranked": [{"ticker": "ETN", "smart_money_score": "0.7",
                    "latest_available_from": "2026-08-14T16:00:00Z"}]}
    sources["operating"]["data"]["prices"] = [{"ticker": "ETN", "previous_close": "300",
                                                  "latest_price_date": "2026-09-04", "currency": "USD"}]
    return sources


def score_fixture():
    """Producer-shaped export. These are test values, never investment evidence."""
    stamp = {"valuation_price_cutoff_date": "2026-09-04", "research_only": True,
             "feature_available_from": "2026-09-05T01:00:00Z",
             "decision_time_utc": "2026-09-05T02:00:00Z", "executed_at_utc": "2026-09-05T03:00:00Z"}
    boundary = {key: False for key in handoff.SAFE_FALSE}
    decision = {**stamp, **boundary, "schema_version": "run287-current-decision-frame-v1",
                "status": "READY_COMPLETE_CURRENT_DECISION_FRAME",
                "current_decision_data_complete": True, "research_model_scoring_prerequisite_passed": True}
    linear = {**stamp, **boundary, "schema_version": "run287-current-decision-score-only-v1",
              "status": "READY_CURRENT_DECISION_SCORE_ONLY_NONRANKING", "source_inputs": {}}
    stack = {**stamp, **boundary, "schema_version": "run287-current-decision-score-stack-audit-v1",
             "status": "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
             "score_stack_audit_passed": True, "fresh_prediction_passthrough_verified": True,
             "stale_prediction_columns_removed_before_join": True, "model_scoring_executed": True,
             "catboost_scoring_executed": True, "adaptive_ensemble_executed": True,
             "source_immutability": {"all_verified_files_unchanged": True},
             "stale_prediction_suffix_collision_count": 0, "contract_failures": [],
             "code": {"git_head": "a" * 40}, "source_inputs": {}, "outputs": {},
             "coverage": {"ticker_count": 3, "active_prediction_head_count": 6,
                          "active_prediction_head_required_count": 6, "prediction_passthrough_pass_count": 6,
                          "prediction_passthrough_required_count": 6}}
    for key in ("target_books_mutated", "source_inputs_mutated", "target_book_generation_allowed",
                "score_sort_executed", "rank_assignment_executed", "top_n_executed"):
        stack[key] = False
    for key in ("frozen_score_stack_manifest", "model_meta"):
        stack["source_inputs"][key] = {"sha256": "b" * 64, "hash_matches": True}
    decision["source_inputs"] = {"model_meta": {"sha256": "b" * 64}}
    linear["source_inputs"]["model_meta"] = {"sha256": "b" * 64}
    identity = {"schema_version": "run287-exact-packet-code-identity-v1", "source_commit_sha": "a" * 40,
                "source_tree_sha": "b" * 40, "files": {k: {"path": v, "sha256": "c" * 64} for k, v in IDENTITY_FILES.items()}}
    identity["identity_sha256"] = identity_sha256(identity)
    bundle = {**stamp, "schema_version": "run287-exact-packet-input-source-bundle-v1",
              "status": "READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY", "code_identity": identity, "inputs": {}}
    rows = [{"ticker": ticker, "score": 0 if i == 0 else -i / 10,
             **{head: i / 10 + .01 for head in handoff.HEADS},
             **{key: True for key in handoff.ROW_FLAGS},
             "corporate_action_quarantine": False, "missing_neutral_applied": False,
             "decision_ranking_allowed": False, "critical_missing_fields": ""}
            for i, ticker in enumerate(("ETN", "AVGO", "VRT"))]
    upstream = {**stamp, "status": "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY", "upstream_ready": True}
    return dict(bundle=bundle, decision=decision, linear=linear, stack=stack, rows=rows, upstream=upstream)


def pack_scores(fixture, *, absolute=False, alter=None):
    f = copy.deepcopy(fixture)
    members = {}
    # Deliberately an earlier attempt: exact reuse follows the root graph.
    root = "outputs/run287_exact_packet_upstream/attempts/1-1/"
    prefix = "/home/runner/work/r1000-quant-engine/r1000-quant-engine/" if absolute else ""

    def add(path, obj):
        if path.endswith(".csv"):
            handle = io.StringIO()
            writer = csv.DictWriter(handle, fieldnames=list(obj[0]))
            writer.writeheader()
            writer.writerows(obj)
            raw = handle.getvalue().encode()
        else:
            raw = json.dumps(obj).encode()
        members[path] = raw
        return {"path": prefix + path, "sha256": hashlib.sha256(raw).hexdigest()}

    decision = add(root + "decision/manifest.json", f["decision"])
    f["linear"]["source_inputs"]["decision_frame_manifest"] = copy.deepcopy(decision)
    f["stack"]["source_inputs"]["decision_frame_manifest"] = copy.deepcopy(decision)
    f["stack"]["source_inputs"]["score_only_manifest"] = add(root + "score_only/manifest.json", f["linear"])
    f["stack"]["outputs"]["ticker_order_score_stack"] = {**add(root + "score_stack/ticker_order_score_stack.csv", f["rows"]), "row_count": len(f["rows"])}
    if alter:
        alter(f)
    f["bundle"]["inputs"]["decision_manifest"] = decision
    f["bundle"]["inputs"]["score_stack_manifest"] = add(root + "score_stack/manifest.json", f["stack"])
    f["upstream"]["source_bundle"] = add("outputs/run287_exact_packet_input_sources/source_bundle.json", f["bundle"])
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name, raw in members.items():
            z.writestr(name, raw)
    return archive.getvalue(), f["upstream"]


def score_source(fixture=None, *, absolute=False, alter=None):
    raw, upstream = pack_scores(fixture or score_fixture(), absolute=absolute, alter=alter)
    source = evidence()["operating"]
    source["data"]["upstream"] = upstream
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "score.zip"
        path.write_bytes(raw)
        data, hashes = handoff.read_score_handoff(path, upstream, CONTRACT["repository"], CONTRACT["max_member_bytes"])
    source["data"]["score_handoff"] = data
    source["files"] = hashes
    return source


class MonitorTests(unittest.TestCase):
    def test_current_score_graph_joins_without_creating_a_rank_or_portfolio(self):
        source = evidence()
        source["operating"] = score_source(absolute=True)
        original = copy.deepcopy(source)
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        self.assertEqual(source, original)
        self.assertTrue(report["current_engine_scores_ready"])
        self.assertFalse(report["current_investment_ranking_ready"])
        self.assertFalse(report["current_portfolio_ready"])
        rows = {r["ticker"]: r for r in report["watchlist"]}
        self.assertEqual(rows["ETN"]["current_engine_score"], 0.0)
        self.assertLess(rows["AVGO"]["current_engine_score"], 0)
        self.assertEqual(rows["ETN"]["engine_code_sha"], "a" * 40)
        self.assertIsNone(rows["NVDA"]["current_engine_score"])
        self.assertIsNone(rows["000660"]["current_engine_score"])
        self.assertIn("operating:SCORE_TICKER_MISSING:NVDA", report["alerts"])
        self.assertIn("nonranking", monitor.render(report))

    def test_score_graph_rejects_cross_attempt_hash_and_path_changes(self):
        with self.assertRaisesRegex(ValueError, "score_decision_link_mismatch"):
            score_source(alter=lambda f: f["stack"]["source_inputs"]["decision_frame_manifest"].update(sha256="d" * 64))
        with self.assertRaisesRegex(ValueError, "score_member_hash_mismatch"):
            score_source(alter=lambda f: f["stack"]["outputs"]["ticker_order_score_stack"].update(sha256="d" * 64))
        for path in ("/tmp/outputs/file.json", "outputs/../secret.json", "outputs/a/../../secret.json",
                     "outputs//file.json", "outputs/a\\file.json", "https://example.com/file.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                handoff.member_path(path, CONTRACT["repository"])

    def test_score_dates_identity_and_failed_runs_fail_closed(self):
        for field, value, expected in (
            ("valuation_price_cutoff_date", "2026-07-13", "SCORE_SESSION_MISMATCH"),
            ("executed_at_utc", "2026-09-06T09:00:00Z", "SCORE_TIME_ORDER_INVALID"),
            ("feature_available_from", "2026-09-05T04:00:00Z", "SCORE_TIME_ORDER_INVALID"),
            ("decision_ranking_allowed", True, "SCORE_EXECUTION_BOUNDARY_INVALID"),
        ):
            fixture = score_fixture()
            fixture["stack"][field] = value
            with self.subTest(field=field):
                result, rows = handoff.evaluate_score_handoff(score_source(fixture), "2026-09-04", NOW)
                self.assertEqual(result["status"], expected)
                self.assertEqual(rows, {})
        source = score_source()
        source["run"]["head_sha"] = "d" * 40
        self.assertEqual(handoff.evaluate_score_handoff(source, "2026-09-04", NOW)[0]["status"], "SCORE_CODE_IDENTITY_MISMATCH")
        source["status"] = "UPSTREAM_FAILED"
        self.assertEqual(handoff.evaluate_score_handoff(source, "2026-09-04", NOW)[1], {})

    def test_duplicate_constant_and_nonfinite_score_exports_are_unusable(self):
        for kind in ("duplicate", "constant", "nonfinite", "boolean", "count"):
            f = score_fixture()
            if kind == "duplicate":
                f["rows"][1]["ticker"] = f["rows"][0]["ticker"]
            elif kind == "constant":
                for row in f["rows"]:
                    row["pred_cat_p"] = 0
            elif kind == "nonfinite":
                f["rows"][0]["score"] = "nan"
            elif kind == "boolean":
                f["rows"][0]["research_eligible_after_quarantine"] = "yes"
            else:
                f["stack"]["coverage"]["ticker_count"] = 20
            with self.subTest(kind=kind):
                result, rows = handoff.evaluate_score_handoff(score_source(f), "2026-09-04", NOW)
                self.assertFalse(result["ready"])
                self.assertEqual(rows, {})

    def test_score_member_missing_duplicate_and_limit(self):
        raw, upstream = pack_scores(score_fixture())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.zip"
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "score_member_size_invalid"):
                handoff.read_score_handoff(path, upstream, CONTRACT["repository"], 2)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "a") as z:
                    z.writestr(upstream["source_bundle"]["path"], "{}")
            with self.assertRaisesRegex(ValueError, "score_member_missing_or_duplicate"):
                handoff.read_score_handoff(path, upstream, CONTRACT["repository"], 999999)

    def test_collection_connects_scores_and_retains_prices_when_score_graph_breaks(self):
        class Fake:
            def __init__(self, broken):
                self.spec = CONTRACT["sources"]["operating"]
                self.run = sample_run()
                self.run["path"] = ".github/workflows/" + self.spec["workflow"]
                raw, upstream = pack_scores(score_fixture())
                if broken:
                    upstream["source_bundle"]["sha256"] = "f" * 64
                archive = io.BytesIO(raw)
                with zipfile.ZipFile(archive, "a") as z:
                    z.writestr(self.spec["members"]["upstream"].format(run_id=2, run_attempt=1), json.dumps(upstream))
                    z.writestr(self.spec["members"]["market"], "{}")
                    z.writestr(self.spec["members"]["prices"], "ticker,previous_close,latest_price_date,currency\nETN,300,2026-09-04,USD\n")
                self.raw = archive.getvalue()
                self.digest = "sha256:" + hashlib.sha256(self.raw).hexdigest()

            def json(self, path):
                if "/workflows/" in path:
                    return {"workflow_runs": [self.run]}
                return {"artifacts": [{"id": 3, "name": self.spec["artifact_prefix"] + "2",
                        "digest": self.digest, "size_in_bytes": len(self.raw),
                        "workflow_run": {"id": 2, "head_sha": "a" * 40}}]}

            def archive(self, artifact_id, destination, limit):
                destination.write_bytes(self.raw)
                return self.digest

        for broken in (False, True):
            with self.subTest(broken=broken):
                source = evidence()
                source["operating"] = monitor.collect_source(Fake(broken), "operating", CONTRACT["sources"]["operating"], CONTRACT)
                report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
                self.assertEqual(report["current_engine_scores_ready"], not broken)
                etn = next(r for r in report["watchlist"] if r["ticker"] == "ETN")
                self.assertEqual(etn["close"], 300)
                if broken:
                    self.assertIsNone(etn["current_engine_score"])
                    self.assertEqual(etn["current_engine_status"], "SCORE_MEMBER_HASH_MISMATCH")

    def test_html_escapes_evidence_and_distinguishes_missing_from_zero(self):
        sources = evidence()
        sources["operating"] = score_source()
        report = monitor.evaluate(sources, "2026-09-04", NOW, CONTRACT)
        report["alerts"].append('<img src=x onerror="alert(1)">')
        result = monitor.render_html(report)
        self.assertIn("0.000000", result)
        self.assertIn('class="num">—', result)
        self.assertNotIn("<img", result)
        self.assertIn("&lt;img", result)
        self.assertIn("Content-Security-Policy", result)
        self.assertIn('id="query"', result)
        self.assertIn("연결 대기", result)
        self.assertNotIn("fetch(", result)

    def test_rendered_html_exposes_all_market_and_coverage_options(self):
        class SelectOptions(HTMLParser):
            def __init__(self):
                super().__init__()
                self.current = None
                self.options = {}

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == "select":
                    self.current = attributes["id"]
                    self.options[self.current] = []
                elif tag == "option" and self.current is not None:
                    self.options[self.current].append(attributes.get("value"))

            def handle_endtag(self, tag):
                if tag == "select":
                    self.current = None

        parsed = SelectOptions()
        parsed.feed(monitor.render_html(monitor.evaluate(evidence(), "2026-09-04", NOW, CONTRACT)))
        self.assertEqual(parsed.options["market"], ["", "US", "KR"])
        self.assertEqual(parsed.options["coverage"], ["", "ready", "missing"])

    def test_latest_failure_is_not_hidden_by_prior_success(self):
        runs = [sample_run(1), sample_run(2, "failure")]
        self.assertEqual(monitor.latest_run(runs, "after_close_daily.yml", CONTRACT["repository"], TACTICAL_EVENTS)["id"], 2)
        foreign = sample_run(3)
        foreign["head_repository"]["full_name"] = "foreign/repo"
        self.assertEqual(monitor.latest_run(runs + [foreign], "after_close_daily.yml", CONTRACT["repository"], TACTICAL_EVENTS)["id"], 2)
        runs[-1]["status"] = "in_progress"
        self.assertEqual(monitor.latest_run(runs, "after_close_daily.yml", CONTRACT["repository"], TACTICAL_EVENTS)["id"], 2)

    def test_ownership_uses_the_newer_sec_triggered_run(self):
        spec = CONTRACT["sources"]["ownership"]
        runs = [sample_run(1), sample_run(2, "failure")]
        for run in runs:
            run["path"] = ".github/workflows/" + spec["workflow"]
        runs[-1]["event"] = "workflow_run"
        selected = monitor.latest_run(runs, spec["workflow"], CONTRACT["repository"], spec["allowed_events"])
        self.assertEqual(selected["id"], 2)
        self.assertEqual(selected["conclusion"], "failure")

    def test_missing_required_members_block_but_keep_failure_diagnostics(self):
        class Fake:
            def __init__(self, key, conclusion):
                self.spec = CONTRACT["sources"][key]
                self.run = sample_run(conclusion=conclusion)
                self.run["path"] = ".github/workflows/" + self.spec["workflow"]
                archive = io.BytesIO()
                label = "recovery" if key == "operating" else "summary"
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr(self.spec["members"][label], json.dumps({"status": "BLOCKED_TEST"}))
                self.raw = archive.getvalue()
                self.digest = "sha256:" + hashlib.sha256(self.raw).hexdigest()

            def json(self, path):
                if "/workflows/" in path:
                    return {"workflow_runs": [self.run]}
                return {"artifacts": [{"id": 3, "name": self.spec["artifact_prefix"] + "2",
                                      "size_in_bytes": len(self.raw), "digest": self.digest,
                                      "workflow_run": {"id": 2, "head_sha": "a" * 40}}]}

            def archive(self, artifact_id, destination, limit):
                destination.write_bytes(self.raw)
                return self.digest
        ownership = monitor.collect_source(Fake("ownership", "success"), "ownership", CONTRACT["sources"]["ownership"], CONTRACT)
        self.assertEqual(ownership["status"], "MISSING_CONTRACT_MEMBERS")
        self.assertEqual(ownership["missing_members"], ["ranked"])
        operating = monitor.collect_source(Fake("operating", "failure"), "operating", CONTRACT["sources"]["operating"], CONTRACT)
        self.assertEqual(operating["status"], "UPSTREAM_FAILED")
        self.assertEqual(operating["data"]["recovery"]["status"], "BLOCKED_TEST")
        self.assertEqual(operating["missing_members"], ["market", "prices", "upstream"])
        sources = evidence()
        sources.update(ownership=ownership, operating=operating)
        report = monitor.evaluate(sources, "2026-09-04", NOW, CONTRACT)
        self.assertIn("ownership:MISSING_CONTRACT_MEMBER:ranked", report["alerts"])
        self.assertIn("operating:BLOCKED_TEST", report["alerts"])

    def test_dates_prices_and_estimate_coverage_are_separate(self):
        report = monitor.evaluate(evidence(), "2026-09-04", NOW, CONTRACT)
        self.assertIn("tactical:latest_scored_rebalance_date:STALE", report["alerts"])
        self.assertNotIn("tactical:data_as_of:STALE", report["alerts"])
        self.assertIn("estimates:PARTIAL_OR_UNKNOWN_FORWARD_ESTIMATE_COVERAGE", report["alerts"])
        self.assertFalse(report["current_investment_ranking_ready"])
        etn = next(row for row in report["watchlist"] if row["ticker"] == "ETN")
        self.assertEqual(etn["close"], 300)
        self.assertEqual(etn["ownership_score"], 0.7)
        self.assertIsNone(etn["current_engine_score"])

    def test_future_and_duplicate_prices_are_not_current(self):
        source = evidence()
        source["operating"]["data"]["prices"][0]["latest_price_date"] = "2026-09-08"
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        etn = next(r for r in report["watchlist"] if r["ticker"] == "ETN")
        self.assertIsNone(etn["close"])
        source["operating"]["data"]["prices"].append(copy.deepcopy(source["operating"]["data"]["prices"][0]))
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        self.assertIn("operating:DUPLICATE_PRICE_TICKERS", report["alerts"])

    def test_disclosure_period_is_not_current_flow_or_zero_imputed(self):
        report = monitor.evaluate(evidence(), "2026-09-04", NOW, CONTRACT)
        self.assertEqual(report["observations"]["ownership"]["required_due_period_end"], "2026-06-30")
        self.assertTrue(all(r["ownership_score"] is None for r in report["watchlist"] if r["market"] == "KR"))
        self.assertIn("000660", [r["ticker"] for r in report["watchlist"]])
        source = evidence()
        source["ownership"]["data"]["ranked"][0]["latest_available_from"] = "2026-09-06T00:00:00Z"
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        self.assertTrue(all(r["ownership_score"] is None for r in report["watchlist"]))

    def test_invalid_date_numeric_and_missing_inputs(self):
        self.assertEqual(monitor.date_state("2026-02-30", "2026-09-04"), "MISSING_OR_INVALID_DATE")
        self.assertFalse(monitor.collection_current("2026-09-04Tgarbage", "2026-09-04", NOW))
        self.assertIsNone(monitor.number("nan"))
        self.assertIsNone(monitor.number("inf"))
        report = monitor.evaluate({}, "2026-09-04", NOW, CONTRACT)
        self.assertEqual(report["status"], "ATTENTION_REQUIRED")
        self.assertIn("operating:MISSING_SOURCE", report["alerts"])

    def test_zip_exact_members_hashes_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.zip"
            raw = b'{"date":"2026-09-04"}'
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("outputs/summary.json", raw)
                z.writestr("../../ignored.py", b"raise RuntimeError()")
            data, hashes = monitor.read_members(path, {"summary": "outputs/summary.json"}, 1000)
            self.assertEqual(data["summary"]["date"], "2026-09-04")
            self.assertEqual(hashes["summary"]["sha256"], hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError, "artifact_member_size"):
                monitor.read_members(path, {"summary": "outputs/summary.json"}, 2)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(path, "a") as z:
                    z.writestr("outputs/summary.json", raw)
            with self.assertRaisesRegex(ValueError, "duplicate_artifact_member"):
                monitor.read_members(path, {"summary": "outputs/summary.json"}, 1000)

    def test_artifact_digest_and_run_identity_fail_closed(self):
        class Fake:
            def json(self, path):
                if "/workflows/" in path:
                    return {"workflow_runs": [sample_run()]}
                return {"artifacts": [{"id": 3, "name": "after-close-daily-2",
                                      "size_in_bytes": 1, "digest": "sha256:" + "a" * 64,
                                      "workflow_run": {"id": 2, "head_sha": "a" * 40}}]}

            def archive(self, artifact_id, destination, limit):
                return "sha256:" + "b" * 64
        result = monitor.collect_source(Fake(), "tactical", CONTRACT["sources"]["tactical"], CONTRACT)
        self.assertEqual(result["reason"], "artifact_digest_mismatch")
        self.assertEqual(result["data"], {})

    def test_weekend_holiday_and_early_close(self):
        self.assertEqual(monitor.completed_session(NOW), "2026-09-04")
        self.assertEqual(monitor.completed_session(monitor.timestamp("2026-09-07T22:00:00Z")), "2026-09-04")
        self.assertEqual(monitor.completed_session(monitor.timestamp("2026-11-27T19:31:00Z")), "2026-11-27")
        self.assertEqual(monitor.completed_session(monitor.timestamp("2026-11-27T19:00:00Z")), "2026-11-25")

    def test_report_does_not_mutate_sources_or_pretend_to_rank(self):
        source = evidence()
        original = copy.deepcopy(source)
        report = monitor.evaluate(source, "2026-09-04", NOW, CONTRACT)
        self.assertEqual(source, original)
        self.assertNotIn('"data"', json.dumps(report["sources"]))
        self.assertIn("**withheld**", monitor.render(report))
        self.assertTrue(report["safety"]["research_only"])
        self.assertTrue(all(v is False for k, v in report["safety"].items() if k != "research_only"))



class ForwardContextTests(unittest.TestCase):
    session = "2026-09-04"

    class Feed:
        """Serve only the pinned GitHub routes and known ZIP members."""
        def __init__(self, key, payloads=None, *, conclusion="success", attempt=1):
            self.spec = CONTRACT["forward_context_sources"][key]
            self.run = sample_run(conclusion=conclusion)
            self.run.update(
                path=".github/workflows/" + self.spec["workflow"], run_attempt=attempt,
                created_at="2026-09-05T01:00:00Z", updated_at="2026-09-05T01:04:00Z",
                head_repository={"full_name": CONTRACT["repository"], "id": 100})
            self.calls = []
            self.jobs = []
            self.artifact = None
            self.artifact_count = 1
            if payloads is not None:
                data = io.BytesIO()
                with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for label, payload in payloads.items():
                        archive.writestr(self.spec["members"][label], json.dumps(payload))
                self.raw = data.getvalue()
                self.actual_digest = "sha256:" + hashlib.sha256(self.raw).hexdigest()
                self.artifact = dict(id=3, name=self.spec["artifact_prefix"] + "2",
                    digest=self.actual_digest, expired=False, size_in_bytes=len(self.raw),
                    created_at="2026-09-05T01:03:00Z",
                    workflow_run=dict(id=2, head_sha="a" * 40, head_branch="master",
                                      repository_id=100, head_repository_id=100))

        def set_jobs(self, proxy="success", managed="success"):
            self.jobs = [dict(id=index, name=self.spec["job_names"][label],
                         run_id=self.run["id"], run_attempt=self.run["run_attempt"],
                         head_sha=self.run["head_sha"], status="completed", conclusion=conclusion)
                         for index, (label, conclusion) in enumerate(
                             (("proxy_validation", proxy), ("managed_refresh", managed)), start=10)]

        def json(self, path):
            self.calls.append(path)
            if path == f"/actions/workflows/{self.spec['workflow']}/runs?branch=master&per_page=30":
                return {"workflow_runs": [self.run]}
            if path == f"/actions/runs/2/attempts/{self.run['run_attempt']}/jobs?per_page=100":
                return {"total_count": len(self.jobs), "jobs": self.jobs}
            if path == "/actions/runs/2/artifacts?per_page=100" and self.artifact is not None:
                return {"total_count": self.artifact_count, "artifacts": [self.artifact]}
            raise AssertionError("unexpected GitHub route")

        def archive(self, artifact_id, destination, limit):
            self.calls.append(("archive", artifact_id, limit))
            if self.artifact is None or artifact_id != 3 or len(self.raw) > limit:
                raise AssertionError("unexpected artifact download")
            destination.write_bytes(self.raw)
            return self.actual_digest

    def collect(self, key, feed):
        return monitor.collect_source(feed, key, feed.spec, CONTRACT, now=NOW, session=self.session)

    def managed_payload(self, *, date=None, blocked=False):
        auth = dict(source_admission=False, pit_verified=False, economic_authority=False)
        result = dict(status="REFRESH_CHECKPOINT_VERIFIED", session=date or self.session,
                      checkpoint_sha256="c" * 64, **auth)
        meter = dict(schema="a1-sip-campaign-meter-v1", run_id=2, run_attempt=1, source_sha="a" * 40,
                     managed_checkpoint_sha256="c" * 64, finalized=True, status="COMPLETE", **auth)
        if blocked:
            result = dict(status="BLOCKED", reason="MANAGED_BOOTSTRAP_INCOMPLETE_GRID", **auth)
            meter.update(status="BLOCKED", managed_checkpoint_sha256=None)
        return dict(result=result, meter=meter)

    def crisis_payload(self, *, date=None, generated="2026-09-05T01:02:00Z"):
        session = date or self.session
        return dict(summary=dict(schema_version="daily-crisis-monitor-v2",
            expected_session=session, generated_at_utc=generated, research_only=True,
            auto_trade_allowed=False, market_analysis=dict(schema="market-analysis-report-v1",
                status="DATA_BLOCKED", market="US", session=session, cutoff="2026-09-05T01:02:00Z",
                blockers=["MARKET_INPUT_UNAVAILABLE_INVALID_OR_EXPIRED", "untrusted URL"],
                market_assessment=dict(risk_score=999))))

    def test_context_survives_ledger_failure_without_changing_queue_or_authority(self):
        original = evidence()
        original["operating"] = {"status": "UPSTREAM_FAILED",
                                 "data": {"recovery": {"status": "BLOCKED_ACCEPTED_LEDGER"}}}
        baseline = monitor.evaluate(original, self.session, NOW, CONTRACT)
        a1 = self.Feed("a1_forward", self.managed_payload())
        a1.set_jobs()
        a4 = self.Feed("a4_forward", self.crisis_payload(), conclusion="failure")
        form4 = self.Feed("sec_form4")
        sources = dict(original, a1_forward=self.collect("a1_forward", a1),
                       a4_forward=self.collect("a4_forward", a4), sec_form4=self.collect("sec_form4", form4))
        before = copy.deepcopy(sources)
        report = monitor.evaluate(sources, self.session, NOW, CONTRACT)
        self.assertEqual(sources, before)
        self.assertEqual(len(form4.calls), 1)
        for key in ("status", "alerts", "watchlist", "safety", "current_portfolio_ready",
                    "current_investment_ranking_ready", "current_engine_scores_ready"):
            self.assertEqual(report[key], baseline[key])
        self.assertEqual(report["observations"]["ownership"], baseline["observations"]["ownership"])
        view = report["observations"]["forward_source_context"]
        self.assertEqual(view["a1"]["managed_generation"]["status"], "MANAGED_CHECKPOINT_REPORTED_FOR_SESSION")
        self.assertIsNone(view["a1"]["proxy_validation"]["session"])
        self.assertEqual(view["a4"]["status"], "DATA_BLOCKED")
        self.assertEqual(view["a4"]["report_session"], self.session)
        self.assertEqual(view["a4"]["reason_codes"], ["MARKET_INPUT_UNAVAILABLE_INVALID_OR_EXPIRED"])
        for key in ("risk_score", "source_session", "source_receipts"):
            self.assertIsNone(view["a4"][key])
        self.assertEqual(view["sec_form4"]["run_conclusion"], "success")
        self.assertIsNone(view["sec_form4"]["filing_available_at"])
        self.assertEqual(view["sec_13f"]["observation_key"], "ownership")
        self.assertIn("forward_source_context", monitor.render(report))
        self.assertIn("forward_source_context", monitor.render_html(report))

    def test_proxy_success_and_managed_failure_are_distinct(self):
        a1 = self.Feed("a1_forward", self.managed_payload(blocked=True), conclusion="failure")
        a1.set_jobs(managed="failure")
        source = self.collect("a1_forward", a1)
        view = monitor.forward_a1_context(source, self.session)
        self.assertEqual(view["proxy_validation"]["job"]["conclusion"], "success")
        self.assertEqual(view["managed_generation"]["job"]["conclusion"], "failure")
        self.assertEqual(view["managed_generation"]["status"], "MANAGED_REFRESH_BLOCKED")
        self.assertEqual(view["managed_generation"]["reason"], "MANAGED_BOOTSTRAP_INCOMPLETE_GRID")
        self.assertIsNone(view["managed_generation"]["session"])
        self.assertIsNone(view["managed_generation"]["checkpoint_sha256"])

    def test_unbound_managed_checkpoints_and_dates_are_refused(self):
        for date, expected in (("2026-09-03", "STALE"), ("2026-09-05", "FUTURE_DATE")):
            with self.subTest(date=date):
                feed = self.Feed("a1_forward", self.managed_payload(date=date))
                feed.set_jobs()
                view = monitor.forward_a1_context(self.collect("a1_forward", feed), self.session)
                self.assertEqual(view["managed_generation"]["status"], expected)
                self.assertIsNone(view["managed_generation"]["checkpoint_sha256"])
        for field, value in (("managed_checkpoint_sha256", "d" * 64),
                             ("run_attempt", True), ("pit_verified", True)):
            with self.subTest(field=field):
                payload = self.managed_payload()
                payload["meter"][field] = value
                feed = self.Feed("a1_forward", payload)
                feed.set_jobs()
                view = monitor.forward_a1_context(self.collect("a1_forward", feed), self.session)
                self.assertEqual(view["managed_generation"]["status"], "MANAGED_EVIDENCE_UNVERIFIED")

    def test_a4_failure_needs_exact_artifact_identity_member_session_and_clock(self):
        for variation, expected in (
            ("digest", "BLOCKED_SOURCE"), ("head", "BLOCKED_SOURCE"), ("repository", "BLOCKED_SOURCE"),
            ("attempt", "UNVERIFIED_RUN_ATTEMPT"), ("session", "A4_SESSION_MISMATCH"),
            ("future_report", "A4_REPORT_CLOCK_UNVERIFIED"), ("member", "A4_REPORT_UNVERIFIED"),
            ("oversize", "BLOCKED_SOURCE"), ("partial_list", "BLOCKED_SOURCE"),
            ("cancelled", "A4_REPORT_UNVERIFIED"),
        ):
            with self.subTest(variation=variation):
                payload = self.crisis_payload(date="2026-09-03" if variation == "session" else None,
                    generated="2026-09-06T01:02:00Z" if variation == "future_report" else "2026-09-05T01:02:00Z")
                feed = self.Feed("a4_forward", {} if variation == "member" else payload,
                    conclusion="cancelled" if variation == "cancelled" else "failure",
                    attempt=2 if variation == "attempt" else 1)
                if variation == "digest":
                    feed.artifact["digest"] = "sha256:" + "d" * 64
                if variation == "head":
                    feed.artifact["workflow_run"]["head_sha"] = "e" * 40
                if variation == "repository":
                    feed.artifact["workflow_run"]["head_repository_id"] = 101
                if variation == "oversize":
                    feed.artifact["size_in_bytes"] = feed.spec["max_artifact_bytes"] + 1
                if variation == "partial_list":
                    feed.artifact_count = 2
                result = monitor.forward_a4_context(self.collect("a4_forward", feed), self.session, NOW)
                self.assertEqual(result["status"], expected)
                self.assertIsNone(result["report_session"])
                self.assertIsNone(result["risk_score"])
                if variation in {"attempt", "head", "repository", "oversize", "partial_list"}:
                    self.assertFalse(any(isinstance(call, tuple) for call in feed.calls))


    def test_malformed_forward_conclusion_preserves_legacy_report(self):
        feed = self.Feed("a4_forward", self.crisis_payload(), conclusion=[])
        blocked = self.collect("a4_forward", feed)
        self.assertEqual(blocked["reason"], "forward_run_conclusion_invalid")
        self.assertFalse(any(isinstance(call, tuple) for call in feed.calls))
        # A malformed conclusion must also be harmless in a supplied source snapshot.
        valid = self.collect("a4_forward", self.Feed("a4_forward", self.crisis_payload(), conclusion="failure"))
        valid["run"]["conclusion"] = []
        sources = evidence()
        baseline = monitor.evaluate(sources, self.session, NOW, CONTRACT)
        sources["a4_forward"] = valid
        report = monitor.evaluate(sources, self.session, NOW, CONTRACT)
        self.assertEqual(report["observations"]["forward_source_context"]["a4"]["status"],
                         "A4_REPORT_UNVERIFIED")
        self.assertEqual(report["watchlist"], baseline["watchlist"])
        self.assertEqual(report["alerts"], baseline["alerts"])
        self.assertEqual(report["safety"], baseline["safety"])


class RotationTests(unittest.TestCase):
    now = monitor.timestamp("2026-11-05T04:00:00Z")
    producer = {"run_id": 2, "run_attempt": 1, "head_sha": "a" * 40}

    def fixture(self):
        config, watch, _ = rotation.policy(CONTRACT)
        sessions, _ = rotation.session_window(self.now)
        history = {ticker: [(day, 100 + i) for i, day in enumerate(sessions)]
                   for ticker in (*rotation.universe(config), *watch)}
        for ticker, jump in (("NVDA", 1.10), ("XLE", 1.05), ("SMH", 1.06)):
            history[ticker][-1] = sessions[-1], history[ticker][-1][1] * jump
        return history

    def analyze(self, history, now=None):
        return rotation.analyze(history, CONTRACT, now=now or self.now, price_basis="SYNTHETIC_ADJUSTED_CLOSE")

    def test_all_42_comparable_and_one_request_per_stock_session(self):
        history = self.fixture()
        result = self.analyze(history)
        rows = result["rows"]
        self.assertEqual((result["status"], result["counts"]["etfs_compared"]), ("CURRENT", 42))
        self.assertEqual((rows["XLE"]["rank5"]["current"], rows["SMH"]["rank5"]["current"]), (1, 1))
        self.assertEqual(rows["NVDA"]["relative_strength"], {"1": 0.1, "5": 0.1, "20": 0.1})
        self.assertEqual(rows["NVDA"]["peer_relative_strength"]["current"]["5"], 0.0377358491)
        self.assertIsNone(rows["QQQ"]["rank5"])
        requests = {row["subject"]["ticker"]: row for row in result["a3_review_requests"]}
        self.assertEqual(len(requests), len(result["a3_review_requests"]))
        self.assertEqual({trigger["scope"] for trigger in requests["NVDA"]["triggers"]},
                         {"STOCK_VS_SPY", "STOCK_VS_REFERENCE", "REFERENCE_ETF_ROTATION"})
        self.assertTrue(all(request["agent"] == "A3" and request["execute"] is False
                            for request in requests.values()))
        replay = self.analyze(history, monitor.timestamp("2026-11-05T08:00:00Z"))
        self.assertEqual(result["a3_review_requests"], replay["a3_review_requests"])

    def test_partial_peer_or_stale_etf_never_looks_like_a_rank_change(self):
        history = self.fixture()
        history["SMH"].pop()
        history["XLE"].pop(6)
        history["QQQ"].append(history["QQQ"][-1])
        result = self.analyze(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["rows"]["SMH"]["gap"], "EXACT_SESSION_MISSING")
        self.assertEqual(result["rows"]["XLE"]["gap"], "WINDOW_GAP")
        self.assertEqual(result["rows"]["QQQ"]["gap"], "DUPLICATE_SESSION")
        self.assertIsNone(result["rows"]["IGV"]["rank5"])
        self.assertIsNone(result["rows"]["NVDA"]["peer_relative_strength"])
        self.assertEqual([row["subject"]["ticker"] for row in result["a3_review_requests"]], ["NVDA"])
        del history["SPY"]
        blocked = self.analyze(history)
        self.assertEqual(blocked["status"], "DATA_BLOCKED")
        self.assertEqual(blocked["counts"]["etfs_compared"], 0)
        self.assertEqual(blocked["a3_review_requests"], [])

    def test_exact_session_and_future_prices_do_not_change_the_result(self):
        history = self.fixture()
        baseline = self.analyze(history)
        for rows in history.values():
            rows.append(("2026-11-05", 999999.0))
        self.assertEqual(self.analyze(history), baseline)
        self.assertEqual(rotation.session_window(monitor.timestamp("2026-11-27T19:29:59Z"))[0][-1],
                         "2026-11-25")
        self.assertEqual(rotation.session_window(monitor.timestamp("2026-11-27T19:30:00Z"))[0][-1],
                         "2026-11-27")

    def test_scheduled_stage_reuses_legacy_frame_and_requires_adjusted_batch(self):
        import pandas as pd
        history = self.fixture()
        stage = rotation.ScheduledRotation(CONTRACT, self.now)
        calls = []

        def frame(symbol, column):
            return pd.DataFrame({column: [value for _, value in history[symbol]]},
                                index=pd.DatetimeIndex([day for day, _ in history[symbol]]))

        fresh = frame("SMH", "Close")
        stale = frame("XLK", "Close").iloc[:-1]

        def fetch(ticker):
            calls.append(ticker)
            return {"SMH": fresh, "XLK": stale}[ticker]

        self.assertIs(stage.legacy_history(fetch, "SMH"), fresh)
        self.assertIs(stage.legacy_history(fetch, "XLK"), stale)
        self.assertEqual(calls, ["SMH", "XLK"])
        requested = []

        def download(tickers, start, end):
            self.assertLessEqual(len(tickers), 20)
            self.assertEqual((start, end), (history["SPY"][0][0], "2026-11-05"))
            requested.extend(tickers)
            return {t: frame(t, "Close" if t == "QQQ" else "Adj Close") for t in tickers}, {}

        result = stage.finish(download)
        self.assertEqual(len(requested), 66)
        self.assertEqual(requested.count("QQQ"), 2)
        self.assertTrue(all(requested.count(t) == 1 for t in set(requested) - {"QQQ"}))
        self.assertNotIn("SMH", requested)
        self.assertIn("XLK", requested)
        self.assertEqual(result["rows"]["QQQ"]["gap"], "EXACT_SESSION_MISSING")
        self.assertEqual(result["counts"]["etfs_compared"], 41)

    def test_scheduled_stage_retries_only_incomplete_windows_once(self):
        import pandas as pd
        from collections import Counter

        history = self.fixture()
        failed = set(sorted(history)[:12])
        stage = rotation.ScheduledRotation(CONTRACT, self.now)
        counts = Counter()
        batches = []

        def download(tickers, start, end):
            batches.append(list(tickers))
            self.assertEqual((start, end), (stage.sessions[0], "2026-11-05"))
            output = {}
            for ticker in tickers:
                values = [value for _, value in history[ticker]]
                if ticker in failed and counts[ticker] == 0:
                    values[5] = float("nan")
                counts[ticker] += 1
                output[ticker] = pd.DataFrame(
                    {"Adj Close": values},
                    index=pd.DatetimeIndex([day for day, _ in history[ticker]]),
                )
            return output, {}

        result = stage.finish(download)
        self.assertEqual(result["status"], "CURRENT")
        self.assertEqual(result["counts"]["etfs_compared"], 42)
        self.assertEqual(result["counts"]["stocks_compared"], 24)
        self.assertEqual({t for t, n in counts.items() if n == 2}, failed)
        self.assertTrue(all(n in {1, 2} for n in counts.values()))
        self.assertEqual(sum(map(len, batches)), len(history) + len(failed))
        self.assertEqual(set(t for batch in batches[4:] for t in batch), failed)
        self.assertTrue(all(len(batch) <= 5 for batch in batches[4:]))
        self.assertEqual(len(batches), 7)

    def test_private_binding_and_failed_parent_preserve_different_statuses(self):
        result = self.analyze(self.fixture())
        objects = {}

        class IsolatedTransport:
            def write(self, path, raw):
                objects[path] = raw
                if rotation.sha256(objects[path]) != path.rsplit("/", 1)[-1]:
                    raise ValueError("readback_failed")

        receipt = rotation.publish_private(result, self.producer, self.now, IsolatedTransport())
        run = sample_run(conclusion="failure")
        run["created_at"] = "2026-11-05T03:00:00Z"
        monitor_now = monitor.timestamp("2026-11-05T08:00:00Z")
        self.assertNotIn("NVDA", json.dumps(receipt))
        self.assertNotIn("relative_strength", json.dumps(receipt))
        spec = CONTRACT["sources"]["tactical"]

        class Feed:
            def __init__(self, rotation_raw):
                data = io.BytesIO()
                with zipfile.ZipFile(data, "w") as archive:
                    archive.writestr(spec["members"]["summary"], '{"data_as_of":"2026-11-04"}')
                    archive.writestr(spec["members"]["etf_rotation"], rotation_raw)
                self.raw = data.getvalue()
                self.artifact = {"id": 1, "name": spec["artifact_prefix"] + "2",
                                 "digest": "sha256:" + rotation.sha256(self.raw),
                                 "workflow_run": {"id": 2, "head_sha": "a" * 40},
                                 "size_in_bytes": len(self.raw), "expired": False,
                                 "created_at": "2026-11-05T04:15:00Z"}

            def json(self, path):
                return {"workflow_runs": [run]} if "/workflows/" in path else {"artifacts": [self.artifact]}

            def archive(self, artifact_id, destination, limit):
                destination.write_bytes(self.raw)
                return self.artifact["digest"]

        def read(feed, session="2026-11-04"):
            return monitor.collect_source(feed, "tactical", spec, CONTRACT, now=monitor_now, session=session)

        source = read(Feed(rotation.canonical(receipt)))
        self.assertEqual(source["status"], "UPSTREAM_FAILED")
        self.assertTrue(source["artifact_hash_verified"])
        observation = source["data"]["etf_rotation"]
        self.assertEqual(observation["a3_handoff_status"], "REVIEW_REQUESTS_READY")
        combined = evidence()
        combined["tactical"] = source
        report = monitor.evaluate(combined, "2026-11-04", monitor_now, CONTRACT)
        stock = next(row for row in report["watchlist"] if row["ticker"] == "NVDA")
        self.assertEqual(stock["a3_rotation_batch_sha256"], observation["private_payload_sha256"])
        self.assertEqual(stock["a3_rotation_batch_status"], "REVIEW_REQUESTS_READY")
        self.assertFalse(report["current_portfolio_ready"])
        self.assertIn("tactical:UPSTREAM_FAILED", report["alerts"])
        raw = objects[rotation.PRIVATE_PREFIX + receipt["private_payload_sha256"]]
        self.assertEqual(rotation.decode_a3_review_requests(observation, raw, CONTRACT)[0]["agent"], "A3")
        with self.assertRaisesRegex(ValueError, "rotation_private_binding"):
            rotation.decode_a3_review_requests(observation, raw + b" ", CONTRACT)
        self.assertEqual(read(Feed(rotation.canonical(receipt)), "2026-11-05")["data"]["etf_rotation"]["status"],
                         "SESSION_MISMATCH")
        for raw in (b"{not-json", rotation.canonical({**receipt, "producer": {**self.producer, "run_attempt": 2}})):
            blocked = read(Feed(raw))
            self.assertEqual(blocked["data"]["etf_rotation"]["status"], "UNVERIFIED_RECEIPT")
            self.assertEqual(blocked["data"]["summary"]["data_as_of"], "2026-11-04")

        class UnavailableTransport:
            def write(self, path, raw):
                raise ValueError("unavailable")

        failed = rotation.publish_private(result, self.producer, self.now, UnavailableTransport())
        observed = read(Feed(rotation.canonical(failed)))["data"]["etf_rotation"]
        self.assertEqual(observed["a3_handoff_status"], "PRIVATE_HANDOFF_BLOCKED")
        self.assertIsNone(observed["private_payload_sha256"])



class ReviewHandoffTests(unittest.TestCase):
    session = "2026-09-04"

    def source(self, *, failed=False):
        return {"status": "UPSTREAM_FAILED" if failed else "VERIFIED_ARTIFACT",
            "artifact_hash_verified": True, "metadata_collected_at": NOW.isoformat(),
            "run": dict(id=21, run_attempt=1, head_sha="a" * 40, status="completed",
                conclusion="failure" if failed else "success", created_at="2026-09-05T06:00:00Z",
                updated_at="2026-09-05T07:00:00Z"),
            "artifact": {"created_at": "2026-09-05T06:40:00Z", "digest": "sha256:" + "b" * 64},
            "files": {"summary": {"sha256": "c" * 64, "bytes": 100}},
            "data": {"summary": {"schema_version": "daily-crisis-monitor-v2", "research_only": True,
                "auto_trade_allowed": False, "expected_session": self.session,
                "generated_at_utc": "2026-09-05T06:30:00Z",
                "market_analysis": {"schema": "market-analysis-report-v1", "market": "US",
                    "session": self.session, "cutoff": "2026-09-05T06:20:00Z",
                    "status": "DATA_BLOCKED" if failed else "READY_RESEARCH_ONLY", "blockers": ["REAL_INPUT_WAIT"],
                    "market_assessment": {"status": "DATA_BLOCKED" if failed else "READY_RESEARCH_ONLY",
                        "state": None if failed else "GREEN", "observed_state": None if failed else "GREEN",
                        "risk_score": None if failed else .2, "axes": [{"axis": "CREDIT", "risk_percentile": .2}],
                        "ready_axis_count": 10, "required_axes_ready": True}}}}}

    def handoff(self, sources=None, **kwargs):
        return monitor.reassessment_handoff(sources or {"a4_forward": self.source()},
            self.session, kwargs.pop("now", NOW), CONTRACT, code_sha="a" * 40, **kwargs)

    def test_real_bridge_preserves_common_risk_requires_without_paper_or_holdings(self):
        value = self.handoff({"a4_forward": self.source(), "operating": {"status": "UPSTREAM_FAILED"}})
        a5 = next(r for r in value["review_requests"] if r["agent"] == "A5")
        self.assertIn("PORTFOLIO_COMMON_RISK_REVIEW", a5["slices"])
        self.assertEqual(set(a5["requires"]), {"CURRENT_A4", "CURRENT_REVALIDATED_A3_ER", "INDEPENDENT_A6"})
        self.assertFalse(a5["execute"])
        self.assertFalse(value["global_scope_complete"])
        self.assertFalse(value["consumption_ack"])
        self.assertEqual(value["intake_export"]["status"], "BLOCKED_CANONICAL_INTAKE_MISSING")
        self.assertTrue(all(v is False for v in value["safety"].values()))

    def test_failed_crisis_is_repair_and_does_not_invent_a5_decision(self):
        value = self.handoff({"a4_forward": self.source(failed=True)})
        agents = {r["agent"] for r in value["review_requests"]}
        self.assertTrue({"A1", "A6"}.issubset(agents))
        self.assertNotIn("A5", agents)
        self.assertTrue(all(r["authority"] == "REVIEW_ONLY" for r in value["review_requests"]))

    def test_transport_recollection_keeps_event_and_intake_identity_without_ack(self):
        first = self.handoff()
        source = self.source()
        later = NOW + monitor.timedelta(minutes=5)
        source["metadata_collected_at"] = later.isoformat()
        source["files"]["summary"]["sha256"] = "d" * 64
        second = self.handoff({"a4_forward": source}, previous=first, now=later)
        self.assertEqual(first["review_intake_id"], second["review_intake_id"])
        self.assertEqual(second["new_event_ids"], [])
        self.assertEqual(second["parameter_proposals"], {})
        self.assertFalse(second["consumption_ack"])

    def test_same_ready_status_changed_actual_regime_or_axis_requests_new_review(self):
        first = self.handoff()
        for change in ({"state": "RED"}, {"axes": [{"axis": "CREDIT", "risk_percentile": .9}]}):
            source = self.source()
            source["metadata_collected_at"] = (NOW + monitor.timedelta(minutes=5)).isoformat()
            source["run"]["updated_at"] = "2026-09-05T07:01:00Z"
            source["data"]["summary"]["market_analysis"]["market_assessment"].update(change)
            result = self.handoff({"a4_forward": source}, previous=first, now=NOW + monitor.timedelta(minutes=5))
            self.assertTrue(result["new_event_ids"])
            self.assertIn("A5", result["parameter_proposals"])
            self.assertNotEqual(first["review_intake_id"], result["review_intake_id"])

    def test_status_only_a4_cannot_invent_a_risk_state(self):
        source = self.source()
        del source["data"]["summary"]["market_analysis"]["market_assessment"]
        result = self.handoff({"a4_forward": source})
        self.assertNotIn("A5", result["parameter_proposals"])

    def test_expired_a4_original_is_repair_not_renewed_observed_evidence(self):
        source = self.source()
        report = source["data"]["summary"]
        report["generated_at_utc"] = "2026-09-05T07:40:00Z"
        report["market_analysis"]["cutoff"] = "2026-09-05T07:30:00Z"
        source["artifact"]["created_at"] = "2026-09-05T07:50:00Z"
        source["run"]["updated_at"] = "2026-09-05T08:00:00Z"
        row = dict(family="MACRO", provider="SYNTHETIC", entity_kind="MACRO_SERIES", entity_id="DGS10",
            metric="level", fiscal_period=None, observation_period=self.session, identity={"unit": "percent"},
            values={"value": 1234567.89}, status="OBSERVED", available_at="2026-09-05T07:00:00Z",
            collected_at="2026-09-05T07:00:00Z", revision_id="v1", source_sha256="f" * 64, causal_event_id=None)
        child = monitor.reassessment.snapshot([row], scope_id="synthetic-a4-only",
            cutoff="2026-09-05T07:30:00Z", expires_at="2026-09-05T08:00:00Z")
        report["market_analysis"]["candidate_reassessment_snapshot"] = child
        value = self.handoff({"a4_forward": source})
        self.assertNotIn("A5", value["parameter_proposals"])
        self.assertIn("A6", value["parameter_proposals"])
        self.assertTrue(all(r["status"] != "OBSERVED" for r in value["current_snapshot"]["rows"]))
        report["market_analysis"]["candidate_reassessment_snapshot"] = monitor.reassessment.snapshot([row],
            scope_id="synthetic-a4-only", cutoff="2026-09-05T07:30:00Z", expires_at="2026-09-05T08:40:00Z")
        fresh = self.handoff({"a4_forward": source})
        self.assertEqual(fresh["current_snapshot"]["expires_at"], "2026-09-05T08:40:00+00:00")
        self.assertNotIn("1234567.89", json.dumps(fresh))

    def test_missing_and_future_original_clocks_block_only_that_scope(self):
        bad = self.source()
        bad["metadata_collected_at"] = (NOW + monitor.timedelta(days=1)).isoformat()
        value = self.handoff({"a4_forward": self.source(), "bad": bad})
        self.assertIn("A5", {r["agent"] for r in value["review_requests"]})
        self.assertIn({"scope": "bad", "reason": "ORIGINAL_SOURCE_IDENTITY_OR_CLOCK_MISSING"}, value["blocked_scopes"])

    def test_private_etf_hash_is_not_an_original_payload(self):
        value = self.handoff({"tactical": {"data": {"etf_rotation": {
            "a3_handoff_status": "REVIEW_REQUESTS_READY", "private_payload_sha256": "e" * 64}}}})
        self.assertFalse(any(r["agent"] == "A3" for r in value["review_requests"]))
        self.assertTrue(any(r["reason"] == "PRIVATE_ETF_PAYLOAD_OR_CHECKED_PUBLICATION_MISSING_NO_RECONSTRUCTION"
                            for r in value["blocked_scopes"]))

    def test_private_etf_original_decoder_preserves_independent_a3_metadata_only(self):
        fixture = RotationTests()
        result = fixture.analyze(fixture.fixture())
        raw = rotation.canonical({**result, "producer": fixture.producer,
                                  "observed_at_utc": fixture.now.isoformat()})
        public = rotation.public_receipt(result, fixture.producer, fixture.now, rotation.sha256(raw))
        run = sample_run(); run["created_at"] = fixture.now.isoformat()
        artifact = {"created_at": fixture.now.isoformat()}
        observation = rotation.receipt_observation(public, run, artifact, result["session"], fixture.now, CONTRACT)
        source = {"tactical": {"metadata_collected_at": fixture.now.isoformat(),
                               "data": {"etf_rotation": observation}}}
        value = monitor.reassessment_handoff(source, result["session"], fixture.now, CONTRACT,
            private_etf_payload=raw, code_sha="a" * 40)
        expected = rotation.decode_a3_review_requests(observation, raw, CONTRACT)
        actual = [r for r in value["review_requests"] if r["agent"] == "A3"]
        self.assertEqual({r["request_id"] for r in actual}, {r["request_id"] for r in expected})
        self.assertTrue(actual)
        self.assertNotIn("relative_strength", json.dumps(value))
        self.assertNotIn("normalized_price_input_sha256", json.dumps(value))
        self.assertTrue(all(r["execute"] is False for r in actual))
        for collected in (None, (fixture.now + monitor.timedelta(seconds=1)).isoformat()):
            broken = copy.deepcopy(source)
            if collected is None:
                del broken["tactical"]["metadata_collected_at"]
            else:
                broken["tactical"]["metadata_collected_at"] = collected
            refused = monitor.reassessment_handoff(broken, result["session"], fixture.now, CONTRACT,
                private_etf_payload=raw, code_sha="a" * 40)
            self.assertFalse(any(r["agent"] == "A3" for r in refused["review_requests"]))
            self.assertNotIn("etf_parameter_proposals", refused)
            self.assertTrue(any(r["scope"] == "etf" for r in refused["blocked_scopes"]))

    def test_new_snapshots_keep_no_private_price_holding_or_url_values(self):
        source = self.source()
        source["run"]["html_url"] = "https://private.invalid/?credential=PRIVATE_SENTINEL"
        source["data"]["summary"]["private_price"] = "PRIVATE_PRICE_SENTINEL"
        source["data"]["summary"]["Actual_holdings"] = ["PRIVATE_HOLDING_SENTINEL"]
        raw = json.dumps(self.handoff({"a4_forward": source}))
        for value in ("PRIVATE_SENTINEL", "PRIVATE_PRICE_SENTINEL", "PRIVATE_HOLDING_SENTINEL"):
            self.assertNotIn(value, raw)

    def test_scheduled_producer_member_to_default_consumer_preserves_a3_a5_cause(self):
        from tools import etf_leadership_snapshot as producer
        fixture = RotationTests()
        result = fixture.analyze(fixture.fixture())
        class Memory:
            def __init__(self):
                self.objects = {}; self.reads = 0
            def write(self, path, raw):
                self.objects[path] = raw
            def read(self, path):
                self.reads += 1
                return self.objects[path]
        remote = Memory()
        receipt = producer.publish_rotation_review(result, fixture.producer, fixture.now, CONTRACT, remote)
        self.assertEqual(remote.reads, 1)
        self.assertIn("safe_review_handoff", receipt)
        self.assertNotIn("relative_strength", json.dumps(receipt))
        spec = CONTRACT["sources"]["tactical"]
        run = sample_run(conclusion="failure")
        run.update(created_at="2026-11-05T03:00:00Z", updated_at="2026-11-05T04:20:00Z")
        observed = monitor.timestamp("2026-11-05T08:00:00Z")
        class Feed:
            def __init__(self, payload):
                content = io.BytesIO()
                with zipfile.ZipFile(content, "w") as archive:
                    archive.writestr(spec["members"]["summary"], '{"data_as_of":"2026-11-04"}')
                    archive.writestr(spec["members"]["etf_rotation"], rotation.canonical(payload))
                self.raw = content.getvalue()
                self.artifact = dict(id=1, name=spec["artifact_prefix"] + "2", expired=False,
                    digest="sha256:" + rotation.sha256(self.raw), size_in_bytes=len(self.raw),
                    created_at="2026-11-05T04:15:00Z", workflow_run={"id": 2, "head_sha": "a" * 40})
            def json(self, path):
                return {"workflow_runs": [run]} if "/workflows/" in path else {"artifacts": [self.artifact]}
            def archive(self, artifact_id, destination, limit):
                destination.write_bytes(self.raw)
                return self.artifact["digest"]
        tactical = monitor.collect_source(Feed(receipt), "tactical", spec, CONTRACT,
            now=observed, session=result["session"])
        self.assertEqual(monitor.published_etf_reviews(tactical, CONTRACT, observed)[0]["agent"], "A3")
        value = monitor.reassessment_handoff({"tactical": tactical}, result["session"], observed,
                                             CONTRACT, code_sha="a" * 40)
        a3 = [r for r in value["review_requests"] if r["agent"] == "A3"]
        a5 = next(r for r in value["review_requests"] if r["agent"] == "A5")
        self.assertTrue(a3)
        self.assertTrue(set(a3[0]["causal_event_ids"]).intersection(a5["event_ids"]))
        self.assertEqual(set(a5["requires"]), {"CURRENT_A4", "CURRENT_REVALIDATED_A3_ER", "INDEPENDENT_A6"})
        sources = evidence(); sources["tactical"] = tactical
        def collect(client, key, *args, **kwargs):
            return sources.get(key, {"status": "MISSING_RUN", "data": {}})
        with tempfile.TemporaryDirectory() as temp, patch.object(monitor, "GitHub"), \
             patch.object(monitor, "collect_source", side_effect=collect), \
             patch.object(monitor, "completed_session", return_value=result["session"]), \
             patch.object(monitor, "datetime", wraps=monitor.datetime) as clock, \
             patch.dict(monitor.os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_EVENT_NAME": "schedule"}), \
             patch.object(sys, "argv", ["monitor", "--output-dir", str(Path(temp) / "report")]):
            clock.now.return_value = observed
            self.assertEqual(monitor.main(), 0)
            exported = json.loads((Path(temp) / "report/candidate_reassessment.json").read_text())
            self.assertTrue(any(r["agent"] == "A3" for r in exported["review_requests"]))
            self.assertTrue(any(r["agent"] == "A5" for r in exported["review_requests"]))
            self.assertFalse(exported["consumption_ack"])
        for field in ("readback_sha256", "decoder_git_lf_sha256", "producer_git_lf_sha256"):
            broken = copy.deepcopy(tactical)
            capsule = broken["data"]["etf_safe_review"]
            capsule[field] = "f" * 64
            capsule["binding_sha256"] = rotation.sha256(rotation.canonical(
                {k: v for k, v in capsule.items() if k != "binding_sha256"}))
            with self.assertRaisesRegex(ValueError, "published_etf_provenance_refused"):
                monitor.published_etf_reviews(broken, CONTRACT, observed)
        class Corrupt(Memory):
            def read(self, path):
                return b"corrupt-original"
        refused = producer.publish_rotation_review(result, fixture.producer, fixture.now, CONTRACT, Corrupt())
        self.assertNotIn("safe_review_handoff", refused)
        self.assertEqual(refused["safe_review_error"], "PRIVATE_READBACK_OR_DECODER_REFUSED")

    def test_daily_current_does_not_assert_weekly_or_holdings_complete(self):
        source = {"artifact_hash_verified": True, "data": {"result": {"session": self.session,
            "cadence_binding_sha256": "f" * 64, "tier_progress": {
                "by_tier": {"DAILY": {"CURRENT": 42, "PENDING": 0, "HELD": 0},
                            "WEEKLY": {"CURRENT": 400, "PENDING": 1, "HELD": 2}},
                "weekly_due": False, "weekly_target_session": "2026-08-28",
                "outside_scope": ["PRIVATE_HOLDING_SENTINEL"], "holdings_completeness": "UNKNOWN",
                "stale_role_counts": {"STALE_PRIORITY_EVIDENCE": 1}}}}}
        value = monitor.cadence_observation(source, self.session)
        self.assertTrue(value["daily_current"])
        self.assertFalse(value["whole_universe_current"])
        self.assertFalse(value["source_admission"])
        self.assertEqual(value["holdings_completeness"], "UNKNOWN")
        self.assertNotIn("PRIVATE_HOLDING_SENTINEL", json.dumps(value))
        progress = source["data"]["result"]["tier_progress"]
        progress["outside_scope"] = []
        progress["by_tier"]["WEEKLY"] = {"CURRENT": 403, "PENDING": 0, "HELD": 0}
        self.assertFalse(monitor.cadence_observation(source, self.session)["whole_universe_current"])
        source["data"]["result"]["tier_progress"]["by_tier"]["DAILY"]["CURRENT"] = True
        self.assertEqual(monitor.cadence_observation(source, self.session)["status"], "CADENCE_UNVERIFIED")

    def test_workflow_completion_is_exact_metadata_and_no_rerun(self):
        run = dict(id=23, run_attempt=1, head_sha="a" * 40, head_branch="master", event="schedule",
            name="Daily Crisis Monitor", path=".github/workflows/daily_crisis_monitor.yml", status="completed",
            conclusion="failure", created_at="2026-09-05T06:00:00Z", updated_at="2026-09-05T07:00:00Z",
            repository={"full_name": CONTRACT["repository"]}, head_repository={"full_name": CONTRACT["repository"]})
        class Feed:
            def json(self, path):
                if path != "/actions/runs/23":
                    raise AssertionError("unexpected mutation or endpoint")
                return run
        event = {"workflow_run": copy.deepcopy(run)}
        value = monitor.completion_trigger(Feed(), CONTRACT, NOW, event)
        self.assertEqual(value["conclusion"], "failure")
        self.assertFalse(value["dispatch"])
        for field, altered in (("head_sha", "b" * 40), ("event", "pull_request"), ("run_attempt", 2)):
            bad = copy.deepcopy(event); bad["workflow_run"][field] = altered
            with self.assertRaisesRegex(ValueError, "untrusted_completion_trigger"):
                monitor.completion_trigger(Feed(), CONTRACT, NOW, bad)
        run["head_repository"]["full_name"] = "fork/untrusted"
        with self.assertRaisesRegex(ValueError, "untrusted_completion_trigger"):
            monitor.completion_trigger(Feed(), CONTRACT, NOW, event)

    def test_full_intake_is_consumable_and_preserves_original_roles_models_and_clocks(self):
        from tools import materialize_system_state as materializer
        board = materializer.board
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            requests = []
            for agent in ("A1", "A2", "A3", "A4", "A5", "A6"):
                inputs = {}
                for role in board.contracts()["agents"][agent]["inputs"]:
                    path = root / (agent + "_" + role + ".json")
                    path.write_text('{"synthetic_only":true}', encoding="utf-8")
                    inputs[role] = dict(path=path.name, sha256=board.file_hash(path), observed_at="2026-09-05T06:00:00Z",
                        available_at="2026-09-05T06:10:00Z", collected_at="2026-09-05T06:20:00Z",
                        expires_at="2026-09-05T09:00:00Z", status="VERIFIED")
                requests.append(dict(agent=agent, inputs=inputs, model={"name": "synthetic-only", "version": "v1"},
                    parameters={"portfolio_mode": "MODEL_PORTFOLIO"} if agent == "A5" else {"original": True}))
            intake = {"observed_at": NOW.isoformat(), "expires_at": (NOW + monitor.timedelta(minutes=30)).isoformat(),
                      "sources": {}, "requests": requests}
            mission = board.mission_targets()
            payloads = {"code": {"repository": CONTRACT["repository"], "default_branch": "master",
                "master_sha": "a" * 40, "observed_at": NOW.isoformat(), "g0_run": {}},
                "mission": {k: mission[k] for k in ("mission_contract_id", "mission_contract_sha256",
                                                   "official_metric_mode", "mission_contract_values")}}
            for role, payload in payloads.items():
                path = root / (role + "_observation.json")
                path.write_text(json.dumps(payload), encoding="utf-8")
                intake["sources"][role] = [dict(path=path.name, sha256=board.file_hash(path),
                    observed_at=NOW.isoformat(), available_at=NOW.isoformat(), collected_at=NOW.isoformat(),
                    expires_at=intake["expires_at"], status="VERIFIED", identity="synthetic-" + role)]
            original = copy.deepcopy(intake)
            merged, receipt = monitor.export_review_intake(intake, self.handoff(), root, NOW, "a" * 40)
            self.assertEqual(intake, original)
            for before, after in zip(original["requests"], merged["requests"]):
                for key in ("agent", "inputs", "model"):
                    self.assertEqual(before[key], after[key])
            self.assertFalse(receipt["execute"])
            self.assertFalse(receipt["consumption_ack"])
            state = materializer.materialize(merged, root, NOW, "a" * 40)
            tasks = board._plan_tasks(state, root, board.contracts(), NOW, "a" * 40, "b" * 64)
            self.assertTrue(all(t["status"] == "BLOCKED" for t in tasks if t["agent"] in {"A3", "A5"}))
            self.assertTrue(all(t["authority"]["execute"] is False for t in tasks))
            old = copy.deepcopy(intake); old["expires_at"] = (NOW - monitor.timedelta(seconds=1)).isoformat()
            with self.assertRaisesRegex(ValueError, "intake_stale_or_future"):
                monitor.export_review_intake(old, self.handoff(), root, NOW, "a" * 40)
            forged = self.handoff(); forged["parameter_proposals"]["A5"]["candidate_reassessment"]["scope"]["requires"] = []
            with self.assertRaisesRegex(ValueError, "intake_proposal_original_required"):
                monitor.export_review_intake(intake, forged, root, NOW, "a" * 40)
            injected = self.handoff(); injected["etf_parameter_proposals"] = {"A5": {"injected": "not-an-original"}}
            with self.assertRaisesRegex(ValueError, "intake_etf_original_required"):
                monitor.export_review_intake(intake, injected, root, NOW, "a" * 40)

    def test_default_main_exports_real_bridge_and_missing_intake_packet(self):
        sources = evidence(); sources["a4_forward"] = self.source(failed=True)
        def collect(client, key, *args, **kwargs):
            return sources.get(key, {"status": "MISSING_RUN", "data": {}})
        with tempfile.TemporaryDirectory() as temp, patch.object(monitor, "GitHub"), \
             patch.object(monitor, "collect_source", side_effect=collect), \
             patch.object(monitor, "completed_session", return_value=self.session), \
             patch.object(monitor, "datetime", wraps=monitor.datetime) as clock, \
             patch.dict(monitor.os.environ, {"GITHUB_SHA": "a" * 40, "GITHUB_EVENT_NAME": "schedule"}), \
             patch.object(sys, "argv", ["monitor", "--output-dir", str(Path(temp) / "report")]):
            clock.now.return_value = NOW
            self.assertEqual(monitor.main(), 0)
            root = Path(temp) / "report"
            value = json.loads((root / "candidate_reassessment.json").read_text())
            self.assertTrue(value["review_requests"])
            self.assertEqual(value["intake_export"]["status"], "BLOCKED_CANONICAL_INTAKE_MISSING")
            self.assertTrue((root / "a0_parameter_proposals.json").exists())
            self.assertTrue((root / "review_queue.csv").exists())


def main() -> int:
    # This existing CI path also exercises the optional strict Theme/ETF reader.
    # No frozen Tier-1 registry or gate definition is changed.
    import theme_etf_source_bridge_smoke
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(MonitorTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(ForwardContextTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(RotationTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(ReviewHandoffTests),
        unittest.defaultTestLoader.loadTestsFromModule(theme_etf_source_bridge_smoke),
    ])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
