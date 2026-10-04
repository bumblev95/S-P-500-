import unittest
import json
import io
import tempfile
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape
from build_market_context import FEEDS, get, parse_csv, parse_table, collect_series, summarize, funding, bond_spreads, credit_state, parse_news, build

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

    def test_credit_full_coverage_counts_four_families_not_indicators(self):
        rows=[dict(id=key,status='ready',severity=0) for key in
              ('NFCI','STLFSI4','FUNDING','DRTSCILM','GZ_SPREAD','EBP')]
        rows.append(dict(id='DGS10',status='ready',severity=3)) # outside credit
        result=credit_state(rows)
        self.assertEqual((result['coverage'],result['expected']),(4,4))
        self.assertTrue(result['complete'])
        self.assertEqual(result['missingFamilies'],[])
        self.assertEqual((result['status'],result['score']),('stable',0))

    def test_credit_successful_fetch_cannot_make_stale_bonds_complete(self):
        rows=[dict(id=key,status='ready',severity=0) for key in
              ('NFCI','STLFSI4','FUNDING','DRTSCILM')]
        rows.extend(dict(id=key,status='stale',severity=3,fetchStatus='ready',fromCache=False)
                    for key in ('GZ_SPREAD','EBP'))
        result=credit_state(rows)
        self.assertEqual((result['coverage'],result['expected']),(3,4))
        self.assertFalse(result['complete'])
        self.assertEqual(result['missingFamilies'],['회사채 GZ/EBP'])
        self.assertEqual((result['status'],result['score']),('stable',0))

    def test_credit_empty_coverage_keeps_expected_and_missing_families(self):
        result=credit_state([])
        self.assertEqual((result['coverage'],result['expected']),(0,4))
        self.assertFalse(result['complete'])
        self.assertEqual(result['missingFamilies'],
                         ['금융여건','단기자금조달','은행대출','회사채 GZ/EBP'])
        self.assertEqual(result['status'],'unknown')
        self.assertIsNone(result['score'])

    def test_credit_each_family_needs_a_ready_member_with_severity(self):
        rows=[dict(id=key,status='ready',severity=0) for key in
              ('NFCI','STLFSI4','FUNDING','DRTSCILM','GZ_SPREAD','EBP')]
        for ids,label in [(('NFCI','STLFSI4'),'금융여건'),(('FUNDING',),'단기자금조달'),
                          (('DRTSCILM',),'은행대출'),(('GZ_SPREAD','EBP'),'회사채 GZ/EBP')]:
            for status,severity in [('stale',3),('missing',None),('unavailable',3),('ready',None)]:
                with self.subTest(family=label,status=status,severity=severity):
                    partial=[dict(q,status=status,severity=severity) if q['id'] in ids else q for q in rows]
                    result=credit_state(partial)
                    self.assertEqual((result['coverage'],result['expected']),(3,4))
                    self.assertFalse(result['complete'])
                    self.assertEqual(result['missingFamilies'],[label])

    def test_credit_one_usable_member_covers_an_overlapping_family(self):
        rows=[dict(id=key,status='ready',severity=0) for key in
              ('STLFSI4','FUNDING','DRTSCILM','EBP')]
        rows.extend(dict(id=key,status='stale',severity=3) for key in ('NFCI','GZ_SPREAD'))
        result=credit_state(rows)
        self.assertEqual((result['coverage'],result['expected']),(4,4))
        self.assertTrue(result['complete']) # family coverage, not every input fresh
        self.assertEqual((result['status'],result['score']),('stable',0))

    def test_credit_partial_coverage_preserves_existing_risk_thresholds(self):
        cases=[({'NFCI':0},'unknown',0,1),
               ({'NFCI':0,'FUNDING':0},'unknown',0,2),
               ({'NFCI':0,'FUNDING':0,'DRTSCILM':0},'stable',0,3),
               ({'NFCI':1},'watch',33,1),
               ({'NFCI':2,'STLFSI4':2},'watch',67,1),
               ({'GZ_SPREAD':2,'EBP':2},'watch',67,1),
               ({'NFCI':3},'risk',100,1),
               ({'NFCI':2,'EBP':2},'risk',67,2)]
        for levels,status,score,coverage in cases:
            with self.subTest(levels=levels):
                result=credit_state([dict(id=k,status='ready',severity=v) for k,v in levels.items()])
                self.assertEqual((result['status'],result['score'],result['coverage']),
                                 (status,score,coverage))
                self.assertEqual(result['expected'],4)
                self.assertFalse(result['complete'])

    def test_credit_bond_freshness_boundary_remains_75_calendar_days(self):
        rows=[dict(id=key,status='ready',severity=0) for key in ('NFCI','FUNDING','DRTSCILM')]
        csv='date,gz_spread,ebp\n2026-07-01,1,-.1\n'
        for today,covered in [(date(2026,9,14),4),(date(2026,9,15),3)]:
            with self.subTest(today=today):
                bonds=bond_spreads(csv,today)
                self.assertTrue(all(q['maxAgeDays']==75 for q in bonds))
                result=credit_state(rows+bonds)
                self.assertEqual((result['coverage'],result['expected']),(covered,4))
                self.assertEqual(result['complete'],covered==4)
                self.assertEqual(result['status'],'stable')

    def test_build_recovered_fred_with_july_bonds_reports_partial_credit(self):
        now=datetime(2026,10,3,16,25,3,tzinfo=timezone.utc)
        def recovered(url):
            if 'fredgraph' in url:
                key=url.split('id=')[1].split('&')[0]
                value={'NFCI':-.5,'STLFSI4':-.4,'DRTSCILM':5,'SOFR':3.6,'IORB':3.65}.get(key,0)
                return 'observation_date,'+key+'\n'+''.join(f'{d},{value}\n' for d in
                       ('2026-09-30','2026-10-01','2026-10-02'))
            if 'ebp_csv' in url: return 'date,gz_spread,ebp\n2026-07-01,1,-.1\n'
            return '<rss><channel/></rss>'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            result=build(root,now,recovered)
            self.assertEqual(json.loads((root/'market/latest.json').read_text())['credit'],result['credit'])
        by={q['id']:q for q in result['indicators']}
        for key in ('DGS10','DTWEXBGS','NFCI','STLFSI4','DRTSCILM','SOFR','IORB','FUNDING'):
            self.assertEqual(by[key]['status'],'ready',key)
        for key in ('GZ_SPREAD','EBP'):
            self.assertEqual(by[key]['status'],'stale',key)
            self.assertEqual(by[key]['asOf'],'2026-07-01',key)
        for q in result['indicators']:
            self.assertEqual(q['fetchStatus'],'ready')
            self.assertFalse(q['fromCache'])
            self.assertEqual(q['lastSuccessAt'],now.isoformat())
        self.assertEqual(result['errors'],[])
        self.assertEqual((result['credit']['coverage'],result['credit']['expected']),(3,4))
        self.assertFalse(result['credit']['complete'])
        self.assertEqual(result['credit']['missingFamilies'],['회사채 GZ/EBP'])
        self.assertEqual((result['credit']['status'],result['credit']['score']),('stable',0))

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

class FedNewsTests(unittest.TestCase):
    def setUp(self):
        silence = patch('builtins.print')
        silence.start(); self.addCleanup(silence.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.now = datetime(2026,10,3,21,30,tzinfo=timezone.utc)

    def article_url(self, slug):
        return 'https://www.federalreserve.gov/newsevents/'+slug+'.htm'

    def xml(self, articles):
        return '<rss><channel>'+''.join(
            '<item><title>'+escape(slug)+'</title><link>'+self.article_url(slug)+
            '</link><pubDate>'+format_datetime(published)+'</pubDate></item>'
            for slug,published in articles)+'</channel></rss>'

    def collect(self, now, responses):
        by_url = {url:responses[name] for name,url in FEEDS}
        def fetch(url):
            if url in by_url:
                response = by_url[url]
                if isinstance(response, Exception): raise response
                return self.xml(response)
            if 'fredgraph' in url:
                key = url.split('id=')[1].split('&')[0]
                value = 3.6 if key=='SOFR' else 3.65 if key=='IORB' else 0
                return 'observation_date,'+key+'\n'+''.join(
                    f'{d},{value}\n' for d in ('2026-09-30','2026-10-01','2026-10-02'))
            if 'ebp_csv' in url: return 'date,gz_spread,ebp\n2026-10-01,1,-.1\n'
            raise AssertionError('Unexpected URL: '+url)
        result = build(self.root, now, fetch)
        self.assertEqual(json.loads((self.root/'market/latest.json').read_text()),
                         json.loads(json.dumps(result)))
        return result

    def test_one_failed_feed_retains_only_its_legacy_cache(self):
        published = self.now-timedelta(days=1)
        original = {'Fed 발표':[('press-old',published)], 'Fed 연설':[('speech-old',published)]}
        for failed,healthy in [('Fed 발표','Fed 연설'),('Fed 연설','Fed 발표')]:
            with self.subTest(failed=failed):
                first = self.collect(self.now,original)
                # Migrate the existing schema-2 snapshot without inventing a new fetch time.
                for item in first['news']:
                    item.pop('fromCache',None); item.pop('lastSuccessAt',None)
                first['feeds'] = [dict(name=name,url=url,status='ready') for name,url in FEEDS]
                (self.root/'market/latest.json').write_text(json.dumps(first))
                later = self.now+timedelta(hours=1)
                failed_url = dict(FEEDS)[failed]
                responses = {failed:HTTPError(failed_url,503,'unavailable',None,None),
                             healthy:[('healthy-new',published)]}
                result = self.collect(later,responses)
                by_source = {item['source']:item for item in result['news']}
                self.assertEqual(len(result['news']),2)
                cached = by_source[failed]
                self.assertEqual(cached['url'],self.article_url(original[failed][0][0]))
                self.assertEqual(cached['publishedAt'],published.isoformat())
                self.assertTrue(cached['fromCache'])
                self.assertEqual(cached['lastSuccessAt'],self.now.isoformat())
                self.assertEqual(by_source[healthy]['url'],self.article_url('healthy-new'))
                self.assertFalse(by_source[healthy]['fromCache'])
                self.assertEqual(by_source[healthy]['lastSuccessAt'],later.isoformat())
                feeds = {feed['name']:feed for feed in result['feeds']}
                self.assertEqual(feeds[failed]['status'],'unavailable')
                self.assertEqual(feeds[failed]['fetchError'],'HTTPError')
                self.assertTrue(feeds[failed]['fromCache'])
                self.assertEqual(feeds[failed]['lastSuccessAt'],self.now.isoformat())
                self.assertEqual(feeds[healthy]['status'],'ready')
                self.assertFalse(feeds[healthy]['fromCache'])
                self.assertEqual(feeds[healthy]['lastSuccessAt'],later.isoformat())
                self.assertTrue(all(feed['lastAttemptAt']==later.isoformat() for feed in feeds.values()))
                self.assertEqual(result['errors'],[failed+': HTTPError'])
                # News collection cannot change financial observations or the credit result.
                self.assertEqual(result['observations'],first['observations'])
                self.assertEqual(result['credit'],first['credit'])
                self.assertEqual([{k:v for k,v in q.items() if k not in ('lastSuccessAt','lastAttemptAt')}
                                  for q in result['indicators']],
                                 [{k:v for k,v in q.items() if k not in ('lastSuccessAt','lastAttemptAt')}
                                  for q in first['indicators']])

    def test_cache_expires_at_the_same_14_day_boundary_as_live_news(self):
        boundary = self.now-timedelta(days=14)
        articles = [('boundary',boundary),('inside',boundary+timedelta(seconds=1)),
                    ('expired',boundary-timedelta(seconds=1))]
        first = self.collect(self.now-timedelta(hours=1),{'Fed 발표':articles,'Fed 연설':[]})
        responses = {'Fed 발표':TimeoutError(),'Fed 연설':[]}
        at_boundary = self.collect(self.now,responses)
        self.assertEqual({n['url'] for n in at_boundary['news']},
                         {self.article_url('boundary'),self.article_url('inside')})
        after_boundary = self.collect(self.now+timedelta(seconds=1),responses)
        self.assertEqual([n['url'] for n in after_boundary['news']],[self.article_url('inside')])
        expired = self.collect(self.now+timedelta(seconds=2),responses)
        self.assertEqual(expired['news'],[])
        feed = expired['feeds'][0]
        self.assertEqual(feed['status'],'unavailable')
        self.assertFalse(feed['fromCache'])
        self.assertEqual(feed['lastSuccessAt'],first['generatedAt'])

    def test_repeated_failure_then_both_feeds_recover_without_old_cache(self):
        published = self.now-timedelta(days=1)
        first = self.collect(self.now,{'Fed 발표':[('press-old',published)],
                                     'Fed 연설':[('speech-old',published)]})
        later = self.now+timedelta(hours=1)
        self.collect(later,{'Fed 발표':TimeoutError(),'Fed 연설':[('speech-new',published)]})
        failed = self.collect(later+timedelta(hours=1),
                              {'Fed 발표':TimeoutError(),'Fed 연설':TimeoutError()})
        feeds = {feed['name']:feed for feed in failed['feeds']}
        self.assertTrue(all(f['status']=='unavailable' and f['fromCache'] for f in feeds.values()))
        self.assertEqual(feeds['Fed 발표']['lastSuccessAt'],first['generatedAt'])
        self.assertEqual(feeds['Fed 연설']['lastSuccessAt'],later.isoformat())
        self.assertTrue(all(n['fromCache'] for n in failed['news']))
        recovered_at = later+timedelta(hours=2)
        recovered = self.collect(recovered_at,{'Fed 발표':[('press-recovered',published)],
                                               'Fed 연설':[('speech-recovered',published)]})
        self.assertEqual({n['url'] for n in recovered['news']},
                         {self.article_url('press-recovered'),self.article_url('speech-recovered')})
        self.assertEqual(recovered['errors'],[])
        for entry in recovered['feeds']+recovered['news']:
            self.assertFalse(entry['fromCache'])
            self.assertEqual(entry['lastSuccessAt'],recovered_at.isoformat())
            self.assertNotIn('fetchError',entry)
        self.assertTrue(all(f['status']=='ready' for f in recovered['feeds']))

    def test_successful_empty_feed_replaces_failed_cache(self):
        published = self.now-timedelta(days=1)
        self.collect(self.now,{'Fed 발표':[('press-old',published)],'Fed 연설':[]})
        self.collect(self.now+timedelta(hours=1),{'Fed 발표':TimeoutError(),'Fed 연설':[]})
        result = self.collect(self.now+timedelta(hours=2),{'Fed 발표':[],'Fed 연설':[]})
        self.assertEqual(result['news'],[])
        self.assertEqual(result['errors'],[])
        self.assertTrue(all(f['status']=='ready' and not f['fromCache'] for f in result['feeds']))

    def test_healthy_feed_cannot_evict_other_feeds_valid_cache(self):
        published = self.now-timedelta(days=2)
        press = [('press-'+str(i),published) for i in range(3)]
        self.collect(self.now,{'Fed 발표':press,'Fed 연설':[]})
        speeches = [('speech-'+str(i),self.now-timedelta(minutes=i)) for i in range(20)]
        result = self.collect(self.now+timedelta(hours=1),{'Fed 발표':TimeoutError(),'Fed 연설':speeches})
        self.assertEqual(len(result['news']),23)
        cached = [n for n in result['news'] if n['source']=='Fed 발표']
        self.assertEqual({n['url'] for n in cached},{self.article_url(slug) for slug,_ in press})
        self.assertTrue(all(n['fromCache'] and n['lastSuccessAt']==self.now.isoformat() for n in cached))

    def test_legacy_unavailable_feed_cannot_claim_snapshot_time_as_last_success(self):
        published = self.now-timedelta(days=1)
        old = dict(generatedAt=self.now.isoformat(),
                   news=parse_news(self.xml([('press-old',published)]),'Fed 발표',self.now),
                   feeds=[dict(name=name,url=url,status='unavailable') for name,url in FEEDS])
        old['news'].extend([dict(old['news'][0],url='https://evil.example/article'),
                           dict(old['news'][0],publishedAt='invalid'),
                           dict(old['news'][0],publishedAt=(self.now+timedelta(days=1)).isoformat()),
                           dict(old['news'][0],source='Unknown feed')])
        (self.root/'market').mkdir()
        (self.root/'market/latest.json').write_text(json.dumps(old))
        result = self.collect(self.now+timedelta(hours=1),{'Fed 발표':TimeoutError(),'Fed 연설':[]})
        self.assertEqual(len(result['news']),1)
        self.assertTrue(result['news'][0]['fromCache'])
        self.assertIsNone(result['news'][0]['lastSuccessAt'])
        self.assertIsNone(result['feeds'][0]['lastSuccessAt'])

if __name__=='__main__':unittest.main()
