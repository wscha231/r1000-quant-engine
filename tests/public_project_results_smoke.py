"""Public adapter regressions: privacy, incomplete dates, exact scores and UI expiry."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.build_public_project_results import build

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
SESSION = '2026-09-11'


def fixture():
    report = {'schema_version':'run287-daily-research-monitor-v1', 'repository':'wscha231/r1000-quant-engine',
        'expected_us_session':SESSION, 'current_engine_scores_ready':True,
        'safety':{'research_only':True, 'orders_allowed':False, 'target_book_write_allowed':False,
                  'ledger_write_allowed':False, 'production_activation_allowed':False},
        'watchlist':[{'ticker':'AMD','market':'US','price_status':'CURRENT','price_as_of':SESSION,'close':120,
                      'current_engine_score':0.0,'engine_score_as_of':SESSION,'engine_research_eligible':True,
                      'account_value':100000,'token':'secret-example','data_gap':'/home/private.txt'}]}
    sources = {'tactical':{'status':'VERIFIED_ARTIFACT','data':{
       'theme':{'research_only':True,'production_activation_allowed':False,'latest_price_date':'2026-09-09',
                'tickers_scored':989,'liquid_tickers':143,'top_tickers':['FAKE'],'scored_source':'/home/private'},
       'macro':{'asof_date':'2026-09-12','spy_close':float('nan'),'regime_state':'bear'},
       'etfs':{'asof_date':'2026-09-12','etfs':{'XLK':{'close':float('nan')}}}}}}
    return report,sources


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

    def test_stale_missing_future_and_nonfinite_scores(self):
        for date in [None,'2026-09-09','2026-09-14']:
            r,s=fixture();r['watchlist'][0]['engine_score_as_of']=date
            self.assertIsNone(self.run_build(r,s)['rows'][0]['engine_score'])
        for value in [float('nan'),float('inf'),True]:
            r,s=fixture();r['watchlist'][0]['current_engine_score']=value
            self.assertIsNone(self.run_build(r,s)['rows'][0]['engine_score'])
        r,s=fixture();r['current_engine_scores_ready']=False
        self.assertIsNone(self.run_build(r,s)['rows'][0]['engine_score'])

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

    def test_browser_expiry_missing_file_and_escape(self):
        result=self.run_build()
        # A hostile label stays escaped, while URLs are constructed from numeric ids.
        result['sources'][0]['label']='<img src=x onerror=alert(1)>'
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const packet=JSON.parse(process.argv[1]);let now=Date.parse('2026-09-12T00:00:00Z'),fail=false;
const elements={};const element=id=>elements[id]??=( {value:'',textContent:'',innerHTML:'',addEventListener(){},replaceChildren(){this.innerHTML='';}} );
const timers=[];const sandbox={Date:class extends Date {static now(){return now;}},Number,String,Array,Error,Promise,
 document:{getElementById:element,addEventListener(){},hidden:false},window:{addEventListener(){},setInterval(fn){timers.push(fn);}},
 fetch:async url=>({ok:!fail,json:async()=>url.includes('project-results')?packet:{status:'COMPLETE',expected_session_date:'2026-09-11',freshness_valid_until_utc:'2026-09-14T20:00:00Z'}})};
vm.runInNewContext(fs.readFileSync('docs/public/project-results.js','utf8'),sandbox);
setImmediate(async()=>{
 assert(element('research-results-body').innerHTML.includes('>0<'));
 assert(element('project-source-cards').innerHTML.includes('&lt;img'));
 now=Date.parse('2026-09-14T20:00:01Z');timers[1]();
 assert(!element('research-results-body').innerHTML.includes('>0<'));
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
