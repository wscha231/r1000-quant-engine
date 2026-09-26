import copy, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.sovereign_fiscal_v1.contracts import (ContractError,contract_hashes,next_day_available,registry,validate_registry,validate_row,validate_vintage_chain)

RAW='a'*64; PUB='b'*64; ROW='c'*64

def contract(cid):
    return next(x for x in registry()['source_contracts'] if x['source_contract_id']==cid)

def base_row(c, **kw):
    exact=c['pit_class']=='HISTORICAL_EXACT_PIT'
    blocked=c['pit_class']=='HISTORICAL_BLOCKED'
    derived=c['pit_class']=='DERIVED_AFTER_PIT_INPUTS'
    pub='2026-09-24T16:00:00-04:00' if exact else ('2026-09-24' if not derived and not blocked else None)
    avail=pub if exact else (next_day_available('2026-09-24',c['source_timezone']) if c['pit_class']=='HISTORICAL_DATE_PIT' else ('2026-09-25T12:00:00+00:00' if not blocked else None))
    row=dict(series_id=c['source_contract_id'],perimeter=c['perimeter'],observation_date_or_period='2026-08',published_at_source=pub,published_at_precision=c['publication_precision'],public_available_at=avail,decision_available_at=avail,revision_status='FIRST_RELEASE',vintage_id='v1',supersedes_vintage_id=None,estimate_type='OBSERVED',methodology_version='v1',unit='PERCENT',currency='USD' if c['country']=='USA' else 'CNY',frequency=c['frequency'],value=1.0,raw_sha256=RAW,parsed_row_sha256=ROW,data_quality='ACCEPTED',pit_class=c['pit_class'],reconstructed_from_release_archive=False,publication_metadata_sha256=PUB)
    row.update(kw); return row

class Contracts(unittest.TestCase):
    def test_registry(self):
        r=validate_registry(); self.assertGreaterEqual(len(r['source_contracts']),33)
        h=contract_hashes(); self.assertEqual(len(h['registry_sha256']),64); self.assertEqual(len(h['schema_sha256']),64)
    def test_positive_exact_tic(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); validate_row(c,base_row(c))
    def test_positive_date_treasury(self):
        c=contract('US_DEBT_HELD_PUBLIC_DAILY'); r=base_row(c); self.assertIn('2026-09-25T00:00:00',r['public_available_at']); validate_row(c,r)
    def test_positive_nbs(self): validate_row(contract('CN_NBS_NOMINAL_REAL_GDP'),base_row(contract('CN_NBS_NOMINAL_REAL_GDP')))
    def test_positive_pboc_methodology(self): validate_row(contract('CN_PBOC_TSF'),base_row(contract('CN_PBOC_TSF'),methodology_version='2023-perimeter-v1'))
    def test_positive_safe_revision_chain(self):
        c=contract('CN_SAFE_CURRENT_ACCOUNT'); a=base_row(c,vintage_id='prelim',revision_status='PRELIMINARY'); b=base_row(c,vintage_id='rev',revision_status='REVISED',supersedes_vintage_id='prelim'); validate_vintage_chain([a,b])
    def test_positive_imf_staff_estimate(self):
        c=contract('CN_IMF_AUGMENTED_DEBT'); r=base_row(c,revision_status='STAFF_ESTIMATE',estimate_type='STAFF_ESTIMATE'); validate_row(c,r)
    def test_positive_acm_forward_only(self): validate_row(contract('US_ACM_TERM_PREMIUM'),base_row(contract('US_ACM_TERM_PREMIUM')))
    def test_negative_worldbank_current_as_pit(self):
        r=copy.deepcopy(registry()); c=copy.deepcopy(r['source_contracts'][0]); c['source_contract_id']='BAD_WB'; c['source_authority']='World Bank current API'; c['pit_class']='HISTORICAL_EXACT_PIT'; c['publication_precision']='COLLECTION_TIMESTAMP'; c['availability_rule']='FIRST_SUCCESSFUL_COLLECTION'; r['source_contracts'].append(c)
        with self.assertRaises(ContractError): validate_registry(r)
    def test_negative_imf_marked_official(self):
        r=copy.deepcopy(registry()); c=next(x for x in r['source_contracts'] if x['source_contract_id']=='CN_IMF_AUGMENTED_DEBT'); c['perimeter']='CN_OFFICIAL_LOCAL_EXPLICIT'
        with self.assertRaises(ContractError): validate_registry(r)
    def test_negative_date_same_day(self):
        c=contract('US_DEBT_HELD_PUBLIC_DAILY'); r=base_row(c,public_available_at='2026-09-24T00:00:00-04:00',decision_available_at='2026-09-24T00:00:00-04:00')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_acm_historical(self):
        r=copy.deepcopy(registry()); c=next(x for x in r['source_contracts'] if x['source_contract_id']=='US_ACM_TERM_PREMIUM'); c['pit_class']='HISTORICAL_EXACT_PIT'; c['publication_precision']='EXACT_TIMESTAMP'; c['availability_rule']='OFFICIAL_TIMESTAMP'
        with self.assertRaises(ContractError): validate_registry(r)
    def test_negative_lgfv_interpolation(self):
        c=contract('CN_LGFV_MONTHLY_HIDDEN_DEBT'); r=base_row(c,decision_available_at='2026-09-25T00:00:00+08:00')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_vintage_overwrite(self):
        c=contract('CN_SAFE_CURRENT_ACCOUNT'); a=base_row(c,vintage_id='same'); b=base_row(c,vintage_id='same',revision_status='REVISED')
        with self.assertRaises(ContractError): validate_vintage_chain([a,b])
    def test_negative_missing_publication_metadata(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c,reconstructed_from_release_archive=True,publication_metadata_sha256='')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_unknown_unit(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c,unit='UNKNOWN')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_forbidden_buy_field(self):
        r=copy.deepcopy(registry()); r['source_contracts'][0]['BUY']=True
        with self.assertRaises(ContractError): validate_registry(r)
    def test_negative_exact_public_before_publication(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c,public_available_at='2026-09-24T15:59:59-04:00',decision_available_at='2026-09-24T15:59:59-04:00')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_decision_before_public(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c,decision_available_at='2026-09-24T15:59:59-04:00')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_series_identity(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c,series_id='US_NOMINAL_GDP')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_frequency_identity(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c,frequency='DAILY')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_future_decision_cutoff(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c)
        with self.assertRaises(ContractError): validate_row(c,r,decision_cutoff='2026-09-24T15:59:59-04:00')
    def test_negative_current_vintage_reconstruction(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c,reconstructed_from_release_archive=True,revision_status='CURRENT_VINTAGE')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_staff_estimate_official_perimeter(self):
        c=contract('CN_MOF_LOCAL_DEBT_BALANCE'); r=base_row(c,revision_status='STAFF_ESTIMATE',estimate_type='STAFF_ESTIMATE')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_projection_as_observed(self):
        c=contract('US_CBO_FISCAL_BASELINE'); r=base_row(c,revision_status='PROJECTION',estimate_type='OBSERVED')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_bad_raw_hash(self):
        c=contract('US_TIC_FOREIGN_DEMAND'); r=base_row(c,raw_sha256='bad')
        with self.assertRaises(ContractError): validate_row(c,r)
    def test_negative_missing_timezone_contract(self):
        r=copy.deepcopy(registry()); r['source_contracts'][0]['source_timezone']=''
        with self.assertRaises(ContractError): validate_registry(r)
    def test_negative_expected_direction(self):
        r=copy.deepcopy(registry()); r['source_contracts'][0]['EXPECTED_DIRECTION']='TAILWIND'
        with self.assertRaises(ContractError): validate_registry(r)

if __name__=='__main__': unittest.main()
