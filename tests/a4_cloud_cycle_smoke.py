"""Cloud recovery boundaries, invalid input attempts and hosted workflow wiring."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import shutil
from datetime import timedelta
from unittest.mock import patch

import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import run_a4_research_cycle as cycle
from tools import a4_macro_learning as learning
from tools.macro_history_sources import encoded,digest
from tests.a4_macro_learning_smoke import fixture

NOW="2026-11-07T10:00:00Z"


class CloudTests(unittest.TestCase):
    def test_primary_market_root_preserves_separate_reviewed_learning_bundle(self):
        p,policy,resolve=fixture();cutoff=(learning.free.utc(p['cutoff'])+timedelta(minutes=20)).isoformat()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);market_root=root/'primary';market_root.mkdir();learn=root/'restored';learn.mkdir()
            original=resolve(None);sha=digest(original);policy_raw=encoded(policy)
            (learn/'original.raw').write_bytes(original);(learn/'policy.json').write_bytes(policy_raw)
            (learn/'inputs.json').write_bytes(encoded(p))
            request=dict(schema='a4-learning-request-v1',policy=dict(path='policy.json',sha256=digest(policy_raw)),
                inputs=dict(path='inputs.json',sha256=digest(encoded(p))),originals={sha:dict(path='original.raw',sha256=sha)})
            (learn/'learning_request.json').write_bytes(encoded(request))
            result=cycle.run_cycle(input_root=market_root,learning_input_root=learn,state_root=root/'state',
                output_dir=root/'attempt',cutoff=cutoff,learning_policy_sha256=digest(policy_raw))
            self.assertEqual(result['learning_status'],'RESEARCH_CYCLE_COMPLETE')
            self.assertTrue(any(e['kind']=='MONTHLY_CHALLENGER_STORED' for e in result['events']))
            self.assertEqual(result['market_status'],'DATA_BLOCKED')
            self.assertFalse(result['accepted_model_changed'])
            self.assertFalse((market_root/'learning_request.json').exists())
            (learn/'original.raw').write_bytes(b'corrupt')
            bad=cycle.run_cycle(input_root=market_root,learning_input_root=learn,state_root=root/'state',
                output_dir=root/'bad',cutoff=cutoff,learning_policy_sha256=digest(policy_raw))
            self.assertEqual(bad['learning_status'],'BLOCKED')
            with self.assertRaisesRegex(ValueError,'LEARNING_STATE_OUTPUT_OVERLAP'):
                cycle.run_cycle(input_root=market_root,learning_input_root=root/'state',state_root=root/'state',
                    output_dir=root/'overlap',cutoff=cutoff)

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

    def test_checkpoint_writer_refuses_oversize_before_durable_state_mutation(self):
        value=dict(schema="a4-weekly-score-v1",week="2026-W45",cutoff=NOW,scores=[])
        raw=encoded(value)
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/"weekly"/(digest(raw)+".json")
            with patch.object(cycle,"MAX_CHECKPOINT_BYTES",len(raw)-1),self.assertRaisesRegex(ValueError,"CHECKPOINT_SIZE"):
                cycle.store_checkpoint(target,value)
            self.assertFalse(target.parent.exists())
            with patch.object(cycle,"MAX_CHECKPOINT_BYTES",len(raw)):
                cycle.store_checkpoint(target,value)
                self.assertEqual(cycle.market.bounded(target,cycle.MAX_CHECKPOINT_BYTES),raw)
            self.assertEqual(json.loads(raw),value)

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

    def test_fixed_report_replay_does_not_backdate_new_cloud_forecasts(self):
        from tests.a4_liquidity_analysis_smoke import raw
        old,old_policy,resolve=fixture(1600)
        trial=learning.fit_trial(old,old_policy,digest(encoded(old_policy)),resolve)
        p,policy,resolve=fixture(10000)  # Actual fixture calendar ends 2026-11-06.
        policy.update(active_trial_sha256=trial['trial_sha256'],reviewed_trial_pins=[trial['trial_sha256']],
                      expires_at='2026-11-10T00:00:00Z')
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);inputs=base/'inputs';inputs.mkdir();state=base/'state'
            learning.store_trial(trial,state)
            def put(name,value):
                body=value if type(value) is bytes else encoded(value)
                (inputs/name).write_bytes(body)
                return dict(path=name,sha256=digest(body))
            original=resolve(None);sha=digest(original)
            request=dict(schema='a4-learning-request-v1',inputs=put('learning_inputs.json',p),
                policy=put('learning_policy.json',policy),originals={sha:put('original.raw',original)})
            put('learning_request.json',request)
            specs=[]
            for sid,value in (('SOFR',4.2),('IORB',4)):
                reference=put(sid+'.csv',raw(sid,[('2026-11-06',value)]))
                specs.append(dict(kind='macro_v2',source_id='fred:'+sid,**reference,status='COLLECTED',
                                  collected_at='2026-11-06T22:00:00Z'))
            market_request=dict(schema=cycle.market.REQUEST_SCHEMA_V2,market='US',session='2026-11-06',inputs=specs,
                available_at='2026-11-07T09:00:00Z',expires_at='2026-11-10T00:00:00Z')
            reference=put('request.json',market_request);(inputs/'request.sha256').write_text(reference['sha256'])
            # A pinned clock context selects fixed replay; incomplete A5 evidence
            # deliberately remains blocked and grants no portfolio admission.
            model=dict(schema='a5-model-proposal-request-v1',inputs=put('model_inputs.json',dict(as_of=NOW)),
                registry=put('registry.json',{}),policy=put('model_policy.json',dict(current_a3_review_profile=dict(
                    available_at='2026-11-07T09:00:00Z',expires_at='2026-11-10T00:00:00Z'))))
            put('a5_request.json',model)
            arguments=dict(input_root=inputs,state_root=state,learning_policy_sha256=request['policy']['sha256'],
                           a5_policy_sha256=model['policy']['sha256'],code_sha='a'*40)
            first=cycle.run_cycle(**arguments,output_dir=base/'first',cutoff=NOW)
            self.assertEqual(first['learning_status'],'RESEARCH_CYCLE_COMPLETE',first)
            paths=list((state/'predictions').iterdir());self.assertEqual(len(paths),1)
            captured=json.loads(paths[0].read_bytes())['predictions']
            self.assertTrue(captured);self.assertTrue(all(r['created_at']==NOW for r in captured))
            late=cycle.run_cycle(**arguments,output_dir=base/'late',cutoff='2026-11-09T21:05:00Z')
            self.assertEqual(late['decision_cutoff'],NOW)
            self.assertEqual(late['learning_status'],'BLOCKED',late)
            self.assertEqual(list((state/'predictions').iterdir()),paths)
            self.assertEqual(late['a5_status'],'BLOCKED')


if __name__=="__main__":unittest.main()
