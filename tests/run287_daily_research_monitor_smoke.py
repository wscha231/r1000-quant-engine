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
import warnings
import zipfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import run_run287_daily_research_monitor as monitor
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


def main() -> int:
    # This existing CI path also exercises the optional strict Theme/ETF reader.
    # No frozen Tier-1 registry or gate definition is changed.
    import theme_etf_source_bridge_smoke
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromTestCase(MonitorTests),
        unittest.defaultTestLoader.loadTestsFromTestCase(ForwardContextTests),
        unittest.defaultTestLoader.loadTestsFromModule(theme_etf_source_bridge_smoke),
    ])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
