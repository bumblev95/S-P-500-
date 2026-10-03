"""Real SEC fixtures plus adversarial chronology/identity/collection regressions."""
import copy
import json
import math
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import build_research_inputs as sec
import sec_fallbacks as policy
from import_sec_companyfacts import ingest, validated
from audit_sec_coverage import sources, audit, FOLDER


def row(value, year=2022, accession=None, filed=None):
    return dict(val=value, start=f'{year}-01-01', end=f'{year}-12-31',
                filed=filed or f'{year+1}-02-01', form='10-K', accn=accession or str(year))


def payload(cik=1535527, tag=policy.INCLUDING_TAX):
    return dict(cik=cik, facts={'us-gaap':{tag:{'units':{'USD':[row(100,2021),row(120)]}}}})


def bank(cik=35527):
    return dict(cik=cik, facts={'us-gaap':{
        'InterestIncomeExpenseNet':{'units':{'USD':[row(60,2021),row(72)]}},
        'NoninterestIncome':{'units':{'USD':[row(40,2021),row(48)]}},
        'NetIncomeLoss':{'units':{'USD':[row(10,2021),row(12)]}}}})


def root_at(tmp, members):
    root=Path(tmp);(root/'research/source-cache').mkdir(parents=True)
    (root/'research/universe.json').write_text(json.dumps({'members':{s:{'cik':c} for s,c in members.items()}}))
    return root


class ReviewedFacts(unittest.TestCase):
    def test_including_tax_is_issuer_scoped_and_legacy_tags_are_unchanged(self):
        self.assertNotIn(policy.INCLUDING_TAX,sec.TAGS['revenue'])
        self.assertEqual(sec.financial_history(payload(cik=1)),[])
        self.assertEqual(sec.financial_history(payload(cik=35527)),[])
        rows=sec.financial_history(payload())
        self.assertAlmostEqual(rows[-1]['revenueGrowth'],.2)
        self.assertEqual(rows[-1]['fallbacks'],['standard_revenue_tag'])
        self.assertEqual(rows[-1]['evidence'][0]['sourceCIK'],1535527)

    def test_primary_revenue_precedes_fallback_on_same_period(self):
        p=payload();p['facts']['us-gaap']['Revenues']={'units':{'USD':[row(10,2021),row(30)]}}
        rows=sec.financial_history(p)
        self.assertEqual(rows[-1]['revenueGrowth'],2)
        self.assertNotIn('fallbacks',rows[-1])

    def test_annual_usd_standard_only(self):
        for mutation in ('quarter','ytd','form','currency','custom','future_end','boolean','nonfinite'):
            with self.subTest(mutation=mutation):
                p=payload();v=p['facts']['us-gaap'][policy.INCLUDING_TAX];r=v['units']['USD']
                if mutation=='quarter':
                    for x in r:x['end']=x['start'][:4]+'-03-31'
                if mutation=='ytd':
                    for x in r:x['end']=x['start'][:4]+'-09-30'
                if mutation=='form':
                    for x in r:x['form']='8-K'
                if mutation=='currency':v['units']['EUR']=v['units'].pop('USD')
                if mutation=='custom':p['facts']['custom']=p['facts'].pop('us-gaap')
                if mutation=='future_end':
                    for x in r:x['filed']=x['start']
                if mutation=='boolean':
                    for x in r:x['val']=True
                if mutation=='nonfinite':
                    for x in r:x['val']=float('inf')
                self.assertEqual(sec.financial_history(p),[])

    def test_bank_components_are_exact_and_evidenced(self):
        r=sec.financial_history(bank())[-1]
        self.assertAlmostEqual(r['revenueGrowth'],.2)
        self.assertAlmostEqual(r['netMargin'],.1)
        self.assertEqual(r['revenueBasis'],policy.BANK_BASIS)
        self.assertEqual({e['tag'] for e in r['evidence']},{*policy.BANK_TAGS,'NetIncomeLoss'})
        self.assertTrue(all(e['sourceCIK']==35527 for e in r['evidence']))

    def test_bank_cannot_join_different_filings_periods_or_conflicting_values(self):
        for mutation in ('accession','start','end','filed','form','missing','conflict'):
            with self.subTest(mutation=mutation):
                p=bank();other=p['facts']['us-gaap']['NoninterestIncome']['units']['USD']
                if mutation=='missing':other.clear()
                elif mutation=='conflict':other.extend([dict(x,val=x['val']+1) for x in list(other)])
                else:
                    key={'accession':'accn'}.get(mutation,mutation)
                    for x in other:x[key]={'accession':'other','start':x['start'][:4]+'-01-02',
                        'end':x['end'][:4]+'-12-30','filed':x['filed'][:4]+'-03-01','form':'10-K/A'}[mutation]
                self.assertEqual(sec.financial_history(p),[])

    def test_bank_never_substitutes_gross_interest_or_partial_customer_revenue(self):
        p=bank();p['facts']['us-gaap'].pop('InterestIncomeExpenseNet')
        p['facts']['us-gaap']['InterestAndDividendIncomeOperating']={'units':{'USD':[row(99)]}}
        p['facts']['us-gaap'][policy.INCLUDING_TAX]={'units':{'USD':[row(3)]}}
        self.assertEqual(sec.financial_history(p),[])
        self.assertEqual(sec.financial_history(bank(1601712)),[])

    def test_reported_negative_noninterest_income_is_not_imputed_or_clipped(self):
        p=bank();p['facts']['us-gaap']['NoninterestIncome']['units']['USD'][-1]['val']=-2
        r=sec.financial_history(p)[-1]
        self.assertAlmostEqual(r['netMargin'],12/70)
        self.assertTrue(any(e['value']==-2 for e in r['evidence']))

    def test_fallbacks_retain_strict_filing_lag_age_and_restatement_vintages(self):
        for p in (payload(),bank()):
            with self.subTest(cik=p['cik']):
                before=sec.financial_history(p)
                self.assertTrue(math.isnan(sec.stock_before(before,'2023-02-01')[0][0]))
                self.assertAlmostEqual(sec.stock_before(before,'2023-02-02')[0][0],.2)
                self.assertTrue(math.isnan(sec.stock_before(before,'2026-01-01')[0][0]))
                tag=policy.INCLUDING_TAX if p['cik']==1535527 else 'InterestIncomeExpenseNet'
                p['facts']['us-gaap'][tag]['units']['USD'].append(row(1e12,filed='2024-02-01'))
                after=sec.financial_history(p)
                a,ad=sec.stock_before(before,'2023-02-02');b,bd=sec.stock_before(after,'2023-02-02')
                self.assertEqual(ad,bd)
                self.assertTrue(all(x==y or (math.isnan(x) and math.isnan(y)) for x,y in zip(a,b)))
                self.assertEqual(before,sec.financial_history(p,as_of='2023-02-02'))

    def test_growth_never_crosses_revenue_tags(self):
        p=payload();p['facts']['us-gaap'][policy.INCLUDING_TAX]['units']['USD'].pop(0)
        p['facts']['us-gaap']['Revenues']={'units':{'USD':[row(100,2021)]}}
        self.assertIsNone(sec.financial_history(p)[-1]['revenueGrowth'])

    def test_cik_decimal_strings_are_exact_and_other_types_rejected(self):
        self.assertEqual(policy.parse_cik('0001535527'),1535527)
        self.assertEqual(validated(json.dumps(payload(cik='1535527')))[0],1535527)
        for value in (True,1535527.0,'1.0','-1','1e3',' 1535527',None,0):
            with self.subTest(value=value),self.assertRaises(ValueError):policy.parse_cik(value)

    def test_unreviewed_or_wrong_predecessor_is_rejected(self):
        for p,other in ((payload(),payload(34088,'Revenues')),
                        (payload(2115436,'Revenues'),payload(1,'Revenues'))):
            with self.assertRaises(ValueError):sec.financial_history(p,other)

    def test_predecessor_waits_for_mapping_and_rejects_post_conversion_revisions(self):
        current={'cik':'2115436','facts':{}}
        old=payload(34088,'Revenues')
        for r in old['facts']['us-gaap']['Revenues']['units']['USD']:
            r.update(start=r['start'].replace('2021','2024').replace('2022','2025'),
                     end=r['end'].replace('2021','2024').replace('2022','2025'),
                     filed=r['filed'].replace('2022','2025').replace('2023','2026'))
        before=sec.financial_history(current,old)
        self.assertEqual(before[0]['availableDate'],'2026-07-01')
        self.assertTrue(all(math.isnan(v) for v in sec.stock_before(before,'2026-07-01')[0]))
        self.assertAlmostEqual(sec.stock_before(before,'2026-07-02')[0][0],.2)
        old['facts']['us-gaap']['Revenues']['units']['USD'].append(
            dict(old['facts']['us-gaap']['Revenues']['units']['USD'][-1],val=1e12,filed='2026-08-01'))
        self.assertEqual(before,sec.financial_history(current,old))
        self.assertEqual(before[0]['mappingEvidence']['sourceCIK'],34088)

    def test_successor_cannot_borrow_predecessor_income_or_growth(self):
        current=payload(2115436,'Revenues');old=payload(34088,'Revenues')
        old['facts']['us-gaap']['NetIncomeLoss']={'units':{'USD':[row(999)]}}
        latest=sec.financial_history(current,old)[-1]
        self.assertIsNone(latest['netMargin'])
        self.assertNotIn('reviewed_predecessor',latest.get('fallbacks',[]))


class CollectionAndImport(unittest.TestCase):
    def test_fresh_empty_history_reprocesses_cache_during_backoff_without_network(self):
        now=datetime(2026,10,1,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=root_at(tmp,{'CRWD':1535527})
            (root/'research/source-cache/CRWD.json').write_text(json.dumps(payload()))
            old=dict(stocks={'CRWD':dict(cik=1535527,rows=[],retrievedAt=now.isoformat())},secBlockedUntil=(now+timedelta(days=1)).isoformat())
            with patch.object(sec,'request') as request,patch.object(sec,'sec_identity'):
                out=sec.collect_sec(old,root,True,now)
            request.assert_not_called()
            self.assertEqual(out['secCoverage']['usableIssuers'],1)
            self.assertEqual(out['secCoverage']['diagnostics']['1535527']['state'],'fallback_applied')
            self.assertEqual(out['stocks']['CRWD']['retrievedAt'],old['stocks']['CRWD']['retrievedAt'])
            self.assertEqual(out['secBlockedUntil'],old['secBlockedUntil'])

    def test_offline_absent_source_does_not_claim_facts_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=root_at(tmp,{'HONA':2089271})
            with patch.object(sec,'request') as request:
                out=sec.collect_sec({},root,False,datetime.now(timezone.utc))
            request.assert_not_called()
            self.assertEqual(out['secCoverage']['diagnostics']['2089271']['reason'],'raw_source_unavailable')

    def test_predecessor_denial_stops_all_further_requests_and_keeps_cooldown(self):
        for code in (401,403,429):
            with self.subTest(code=code),tempfile.TemporaryDirectory() as tmp:
                root=root_at(tmp,{'XOM':2115436,'B':2});now=datetime(2026,10,1,tzinfo=timezone.utc)
                with patch.object(sec,'sec_identity'),patch.object(sec.time,'sleep'),patch.object(sec,'request',
                    side_effect=[{'cik':'2115436','facts':{}},HTTPError('https://data.sec.gov',code,'denied',{},None)]) as request:
                    out=sec.collect_sec({},root,True,now)
                self.assertEqual(request.call_count,2)
                self.assertEqual(out['secCoverage']['status']['2'],'deferred')
                self.assertGreater(out['secBlockedUntil'],now.isoformat())

    def test_bad_refresh_keeps_last_good_history(self):
        now=datetime(2026,10,1,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root=root_at(tmp,{'CRWD':1535527});prior=dict(cik=1535527,rows=sec.financial_history(payload()),retrievedAt='2026-09-01T00:00:00+00:00')
            with patch.object(sec,'sec_identity'),patch.object(sec.time,'sleep'),patch.object(sec,'request',return_value={'cik':1535527,'facts':{}}):
                out=sec.collect_sec({'stocks':{'CRWD':prior}},root,True,now)
            self.assertEqual(out['stocks']['CRWD'],prior)
            self.assertTrue(out['secCoverage']['diagnostics']['1535527']['retainedPreviousHistory'])

    def test_import_updates_coverage_aliases_and_keeps_backoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=root_at(tmp,{'CRWD':1535527,'CRWD.A':1535527})
            (root/'research/inputs.json').write_text(json.dumps({'secBlockedUntil':'2099-01-01T00:00:00+00:00'}))
            p=root/'facts.json';p.write_text(json.dumps(payload(cik='1535527')))
            out=ingest([p],root)
            self.assertEqual(out['secCoverage']['usableIssuers'],1)
            self.assertEqual(out['secCoverage']['usableTickers'],2)
            self.assertEqual(out['secCoverage']['fallbackIssuers'],1)
            self.assertIsNone(out['stocks']['CRWD']['retrievedAt'])
            self.assertEqual(out['secBlockedUntil'],'2099-01-01T00:00:00+00:00')

    def test_future_import_or_unsupported_file_cannot_partially_write(self):
        for bad in (payload(1),payload()):
            with self.subTest(cik=bad['cik']),tempfile.TemporaryDirectory() as tmp:
                root=root_at(tmp,{'CRWD':1535527})
                target=root/'research/inputs.json';target.write_text('{"stocks":{}}');original=target.read_bytes()
                if bad['cik']==1535527:
                    for r in bad['facts']['us-gaap'][policy.INCLUDING_TAX]['units']['USD']:r['filed']='2099-01-01'
                a=root/'a.json';a.write_text(json.dumps(payload()));b=root/'b.json';b.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):ingest([a,b],root)
                self.assertEqual(target.read_bytes(),original)
                self.assertEqual(list((root/'research/source-cache').iterdir()),[])

    def test_shortened_import_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=root_at(tmp,{'CRWD':1535527});p=root/'facts.json';p.write_text(json.dumps(payload()))
            ingest([p],root);before=(root/'research/inputs.json').read_bytes();cached=(root/'research/source-cache/CRWD.json').read_bytes()
            short=payload();short['facts']['us-gaap'][policy.INCLUDING_TAX]['units']['USD'].pop(0)
            p.write_text(json.dumps(short))
            with self.assertRaisesRegex(ValueError,'shorten'):ingest([p],root)
            self.assertEqual((root/'research/inputs.json').read_bytes(),before)
            self.assertEqual((root/'research/source-cache/CRWD.json').read_bytes(),cached)


class PinnedOfficialSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.manifest,cls.payloads=sources()

    def test_twelve_real_cases_and_exact_baseline_coverage_reproduce(self):
        result=audit()
        self.assertEqual(result['baselineCoverage'],dict(targetIssuers=500,usableIssuers=488,targetTickers=503,usableTickers=491))
        self.assertEqual(result['offlineCoverage']['usableIssuers'],497)
        self.assertEqual(result['offlineCoverage']['usableTickers'],500)
        self.assertEqual(result['offlineCoverage']['missingSymbols'],['APA','HONA','SYF'])
        self.assertEqual(result['retainedCoveredTickers'],491)
        self.assertTrue(all(d['baselineAnnualRevenueFacts']==0 for d in result['issuers'].values()))

    def test_full_offline_collector_reprocesses_twelve_without_rewriting_covered_history(self):
        old=self.payloads['baseline-inputs.json'];universe=self.payloads['baseline-universe.json']
        with tempfile.TemporaryDirectory() as tmp:
            root=root_at(tmp,{s:v['cik'] for s,v in universe['members'].items()})
            for symbol in old['secCoverage']['missingSymbols']:
                cik=universe['members'][symbol]['cik']
                (root/'research/source-cache'/f'{symbol}.json').write_text(json.dumps(self.payloads[f'CIK{cik:010d}.json']))
            (root/'research/source-cache/CIK0000034088.json').write_text(json.dumps(self.payloads['CIK0000034088.json']))
            with patch.object(sec,'request') as request:
                out=sec.collect_sec(old,root,False,datetime(2026,10,1,14,tzinfo=timezone.utc))
            request.assert_not_called()
            self.assertEqual(out['secCoverage']['requests'],0)
            self.assertEqual(out['secCoverage']['usableIssuers'],497)
            self.assertEqual(out['secCoverage']['missingSymbols'],['APA','HONA','SYF'])
            for s in universe['members']:
                if s not in old['secCoverage']['missingSymbols']:self.assertEqual(out['stocks'][s],old['stocks'][s])
            self.assertEqual(json.loads((root/'research/inputs.json').read_text()),out)

    def test_successor_collection_requests_only_reviewed_source_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=root_at(tmp,{'XOM':2115436,'XOM.A':2115436});now=datetime(2026,10,1,tzinfo=timezone.utc)
            with patch.object(sec,'sec_identity'),patch.object(sec.time,'sleep'),patch.object(sec,'request',side_effect=[
                self.payloads['CIK0002115436.json'],self.payloads['CIK0000034088.json']]) as request:
                out=sec.collect_sec({},root,True,now)
                again=sec.collect_sec(out,root,True,now+timedelta(hours=1))
            self.assertEqual(request.call_count,2)
            self.assertIn('CIK0000034088.json',request.call_args_list[1].args[0])
            self.assertEqual(out['secCoverage']['usableTickers'],2)
            self.assertEqual(again['secCoverage']['requests'],0)
            self.assertEqual(out['stocks']['XOM'],again['stocks']['XOM.A'])

    def test_original_parser_features_and_evidence_are_unchanged_for_control(self):
        code=self.payloads['baseline-parser.py']
        namespace={'__file__':str(sec.ROOT/'scripts/build_research_inputs.py'),'__name__':'pinned_parser'}
        exec(compile(code,'pinned_parser','exec'),namespace)
        p=self.payloads['control-NVDA.json']
        self.assertEqual(namespace['financial_history'](p),sec.financial_history(p))

    def test_genuine_unsupported_cases_remain_missing(self):
        for cik in (1841666,2089271,1601712):
            with self.subTest(cik=cik):self.assertEqual(sec.financial_history(self.payloads[f'CIK{cik:010d}.json']),[])

    def test_official_bank_denominators_match_reviewed_statements(self):
        for cik,total in ((35527,9017000000),(92230,20319000000),(1281761,7526000000)):
            with self.subTest(cik=cik):
                r=sec.financial_history(self.payloads[f'CIK{cik:010d}.json'])[-1]
                self.assertEqual(sum(e['value'] for e in r['evidence'][:2]),total)

    def test_import_reviewed_predecessor_requires_real_current_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=root_at(tmp,{'XOM':2115436})
            p=root/'old.json';p.write_text(json.dumps(self.payloads['CIK0000034088.json']))
            with self.assertRaisesRegex(ValueError,'current CompanyFacts'):ingest([p],root)
            current=root/'current.json';current.write_text(json.dumps(self.payloads['CIK0002115436.json']))
            out=ingest([current,p],root)
            self.assertEqual(out['secCoverage']['usableIssuers'],1)
            self.assertEqual(out['stocks']['XOM']['cik'],2115436)
            self.assertEqual(out['stocks']['XOM']['rows'][0]['availableDate'],'2026-07-01')
            self.assertIn('34088',out['stocks']['XOM']['sourcePayloadHashes'])
            self.assertIsNone(out['stocks']['XOM']['retrievedAt'])
            z=root/'sources.zip'
            with zipfile.ZipFile(z,'w') as archive:
                archive.writestr('CIK0002115436.json',current.read_bytes())
                archive.writestr('CIK0000034088.json',p.read_bytes())
            zipped=ingest([z],root)
            self.assertEqual(out['stocks']['XOM']['rows'],zipped['stocks']['XOM']['rows'])

    def test_source_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=copy.deepcopy(self.manifest)
            first=next(iter(manifest['sources']));manifest['sources']={first:manifest['sources'][first]}
            path=root/manifest['sources'][first]['path'];path.parent.mkdir();path.write_bytes(b'changed')
            (root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'source changed'):sources(root)


if __name__=='__main__':unittest.main()
