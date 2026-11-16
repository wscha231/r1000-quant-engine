"""Synthetic extension proof only; no numerical supplier workbook."""
import sys,io,gzip,json,tempfile,unittest,importlib.util,zipfile
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.macro_history_sources import digest,encoded
P=ROOT/'tools/a4_rtdsm_extension.py'
from tools import a4_rtdsm_extension as v

def workbook(alias='PCPI',labels=('PCPI18M1','PCPI18M2'),*,values=None,formula=False,external=False,extra=None):
    values=values or [('2017:11',[100,110]),('2017:12',[101,112]),('2018:01',[None,113])]
    strings=['DATE',*labels,*[r[0] for r in values],'#N/A']
    q=lambda s:'{'+v.MAIN+'}'+s
    sheet=ET.Element(q('worksheet'));data=ET.SubElement(sheet,q('sheetData'))
    first=ET.SubElement(data,q('row'),r='1')
    def col(i):
        text=''
        while i:i,n=divmod(i-1,26);text=chr(65+n)+text
        return text
    for i in range(len(labels)+1):
        c=ET.SubElement(first,q('c'),r=col(i+1)+'1',t='s');ET.SubElement(c,q('v')).text=str(i)
    for n,(observed,items) in enumerate(values,2):
        row=ET.SubElement(data,q('row'),r=str(n));c=ET.SubElement(row,q('c'),r='A'+str(n),t='s')
        ET.SubElement(c,q('v')).text=str(strings.index(observed))
        for i,value in enumerate(items,2):
            c=ET.SubElement(row,q('c'),r=col(i)+str(n),**({'t':'s'} if value is None else {}))
            if formula and n==2 and i==2:ET.SubElement(c,q('f')).text='1+1'
            ET.SubElement(c,q('v')).text=str(strings.index('#N/A')) if value is None else str(value)
    ss=ET.Element(q('sst'))
    for s in strings:ET.SubElement(ET.SubElement(ss,q('si')),q('t')).text=s
    book=ET.Element(q('workbook'));sheets=ET.SubElement(book,q('sheets'))
    ET.SubElement(sheets,q('sheet'),name=alias.lower(),sheetId='1',
        **{'{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id':'rId1'})
    rel=ET.Element('{'+v.RELS+'}Relationships')
    ET.SubElement(rel,'{'+v.RELS+'}Relationship',Id='rId1',Target='worksheets/sheet1.xml',
        **({'TargetMode':'External'} if external else {}))
    files={'xl/workbook.xml':ET.tostring(book),'xl/_rels/workbook.xml.rels':ET.tostring(rel),
        'xl/sharedStrings.xml':ET.tostring(ss),'xl/worksheets/sheet1.xml':ET.tostring(sheet)}
    files.update(extra or {})
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,raw in files.items():z.writestr(name,raw)
    return out.getvalue()

class ExtensionChecks(unittest.TestCase):
 def test_capture_reference_hash_url_and_clocks_are_bound(self):
  raw=workbook('IPT',('IPT18M1','IPT18M2'))
  clock=dict(source_uri=v.source_uri('rtdsm_ext_ipt'),original_sha256=digest(raw),original_bytes=len(raw),request_started_at='2018-03-01T23:59:59Z',body_completed_at='2018-03-02T00:00:00Z',http_status=200)
  _,meta=v.normalize(raw,'rtdsm_ext_ipt',collected_at=clock['body_completed_at'],capture_ref=clock)
  self.assertEqual(meta['capture_ref'],clock)
  self.assertEqual(meta['capture_clock_precision'],'BODY_COMPLETION_CALLER_REFERENCE')
  for change in ({'original_sha256':'0'*64},{'source_uri':'https://example.org/data.xlsx'},{'request_started_at':'2018-03-02T00:00:01Z'},{'body_completed_at':'2018-03-02T00:00:01Z'},{'original_bytes':True},{'http_status':302}):
   altered=dict(clock,**change)
   with self.subTest(change=change),self.assertRaises(ValueError):v.normalize(raw,'rtdsm_ext_ipt',collected_at=clock['body_completed_at'],capture_ref=altered)
 def rows(self,alias='PCPIX',**kwargs):
  labels=kwargs.pop('labels',(alias+'18M1',alias+'18M2'))
  raw=workbook(alias,labels,**kwargs)
  return v.normalize(raw,'rtdsm_ext_'+alias.lower(),collected_at='2018-03-02T00:00:00Z')
 def test_closed_feeds_and_units(self):
  for alias,unit in [('PCPIX','index'),('IPT','index'),('CUT','percent')]:
   rows,meta=self.rows(alias,values=[('2017:11',[80,81]),('2017:12',[82,83]),('2018:01',[None,84])])
   self.assertEqual(meta['observations'],5);self.assertEqual(meta['vintages'],2)
   self.assertEqual({r['source_id'] for r in rows},{'rtdsm-ext:'+alias})
   self.assertEqual({r['unit'] for r in rows},{unit})
   self.assertEqual(meta['value_basis'],'PERCENTAGE_POINTS' if alias=='CUT' else 'NATIVE_VINTAGE_SPECIFIC_BASE')
   self.assertTrue(all(not x['independent_signal_counted'] for x in rows))
   self.assertTrue(all(not meta[k] for k in v.SAFETY))
 def test_1962_industrial_vintage_does_not_rewrite_legacy(self):
  before=digest(Path(v.legacy.__file__).read_bytes())
  raw=workbook('IPT',('IPT62M11',),values=[('1962:09',[70]),('1962:10',[71])])
  rows,_=v.normalize(raw,'rtdsm_ext_ipt',collected_at='2026-11-16T00:00:00Z',start='1962-11-01')
  self.assertEqual(rows[0]['available_at'],'1962-12-01T00:00:00-05:00')
  with self.assertRaises(ValueError):v.legacy.vintage_boundary('IPT62M11','IPT')
  self.assertEqual(before,digest(Path(v.legacy.__file__).read_bytes()))
  self.assertEqual(set(v.legacy.register()),{'EMPLOY','PCPI','RUC'})
 def test_documented_prefix_monthly_frequency_and_hard_end(self):
  for alias,label in [('IPT','IPT62M10'),('PCPIX','PCPIX98M10'),('CUT','CUT83M6'),('IPT','IPT18Q1'),('IPT','IPT36M1')]:
   with self.subTest(label=label),self.assertRaises(ValueError):v.vintage_boundary(label,alias)
  self.assertEqual(v.vintage_boundary('IPT26M10','IPT')[2],'2026-11-01T00:00:00-04:00')
 def test_fraction_units_and_signed_native_value_rules(self):
  for alias,value in [('CUT',101),('CUT',-1),('PCPIX',0),('IPT',-1)]:
   with self.subTest(alias=alias,value=value),self.assertRaises(ValueError):self.rows(alias,values=[('2017:11',[value,value]),('2017:12',[value,value]),('2018:01',[None,value])])
  rows,_=self.rows('CUT',values=[('2017:11',[0,0]),('2017:12',[0,0]),('2018:01',[None,0])]);self.assertEqual(rows[0]['value'],0)
 def test_no_future_fill_or_fake_publication(self):
  rows,_=self.rows(values=[('2017:11',[100,200]),('2017:12',[101,201]),('2018:01',[None,None])])
  self.assertEqual(v.asof_rows(rows,'2018-02-01T04:59:59Z'),[])
  first=v.asof_rows(rows,'2018-02-01T05:00:00Z')
  self.assertEqual([r['value'] for r in first],[100,101])
  last=v.asof_rows(rows,'2018-03-01T05:00:00Z')
  self.assertIsNone(last[-1]['value']);self.assertTrue(all(r['published_at'] is None for r in last))
 def test_nonmonthly_duplicate_and_grid_refuse(self):
  for args in [dict(labels=('IPT18M1','IPT18M1')),dict(labels=('IPT18M2','IPT18M1')),dict(labels=('IPT18Q1','IPT18Q2')),dict(values=[('2017:11',[1,1]),('2018:01',[1,1])])]:
   with self.subTest(args=args),self.assertRaises(ValueError):self.rows('IPT',**args)
 def test_untrusted_workbook_structure_refuses(self):
  for args in [dict(formula=True),dict(external=True),dict(extra={'../outside.xml':b'x'})]:
   with self.subTest(args=args),self.assertRaises(ValueError):self.rows(**args)
 def test_tail_and_original_replay_idempotence(self):
  docs=b'SYNTHETIC method';rights=b'SYNTHETIC research notice, no supplier permission'
  feeds={k:(*spec[:4],digest(docs)) for k,spec in v.FEEDS.items()}
  with patch.dict(v.FEEDS,feeds),tempfile.TemporaryDirectory() as tmp:
   raw=workbook('IPT',('IPT18M1','IPT18M2'))
   kwargs=dict(collected_at='2018-03-02T00:00:00Z',documentation_raw=docs,rights_raw=rights)
   a=v.store_capture(tmp,raw,'rtdsm_ext_ipt',**kwargs);b=v.store_capture(tmp,raw,'rtdsm_ext_ipt',**kwargs)
   self.assertEqual(a,b)
   rows,meta=v.read_generation(v.PreparedReader(tmp),a['generation_sha256'],cutoff='2018-03-02T00:00:00Z')
   self.assertEqual(meta['schema'],'a4-rtdsm-extension-bundle-v1')
   self.assertEqual(meta['legacy_codec_sha256'],v.LOADED_LEGACY_CODEC_SHA256)
   self.assertEqual(len(rows),5)
   obj=Path(tmp)/'objects'/meta['original_sha256'];obj.write_bytes(b'tampered')
   with self.assertRaises(ValueError):v.read_generation(v.PreparedReader(tmp),a['generation_sha256'],cutoff='2018-03-02T00:00:00Z')
 def test_decoded_budget_is_enforced_in_reader_and_writer(self):
  rows,_=self.rows()
  with patch.object(v,'MAX_DECODED',10),self.assertRaisesRegex(ValueError,'DECODED_BUDGET'):list(v._normalized_lines(rows))
 def test_legacy_or_new_code_tamper_is_refused(self):
  with patch.object(v,'LOADED_LEGACY_CODEC_SHA256','0'*64),self.assertRaisesRegex(ValueError,'LOADED_CODE_CHANGED'):self.rows()
  with patch.object(v,'LOADED_NORMALIZER_SHA256','0'*64),self.assertRaisesRegex(ValueError,'LOADED_CODE_CHANGED'):self.rows()

 def test_hash_bound_code_keeps_exact_bytes_after_autocrlf_checkout(self):
  import subprocess
  names=('tools/a4_rtdsm_extension.py','tools/collect_a4_primary_data.py','tools/a4_data_center.py','tools/a4_rtdsm_sources.py','tools/a4_primary_sources.py')
  attributes=(ROOT/'.gitattributes').read_text(encoding='utf8')
  for name in names:self.assertEqual(attributes.splitlines().count(name+' text eol=lf'),1)
  with tempfile.TemporaryDirectory() as tmp:
   repository=Path(tmp)/'fixture';checkout=Path(tmp)/'checkout';repository.mkdir();checkout.mkdir()
   run=lambda *args:subprocess.run(['git','-c','core.autocrlf=true',*args],cwd=repository,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   run('init','--quiet')
   (repository/'.gitattributes').write_text('\n'.join(name+' text eol=lf' for name in names)+'\n',encoding='utf8')
   expected={}
   for name in names:
    body=(ROOT/name).read_bytes();expected[name]=digest(body);path=repository/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
   run('add','--','.gitattributes',*names)
   run('checkout-index','--all','--force','--prefix='+checkout.as_posix()+'/')
   self.assertEqual({name:digest((checkout/name).read_bytes()) for name in names},expected)

class CollectorChecks(unittest.TestCase):
 def setUp(self):
  self.docs=b'SYNTHETIC method, not provider evidence';self.rights=b'SYNTHETIC rights notice, not permission'
  self.feeds=patch.dict(v.FEEDS,{k:(*s[:4],digest(self.docs)) for k,s in v.FEEDS.items()});self.feeds.start();self.addCleanup(self.feeds.stop)
  prior=sys.modules.get('tools.a4_rtdsm_extension');sys.modules['tools.a4_rtdsm_extension']=v
  def restore_module():
   if prior is None:sys.modules.pop('tools.a4_rtdsm_extension',None)
   else:sys.modules['tools.a4_rtdsm_extension']=prior
  self.addCleanup(restore_module)
  spec=importlib.util.spec_from_file_location('collector_extension_candidate',P.with_name('collect_a4_primary_data.py'))
  self.c=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.c)
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.material=self.root/'materials';(self.material/'objects').mkdir(parents=True)
  for raw in (self.docs,self.rights):(self.material/'objects'/digest(raw)).write_bytes(raw)
  self.recipe=dict(schema='a4-rtdsm-extension-capture-recipe-v1',feeds=list(v.FEEDS),start='2018-01-01',through='2018-02-01',rights_notice_sha256=digest(self.rights),normalizer_sha256=v.LOADED_NORMALIZER_SHA256,legacy_codec_sha256=v.LOADED_LEGACY_CODEC_SHA256,shared_codec_sha256=v.LOADED_SHARED_CODEC_SHA256,collector_sha256=digest(Path(self.c.__file__).read_bytes().replace(b'\r\n',b'\n')),reuse_generations={})
  self.calls=[]
 def fetch(self,uri,limit):
  self.calls.append(uri);self.assertIn(uri,[v.source_uri(f) for f in v.FEEDS]);self.assertEqual(limit,v.MAX_RAW)
  alias=next(s[0] for f,s in v.FEEDS.items() if v.source_uri(f)==uri)
  return workbook(alias,(alias+'18M1',alias+'18M2'),values=[('2017:11',[80,81]),('2017:12',[82,83]),('2018:01',[None,84])])
 def collect(self,name='attempt',**kwargs):
  raw=encoded(self.recipe)
  return self.c.collect_rtdsm_extension(self.root/name,code_sha='0'*40,recipe_raw=raw,expected_recipe_sha256=digest(raw),material_root=self.material,fetcher=kwargs.pop('fetcher',self.fetch),**kwargs)
 def test_closed_capture_clocks_and_no_native_consumer(self):
  result=self.collect();self.assertEqual(result['status'],'LOCAL_EXTENSION_RESEARCH_CAPTURE_COMPLETE');self.assertEqual(result['provider_requests'],3)
  self.assertEqual(result['failures'],[]);self.assertEqual(result['not_run_feeds'],[])
  for feed in v.FEEDS:
   ref=json.loads((self.root/'attempt/capture_receipts'/(feed+'.json')).read_bytes())
   self.assertEqual(ref['source_uri'],v.source_uri(feed));self.assertLessEqual(v.p.clock(ref['request_started_at']),v.p.clock(ref['body_completed_at']))
  self.assertEqual(len(result['generation_sha256s']),3)
  for key in (*v.SAFETY,'a3_executed','a5_executed','model_fit_performed'):self.assertFalse(result[key])
 def test_invalid_recipe_or_material_never_requests(self):
  self.recipe['feeds']=['not-registered']
  with self.assertRaisesRegex(ValueError,'CLOSED_RECIPE'):self.collect()
  self.assertEqual(self.calls,[])
  self.recipe['feeds']=list(v.FEEDS);(self.material/'objects'/digest(self.docs)).write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'MATERIAL_HASH'):self.collect()
  self.assertEqual(self.calls,[])
 def test_code_pin_refuses_before_request(self):
  self.recipe['collector_sha256']='0'*64
  with self.assertRaisesRegex(ValueError,'RECIPE_CODE'):self.collect()
  self.assertEqual(self.calls,[])
 def test_failed_workbook_body_and_capture_clock_are_retained(self):
  result=self.collect(fetcher=lambda *_:b'not a workbook')
  self.assertEqual(result['status'],'BLOCKED_EXTENSION_CAPTURE');self.assertEqual(result['provider_requests'],1)
  self.assertTrue((self.root/'attempt/returned_originals'/digest(b'not a workbook')).is_file())
  self.assertEqual(len(list((self.root/'attempt/capture_receipts').iterdir())),1)
  self.assertEqual(len(result['not_run_feeds']),2);self.assertEqual(result['publication'],[])
 def test_http_failure_stops_without_retry_or_old_fallback(self):
  from urllib.error import HTTPError
  def fail(uri,limit):self.calls.append(uri);raise HTTPError(uri,429,'quota',None,None)
  result=self.collect(fetcher=fail)
  self.assertEqual(result['failures'][0]['http_status'],429);self.assertEqual(len(self.calls),1)
  self.assertEqual(result['generation_sha256s'],[]);self.assertEqual(result['provider_retries'],0)
 def test_time_budget_retains_returned_body_and_stops(self):
  clock=[1.]
  def late(uri,limit):
   raw=self.fetch(uri,limit);clock[0]=1000.;return raw
  with patch('time.monotonic',side_effect=lambda:clock[0]):result=self.collect(fetcher=late)
  self.assertEqual(result['status'],'BLOCKED_EXTENSION_CAPTURE');self.assertEqual(result['provider_requests'],1)
  self.assertEqual(len(list((self.root/'attempt/returned_originals').iterdir())),1)
 def test_explicit_resume_replays_without_new_provider_requests(self):
  original=self.collect();self.calls.clear()
  self.recipe['reuse_generations']={x['feed']:x['generation_sha256'] for x in original['captures']}
  result=self.collect('resume',reuse_archive_root=self.root/'attempt/archive',fetcher=lambda *_:self.fail('resume must not call provider'))
  self.assertEqual(result['provider_requests'],0);self.assertEqual(result['generation_sha256s'],original['generation_sha256s'])
  self.assertTrue(all(x['reused'] for x in result['captures']))
 def test_broken_resume_and_reused_attempt_fail_before_request(self):
  original=self.collect();self.calls.clear()
  with self.assertRaises(ValueError):self.collect()
  self.assertEqual(self.calls,[])
  self.recipe['reuse_generations']={next(iter(v.FEEDS)):'0'*64}
  with self.assertRaises((ValueError,OSError)):self.collect('resume',reuse_archive_root=self.root/'attempt/archive')
  self.assertEqual(self.calls,[])
 def test_local_publication_is_never_drive_verified(self):
  from tools.macro_research_checkpoint import LocalTransport
  result=self.collect(transport=LocalTransport(self.root/'durable'))
  self.assertEqual(result['status'],'LOCAL_EXTENSION_TRANSPORT_CHECKED')
  self.assertTrue(all(x['transport_readback_verified'] is False for x in result['publication']))
 def test_execution_readback_failure_has_separate_witness(self):
  class Broken:
   remote_verified=True
   def write(self,*args):raise ValueError('synthetic failure')
  with self.assertRaisesRegex(ValueError,'EXECUTION_READBACK_FAILED'):self.collect(transport=Broken())
  self.assertTrue((self.root/'attempt/execution.json').is_file())
  self.assertTrue((self.root/'attempt/publication_failed.json').is_file())


class DataCenterChecks(unittest.TestCase):
 fetch=CollectorChecks.fetch
 collect=CollectorChecks.collect
 def setUp(self):
  CollectorChecks.setUp(self)
  spec=importlib.util.spec_from_file_location('data_center_extension_candidate',P.with_name('a4_data_center.py'))
  self.center=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.center)
 def test_typed_context_is_separate_and_replays_originals(self):
  result=self.collect();refs=[dict(root=self.root/'attempt/archive',generation_sha256=x,execution_sha256=digest(encoded(result))) for x in result['generation_sha256s']]
  items,audit,n=self.center.extension_vintage_context(refs,v.p.now(),budget={'bytes':0})
  self.assertEqual(len(items),3);self.assertEqual(audit,[]);self.assertEqual(n,15)
  self.assertTrue(all(x['status']=='VERIFIED_EXTENSION_DATED_VINTAGE_RESEARCH_ONLY' for x in items))
  self.assertTrue(all(not x['source_admitted'] and not x['training_admitted'] and not x['historical_pit_certified'] for x in items))
  with self.assertRaisesRegex(ValueError,'VINTAGE_SCHEMA'):self.center.vintage_context([{k:r[k] for k in ('root','generation_sha256')} for r in refs],v.p.now(),budget={'bytes':0})
 def test_shared_byte_budget_and_duplicate_reference_refuse(self):
  result=self.collect();ref=dict(root=self.root/'attempt/archive',generation_sha256=result['generation_sha256s'][0],execution_sha256=digest(encoded(result)))
  budget={'bytes':self.center.MAX_BYTES-1}
  with self.assertRaisesRegex(ValueError,'ARCHIVE_UNAVAILABLE'):self.center.extension_vintage_context([ref],v.p.now(),budget=budget)
  self.assertGreater(budget['bytes'],self.center.MAX_BYTES)
  with self.assertRaisesRegex(ValueError,'DUPLICATE_VINTAGE'):self.center.extension_vintage_context([ref,ref],v.p.now(),budget={'bytes':0})
 def test_future_capture_excluded_and_broken_latest_never_falls_back(self):
  result=self.collect();pin=result['generation_sha256s'][0];root=self.root/'attempt/archive'
  original=json.loads((root/'generations'/(pin+'.json')).read_bytes())
  later=dict(original,collected_at='2030-01-01T00:00:00Z');body=encoded(later);new=digest(body)
  (root/'generations'/(new+'.json')).write_bytes(body)
  refs=[dict(root=root,generation_sha256=x,execution_sha256=digest(encoded(result))) for x in (pin,new)]
  items,audit,n=self.center.extension_vintage_context(refs,v.p.now(),budget={'bytes':0})
  self.assertEqual(len(items),1);self.assertEqual(len(audit),1);self.assertEqual(n,5)
  with self.assertRaises(ValueError):self.center.extension_vintage_context(refs,'2031-01-01T00:00:00Z',budget={'bytes':0})
 def test_combined_capture_cap_refuses_before_output_creation(self):
  expected={Path(self.center.__file__).name:self.center.LOADED_INDEX_SHA256}
  for legacy,extra in (([{}]*3,[{}]*6),([],False)):
   with patch.object(self.center,'index_identity',return_value=expected):
    with self.assertRaisesRegex(ValueError,'COMBINED_VINTAGE_BUDGET'):
     self.center.build([dict(root=self.root,execution_sha256='0'*64)],cutoff=v.p.now(),output_dir=self.root/'must-not-exist',vintage_references=legacy,extension_vintage_references=extra)
   self.assertFalse((self.root/'must-not-exist').exists())


 def test_failed_component_execution_cannot_admit_partial_generations(self):
  from urllib.error import HTTPError
  def partial(uri,limit):
   if len(self.calls)==2:
    self.calls.append(uri);raise HTTPError(uri,429,'quota',None,None)
   return self.fetch(uri,limit)
  result=self.collect(fetcher=partial)
  self.assertEqual(len(result['generation_sha256s']),2)
  refs=[dict(root=self.root/'attempt/archive',generation_sha256=result['generation_sha256s'][0],execution_sha256=digest(encoded(result)))]
  with self.assertRaisesRegex(ValueError,'EXTENSION_EXECUTION_BINDING'):self.center.extension_vintage_context(refs,v.p.now(),budget={'bytes':0})


 def bound_ref(self,result):
  body=encoded(result);pin=digest(body);root=self.root/'attempt/archive'
  (root/'executions'/(pin+'.json')).write_bytes(body)
  return dict(root=root,generation_sha256=result['generation_sha256s'][0],execution_sha256=pin)
 def test_repeated_generation_and_wrong_capture_feed_refuse(self):
  import copy
  result=self.collect()
  changes=[dict(generation_sha256s=[result['generation_sha256s'][0]]*3),
   dict(captures=[dict(x,feed='rtdsm_ext_pcpix') for x in result['captures']])]
  for change in changes:
   altered=copy.deepcopy(result);altered.update(change)
   with self.assertRaisesRegex(ValueError,'EXTENSION_CAPTURE_BINDING'):
    self.center.extension_vintage_context([self.bound_ref(altered)],v.p.now(),budget={'bytes':0})
 def test_recipe_original_is_required_and_rebound_semantic_change_refuses(self):
  import copy
  result=self.collect();root=self.root/'attempt/archive';recipe_path=root/'objects'/result['recipe_sha256']
  original=recipe_path.read_bytes();recipe_path.unlink()
  with self.assertRaisesRegex(ValueError,'ARCHIVE_UNAVAILABLE'):
   self.center.extension_vintage_context([self.bound_ref(result)],v.p.now(),budget={'bytes':0})
  recipe_path.write_bytes(original)
  for change in ({'start':'2017-01-01'},{'rights_notice_sha256':'0'*64},{'normalizer_sha256':'0'*64},{'collector_sha256':'0'*64},
                 {'reuse_generations':{result['captures'][0]['feed']:result['generation_sha256s'][0]}}):
   changed=json.loads(original);changed.update(change);body=encoded(changed);pin=digest(body)
   (root/'objects'/pin).write_bytes(body);altered=copy.deepcopy(result);altered['recipe_sha256']=pin
   with self.subTest(change=change),self.assertRaisesRegex(ValueError,'EXTENSION_RECIPE_BINDING'):
    self.center.extension_vintage_context([self.bound_ref(altered)],v.p.now(),budget={'bytes':0})
 def test_publication_status_and_transport_evidence_cannot_disagree(self):
  import copy
  result=self.collect()
  publication=[dict(generation_sha256=x,observations=5,transport_readback_verified=False,**v.SAFETY) for x in result['generation_sha256s']]
  for change in (dict(status='DURABLE_EXTENSION_RESEARCH_CAPTURE_COMPLETE',publication=publication),
                 dict(publication=publication)):
   altered=copy.deepcopy(result);altered.update(change)
   with self.assertRaisesRegex(ValueError,'EXTENSION_PUBLICATION_BINDING'):
    self.center.extension_vintage_context([self.bound_ref(altered)],v.p.now(),budget={'bytes':0})
 def test_successful_local_transport_remains_unverified_remote(self):
  from tools.macro_research_checkpoint import LocalTransport
  result=self.collect(transport=LocalTransport(self.root/'durable'))
  ref=self.bound_ref(result)
  items,audit,n=self.center.extension_vintage_context([ref],v.p.now(),budget={'bytes':0})
  self.assertEqual((len(items),n),(1,5));self.assertFalse(items[0]['original_pairs_remote_verified'])
 def test_changed_loaded_producer_refuses_before_archive_reads(self):
  result=self.collect();ref=self.bound_ref(result);budget={'bytes':0}
  changed=self.root/'changed-producer.py';changed.write_bytes(b'SYNTHETIC changed producer bytes')
  with patch.object(self.center.collector,'__file__',str(changed)):
   with self.assertRaisesRegex(ValueError,'LOADED_COLLECTOR_CHANGED'):
    self.center.extension_vintage_context([ref],v.p.now(),budget=budget)
  self.assertEqual(budget['bytes'],0)
 def test_accepted_state_write_flag_refuses(self):
  result=self.collect();result['accepted_state_written']=True
  with self.assertRaisesRegex(ValueError,'EXTENSION_EXECUTION_BINDING'):
   self.center.extension_vintage_context([self.bound_ref(result)],v.p.now(),budget={'bytes':0})
 def test_recipe_object_is_published_before_any_generation(self):
  from tools.macro_research_checkpoint import LocalTransport
  class Recording(LocalTransport):
   def __init__(self,root):super().__init__(root);self.writes=[]
   def write(self,path,body):self.writes.append((path,body));return super().write(path,body)
  transport=Recording(self.root/'durable');result=self.collect(transport=transport)
  paths=[x[0] for x in transport.writes];recipe_path=v.p.PREFIX+'/objects/'+result['recipe_sha256']
  self.assertIn(recipe_path,paths)
  self.assertLess(paths.index(recipe_path),min(i for i,x in enumerate(paths) if '/generations/' in x))
  self.assertEqual(transport.writes[paths.index(recipe_path)][1],encoded(self.recipe))


 def test_offline_replay_cannot_claim_verified_collection_without_body_clock(self):
  result=self.collect();root=self.root/'attempt/archive';pins=[];captures=[]
  for feed in v.FEEDS:
   alias=v.FEEDS[feed][0]
   raw=workbook(alias,(alias+'18M1',alias+'18M2'),values=[('2017:11',[80,81]),('2017:12',[82,83]),('2018:01',[None,84])])
   offline=v.store_capture(root,raw,feed,collected_at=result['cutoff'],start=self.recipe['start'],through=self.recipe['through'],documentation_raw=self.docs,rights_raw=self.rights)
   pin=offline['generation_sha256'];rows,meta=v.read_generation(v.PreparedReader(root),pin,cutoff=v.p.now())
   self.assertEqual(len(rows),5);self.assertIsNone(meta['capture_ref'])
   self.assertEqual(meta['capture_clock_precision'],'CALLER_SUPPLIED_OFFLINE_CLOCK')
   pins.append(pin);captures.append(dict(feed=feed,generation_sha256=pin,reused=False))
  result['generation_sha256s']=pins;result['captures']=captures
  with self.assertRaisesRegex(ValueError,'EXTENSION_CAPTURE_CLOCK_REQUIRED'):
   self.center.extension_vintage_context([self.bound_ref(result)],v.p.now(),budget={'bytes':0})

if __name__=='__main__':unittest.main()
