"""Public adapter regressions: privacy, incomplete dates, exact scores and UI expiry."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.build_public_project_results import build, collect_history
from tests.run287_daily_research_monitor_smoke import score_fixture, score_source

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
SESSION = '2026-09-11'


def fixture(session=SESSION, close='2026-09-11T20:00:00Z'):
    close = datetime.fromisoformat(close.replace('Z', '+00:00'))
    original = score_fixture()
    for key in ('bundle', 'decision', 'linear', 'stack', 'upstream'):
        original[key].update(valuation_price_cutoff_date=session,
                             feature_available_from=(close + timedelta(minutes=5)).isoformat(),
                             decision_time_utc=(close + timedelta(minutes=10)).isoformat(),
                             executed_at_utc=(close + timedelta(minutes=20)).isoformat())
    original['rows'][0]['ticker'] = 'AMD'
    operating = score_source(original)
    operating['run']['created_at'] = close.isoformat()
    operating['artifact'] = {'id': 91, 'digest': 'sha256:' + 'd' * 64}
    report = {'schema_version':'run287-daily-research-monitor-v1', 'repository':'wscha231/r1000-quant-engine',
        'expected_us_session':session, 'current_engine_scores_ready':True,
        'safety':{'research_only':True, 'orders_allowed':False, 'target_book_write_allowed':False,
                  'ledger_write_allowed':False, 'production_activation_allowed':False},
        'watchlist':[{'ticker':'AMD','market':'US','price_status':'CURRENT','price_as_of':session,'close':120,
                      'current_engine_score':0.0,'engine_score_as_of':session,'engine_research_eligible':True,
                      'account_value':100000,'token':'secret-example','data_gap':'/home/private.txt'}]}
    sources = {'tactical':{'status':'VERIFIED_ARTIFACT','data':{
       'theme':{'research_only':True,'production_activation_allowed':False,'latest_price_date':'2026-09-09',
                'tickers_scored':989,'liquid_tickers':143,'top_tickers':['FAKE'],'scored_source':'/home/private'},
       'macro':{'asof_date':'2026-09-12','spy_close':float('nan'),'regime_state':'bear'},
       'etfs':{'asof_date':'2026-09-12','etfs':{'XLK':{'close':float('nan')}}}}},
       'operating': operating}
    return report,sources


def history_run(run_id, event='schedule', status='completed', conclusion='success', **changes):
    from datetime import timedelta
    run=dict(id=run_id,event=event,status=status,conclusion=conclusion,
             created_at=(NOW+timedelta(minutes=run_id)).isoformat(),
             path='.github/workflows/long_history_research.yml',head_branch='master',
             head_repository={'full_name':'wscha231/r1000-quant-engine'})
    run.update(changes)
    return run


class HistoryRunsClient:
    def __init__(self,runs):self.runs=runs;self.requests=[]
    def json(self,path):
        from urllib.parse import parse_qs,urlsplit
        self.requests.append(path)
        query=parse_qs(urlsplit(path).query)
        event=query.get('event',[None])[0]
        return {'workflow_runs':[r for r in self.runs if event is None or r['event']==event][:30]}


class Tests(unittest.TestCase):
    def run_build(self, report=None, sources=None):
        r,s=fixture()
        return build(report or r, sources or s, SESSION, NOW, 'a'*40, 'b'*64)

    def test_privacy_and_zero(self):
        result=self.run_build(); raw=json.dumps(result,allow_nan=False)
        for secret in ['secret-example','account_value','/home/private','FAKE','bear']:
            self.assertNotIn(secret,raw)
        self.assertEqual(result['rows'][0]['engine_score'],0)
        self.assertFalse(result['ranking_ready'])
        self.assertEqual(result['diagnostics']['theme']['status'],'STALE')
        self.assertEqual(result['diagnostics']['etfs']['finite_close_count'],0)
        context = result['research_scores']
        self.assertTrue(context['ready'])
        self.assertEqual(context['freshness_valid_until_utc'], '2026-09-14T20:00:00+00:00')
        self.assertEqual(context['engine_code_sha'], 'a' * 40)
        self.assertEqual(context['model_anchor_sha256'], 'b' * 64)
        self.assertFalse(context['predictive_value_validated'])
        self.assertNotIn('weights', result)
        self.assertNotIn('performance', result)

    def test_original_score_proof_is_required_despite_report_ready(self):
        def future(s):
            s['data']['score_handoff']['stack']['executed_at_utc'] = '2026-09-20T00:00:00Z'
        mutations = [lambda s: s.update(status='UPSTREAM_FAILED'),
                     lambda s: s.update(artifact_hash_verified=False),
                     lambda s: s['run'].update(head_sha='c' * 40),
                     lambda s: s['run'].update(conclusion='failure'),
                     lambda s: s['data'].pop('score_handoff'),
                     lambda s: s['artifact'].update(digest=None),
                     lambda s: s['artifact'].update(id=None), future]
        for mutate in mutations:
            r,s=fixture(); mutate(s['operating'])
            result=self.run_build(r,s)
            self.assertFalse(result['research_scores']['ready'])
            self.assertIsNone(result['rows'][0]['engine_score'])
        r,s=fixture();s.pop('operating')
        self.assertIsNone(self.run_build(r,s)['rows'][0]['engine_score'])

    def test_original_row_flags_and_values_are_not_report_substitutions(self):
        r,s=fixture();r['watchlist'][0]['engine_corporate_action_quarantine']=True
        result=self.run_build(r,s)
        self.assertFalse(result['rows'][0]['quarantined'])
        r['watchlist'][0]['current_engine_score']=42
        self.assertIsNone(self.run_build(r,s)['rows'][0]['engine_score'])

    def test_next_close_settlement_does_not_renew_previous_session(self):
        r,s=fixture()
        for stamp in ['2026-09-14T20:00:00+00:00','2026-09-14T20:30:00+00:00',
                      '2026-09-14T22:00:00+00:00']:
            result=build(r,s,SESSION,datetime.fromisoformat(stamp),'a'*40,'b'*64)
            self.assertFalse(result['research_scores']['ready'])
            self.assertIsNone(result['rows'][0]['engine_score'])

    def test_score_expiry_uses_actual_holidays_early_close_and_dst(self):
        cases=[('2026-03-06','2026-03-06T21:00:00Z','2026-03-09T20:00:00+00:00'),
               ('2026-10-30','2026-10-30T20:00:00Z','2026-11-02T21:00:00+00:00'),
               ('2026-11-25','2026-11-25T21:00:00Z','2026-11-27T18:00:00+00:00'),
               ('2026-11-27','2026-11-27T18:00:00Z','2026-11-30T21:00:00+00:00')]
        for session,close,deadline in cases:
            r,s=fixture(session,close);now=datetime.fromisoformat(close.replace('Z','+00:00'))+timedelta(hours=2)
            result=build(r,s,session,now,'c'*40,'e'*64)
            self.assertTrue(result['research_scores']['ready'], (session,result['research_scores']))
            self.assertEqual(result['research_scores']['freshness_valid_until_utc'], deadline)
            self.assertEqual(result['research_scores']['engine_code_sha'], 'a'*40)
            self.assertEqual(result['source_commit'], 'c'*40)

    def test_stale_missing_future_and_nonfinite_scores(self):
        for date in [None,'2026-09-09','2026-09-14']:
            r,s=fixture();r['watchlist'][0]['engine_score_as_of']=date
            self.assertIsNone(self.run_build(r,s)['rows'][0]['engine_score'])
        for value in [float('nan'),float('inf'),True]:
            r,s=fixture();r['watchlist'][0]['current_engine_score']=value
            self.assertIsNone(self.run_build(r,s)['rows'][0]['engine_score'])
        r,s=fixture();r['current_engine_scores_ready']=False
        self.assertIsNone(self.run_build(r,s)['rows'][0]['engine_score'])

    def test_nonpositive_diagnostic_closes(self):
        for value in [0, -1, None, float('nan')]:
            r,s=fixture();s['tactical']['data']['macro']['spy_close']=value
            s['tactical']['data']['etfs']['etfs']['XLK']['close']=value
            result=self.run_build(r,s)
            self.assertFalse(result['diagnostics']['macro']['price_present'])
            self.assertEqual(result['diagnostics']['etfs']['finite_close_count'],0)

    def test_optional_history_is_omitted_until_installed(self):
        class NoCalls:
            def json(self, path):raise AssertionError('uninstalled workflow queried')
        self.assertIsNone(collect_history(NoCalls(),ROOT/'tests/uninstalled-history-workflow.yml'))

    def test_history_code_push_cannot_replace_scheduled_evidence(self):
        runs=[history_run(100+i,event='push') for i in range(40)]
        runs+=[history_run(10),history_run(8,event='workflow_dispatch')]
        client=HistoryRunsClient(runs)
        result=collect_history(client)
        self.assertEqual(result['run']['id'],10)
        self.assertEqual(result['status'],'WORKFLOW_SUCCESS_DATA_UNVERIFIED')
        self.assertEqual(set(client.requests),{
            '/actions/workflows/long_history_research.yml/runs?branch=master&per_page=30&event=schedule',
            '/actions/workflows/long_history_research.yml/runs?branch=master&per_page=30&event=workflow_dispatch'})

    def test_history_push_only_is_not_producer_evidence(self):
        result=collect_history(HistoryRunsClient([history_run(3,event='push')]))
        self.assertEqual(result,{'status':'MISSING_RUN'})

    def test_history_explicit_skipped_producer_run_is_ignored(self):
        result=collect_history(HistoryRunsClient([
            history_run(20,conclusion='skipped'),history_run(10,event='workflow_dispatch')]))
        self.assertEqual(result['run']['id'],10)

    def test_history_latest_actual_failure_and_cancel_remain_visible(self):
        for conclusion in ('failure','cancelled','timed_out'):
            with self.subTest(conclusion=conclusion):
                result=collect_history(HistoryRunsClient([
                    history_run(40,event='push'),history_run(30,event='workflow_dispatch',conclusion=conclusion),
                    history_run(10)]))
                self.assertEqual(result['run']['id'],30)
                self.assertEqual(result['status'],'UPSTREAM_FAILED')

    def test_history_current_actual_run_is_not_hidden_by_old_success(self):
        for status in ('queued','in_progress'):
            with self.subTest(status=status):
                result=collect_history(HistoryRunsClient([
                    history_run(40,event='push'),history_run(30,status=status,conclusion=None),history_run(10)]))
                self.assertEqual(result['run']['id'],30)
                self.assertEqual(result['status'],'UPSTREAM_IN_PROGRESS')

    def test_history_trusted_repository_branch_and_path_filters_remain(self):
        runs=[history_run(40,head_repository={'full_name':'fork/repo'}),
              history_run(30,head_branch='feature'),history_run(20,path='.github/workflows/other.yml'),history_run(10)]
        result=collect_history(HistoryRunsClient(runs))
        self.assertEqual(result['run']['id'],10)

    def test_failed_producer_cannot_supply_diagnostics(self):
        r,s=fixture();s['tactical']['status']='UPSTREAM_FAILED'
        self.assertIsNone(self.run_build(r,s)['diagnostics']['theme']['data_as_of'])

    def test_safety_and_duplicate_identity(self):
        r,s=fixture();r['safety']['orders_allowed']=True
        with self.assertRaises(ValueError):self.run_build(r,s)
        r,s=fixture();r['watchlist'].append(copy.deepcopy(r['watchlist'][0]))
        with self.assertRaises(ValueError):self.run_build(r,s)

    def test_workflow_separates_account_and_research(self):
        import yaml
        raw=(ROOT/'.github/workflows/pages_deploy.yml').read_text(); w=yaml.safe_load(raw)
        steps=w['jobs']['build']['steps']
        daily=next(x for x in steps if x.get('id')=='daily_artifact')
        self.assertIn("workflow_run.name == 'Daily Operating Selection Refresh'", daily['if'])
        self.assertIn("workflow_run.conclusion == 'success'",daily['if'])
        publish=next(x for x in steps if x.get('name')=='Connect current project research results')
        self.assertEqual(publish['env'],{'GH_TOKEN':'${{ github.token }}'})
        self.assertNotIn('continue-on-error', publish)
        upload=next(x for x in steps if x.get('uses','').startswith('actions/upload-pages-artifact'))
        self.assertEqual(upload['with']['path'],'docs/public')
        self.assertIn('docs/run287_daily_research_monitor_contract.json',raw)
        self.assertIn('Run287 Daily Research Monitor',raw)
        guard=w['jobs']['build']['if']
        self.assertIn('head_repository.full_name == github.repository',guard)
        self.assertIn('github.event.workflow_run.event',guard)
        self.assertNotIn('pull_request',guard)
        self.assertIn('.github/workflows/long_history_research.yml',raw)
        checkout=next(x for x in steps if x.get('uses','').startswith('actions/checkout@'))
        self.assertIn('.github/workflows/pages_deploy.yml',checkout['with']['sparse-checkout'].splitlines())

    def test_browser_expiry_missing_file_and_escape(self):
        result=self.run_build()
        # A hostile label stays escaped, while URLs are constructed from numeric ids.
        result['sources'][0]['label']='<img src=x onerror=alert(1)>'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let packet=JSON.parse(process.argv[1]);const validPacket=structuredClone(packet);
let now=Date.parse('2026-09-12T00:00:00Z'),fail=false,missing='';
const dashboard={schema_version:'run287-public-dashboard-v1',as_of_close:'2026-07-10',status:{review_only:true,live_trading_enabled:false},portfolios:{main:{holdings:[{ticker:'AMD'}]}}};
const validQuotes={schema_version:'run287-public-market-quotes-v1',status:'COMPLETE',review_only:true,live_trading_enabled:false,portfolio_revalued:false,portfolio_as_of_close:'2026-07-10',as_of_close:'2026-09-11',expected_session_date:'2026-09-11',checked_at_utc:'2026-09-12T00:00:00Z',freshness_valid_until_utc:'2026-09-14T20:00:00Z',quotes:[{ticker:'AMD',currency:'USD',close:120,session_date:'2026-09-11'}]};
let quotePacket=structuredClone(validQuotes);
const elements={};const element=id=>elements[id]??=( {value:'',textContent:'',innerHTML:'',addEventListener(){},replaceChildren(){this.innerHTML='';}} );
const timers=[];const sandbox={Date:class extends Date {static now(){return now;}},Number,String,Array,Error,Promise,
 document:{getElementById:element,addEventListener(){},hidden:false},window:{addEventListener(){},setInterval(fn){timers.push(fn);}},
 fetch:async url=>({ok:!fail && (!missing || !url.includes(missing)),json:async()=>url.includes('project-results')?packet:url.includes('market-quotes')?quotePacket:dashboard})};
const app=fs.readFileSync('docs/public/app.js','utf8');
vm.runInNewContext(app.slice(app.indexOf('function validateQuotes('),app.indexOf('function renderMetricCards(')),sandbox);
vm.runInNewContext(fs.readFileSync('docs/public/project-results.js','utf8'),sandbox);
setImmediate(async()=>{
 assert(element('research-results-body').innerHTML.includes('>0<'));
 assert(element('project-source-cards').innerHTML.includes('&lt;img'));
 assert(element('project-diagnostics').textContent.includes('모형 bbbbbbbb'));
 assert(element('project-diagnostics').textContent.includes('성과 검증 전'));
 for(const name of ['market-quotes','dashboard']){
   missing=name;await timers[0]();assert(element('research-results-body').innerHTML.includes('>0<'));
   assert(!element('research-results-body').innerHTML.includes('>120<'));
 }missing='';
 for(const mutate of [q=>delete q.schema_version,q=>delete q.quotes,q=>q.quotes=[],q=>q.quotes.push(q.quotes[0]),q=>q.quotes[0].close=0,q=>q.quotes[0].currency='KRW',q=>q.as_of_close='2026-09-10',q=>q.checked_at_utc='2026-09-20T00:00:00Z',q=>q.portfolio_as_of_close='2026-07-11']){
   quotePacket=structuredClone(validQuotes);mutate(quotePacket);await timers[0]();
   assert(element('research-results-body').innerHTML.includes('>0<'));
   assert(!element('research-results-body').innerHTML.includes('>120<'));
 }
 quotePacket=structuredClone(validQuotes);
 const mutations=[p=>delete p.research_scores,p=>p.research_scores.ready=false,p=>p.research_scores.ranking_allowed=true,
   p=>p.research_scores.status='BLOCKED',p=>p.research_scores.model_anchor_sha256='wrong',
   p=>p.research_scores.engine_code_sha='c'.repeat(40),p=>delete p.research_scores.model_meta_sha256,
   p=>p.research_scores.source_artifact_sha256='c'.repeat(64),p=>p.research_scores.source_run_id=42,
   p=>p.research_scores.checked_at_utc='2026-09-20T00:00:00Z',p=>p.generated_at='2026-09-12T00:00:01Z',
   p=>p.research_scores.feature_available_from='2026-09-12T00:00:00Z',
   p=>p.research_scores.decision_time_utc='2026-09-11T19:59:00Z',
   p=>p.research_scores.score_as_of='2026-09-10',p=>p.rows[0].score_as_of='2026-09-10',
   p=>p.rows[0].market='KR',p=>p.sources.find(s=>s.key==='operating').artifact_verified=false];
 for(const mutate of mutations){
   packet=structuredClone(validPacket);mutate(packet);await timers[0]();
   assert(!element('research-results-body').innerHTML.includes('>0<'));
   assert(element('research-results-body').innerHTML.includes('>120<'));
 }
 packet=structuredClone(validPacket);await timers[0]();assert(element('research-results-body').innerHTML.includes('>0<'));
 // A complete legacy quote packet cannot extend research score freshness.
 quotePacket.freshness_valid_until_utc='2026-09-15T20:00:00Z';await timers[0]();
 now=Date.parse('2026-09-14T20:00:01Z');timers[1]();
 assert(!element('research-results-body').innerHTML.includes('>0<'));
 assert(element('research-results-body').innerHTML.includes('>120<'));
 assert(element('project-results-status').textContent.includes('최신성 확인 필요'));
 fail=true;await timers[0]();assert.equal(element('research-results-body').innerHTML,'');
});
'''
        subprocess.run(['node','-e',script,json.dumps(result)],cwd=ROOT,check=True)


def main():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    if not unittest.TextTestRunner().run(suite).wasSuccessful():raise SystemExit(1)
    return 0
if __name__=='__main__':main()
