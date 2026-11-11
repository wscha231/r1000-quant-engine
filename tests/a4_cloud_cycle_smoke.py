"""Cloud recovery boundaries, invalid input attempts and hosted workflow wiring."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import shutil
from datetime import timedelta

import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import run_a4_research_cycle as cycle
from tools import a4_macro_learning as learning
from tools.macro_history_sources import encoded,digest
from tests.a4_macro_learning_smoke import fixture

NOW="2026-11-07T10:00:00Z"


class CloudTests(unittest.TestCase):
    def test_missing_inputs_publish_only_new_blocked_attempt_not_old_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);inputs=root/"inputs";inputs.mkdir()
            state=root/"state";state.mkdir()
            old=root/"attempts/old";old.mkdir(parents=True)
            (old/"cycle.json").write_bytes(b'{"status":"old_success"}')
            result=cycle.run_cycle(input_root=inputs,state_root=state,output_dir=root/"attempts/new",cutoff=NOW)
            self.assertEqual(result["status"],"PARTIAL_RESEARCH")
            self.assertEqual(result["market_status"],"DATA_BLOCKED")
            self.assertFalse(result["durable_remote_verified"])
            self.assertEqual((old/"cycle.json").read_bytes(),b'{"status":"old_success"}')
            self.assertEqual(list(state.iterdir()),[])

    def test_existing_attempt_and_overlapping_roots_refuse_before_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/"out";out.mkdir()
            for paths in ((root/"input",root/"state",out),(root,root/"state",root/"out2")):
                with self.subTest(paths=paths),self.assertRaises(ValueError):
                    cycle.run_cycle(input_root=paths[0],state_root=paths[1],output_dir=paths[2],cutoff=NOW)

    def test_prepared_input_policy_must_match_external_raw_pin(self):
        p,policy,resolve=fixture()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            raw_policy=json.dumps(policy,indent=2).encode();raw_inputs=encoded(p)
            (root/"policy.json").write_bytes(raw_policy);(root/"inputs.json").write_bytes(raw_inputs)
            request=dict(schema="a4-learning-request-v1",policy=dict(path="policy.json",sha256=digest(raw_policy)),
                         inputs=dict(path="inputs.json",sha256=digest(raw_inputs)),originals={})
            (root/"learning_request.json").write_bytes(encoded(request))
            with self.assertRaises(ValueError):cycle.load_learning(root,"a"*64)
            actual,loaded,_=cycle.load_learning(root,digest(raw_policy))
            self.assertEqual(actual,p);self.assertEqual(loaded,policy)

    def test_restore_rechecks_trial_bytes_and_rejects_future_or_corrupt_state(self):
        p,policy,resolve=fixture();trial=learning.fit_trial(p,policy,digest(encoded(policy)),resolve)
        with tempfile.TemporaryDirectory() as d:
            learning.store_trial(trial,d)
            self.assertEqual(cycle.restored_trials(d,NOW),[trial])
            path=next((Path(d)/"trials").iterdir());path.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):cycle.restored_trials(d,NOW)

    def test_existing_workflow_runs_hosted_and_fails_without_transport_readback(self):
        workflow=yaml.safe_load((ROOT/".github/workflows/daily_crisis_monitor.yml").read_text())
        job=workflow["jobs"]["monitor"]
        self.assertEqual(job["runs-on"],"ubuntu-latest")
        self.assertFalse(job["concurrency"]["cancel-in-progress"])
        steps=job["steps"]
        run=next(s for s in steps if s.get("id")=="a4_cycle")
        self.assertIn("run_a4_research_cycle.py",run["run"])
        persist=next(s for s in steps if s.get("id")=="a4_persist")
        self.assertIn("--immutable",persist["run"])
        self.assertIn("rclone check",persist["run"])
        self.assertNotIn("|| true",persist["run"])
        restore=next(s for s in steps if s.get("id")=="a4_restore")
        self.assertIn("namespace exists",restore["run"])
        final=steps[-1]
        self.assertIn('test "$PERSIST" = success',final["run"])
        self.assertIn("vars.A4_RESEARCH_ENABLED",run["if"])

    def test_monthly_trial_resumes_on_another_machine_without_refit_or_promotion(self):
        p,policy,resolve=fixture()
        cutoff=(learning.free.utc(p["cutoff"])+timedelta(minutes=20)).isoformat()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);inputs=root/"inputs";inputs.mkdir()
            raw_policy=encoded(policy);original=resolve(None);sha=digest(original)
            (inputs/"policy.json").write_bytes(raw_policy);(inputs/"inputs.json").write_bytes(encoded(p))
            (inputs/"original.raw").write_bytes(original)
            request=dict(schema="a4-learning-request-v1",policy=dict(path="policy.json",sha256=digest(raw_policy)),
                inputs=dict(path="inputs.json",sha256=digest(encoded(p))),
                originals={sha:dict(path="original.raw",sha256=sha)})
            (inputs/"learning_request.json").write_bytes(encoded(request))
            first=cycle.run_cycle(input_root=inputs,state_root=root/"machine1",output_dir=root/"attempt1",
                cutoff=cutoff,learning_policy_sha256=digest(raw_policy))
            self.assertEqual(first["learning_status"],"RESEARCH_CYCLE_COMPLETE")
            self.assertTrue(any(e["kind"]=="MONTHLY_CHALLENGER_STORED" for e in first["events"]))
            # Transport is simulated by an exact local copy, never claimed Drive proof.
            shutil.copytree(root/"machine1",root/"machine2")
            second=cycle.run_cycle(input_root=inputs,state_root=root/"machine2",output_dir=root/"attempt2",
                cutoff=cutoff,learning_policy_sha256=digest(raw_policy))
            self.assertEqual(second["learning_status"],"RESEARCH_CYCLE_COMPLETE")
            self.assertFalse(any(e["kind"]=="MONTHLY_CHALLENGER_STORED" for e in second["events"]))
            self.assertFalse(second["accepted_model_changed"])
            self.assertFalse(second["durable_remote_verified"])


if __name__=="__main__":unittest.main()
