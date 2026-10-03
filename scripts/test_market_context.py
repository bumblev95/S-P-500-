import unittest
import json
import io
import tempfile
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from datetime import date, datetime, timezone
from build_market_context import get, parse_csv, parse_table, collect_series, summarize, funding, credit_state, parse_news, build

class Tests(unittest.TestCase):
    def setUp(self):
        silence = patch("builtins.print")
        silence.start(); self.addCleanup(silence.stop)
    def test_bad_rows(self):
        self.assertEqual(parse_csv('DATE,NFCI\n2026-09-01,.\n2026-09-02,nan\n2026-09-03,0.4\n2027-01-01,2','NFCI',date(2026,9,11)), [('2026-09-03',0.4)])
    def test_stale(self):
        self.assertEqual(summarize('NFCI',[('2026-01-01',-1)],date(2026,9,11))['status'],'stale')

    def test_fred_timeout_is_shorter_without_changing_other_sources(self):
        for url, timeout in [
            ('https://fred.stlouisfed.org/graph/fredgraph.csv?id=NFCI',10),
            ('https://fred.stlouisfed.org/data/NFCI.txt',10),
            ('https://www.federalreserve.gov/feeds/press_all.xml',30),
        ]:
            with self.subTest(url=url), patch('build_market_context.urlopen',return_value=io.BytesIO(b'\xef\xbb\xbfdata')) as opened:
                self.assertEqual(get(url),'data')
                self.assertEqual(opened.call_args.kwargs['timeout'],timeout)
                request=opened.call_args.args[0]
                self.assertEqual(request.get_header('User-agent'),'PublicMarketMonitor/1.0')
                if timeout==10:
                    self.assertEqual(request.get_header('Accept'),'text/csv,text/plain,text/html,*/*')
                else:
                    self.assertIsNone(request.get_header('Accept'))

    def test_both_endpoints_timeout_is_unavailable_and_records_both_errors(self):
        calls=[]
        def fail(url):
            calls.append(url)
            raise TimeoutError()
        rows, meta=collect_series('NFCI',date(2026,10,3),fail)
        self.assertEqual(rows,[])
        self.assertEqual(meta['fetchStatus'],'unavailable')
        self.assertEqual(meta['fetchError'],'csv: TimeoutError; table: TimeoutError')
        self.assertEqual(len(calls),2)

    def test_real_get_timeout_still_uses_table_fallback(self):
        table=b'<tr><th scope="row">2026-10-02</th><td>0</td></tr>'
        with patch('build_market_context.urlopen',side_effect=[TimeoutError(),io.BytesIO(table)]) as opened:
            rows, meta=collect_series('NFCI',date(2026,10,3),get)
        self.assertEqual(rows,[('2026-10-02',0)])
        self.assertEqual(meta['fetchStatus'],'ready')
        self.assertEqual(meta['fetchWarnings'],['csv: TimeoutError'])
        self.assertTrue(meta['dataUrl'].endswith('/data/NFCI.txt'))
        self.assertTrue(all(call.kwargs['timeout']==10 for call in opened.call_args_list))

    def test_http_200_without_observations_is_not_collection_success(self):
        responses=['<html>Service unavailable</html>', '#2026-10-02|nan\n#2026-10-03|.']
        with patch('build_market_context.get',side_effect=responses) as fetch:
            rows, meta=collect_series('NFCI',date(2026,10,3),fetch)
        self.assertEqual(rows,[])
        self.assertEqual(meta['fetchStatus'],'unavailable')
        self.assertEqual(meta['fetchError'],'csv: ValueError; table: ValueError')
        self.assertEqual(fetch.call_count,2)

    def test_successful_fetch_of_old_observations_stays_stale(self):
        now=datetime(2026,10,3,tzinfo=timezone.utc)
        def old_data(url):
            if 'fredgraph' in url:
                key=url.split('id=')[1].split('&')[0]
                return 'observation_date,'+key+'\n2026-09-01,0\n'
            if 'ebp_csv' in url: return 'date,gz_spread,ebp\n2026-07-01,1,0\n'
            return '<rss><channel/></rss>'
        with tempfile.TemporaryDirectory() as tmp:
            result=build(Path(tmp),now,old_data)
        by={q['id']:q for q in result['indicators']}
        for key in ('DGS10','DTWEXBGS','NFCI','STLFSI4','SOFR','IORB'):
            self.assertEqual(by[key]['status'],'stale',key)
            self.assertEqual(by[key]['fetchStatus'],'ready',key)
            self.assertFalse(by[key]['fromCache'],key)
            self.assertEqual(by[key]['lastSuccessAt'],now.isoformat(),key)
        self.assertEqual(result['credit']['status'],'unknown')

    def test_total_failure_without_cache_never_becomes_ready_or_zero(self):
        def fail(url): raise TimeoutError()
        with tempfile.TemporaryDirectory() as tmp:
            result=build(Path(tmp),datetime(2026,10,3,tzinfo=timezone.utc),fail)
        self.assertEqual(result['credit']['status'],'unknown')
        self.assertIsNone(result['credit']['score'])
        self.assertTrue(result['errors'])
        for entry in result['indicators']:
            self.assertEqual(entry['status'],'missing')
            self.assertEqual(entry['fetchStatus'],'unavailable')
            self.assertIsNone(entry['value'])
            self.assertFalse(entry['fromCache'])
            self.assertNotIn('lastSuccessAt',entry)
    def test_funding_aligned(self):
        a=[('2026-09-08',4),('2026-09-09',4),('2026-09-10',4)]
        b=[('2026-09-08',3.6),('2026-09-09',3.6),('2026-09-10',3.6),('2026-09-11',8)]
        self.assertEqual(funding(a,b,date(2026,9,11))['severity'],3)
        self.assertEqual(funding(a,b[:1],date(2026,9,11))['status'],'missing')
    def test_coverage(self):
        self.assertEqual(credit_state([])['status'],'unknown')
        rows=[dict(id='NFCI',status='ready',severity=2),dict(id='STLFSI4',status='ready',severity=2)]
        self.assertNotEqual(credit_state(rows)['status'],'risk')
        rows.append(dict(id='FUNDING',status='ready',severity=2))
        self.assertEqual(credit_state(rows)['status'],'risk')
    def test_news_link(self):
        xml='<rss><channel><item><title>risk</title><link>https://evil.example/</link><pubDate>Thu, 10 Sep 2026 12:00:00 GMT</pubDate></item></channel></rss>'
        self.assertEqual(parse_news(xml,'test',datetime(2026,9,11,tzinfo=timezone.utc)),[])

    def test_table_fallback_parses_deferred_rows_and_rejects_missing_future(self):
        table='<tr><th scope="row">2026-09-08</th><td>0</td></tr><div id="extra-rows">#2026-09-09|-.5\n#2026-09-10|.\n#2026-09-11|nan\n#2027-01-01|99</div>'
        calls=[]
        def fetch(url):
            calls.append(url)
            if 'graph/' in url: raise TimeoutError()
            return table
        rows, meta=collect_series('NFCI',date(2026,9,14),fetch)
        self.assertEqual(rows,[('2026-09-08',0),('2026-09-09',-.5)])
        self.assertEqual(meta['fetchStatus'],'ready')
        self.assertEqual(len(calls),2)
        self.assertEqual(meta['fetchWarnings'],['csv: TimeoutError'])
        self.assertEqual(parse_table('<html>Service unavailable</html>',date(2026,9,14)),[])

    def test_access_rejection_does_not_retry_alternate_endpoint(self):
        for code in (403,429):
            calls=[]
            def reject(url):
                calls.append(url); raise HTTPError(url,code,'rejected',None,None)
            rows, meta=collect_series('NFCI',date(2026,9,14),reject)
            self.assertEqual(rows,[])
            self.assertEqual(len(calls),1)
            self.assertIn(str(code),meta['fetchError'])

    def test_failure_retains_values_dates_aligned_funding_then_recovers(self):
        now=datetime(2026,9,14,20,tzinfo=timezone.utc)
        def success(url):
            if 'fredgraph' in url:
                key=url.split('id=')[1].split('&')[0]
                value=3.8 if key=='SOFR' else 3.65 if key=='IORB' else 0
                return 'observation_date,'+key+'\n'+''.join(f'2026-09-{d:02d},{value}\n' for d in (8,9,10,11))
            if 'ebp_csv' in url: return 'date,gz_spread,ebp\n2026-06-01,1.1,-.1\n2026-07-01,1,0\n'
            return '<rss><channel/></rss>'
        def fail(url): raise TimeoutError()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=build(root,now,success)
            cached=build(root,datetime(2026,9,15,20,tzinfo=timezone.utc),fail)
            a={q['id']:q for q in first['indicators']};b={q['id']:q for q in cached['indicators']}
            for key in a:
                self.assertEqual(b[key]['value'],a[key]['value'])
                self.assertEqual(b[key]['asOf'],a[key]['asOf'])
                self.assertEqual(b[key].get('lastSuccessAt'),a[key].get('lastSuccessAt'), key)
                self.assertTrue(b[key]['fromCache'])
                self.assertEqual(b[key]['fetchStatus'],'unavailable')
                self.assertEqual(b[key]['lastAttemptAt'],'2026-09-15T20:00:00+00:00')
            self.assertEqual(b['NFCI']['status'],'ready')
            self.assertEqual(b['NFCI']['value'],0)
            self.assertEqual(b['GZ_SPREAD']['status'],'stale')
            self.assertEqual(a['GZ_SPREAD']['status'],'ready') # 75 calendar days
            self.assertEqual(b['FUNDING']['severity'],a['FUNDING']['severity'])
            repeated=build(root,datetime(2026,9,16,20,tzinfo=timezone.utc),fail)
            for q in repeated['indicators']:
                self.assertEqual(q.get('lastSuccessAt'),a[q['id']].get('lastSuccessAt'))
                self.assertEqual(q['asOf'],a[q['id']]['asOf'])
                self.assertTrue(q['fromCache'])
                self.assertEqual(q['fetchStatus'],'unavailable')
            stale=build(root,datetime(2026,10,15,tzinfo=timezone.utc),fail)
            self.assertEqual(next(q for q in stale['indicators'] if q['id']=='NFCI')['status'],'stale')
            recovered=build(root,now,success)
            self.assertEqual(recovered['errors'],[])
            self.assertTrue(all(q['fetchStatus']=='ready' and not q['fromCache'] for q in recovered['indicators']))

    def test_legacy_snapshot_recovers_severity_without_mismatching_funding_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'market').mkdir()
            old=[summarize('NFCI',[('2026-09-11',.6)],date(2026,9,14)),
                 summarize('SOFR',[('2026-09-10',3.62)],date(2026,9,14)),
                 summarize('IORB',[('2026-09-11',3.65)],date(2026,9,14))]
            for q in old: q.update(status='unavailable',severity=None)
            (root/'market/latest.json').write_text(json.dumps(dict(indicators=old)))
            def fail(url): raise TimeoutError()
            result=build(root,datetime(2026,9,14,tzinfo=timezone.utc),fail)
            by={q['id']:q for q in result['indicators']}
            self.assertEqual(by['NFCI']['severity'],2)
            self.assertIsNone(by['FUNDING']['value'])
            self.assertIsNone(by['DGS10']['value'])

if __name__=='__main__':unittest.main()
