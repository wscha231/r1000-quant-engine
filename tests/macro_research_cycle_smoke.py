#!/usr/bin/env python3
"""Checkpoint corruption/failure/retry and orchestration regressions; synthetic."""
from pathlib import Path
from contextlib import redirect_stdout
import configparser
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import macro_history_sources as source
from tools import macro_research_checkpoint as checkpoint
from tools import macro_research_cycle as cycle
from tools import configure_macro_research_drive as drive_config


def fixture(root):
    fetcher = lambda *a: ([b"DATE,UNRATE\n2020-01-01,3.5\n"], "2026-09-11T00:00:00Z")
    source.collect(root / "store", ["UNRATE"], "2020-01-01", "2020-01-31", fetcher=fetcher)
    raw = source.REGISTRY.read_bytes()
    source.exclusive(root / "store/registries" / (source.digest(raw) + ".json"), raw)
    source.exclusive(root / "reports/fixture.json", source.encoded(dict(data_kind="SYNTHETIC")))


class CheckpointTests(unittest.TestCase):
    def test_roundtrip_and_stale_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "first")
            transport = checkpoint.LocalTransport(root / "remote")
            result = checkpoint.publish(transport, root / "first", None, "one")
            self.assertFalse(result["remote_verified"])
            restored = checkpoint.restore_latest(transport, root / "clean")
            self.assertEqual(result["manifest_sha256"], restored["manifest_sha256"])
            self.assertEqual(result["commit"], restored["commit"])
            with self.assertRaisesRegex(ValueError, "stale_parent"):
                checkpoint.publish(transport, root / "first", None, "stale")
            with self.assertRaisesRegex(ValueError, "destination_exists"):
                checkpoint.restore_latest(transport, root / "clean")

    def test_corruption_and_partial_upload_never_advance_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "data")
            transport = checkpoint.LocalTransport(root / "remote")
            original = transport.download
            def corrupt(hashes, target):
                original(hashes, target)
                next(target.iterdir()).write_bytes(b"corrupt")
            with patch.object(transport, "download", corrupt):
                with self.assertRaisesRegex(ValueError, "checkpoint_hash"):
                    checkpoint.publish(transport, root / "data", None, "broken")
            self.assertIsNone(checkpoint.head(transport)[0])
            result = checkpoint.publish(transport, root / "data", None, "retry")
            # Damage a referenced remote raw object after an accepted roundtrip.
            next((root / "remote/objects").iterdir()).write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "checkpoint_hash"):
                checkpoint.restore_latest(transport, root / "restore")
            self.assertFalse((root / "restore").exists())
            self.assertEqual(checkpoint.head(transport)[0], result["commit"])

    def test_broken_chain_does_not_fall_back_to_old_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "data")
            transport = checkpoint.LocalTransport(root / "remote")
            first = checkpoint.publish(transport, root / "data", None, "first")
            broken = dict(schema="macro-checkpoint-commit-v1", parent="a"*64,
                          generation=2, manifest=first["manifest_sha256"], eligible_for_selector=False)
            raw = source.encoded(broken)
            transport.write("commits/" + source.digest(raw) + ".json", raw)
            with self.assertRaisesRegex(ValueError, "broken_chain"):
                checkpoint.restore_latest(transport, root / "restore")

    def test_path_secret_scope_and_symlink_rejection(self):
        for name in ("../secret", "/absolute", "store/../../ledger", "reports/token.txt"):
            with self.assertRaises(ValueError):
                checkpoint.data_path(name)
        for remote in ("gdrive:accounts", "other:research/macro_technical_evidence/v1/scheduled"):
            with self.assertRaisesRegex(ValueError, "research_remote_scope"):
                checkpoint.RcloneTransport(remote)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "data")
            (root / "data/reports/secret.json").symlink_to(root / "data/reports/fixture.json")
            with self.assertRaisesRegex(ValueError, "symlink"):
                checkpoint.prepare(root / "data", root / "stage")

    def test_commit_acknowledgement_failure_is_recovered_without_duplicate_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); fixture(root / "data")
            transport = checkpoint.LocalTransport(root / "remote")
            write = transport.write
            def uncertain(path, raw):
                write(path, raw)
                if path.startswith("commits/"):
                    raise ValueError("readback_rate_limit")
            with patch.object(transport, "write", uncertain):
                with self.assertRaisesRegex(ValueError, "readback_rate_limit"):
                    checkpoint.publish(transport, root / "data", None, "one")
            restored = checkpoint.restore_latest(transport, root / "clean")
            self.assertEqual(restored["generation"], 1)
            next_result = checkpoint.publish(transport, root / "data", restored["commit"], "two")
            self.assertEqual(next_result["parent"], restored["commit"])

    def test_read_rate_backoff_is_bounded_and_does_not_retry_quota_or_permission(self):
        transport = object.__new__(checkpoint.RcloneTransport)
        transport.root = "gdrive:research/macro_technical_evidence/v1/pr-413"
        limited = ValueError("research_transport_failed:cat:exit_1:RATE_LIMIT")
        with patch.object(transport, "call", side_effect=[limited, limited, b"payload"]) as call, patch.object(checkpoint.time, "sleep") as sleep:
            self.assertEqual(transport.read("commits/" + "a"*64 + ".json"), b"payload")
            self.assertEqual(call.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
        for reason in ["DOWNLOAD_QUOTA", "STORAGE_QUOTA", "PERMISSION", "AUTHENTICATION_INVALID_GRANT", "AUTHENTICATION_INVALID_CLIENT"]:
            with patch.object(transport, "call", side_effect=ValueError(":" + reason)) as call:
                with self.assertRaises(ValueError):
                    transport.read("commits/" + "a"*64 + ".json")
                self.assertEqual(call.call_count, 1)
        with patch.object(transport, "call", side_effect=limited) as call, patch.object(checkpoint.time, "sleep") as sleep:
            with self.assertRaisesRegex(ValueError, "RATE_LIMIT"):
                transport.read("commits/" + "a"*64 + ".json")
            self.assertEqual(call.call_count, 7)
            self.assertEqual(sleep.call_count, 6)
        missing = ValueError("research_transport_failed:cat:exit_3:NOT_FOUND")
        with patch.object(transport, "call", side_effect=[missing, b"same-file"]) as call, patch.object(checkpoint.time, "sleep"):
            self.assertEqual(transport.read("commits/" + "a"*64 + ".json"), b"same-file")
            self.assertEqual(call.call_args_list[0], call.call_args_list[1])
        with patch.object(transport, "call", side_effect=missing) as call, patch.object(checkpoint.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "NOT_FOUND"):
                transport.read("commits/" + "a"*64 + ".json")
            self.assertEqual(call.call_count, 7)

    def test_existing_research_folder_is_resolved_once_and_pinned_without_creation(self):
        remote = "gdrive:research/macro_technical_evidence/v1/pr-413"
        row = dict(Name="pr-413", IsDir=True, ID="verified-folder")
        with patch.object(checkpoint.RcloneTransport, "call", return_value=source.encoded([row])) as call:
            transport = checkpoint.RcloneTransport(remote)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args, ("lsjson", remote.rsplit("/", 1)[0], "--dirs-only"))
            self.assertEqual(transport.folder_id, "verified-folder")
            self.assertEqual(transport.path("objects/" + "a"*64), "gdrive:objects/" + "a"*64)
        with patch.object(checkpoint.RcloneTransport, "call", return_value=source.encoded([row, dict(row, ID="another-folder")])):
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                checkpoint.RcloneTransport(remote)

    def test_changed_retrieval_is_not_changed_economy(self):
        old = dict(series="UNRATE", observation_date="2020-01-01", vintage_date=None, value=3.5, retrieved_at="2020-02-01")
        self.assertFalse(cycle.source_changes({"UNRATE": [old]}, {"UNRATE": [dict(old, retrieved_at="2026-09-11")]})[0]["changed"])
        self.assertEqual(cycle.source_changes({"UNRATE": [old]}, {"UNRATE": [dict(old, value=3.6)]})[0]["revised"], 1)
        self.assertEqual(cycle.source_changes({"UNRATE": [old]}, {})[0]["removed"], 1)

    def test_poll_does_not_confirm_release_and_rechecks_late_data(self):
        calendar = dict(events=[dict(series="UNRATE", release_at="2026-09-11T04:00:00Z")])
        previous = dict(sources=[dict(series="UNRATE", status="COLLECTED", retrieved_at="2026-09-11T06:00:00Z", latest="2026-07-01")])
        job = next(j for j in cycle.job_plan("2026-09-11T07:00:00Z", previous, calendar)["jobs"] if j["series"] == "UNRATE")
        self.assertEqual(job["collection_action"], "REFRESH_FULL_HISTORY")
        self.assertFalse(job["release_confirmed"])

    def test_rolling_price_window_retains_old_history_but_not_missing_interior(self):
        with tempfile.TemporaryDirectory() as tmp:
            def row(day, value):
                return dict(observation_date=day, value=value, evidence="current_only")
            old = {"SP500": [row("2016-01-01", 100), row("2016-01-02", 110), row("2016-01-03", 120)]}
            new = {"SP500": [row("2016-01-02", 111), row("2016-01-04", 130)]}
            old_receipt = dict(sources=[dict(series="SP500", status="COLLECTED", raw_sha256=["a"*64])])
            fresh = dict(sources=[dict(series="SP500", status="COLLECTED", raw_sha256=["b"*64], earliest="2016-01-02", provider_window_start="2016-01-02")])
            receipt, merged = cycle.retain_expired_price_history(tmp, fresh, new, old_receipt, old)
            self.assertEqual([(r["observation_date"], r["value"]) for r in merged["SP500"]],
                [("2016-01-01", 100), ("2016-01-02", 111), ("2016-01-04", 130)])
            self.assertEqual(receipt["sources"][0]["retained_expired_provider_rows"], 1)

    def test_collected_price_boundary_excludes_new_leading_missing_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_raw=b'DATE,SP500\n2020-01-01,10\n2020-01-02,.\n2020-01-03,30\n2020-01-04,40\n'
            new_raw=b'DATE,SP500\n2020-01-03,.\n2020-01-04,41\n'
            fetcher=lambda *a: ([old_raw], '2026-09-12T00:00:00Z')
            _,old_path=source.collect(tmp,['SP500'],'2020-01-01','2026-09-12',fetcher=fetcher)
            old_receipt,old=source.load_bundle(tmp,old_path)
            fetcher=lambda *a: ([new_raw], '2026-09-12T00:00:00Z')
            _,new_path=source.collect(tmp,['SP500'],'2020-01-01','2026-09-12',fetcher=fetcher)
            fresh,new=source.load_bundle(tmp,new_path)
            self.assertEqual(fresh['sources'][0]['provider_window_start'],'2020-01-03')
            receipt,records=cycle.retain_expired_price_history(tmp,fresh,new,old_receipt,old)
            self.assertEqual([(r['observation_date'],r['value']) for r in records['SP500']],
                             [('2020-01-01',10),('2020-01-04',41)])
            item=receipt['sources'][0]
            self.assertEqual(item['missing_observation_dates'],['2020-01-02','2020-01-03'])
            self.assertEqual(item['missing_value_count'],2)
            self.assertTrue(item['retained_missing_dates_complete'])
            del fresh['sources'][0]['provider_window_start']
            with self.assertRaisesRegex(ValueError,'provider_window_start_required'):
                cycle.retain_expired_price_history(tmp,fresh,new,old_receipt,old)

    def test_transport_redacts_errors_and_environment_collisions(self):
        import subprocess
        transport = object.__new__(checkpoint.RcloneTransport)
        transport.binary = "rclone"
        with patch.dict(os.environ, {"MACRO_RCLONE_CONFIG": "/tmp/config", "RCLONE_VERSION": "1.75.0", "RCLONE_CONFIG_GDRIVE": "secret"}):
            def fail(args, **kwargs):
                self.assertNotIn("RCLONE_VERSION", kwargs["env"])
                self.assertNotIn("RCLONE_CONFIG_GDRIVE", kwargs["env"])
                return subprocess.CompletedProcess(args, 1, b"", b"private-secret")
            with patch.object(checkpoint.subprocess, "run", fail):
                with self.assertRaisesRegex(ValueError, "^research_transport_failed:command:exit_1:UNCLASSIFIED$"):
                    transport.call("version")
        message = checkpoint.transport_failure(b"secret-key: Error 403: insufficient permissions", "cat", 1)
        self.assertEqual(message, "research_transport_failed:cat:exit_1:PERMISSION")
        wrapped = checkpoint.transport_failure(b"couldn't find root: userRateLimitExceeded", "lsjson", 1)
        self.assertEqual(wrapped, "research_transport_failed:lsjson:exit_1:RATE_LIMIT")
        for reason in ("invalid_grant", "invalid_client", "unauthorized_client", "invalid_scope"):
            stderr = ('couldn\'t find root: {"error":"' + reason + '","error_description":"private-secret"}').encode()
            self.assertEqual(checkpoint.transport_failure(stderr, "lsjson", 1),
                "research_transport_failed:lsjson:exit_1:AUTHENTICATION_" + reason.upper())
        self.assertEqual(checkpoint.transport_failure(b"invalid_grant userRateLimitExceeded private-secret", "cat", 1),
            "research_transport_failed:cat:exit_1:RATE_LIMIT")

    def test_oauth_shape_accepts_expired_modern_legacy_and_service_account_configs(self):
        token = dict(access_token="fixture-access", refresh_token="fixture-refresh", expiry="2000-01-01T00:00:00Z")
        remote = dict(client_id="123-fixture.apps.googleusercontent.com", client_secret="fixture-client-secret", token=json.dumps(token))
        drive_config.validate_drive_config(remote)
        drive_config.validate_drive_config(dict(token=json.dumps(token)))  # rclone's built-in client
        legacy = dict(AccessToken="fixture-access", RefreshToken="fixture-refresh", Expiry="2000-01-01T00:00:00+00:00")
        drive_config.validate_drive_config(dict(token=json.dumps(legacy)))
        for key in ("service_account_file", "service_account_credentials"):
            drive_config.validate_drive_config({key: "fixture-service-account"})

    def test_oauth_missing_placeholder_and_malformed_fields_fail_closed(self):
        token = dict(access_token="fixture-access", refresh_token="fixture-refresh", expiry="2000-01-01T00:00:00Z")
        base = dict(client_id="123-fixture.apps.googleusercontent.com", client_secret="fixture-client-secret", token=json.dumps(token))
        cases = [
            (dict(token=""), "OAUTH_TOKEN_MISSING"),
            (dict(token="private-secret{"), "OAUTH_TOKEN_JSON"),
            (dict(token="[]"), "OAUTH_TOKEN_JSON"),
            (dict(client_id=""), "OAUTH_CLIENT_PAIR_INCOMPLETE"),
            (dict(client_secret=""), "OAUTH_CLIENT_PAIR_INCOMPLETE"),
            (dict(client_id="123"), "OAUTH_CLIENT_ID_FORMAT"),
            (dict(client_secret="YOUR_FULL_WEB_CLIENT_SECRET"), "OAUTH_PLACEHOLDER"),
        ]
        for delta, code in [
            (dict(access_token=""), "OAUTH_ACCESS_TOKEN_MISSING"),
            (dict(refresh_token=None), "OAUTH_REFRESH_TOKEN_MISSING"),
            (dict(refresh_token="YOUR_REFRESH_TOKEN"), "OAUTH_PLACEHOLDER"),
            (dict(access_token="YOUR_ACCESS_TOKEN"), "OAUTH_PLACEHOLDER"),
            (dict(refresh_token=123), "OAUTH_FIELD_FORMAT"),
            (dict(refresh_token="fixture refresh"), "OAUTH_FIELD_FORMAT"),
            (dict(expiry=None, expires_in=3600), "OAUTH_EXPIRY_FORMAT"),
            (dict(expiry="2026-02-30T00:00:00Z"), "OAUTH_EXPIRY_FORMAT"),
            (dict(expiry="2026-09-11T00:00:00"), "OAUTH_EXPIRY_FORMAT"),
        ]:
            cases.append((dict(token=json.dumps(dict(token, **delta))), code))
        # Mixed schemas must not appear valid when rclone would discard refresh.
        cases.append((dict(token=json.dumps(dict(access_token="fixture-access", RefreshToken="fixture-refresh"))), "OAUTH_REFRESH_TOKEN_MISSING"))
        for delta, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(drive_config.DriveConfigurationError, "^" + code + "$"):
                drive_config.validate_drive_config(dict(base, **delta))

    def test_configuration_preserves_existing_root_and_keeps_credentials_temporary(self):
        token = json.dumps(dict(access_token="fixture-access", refresh_token="fixture-refresh", expiry="2000-01-01T00:00:00Z"))
        supplied = "[gdrive]\ntype = drive\nroot_folder_id = fixture-root\nteam_drive = fixture-team\ntoken = " + token + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = dict(MACRO_RESEARCH_LANE="pr-413", RUNNER_TEMP=tmp, GITHUB_ENV=str(root / "env"), MACRO_DRIVE_CONFIG=supplied)
            previous_umask = os.umask(0o077)
            try:
                stdout = io.StringIO()
                with patch.dict(os.environ, env, clear=True), redirect_stdout(stdout):
                    drive_config.main()
                config = configparser.ConfigParser(interpolation=None)
                config.read(root / "macro-rclone.conf")
                self.assertEqual(config["gdrive"]["root_folder_id"], "fixture-root")
                self.assertEqual(config["gdrive"]["team_drive"], "fixture-team")
                self.assertEqual(config["gdrive"]["token"], token)
                self.assertEqual((root / "macro-rclone.conf").stat().st_mode & 0o777, 0o600)
                self.assertIn("MACRO_RESEARCH_REMOTE=gdrive:research/macro_technical_evidence/v1/pr-413\n", (root / "env").read_text())
                self.assertNotIn("fixture", stdout.getvalue() + (root / "env").read_text())
                self.assertIn("Google access is not yet verified", stdout.getvalue())
            finally:
                os.umask(previous_umask)

    def test_configuration_cli_never_reports_untrusted_exception_text(self):
        for error, expected in [
            (drive_config.DriveConfigurationError("OAUTH_TOKEN_MISSING"), ":OAUTH_TOKEN_MISSING"),
            (drive_config.DriveConfigurationError("private-secret"), ":INVALID_CONFIG"),
            (ValueError("private-secret"), ""),
        ]:
            with patch.object(drive_config, "configure", side_effect=error), self.assertRaises(SystemExit) as failure:
                drive_config.main()
            self.assertEqual(str(failure.exception), "BLOCKED_RESEARCH_DRIVE_CONFIGURATION" + expected)
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(MACRO_RESEARCH_LANE="pr-413", RUNNER_TEMP=tmp, GITHUB_ENV=str(Path(tmp) / "env"))
            previous_umask = os.umask(0o077)
            try:
                for text, code in [("", "CREDENTIALS_MISSING"), ("gdrive]\nprivate-secret", "INVALID_CONFIG"), ("[gdrive]\ntype=drive", "OAUTH_TOKEN_MISSING")]:
                    with patch.dict(os.environ, dict(env, MACRO_DRIVE_CONFIG=text), clear=True), self.assertRaises(SystemExit) as failure:
                        drive_config.main()
                    self.assertEqual(str(failure.exception), "BLOCKED_RESEARCH_DRIVE_CONFIGURATION:" + code)
                    self.assertFalse((Path(tmp) / "macro-rclone.conf").exists())
            finally:
                os.umask(previous_umask)

    def test_two_cycles_failure_journal_and_readonly_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transport = checkpoint.LocalTransport(root / "remote")
            def collector(store, ids, start, through, mode="current"):
                # Actual parsers, receipts, raw persistence; only HTTP is synthetic.
                def fetcher(sid, *args):
                    if mode == "current":
                        raw = f"DATE,{sid}\n2020-01-01,100\n2020-02-01,101\n".encode()
                    else:
                        rows = [dict(date="2020-01-01", value="100", realtime_start="2020-02-07", realtime_end="9999-12-31")]
                        raw = source.encoded(dict(units="lin", output_type=1, count=1, offset=0, observations=rows))
                    return [raw], source.utc_now()
                return source.collect(store, ids, start, through, mode, fetcher)
            def evaluate(*args):
                rows = [dict(asset=asset, feature=f"synthetic_{feature}", horizon_sessions=horizon,
                    status="INSUFFICIENT_INDEPENDENT_EVIDENCE", oos_rows=0, nonoverlap_windows=0,
                    effect_per_training_sd_pp=None, effect_ci95_pp=None, family_q_value=None,
                    oos_mse_improvement=None) for asset in ["SP500", "NASDAQCOM"]
                    for feature in range(24) for horizon in [1, 5, 10, 21, 63, 126, 252]]
                return dict(schema="macro-technical-evidence-v1", as_of=source.utc_now(),
                    tests_declared=336, coverage=dict(SP500={}, NASDAQCOM={}), results=rows,
                    code_file_sha256={}, input_receipt_sha256="a"*64,
                    eligible_for_selector=False, model_promoted=False)
            calendar = lambda *args: dict(schema="macro-release-calendar-v1", events=[], retrieved_at=source.utc_now())
            first = cycle.run_cycle(transport, root / "one", "one", collector=collector, calendar_fetcher=calendar, evaluator=evaluate)
            first_head = first["checkpoint"]["commit"]
            self.assertFalse(first["checkpoint"]["remote_verified"])
            # Subsequent provider failure must preserve the accepted predecessor.
            with self.assertRaisesRegex(ValueError, "macro_cycle_blocked"):
                cycle.run_cycle(transport, root / "failed", "failed", collector=lambda *a, **k: (_ for _ in ()).throw(ValueError("secret")), calendar_fetcher=calendar, evaluator=evaluate)
            self.assertEqual(checkpoint.head(transport)[0], first_head)
            second = cycle.run_cycle(transport, root / "two", "two", collector=collector, calendar_fetcher=calendar, evaluator=evaluate)
            self.assertEqual(second["checkpoint"]["parent"], first_head)
            changes = json.loads((root / "two/current/reports/comparison.json").read_bytes())
            self.assertFalse(changes["economic_data_changed"])
            context = json.loads((root / "two/current/reports/engine-context.json").read_bytes())
            self.assertFalse(context["eligible_for_selector"])
            self.assertEqual(context["stock_selection_weight"], 0)
            journal = [json.loads(p.read_bytes()) for p in (root / "remote/attempts").iterdir()]
            self.assertEqual(sum(r["phase"] == "STARTED" for r in journal), 3)
            self.assertEqual(sum(r["phase"] == "FAILED" for r in journal), 1)
            self.assertNotIn("secret", source.encoded(journal).decode())


def run_tests():
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(CheckpointTests))
    if not result.wasSuccessful():
        raise AssertionError("macro_research_cycle_smoke_failed")


if __name__ == "__main__":
    run_tests()
