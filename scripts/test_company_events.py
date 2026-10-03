import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import build_company_events as m

NOW = datetime(2026, 10, 3, 2, tzinfo=timezone.utc)


def submission(cik=1045810, rows=None):
    rows = rows if rows is not None else [dict(form='8-K', filingDate='2026-10-02', reportDate='2026-09-30',
        accessionNumber='0001045810-26-000100', primaryDocument='nvda-20260930.htm',
        acceptanceDateTime='2026-10-02T20:00:00Z', items='2.02,7.01,9.01')]
    keys = ('form', 'filingDate', 'reportDate', 'accessionNumber', 'primaryDocument', 'acceptanceDateTime', 'items')
    return dict(cik=str(cik), name='Company', filings={'recent':{k:[r.get(k, '') for r in rows] for k in keys}})


class CompanyEvents(unittest.TestCase):
    def parse(self, payload, cik=1045810, observed=NOW.isoformat()):
        return m.parse_submissions(payload, cik, observed, NOW)

    def test_public_date_not_period_date_and_metadata_not_guidance(self):
        rows, rejected = self.parse(submission())
        self.assertEqual(rejected, {})
        self.assertEqual(rows[0]['date'], '2026-10-02')
        self.assertEqual(rows[0]['reportDate'], '2026-09-30')
        self.assertEqual(rows[0]['category'], 'earnings')
        self.assertNotIn('가이던스', rows[0]['title'])
        self.assertIn('/1045810/000104581026000100/', rows[0]['source']['url'])
        title, category, _ = m.describe('8-K', ['7.01', '8.01', '9.01'])
        self.assertEqual(category, 'disclosure')
        self.assertNotRegex(title, '규제|계약|가이던스|배당')

    def test_wrong_identity_or_unaligned_columns_fail_whole_response(self):
        with self.assertRaises(ValueError): self.parse(submission(320193))
        p = submission(); p['filings']['recent']['items'] = []
        with self.assertRaises(ValueError): self.parse(p)
        p = submission(); del p['filings']['recent']['primaryDocument']
        with self.assertRaises(ValueError): self.parse(p)
        with self.assertRaises(ValueError): self.parse(submission(), observed='2099-01-01T00:00:00Z')

    def test_future_rows_and_sources_never_appear(self):
        row = {k:v[0] for k,v in submission()['filings']['recent'].items()}
        for changes, reason in [({'filingDate':'2026-10-04'}, 'future_filing'),
                                ({'acceptanceDateTime':'2026-10-03T03:00:00Z'}, 'invalid_or_future_acceptance')]:
            rows, rejected = self.parse(submission(rows=[{**row, **changes}]))
            self.assertEqual(rows, []); self.assertEqual(rejected[reason], 1)
        # Replaying an older capture cannot show a filing that wasn't known then.
        rows, rejected = self.parse(submission(), observed='2026-10-01T20:00:00Z')
        self.assertEqual(rows, []); self.assertEqual(rejected['future_filing'], 1)

    def test_window_order_duplicates_and_forms(self):
        row = {k:v[0] for k,v in submission()['filings']['recent'].items()}
        dated = lambda d, n, form='10-Q': {**row,'form':form,'filingDate':d,'reportDate':'',
            'items':'','accessionNumber':f'0001045810-26-{n:06d}','acceptanceDateTime':d+'T00:00:00Z'}
        p = submission(rows=[dated('2026-09-01',2), dated('2026-10-02',3), dated('2026-10-02',3),
                             dated('2026-10-02',4,'4'), dated('2026-01-01',1)])
        rows, _ = self.parse(p)
        self.assertEqual([r['date'] for r in rows], ['2026-10-02','2026-09-01'])
        with self.assertRaises(ValueError):
            self.parse(submission(rows=[row,{**row,'items':'1.01'}]))

    def test_unsafe_documents_and_invalid_dates_rejected(self):
        row = {k:v[0] for k,v in submission()['filings']['recent'].items()}
        for changes in [{'primaryDocument':'../private.htm'}, {'primaryDocument':'evil.htm?redirect=evil'},
                        {'filingDate':'2026-09-31'}, {'reportDate':'2026-10-04'},
                        {'items':'8.01<script>'}, {'accessionNumber':'../../bad'}]:
            rows, rejected = self.parse(submission(rows=[{**row,**changes}]))
            self.assertEqual(rows, []); self.assertEqual(rejected['invalid_row'], 1)

    def test_original_release_details_require_dated_explicit_guidance(self):
        row=dict(symbol='NVDA',availableDate='2026-08-26',periodEnd='2026-07-26',
                 firstRetrievedAt='2026-09-13T00:20:00Z',basis='GAAP',currency='USD',
                 fiscalYear=2027,quarter=2,revenue=96221,nextQuarterRevenue=108000,
                 sourceUrl='https://nvidianews.nvidia.com/news/nvidia-financial-results')
        events=m.release_events([row],'NVDA',NOW)
        self.assertEqual(events[0]['date'],'2026-08-26')
        self.assertEqual(len(events[0]['details']),3)
        self.assertNotIn('상향',events[0]['summary'])
        events=m.release_events([{**row,'nextQuarterRevenue':None}],'NVDA',NOW)
        self.assertEqual(len(events[0]['details']),2)
        self.assertNotIn('전망',events[0]['summary'])
        self.assertEqual(m.release_events([{**row,'availableDate':'2026-10-04'}],'NVDA',NOW),[])
        self.assertEqual(m.release_events([{**row,'firstRetrievedAt':'2026-08-25T00:00:00Z'}],'NVDA',NOW),[])

    def test_reviewed_predecessor_archive_and_agent_prefix(self):
        row = {k:v[0] for k,v in submission()['filings']['recent'].items()}
        xom = {**row,'form':'10-Q','items':'','accessionNumber':'0000034088-26-000093'}
        rows, _ = self.parse(submission(2115436,[xom]),2115436)
        self.assertEqual(rows[0]['archiveCIK'],34088)
        agent = {**row,'accessionNumber':'0001193125-26-000100'}
        rows, _ = self.parse(submission(rows=[agent]))
        self.assertEqual(rows[0]['archiveCIK'],1045810)

    def prepare(self, root, members=None):
        (root/'research').mkdir()
        m.atomic_json(root/'research/universe.json', {'sourceHash':'frozen','members':members or {
            'NVDA':{'cik':1045810,'name':'Nvidia'},'NVDA.B':{'cik':1045810,'name':'Same issuer'}}})
        (root/'fundamentals').mkdir()
        with (root/'fundamentals/latest_fundamentals.csv').open('w') as f:
            writer = csv.DictWriter(f,fieldnames=['symbol','nextEarningsDate','updatedAt','source','error'])
            writer.writeheader();writer.writerow(dict(symbol='NVDA',nextEarningsDate='2026-11-17',
                 updatedAt='2026-10-02T20:00:00Z',source='Yahoo fundamentals quoteSummary',error=''))
        # Immutable research files must never be used as a place to put events.
        (root/'research/inputs.json').write_text('{"unchanged":true}')

    def test_one_request_per_issuer_share_classes_and_model_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.prepare(root)
            before=(root/'research/inputs.json').read_bytes()
            with patch.object(m,'sec_identity',return_value='Configured real contact'), \
                 patch.object(m,'request',return_value=submission()) as network, patch.object(m.time,'sleep'):
                result=m.build(root,now=NOW)
            self.assertEqual(network.call_count,1)
            self.assertEqual(result['symbols']['NVDA-B'],result['symbols']['NVDA'])
            self.assertEqual(result['collection']['freshIssuers'],1)
            self.assertEqual(result['collection']['freshTickers'],2)
            self.assertEqual(result['upcoming']['NVDA'][0]['dateKind'],'estimated')
            self.assertEqual(before,(root/'research/inputs.json').read_bytes())

    def test_access_denial_stops_requests_and_preserves_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.prepare(root,{'NVDA':{'cik':1045810,'name':'Nvidia'},'B':{'cik':2115436,'name':'B'}})
            with patch.object(m,'sec_identity',return_value='Configured contact'), \
                 patch.object(m,'request',side_effect=[submission(),submission(2115436)]), patch.object(m.time,'sleep'):
                first=m.build(root,now=NOW)
            later=NOW+timedelta(days=1)
            with patch.object(m,'sec_identity',return_value='Configured contact'), \
                 patch.object(m,'request',side_effect=HTTPError('SEC',403,'blocked',{},None)) as network, patch.object(m.time,'sleep'):
                result=m.build(root,now=later)
                self.assertEqual(network.call_count,1)
            for cik in ('1045810','2115436'):
                self.assertEqual(result['issuers'][cik]['sec']['lastSuccessAt'],NOW.isoformat())
                self.assertEqual(result['issuers'][cik]['events'],first['issuers'][cik]['events'])
                self.assertNotEqual(result['issuers'][cik]['sec']['status'],'ready')
            with patch.object(m,'request') as network:
                again=m.build(root,now=later+timedelta(minutes=5))
                self.assertEqual(network.call_count,0)
                self.assertEqual(again['collection']['blockedReason'],'backoff')

    def test_missing_contact_sends_no_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.prepare(root)
            with patch.object(m,'sec_identity',side_effect=ValueError('missing')), patch.object(m,'request') as network:
                result=m.build(root,now=NOW)
            self.assertEqual(network.call_count,0)
            self.assertEqual(result['collection']['blockedReason'],'contact_not_configured')
            self.assertEqual(result['issuers']['1045810']['events'],[])

    def test_offline_replay_does_not_refresh_capture_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.prepare(root)
            p=submission();when='2026-10-02T22:00:00Z'
            m.atomic_json(root/'research/source-cache/events/CIK0001045810.json',
                          {'payload':p,'sourceHash':m.payload_hash(p),'observedAt':when})
            with patch.object(m,'request') as network: result=m.build(root,download=False,now=NOW)
            self.assertEqual(network.call_count,0)
            self.assertEqual(result['issuers']['1045810']['sec']['lastSuccessAt'],when)
            self.assertEqual(result['issuers']['1045810']['events'][0]['observedAt'],when)

    def test_stale_future_or_past_calendar_values_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.prepare(root)
            members={'NVDA':{}}
            self.assertTrue(m.calendar_events(root,members,NOW))
            self.assertEqual(m.calendar_events(root,members,NOW+timedelta(days=9)),{})
            self.assertEqual(m.calendar_events(root,members,NOW-timedelta(days=2)),{})
            self.assertEqual(m.calendar_events(root,members,NOW+timedelta(days=60)),{})

    def test_bad_refresh_keeps_valid_existing_events(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.prepare(root)
            with patch.object(m,'sec_identity',return_value='Configured contact'), \
                 patch.object(m,'request',return_value=submission()), patch.object(m.time,'sleep'):
                first=m.build(root,now=NOW)
            with patch.object(m,'sec_identity',return_value='Configured contact'), \
                 patch.object(m,'request',return_value=submission(320193)), patch.object(m.time,'sleep'):
                result=m.build(root,now=NOW+timedelta(hours=1))
            self.assertEqual(result['issuers']['1045810']['events'],first['issuers']['1045810']['events'])
            self.assertEqual(result['issuers']['1045810']['sec']['status'],'invalid_response')


if __name__=='__main__': unittest.main()
