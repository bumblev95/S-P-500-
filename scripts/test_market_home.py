from copy import deepcopy
from datetime import datetime, timedelta, timezone
import errno
from http.client import IncompleteRead
import io
import json
from pathlib import Path
import socket
import ssl
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call, patch
from urllib.error import HTTPError, URLError
from xml.sax.saxutils import escape

import build_market_home as h

NOW=datetime(2026,10,3,23,tzinfo=timezone.utc)


def rss(title='U.S. economy outlook', url='https://www.federalreserve.gov/newsevents/speech/test.htm', published='Fri, 02 Oct 2026 16:00:00 GMT', description='The economy grew while inflation remained above target.'):
    return '<rss><channel><item><title>'+title+'</title><link>'+url+'</link><pubDate>'+published+'</pubDate><description>'+description+'</description></item></channel></rss>'


class Periods(unittest.TestCase):
    def test_week_is_monday_friday_in_new_york_not_rolling_seven_days(self):
        self.assertEqual(tuple(map(str,h.week_bounds(NOW))),('2026-09-28','2026-10-02'))
        midnight_utc=datetime(2026,10,5,2,tzinfo=timezone.utc) # still Sunday in New York
        self.assertEqual(str(h.week_bounds(midnight_utc)[0]),'2026-09-28')
        self.assertEqual(str(h.week_bounds(midnight_utc+timedelta(hours=3))[0]),'2026-10-05')

    def test_week_uses_previous_friday_and_holiday_uses_last_prior_session(self):
        rows=[{'date':'2026-09-25','close':100},{'date':'2026-09-28','close':110},{'date':'2026-10-01','close':115},{'date':'2026-10-02','close':120}]
        q=h.returns(rows,NOW)
        self.assertAlmostEqual(q['week'],20)
        self.assertAlmostEqual(q['day'],(120/115-1)*100)
        self.assertEqual(q['weekBaseDate'],'2026-09-25')
        rows[0]['date']='2026-09-24'
        self.assertEqual(h.returns(rows,NOW)['weekBaseDate'],'2026-09-24')

    def test_new_monday_before_first_close_has_no_this_week_return(self):
        rows=[{'date':'2026-10-01','close':100},{'date':'2026-10-02','close':110}]
        q=h.returns(rows,datetime(2026,10,5,13,tzinfo=timezone.utc))
        self.assertIsNone(q['week']);self.assertIsNone(q['weekBaseDate'])

    def test_intraday_bar_is_not_a_final_daily_close(self):
        timestamps=[int(datetime(2026,10,d,13,30,tzinfo=timezone.utc).timestamp()) for d in [1,2]]
        data={'chart':{'result':[{'timestamp':timestamps,'meta':{'regularMarketTime':int(datetime(2026,10,2,19,tzinfo=timezone.utc).timestamp())},'indicators':{'quote':[{'close':[100,500]}]}}]}}
        self.assertEqual([q['date'] for q in h.closed_rows(data,datetime(2026,10,2,19,30,tzinfo=timezone.utc))],['2026-10-01'])
        # Even after close, a provider observation from 15:00 cannot claim a final bar.
        self.assertEqual(len(h.closed_rows(data,datetime(2026,10,2,21,tzinfo=timezone.utc))),1)
        data['chart']['result'][0]['meta']['regularMarketTime']=int(datetime(2026,10,2,20,1,tzinfo=timezone.utc).timestamp())
        self.assertEqual(len(h.closed_rows(data,datetime(2026,10,2,21,tzinfo=timezone.utc))),2)


class Feeds(unittest.TestCase):
    def setUp(self):
        self.sleep=self.enterContext(patch.object(h,'sleep'))
        self.old=h.parse_feed(rss(),'Fed 발표',NOW-timedelta(hours=1))[0]
        self.old.update(headlineKo='이전 경제 전망',summaryKo='확인한 발표 요약',translationStatus='ready',translationMethod='reviewed-summary',importance='important',importanceReason='검토한 정책 발언')
        self.prior={'news':[self.old], 'feeds':[{'name':'Fed 발표','lastSuccessAt':self.old['lastSuccessAt']}]}

    def test_each_official_feed_recovers_in_same_run_after_one_http_failure(self):
        for source,feed_url in h.FEEDS:
            with self.subTest(source=source):
                old=deepcopy(self.old);old['source']=source
                prior={'news':[old],'feeds':[{'name':source,'lastSuccessAt':old['lastSuccessAt']}]}
                def healthy(url):
                    if url==feed_url:return rss('U.S. economy outlook updated',published='Sat, 03 Oct 2026 22:30:00 GMT')
                    if url in [f[1] for f in h.FEEDS]:return '<rss><channel/></rss>'
                    return '<p>The economy expanded while inflation remained above target.</p>'
                expected=h.collect_news(prior,NOW,{},healthy)
                attempts=[]
                def fetch(url):
                    if url==feed_url:
                        attempts.append(url)
                        if len(attempts)==1:raise HTTPError(url,503,'Unavailable',{},None)
                    return healthy(url)
                self.sleep.reset_mock()
                items,feeds=h.collect_news(prior,NOW,{},fetch)
                self.assertEqual((items,feeds),expected)
                self.assertEqual(len(attempts),2);self.sleep.assert_called_once_with(0.5)
                self.assertEqual(items[0]['title'],'U.S. economy outlook updated')
                self.assertEqual(items[0]['firstPublishedAt'],old['firstPublishedAt'])
                self.assertFalse(items[0]['fromCache'])
                recovered=next(f for f in feeds if f['name']==source)
                self.assertEqual(recovered['status'],'ready');self.assertFalse(recovered['fromCache'])
                self.assertEqual(recovered['lastSuccessAt'],NOW.isoformat());self.assertNotIn('error',recovered)
                self.assertEqual(prior['news'],[old])

    def test_retry_exhaustion_preserves_cache_and_last_success(self):
        for kind in ('http','timeout'):
            with self.subTest(kind=kind):
                attempts=[]
                def fetch(url):
                    if url==h.FEEDS[0][1]:
                        attempts.append(url)
                        if kind=='http':raise HTTPError(url,503,'Unavailable',{},None)
                        raise URLError(TimeoutError('timed out'))
                    return '<rss><channel/></rss>'
                self.sleep.reset_mock()
                items,feeds=h.collect_news(self.prior,NOW,{},fetch)
                self.assertEqual(len(attempts),3)
                self.assertEqual(self.sleep.call_args_list,[call(0.5),call(1.0)])
                self.assertEqual(items,[{**self.old,'fromCache':True,'sourceStatus':'unavailable'}])
                self.assertEqual(feeds[0],{'name':h.FEEDS[0][0],'url':h.FEEDS[0][1],
                    'status':'unavailable','lastAttemptAt':NOW.isoformat(),
                    'lastSuccessAt':self.old['lastSuccessAt'],'fromCache':True,
                    'error':'HTTPError' if kind=='http' else 'URLError'})
                self.assertTrue(all(f['status']=='ready' and not f['fromCache'] for f in feeds[1:]))
                self.assertEqual(self.prior['news'],[self.old])

    def test_only_transient_http_and_network_errors_are_retried(self):
        url=h.FEEDS[0][1]
        errors=[HTTPError(url,code,'Transient',{},None) for code in [408,429,500,502,503,504]]
        errors += [TimeoutError(),ConnectionResetError(),ConnectionRefusedError(),
                   URLError(TimeoutError()),URLError(ConnectionResetError()),
                   socket.gaierror(socket.EAI_AGAIN,'Temporary DNS failure'),
                   URLError(socket.gaierror(socket.EAI_AGAIN,'Temporary DNS failure')),
                   OSError(errno.ENETUNREACH,'Network unreachable'),IncompleteRead(b'partial',100)]
        for error in errors:
            with self.subTest(error=repr(error)):
                self.sleep.reset_mock();fetch=Mock(side_effect=[error,'latest response'])
                self.assertEqual(h.fetch_feed(url,fetch),'latest response')
                self.assertEqual(fetch.call_args_list,[call(url),call(url)])
                self.sleep.assert_called_once_with(0.5)

    def test_permanent_http_tls_dns_and_validation_failures_do_not_retry(self):
        url=h.FEEDS[0][1]
        errors=[HTTPError(url,code,'Permanent',{},None) for code in [400,401,403,404,410,501,505]]
        errors += [URLError(ssl.SSLCertVerificationError('Invalid certificate')),
                   URLError(socket.gaierror(socket.EAI_NONAME,'Unknown host')),
                   URLError('unknown url type'),ValueError('Response too large'),RuntimeError('Invalid data')]
        for error in errors:
            with self.subTest(error=repr(error)):
                self.sleep.reset_mock();fetch=Mock(side_effect=error)
                with self.assertRaises(type(error)) as caught:h.fetch_feed(url,fetch)
                self.assertIs(caught.exception,error);fetch.assert_called_once_with(url)
                self.sleep.assert_not_called()

    def test_permanent_error_after_transient_error_stops_retry_and_uses_cache(self):
        url=h.FEEDS[0][1]
        fetch=Mock(side_effect=[HTTPError(url,503,'Unavailable',{},None),HTTPError(url,403,'Forbidden',{},None)])
        with patch.object(h,'FEEDS',[h.FEEDS[0]]):
            items,feeds=h.collect_news(self.prior,NOW,{},fetch)
        self.assertEqual(fetch.call_count,2);self.sleep.assert_called_once_with(0.5)
        self.assertTrue(items[0]['fromCache']);self.assertEqual(feeds[0]['error'],'HTTPError')

    def test_malformed_xml_falls_back_without_transport_retry(self):
        fetch=Mock(return_value='<rss><channel>')
        with patch.object(h,'FEEDS',[h.FEEDS[0]]):
            items,feeds=h.collect_news(self.prior,NOW,{},fetch)
        fetch.assert_called_once_with(h.FEEDS[0][1]);self.sleep.assert_not_called()
        self.assertTrue(items[0]['fromCache']);self.assertEqual(feeds[0]['error'],'ParseError')

    def test_default_fetch_recovers_from_timeout_while_reading_response(self):
        response=Mock()
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.read=Mock(side_effect=[TimeoutError(),b'<rss><channel/></rss>'])
        with patch.object(h,'FEEDS',[h.FEEDS[0]]), patch.object(h.urllib.request,'urlopen',return_value=response) as opened:
            items,feeds=h.collect_news(self.prior,NOW,{})
        self.assertEqual(items,[]);self.assertEqual(feeds[0]['status'],'ready')
        self.assertFalse(feeds[0]['fromCache']);self.assertEqual(opened.call_count,2)
        self.assertEqual(response.__exit__.call_count,2);self.sleep.assert_called_once_with(0.5)

    def test_only_failed_feed_keeps_its_cache_and_recovery_replaces_it(self):
        def fetch(url):
            if url==h.FEEDS[0][1]:raise TimeoutError()
            if url in [f[1] for f in h.FEEDS]:return '<rss><channel/></rss>'
            return '<p>The economy expanded while inflation remained above target.</p>'
        items,feeds=h.collect_news(self.prior,NOW,{},fetch)
        self.assertEqual(len(items),1)
        self.assertTrue(items[0]['fromCache']);self.assertEqual(items[0]['sourceStatus'],'unavailable')
        self.assertEqual(items[0]['publishedAt'],self.old['publishedAt'])
        self.assertEqual(items[0]['lastSuccessAt'],self.old['lastSuccessAt'])
        self.assertEqual(items[0]['importance'],'important')
        self.assertEqual(items[0]['importanceReason'],'검토한 정책 발언')
        self.assertEqual([f['status'] for f in feeds],['unavailable']+['ready']*(len(h.FEEDS)-1))
        items,feeds=h.collect_news({'news':items,'feeds':feeds},NOW,{},lambda _: '<rss><channel/></rss>')
        self.assertEqual(items,[]);self.assertTrue(all(f['status']=='ready' for f in feeds))

    def test_exact_14_day_expiry_and_source_validation(self):
        item=deepcopy(self.old);item['publishedAt']=(NOW-timedelta(days=14)).isoformat()
        self.assertEqual(len(h.retain_news([item],'Fed 발표',NOW)),1)
        self.assertEqual(h.retain_news([item],'Fed 발표',NOW+timedelta(seconds=1)),[])
        self.assertEqual(h.retain_news([item],'Fed 연설',NOW),[])
        item['url']='https://attacker.example/article'
        self.assertEqual(h.retain_news([item],'Fed 발표',NOW),[])

    def test_new_fetch_does_not_restart_first_publication_time(self):
        def fetch(url):
            if url==h.FEEDS[0][1]:return rss(published='Sat, 03 Oct 2026 22:30:00 GMT')
            if url in [f[1] for f in h.FEEDS]:return '<rss><channel/></rss>'
            return '<p>The economy expanded while inflation remained above target.</p>'
        items,_=h.collect_news(self.prior,NOW,{},fetch)
        self.assertEqual(items[0]['firstPublishedAt'],self.old['publishedAt'])
        self.assertEqual(items[0]['publishedAt'],'2026-10-03T22:30:00+00:00')

    def test_review_requires_matching_title_and_source_evidence(self):
        review={self.old['url']:{'title':self.old['title'],'evidence':['inflation remained above target'],'headline':'성장 이어졌지만 물가 목표 상회','summary':'경제는 성장했고 물가는 목표 위에 머물렀다.'}}
        def fetch(url):
            if url==h.FEEDS[0][1]:return rss()
            if url in [f[1] for f in h.FEEDS]:return '<rss><channel/></rss>'
            return '<p>The economy expanded while inflation remained above target.</p>'
        items,_=h.collect_news({},NOW,review,fetch)
        self.assertEqual(items[0]['translationMethod'],'reviewed-summary')
        review[self.old['url']]['evidence']=['interest rates were cut']
        items,_=h.collect_news({},NOW,review,fetch)
        self.assertNotIn('headlineKo',items[0]);self.assertIn('_translate',items[0])

    def test_recent_normal_news_precedes_older_important_news(self):
        recent_url='https://www.cnbc.com/2026/10/03/stocks-market-test.html'
        old_url='https://www.federalreserve.gov/newsevents/pressreleases/old.htm'
        def fetch(url):
            if url==h.FEEDS[0][1]:
                return rss('Fed raises interest rates after inflation report',old_url,'Fri, 02 Oct 2026 12:00:00 GMT')
            if url==h.FEEDS[4][1]:
                return rss('Wall Street stocks rise after strong earnings',recent_url,'Sat, 03 Oct 2026 22:00:00 GMT')
            if url in [f[1] for f in h.FEEDS]:
                return '<rss><channel/></rss>'
            return '<p>Federal Reserve policy statement on inflation and interest rates.</p>'
        items,_=h.collect_news({},NOW,{},fetch)
        self.assertEqual(items[0]['url'],recent_url)
        self.assertEqual(items[0]['importance'],'normal')
        self.assertEqual(items[1]['url'],old_url)
        self.assertEqual(items[1]['importance'],'important')

    def test_speculation_is_not_promoted_to_confirmed_important_event(self):
        def fetch(url):
            if url==h.FEEDS[3][1]:return rss('Country could launch invasion as war fears grow','https://www.bbc.com/news/articles/test')
            return '<rss><channel/></rss>'
        items,_=h.collect_news({},NOW,{},fetch)
        self.assertEqual(items[0]['importance'],'normal')

    def test_invasion_contingency_headline_is_not_a_confirmed_event(self):
        def fetch(url):
            if url==h.FEEDS[3][1]:return rss('Why Canada is preparing for a (long shot) US invasion','https://www.bbc.com/news/articles/test')
            return '<rss><channel/></rss>'
        items,_=h.collect_news({},NOW,{},fetch)
        self.assertEqual(items[0]['importance'],'normal')

    def test_old_machine_translation_is_refreshed_when_translation_version_changes(self):
        current=deepcopy(self.old)
        current.update(source='CNBC 주요',url='https://www.cnbc.com/2026/10/03/stocks-market-test.html',
                       title='Wall Street stocks rise after strong earnings',headlineKo='이전 번역',summaryKo='이전 요약',
                       translationStatus='ready',translationMethod='machine-translation',sourceHash='old')
        prior={'news':[current],'feeds':[{'name':name,'lastSuccessAt':NOW.isoformat()} for name,_ in h.FEEDS]}
        xml=rss(current['title'],current['url'])
        def fetch(request):
            if request==h.FEEDS[4][1]:return xml
            return '<rss><channel/></rss>'
        items,_=h.collect_news(prior,NOW,{},fetch)
        self.assertIn('_translate',items[0])
        self.assertNotEqual(items[0].get('translationVersion'),h.HOME_TRANSLATION_VERSION)

    def test_bbc_review_is_bound_to_exact_title_and_source_excerpt(self):
        url='https://www.bbc.com/news/articles/test'
        xml=rss('Suppliers pile pressure on government over energy bills',url)
        def fetch(request):return xml if request==h.FEEDS[2][1] else '<rss><channel/></rss>'
        items,_=h.collect_news({},NOW,{},fetch)
        digest=items[0]['sourceHash']
        review={url:{'title':items[0]['title'],'sourceHash':digest,'headline':'에너지 업계, 요금 부담 완화 대책 촉구','summary':'에너지 업체들이 정부 조치를 요구했다.'}}
        items,_=h.collect_news({},NOW,review,fetch)
        self.assertEqual(items[0]['translationMethod'],'reviewed-summary')
        review[url]['sourceHash']='changed'
        items,_=h.collect_news({},NOW,review,fetch)
        self.assertIn('_translate',items[0]);self.assertNotIn('headlineKo',items[0])

    def test_future_invalid_and_off_topic_feed_items_are_excluded(self):
        self.assertEqual(h.parse_feed(rss(published='Sun, 04 Oct 2026 16:00:00 GMT'),'BBC 국제',NOW),[])
        self.assertEqual(h.parse_feed(rss('Celebrity wedding announced'),'BBC 국제',NOW),[])
        self.assertFalse(h.allowed('javascript:alert(1)'))

    def test_cnbc_market_feed_is_allowed_and_duplicate_urls_are_ranked_once(self):
        url='https://www.cnbc.com/2026/10/03/stocks-market-test.html'
        xml=rss('Wall Street stocks rise after strong earnings',url)
        def fetch(request):
            if request in [f[1] for f in h.FEEDS if f[0].startswith('CNBC')]:return xml
            return '<rss><channel/></rss>'
        items,feeds=h.collect_news({},NOW,{},fetch)
        self.assertTrue(h.allowed(url))
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['category'],'주식시장')
        self.assertEqual(sum(f['name'].startswith('CNBC') for f in feeds),3)


class HeadlineTranslation(unittest.TestCase):
    TITLE='Stocks are hitting records despite surging yields. Cramer explains why'
    EXCERPT='CNBC’s Jim Cramer said Nvidia, Microsoft and Meta are helping push stocks to records even as surging Treasury yields pressure much of the broader market.'
    BROKEN='크레이머 (Cramer) 는 왜'
    SUMMARY='CNBC의 짐 크레이머 (Jim Cramer) 는 Nvidia, 마이크로소프트 및 메타가 주식을 기록으로 끌어올리는 데 도움을 주고 있다고 말했습니다. 미국 정부 채권 금리 상승은 더 넓은 시장에 압력을 가하고 있습니다.'
    GOOD='금리 급등에도 주가 신고가'
    RETRY='Stock prices are at record highs despite sharply rising bond interest rates.'

    def setUp(self):
        self.now=datetime(2026,10,6,0,51,tzinfo=timezone.utc)
        self.url='https://www.cnbc.com/2026/10/05/cramer-ai-stocks-treasury-yields.html'
        cramer=rss(self.TITLE,self.url,'Mon, 05 Oct 2026 22:18:13 GMT',self.EXCERPT)
        good=rss('Wall Street stocks rise after strong earnings',
                 'https://www.cnbc.com/2026/10/05/stocks-market-test.html','Mon, 05 Oct 2026 23:00:00 GMT')
        self.xml=good.replace('</channel></rss>',cramer.split('<channel>')[1])
        items,_=h.collect_news({},self.now,{},self.fetch)
        for item in items:
            item.pop('_translate',None);item.pop('_excerpt',None)
            item.update(headlineKo=self.BROKEN if item['url']==self.url else '미국 주식 실적 호조에 상승',
                        summaryKo=self.SUMMARY if item['url']==self.url else '실적 호조로 미국 주가가 올랐습니다.',
                        translationStatus='ready',translationMethod='machine-translation',translationVersion='home-news-ko-v2')
        self.prior={'news':items}
        self.cramer=deepcopy(items[1])
        self.assertEqual(self.cramer['sourceHash'],'3ecf4d13dbcb6db6393ad01c811b7df2df36d1e6ac6dd4d53b40f3353782e605')

    def fetch(self,url):
        return self.xml if url==h.FEEDS[4][1] else '<rss><channel/></rss>'

    def fresh(self):
        item=deepcopy(self.cramer)
        for key in h.TRANSLATION_FIELDS:item.pop(key,None)
        item['_translate']=[self.TITLE,self.EXCERPT]
        return item

    def translator(self,batches):
        calls=[]
        def translate(texts):
            calls.append(texts)
            output=batches[len(calls)-1]
            if isinstance(output,Exception):raise output
            return output
        return translate,calls

    def quotes(self):
        return {s:{'symbol':s,'name':name,'status':'unavailable'} for s,name,_ in h.INDICES+h.SECTORS}

    def test_cramer_retries_once_with_simpler_input_and_keeps_first_summary(self):
        item=self.fresh();before=deepcopy(item)
        translate,calls=self.translator([[self.BROKEN,self.SUMMARY],[self.GOOD]])
        h.translate_news([item],Path('/unused'),translate)
        self.assertEqual(calls,[[self.TITLE,self.EXCERPT],[self.RETRY]])
        self.assertEqual(item['headlineKo'],self.GOOD);self.assertEqual(item['summaryKo'],self.SUMMARY)
        self.assertEqual(item['translationStatus'],'ready')
        for key in before:
            if key!='_translate':self.assertEqual(item[key],before[key])

    def test_failed_retry_uses_source_title_and_preserves_valid_summary_and_display_order(self):
        item=self.fresh()
        translate,calls=self.translator([[self.BROKEN,self.SUMMARY],['크레이머는 왜?']])
        h.translate_news([item],Path('/unused'),translate)
        self.assertEqual(calls,[[self.TITLE,self.EXCERPT],[self.RETRY]])
        self.assertEqual(item['headlineKo'],self.TITLE);self.assertEqual(item['summaryKo'],self.SUMMARY)
        self.assertEqual(item['translationStatus'],'headline-fallback')
        self.assertNotIn('_translate',item)
        news=[deepcopy(self.prior['news'][0]),item]
        snapshot=h.assemble(self.quotes(),news,[],{'buy':[],'sell':[]},self.now)
        self.assertEqual([a['url'] for a in snapshot['news']],[a['url'] for a in news])
        self.assertEqual(snapshot['news'][1]['summaryKo'],self.SUMMARY)
        for key in ['sourceHash','importance','importanceReason','title','publishedAt','firstPublishedAt']:
            self.assertEqual(snapshot['news'][1][key],self.cramer[key])
        again,_=h.collect_news({'news':news},self.now,{},self.fetch)
        self.assertTrue(all('_translate' not in a for a in again),'A completed failed quality retry is reusable')

    def test_retry_exception_or_count_mismatch_cannot_discard_first_summary(self):
        for failed in [TimeoutError(),[],[self.GOOD,self.GOOD]]:
            with self.subTest(failed=failed),patch('sys.stdout',io.StringIO()):
                item=self.fresh()
                translate,calls=self.translator([[self.BROKEN,self.SUMMARY],failed])
                h.translate_news([item],Path('/unused'),translate)
                self.assertEqual(len(calls),2);self.assertEqual(item['headlineKo'],self.TITLE)
                self.assertEqual(item['summaryKo'],self.SUMMARY)
                self.assertEqual(item['translationStatus'],'headline-fallback')
                again,_=h.collect_news({'news':[item]},self.now,{},self.fetch)
                self.assertEqual(again[1]['_translate'],[self.TITLE,None],'Availability failures must remain retryable')

    def test_mixed_batch_retries_only_bad_headline_without_shifting_summaries(self):
        good=deepcopy(self.prior['news'][0]);good['_translate']=[good['title'],good['sourceExcerpt']]
        item=self.fresh();summary='실적 호조로 미국 주가가 상승했습니다.'
        translate,calls=self.translator([['미국 주식 실적 호조에 상승',summary,self.BROKEN,self.SUMMARY],[self.GOOD]])
        h.translate_news([good,item],Path('/unused'),translate)
        self.assertEqual(calls,[[good['title'],good['sourceExcerpt'],self.TITLE,self.EXCERPT],[self.RETRY]])
        self.assertEqual(good['summaryKo'],summary);self.assertEqual(item['summaryKo'],self.SUMMARY)
        self.assertEqual(good['translationStatus'],'ready');self.assertEqual(item['translationStatus'],'ready')

    def test_only_failed_current_v2_cache_retranslates_headline_and_not_healthy_summary(self):
        items,_=h.collect_news(self.prior,self.now,{},self.fetch)
        self.assertNotIn('_translate',items[0]);self.assertEqual(items[1]['_translate'],[self.TITLE,None])
        translate,calls=self.translator([[self.BROKEN],[self.GOOD]])
        h.translate_news(items,Path('/unused'),translate)
        self.assertEqual(calls,[[self.TITLE],[self.RETRY]])
        self.assertEqual(items[0],self.prior['news'][0])
        self.assertEqual(items[1]['summaryKo'],self.SUMMARY)
        self.assertEqual(h.HOME_TRANSLATION_VERSION,'home-news-ko-v2')
        for before,after in zip(self.prior['news'],items):
            for key in ['url','title','sourceHash','importance','importanceReason','publishedAt','firstPublishedAt']:
                self.assertEqual(before[key],after[key])
        again,_=h.collect_news({'news':items},self.now,{},self.fetch)
        self.assertTrue(all('_translate' not in a for a in again))

    def test_source_fallback_cache_is_reused_but_changed_source_retranslates_both_fields(self):
        cached=deepcopy(self.prior)
        cached['news'][1].update(headlineKo=self.TITLE,translationStatus='headline-fallback',headlineFallbackVersion=h.HEADLINE_QUALITY_VERSION)
        items,_=h.collect_news(cached,self.now,{},self.fetch)
        self.assertTrue(all('_translate' not in a for a in items))
        cached['news'][1]['sourceHash']='different-source'
        changed,_=h.collect_news(cached,self.now,{},self.fetch)
        self.assertEqual(changed[1]['_translate'],[self.TITLE,self.EXCERPT])
        self.assertNotIn('summaryKo',changed[1])

    def test_healthy_headline_has_no_retry_and_bad_summary_cannot_be_displayed(self):
        for summary,status in [(self.SUMMARY,'ready'),('English only','unavailable')]:
            with self.subTest(summary=summary):
                item=self.fresh()
                translate,calls=self.translator([[self.GOOD,summary]])
                h.translate_news([item],Path('/unused'),translate)
                self.assertEqual(calls,[[self.TITLE,self.EXCERPT]])
                self.assertEqual(item['translationStatus'],status)
                self.assertEqual(h.usable_translation(item),status=='ready')

    def test_failed_feed_cache_is_gated_even_when_translation_is_disabled(self):
        def fetch(url):
            if url==h.FEEDS[4][1]:raise TimeoutError()
            return '<rss><channel/></rss>'
        items,_=h.collect_news(self.prior,self.now,{},fetch)
        self.assertEqual(items[1]['headlineKo'],self.TITLE)
        self.assertEqual(items[1]['translationStatus'],'headline-fallback')
        self.assertEqual(items[1]['summaryKo'],self.SUMMARY)
        self.assertEqual(items[1]['sourceHash'],self.cramer['sourceHash'])
        self.assertTrue(items[1]['fromCache']);self.assertEqual(items[1]['sourceStatus'],'unavailable')

    def test_initial_engine_failure_keeps_good_cached_summary_with_source_title(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);h.atomic(root/'market/home-cache.json',self.prior)
            translate,calls=self.translator([TimeoutError()])
            with patch.object(h,'home_rankings',return_value={'buy':[],'sell':[]}), \
                    patch.object(h,'prices',return_value=(self.quotes(),{})),patch('sys.stdout',io.StringIO()):
                snapshot=h.build(root,self.now,self.fetch,translate)
            self.assertEqual(calls,[[self.TITLE]])
            self.assertEqual(snapshot['news'][1]['headlineKo'],self.TITLE)
            self.assertEqual(snapshot['news'][1]['summaryKo'],self.SUMMARY)
            self.assertEqual(snapshot['news'][1]['translationStatus'],'headline-fallback')
            saved=json.loads((root/'market/home-cache.json').read_text())
            again,_=h.collect_news(saved,self.now,{},self.fetch)
            self.assertEqual(again[1]['_translate'],[self.TITLE,None])

    def test_disabled_translation_saves_safe_title_and_retries_only_that_title_on_recovery(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);h.atomic(root/'market/home-cache.json',self.prior)
            with patch.object(h,'home_rankings',return_value={'buy':[],'sell':[]}), \
                    patch.object(h,'prices',return_value=(self.quotes(),{})),patch('sys.stdout',io.StringIO()):
                fallback=h.build(root,self.now,self.fetch,translate_enabled=False)
                self.assertEqual(fallback['news'][1]['headlineKo'],self.TITLE)
                self.assertEqual(fallback['news'][1]['summaryKo'],self.SUMMARY)
                self.assertEqual(fallback['news'][1]['translationStatus'],'headline-fallback')
                translate,calls=self.translator([[self.GOOD]])
                recovered=h.build(root,self.now,self.fetch,translate)
            self.assertEqual(calls,[[self.TITLE]])
            self.assertEqual(recovered['news'][1]['translationStatus'],'ready')
            self.assertEqual(recovered['news'][1]['headlineKo'],self.GOOD)
            self.assertEqual(recovered['news'][1]['summaryKo'],self.SUMMARY)
            self.assertNotIn('headlineFallbackVersion',recovered['news'][1])


class HeadlineMeaning(unittest.TestCase):
    """Exact October 6 production sources, bad titles, summaries and hashes."""
    GOOD={
        'd71f54fdb885c57e438b68ad86343a916632af52ab20be811a51effdacbc402c':
            '투자자들이 FOMC 의사록 공개를 기다리는 가운데 미국 국채 금리는 보합',
        '90e81fb981891316e63fd7fc0b8deda42e7ccca5766d9bcc1d08dc4ecab2ffed':
            '퀀트 펀드가 선제적이고 역발상적인 투자로 시장을 이긴 방법',
        'cd5b6abdfb88c01254b3de9f3a3238b6b8b36f6cff09389efd08a65bc7d38f3d':
            '우드 그룹 해상 노동자, 임금 갈등으로 48시간 파업',
        '15ec28bf103c462504f1a5aa239bf5894f22807c69c980d90d7a17e58de4c8df':
            '포트 후드 총격범 총살형 집행 예정, 미군에서 2차 세계대전 이후 처음',
    }

    def setUp(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/market-headline-terms.json').read_text())
        self.now=h.stamp(fixture['observedAt'])
        self.prior={'news':fixture['news']}
        self.bad=[a for a in self.prior['news'] if a['sourceHash'] in self.GOOD]
        self.assertEqual(len(self.bad),4)
        for item in self.bad:
            self.assertEqual(h.sha256((item['title']+'\n'+item['sourceExcerpt']).encode()).hexdigest(),item['sourceHash'])
            if not item['title'].startswith('Fort Hood'):
                self.assertTrue(h.valid_korean_headline(item['headlineKo']))
            self.assertFalse(h.valid_korean_headline(item['headlineKo'],item['title']))

    def fetch(self,url):
        spec=next((source for source,feed in h.FEEDS if feed==url),None)
        if spec is None:raise AssertionError('Unexpected fixture request: '+url)
        rows=[a for a in self.prior['news'] if a['source']==spec]
        return '<rss><channel>'+''.join(
            rss(escape(a['title']),escape(a['url']),h.stamp(a['publishedAt']).strftime('%a, %d %b %Y %H:%M:%S GMT'),
                escape(a['sourceExcerpt'])).split('<channel>')[1].split('</channel>')[0] for a in rows)+'</channel></rss>'

    def translator(self,batches):
        calls=[]
        def translate(texts):
            calls.append(texts)
            output=batches[len(calls)-1]
            if isinstance(output,Exception):raise output
            return output
        return translate,calls

    def assert_preserved(self,before,after):
        changed={'headlineKo','translationStatus','headlineFallbackVersion'}
        self.assertEqual({k:v for k,v in before.items() if k not in changed},
                         {k:v for k,v in after.items() if k not in changed})

    def assert_display_order(self,items):
        quotes={s:{'symbol':s,'name':name,'status':'unavailable'} for s,name,_ in h.INDICES+h.SECTORS}
        public=h.assemble(quotes,items,[],{'buy':[],'sell':[]},self.now)['news']
        self.assertEqual([a['url'] for a in public],[a['url'] for a in self.prior['news']])
        self.assertEqual([a['summaryKo'] for a in public],[a['summaryKo'] for a in self.prior['news']])

    def test_actual_v2_cache_retranslates_only_bad_titles_and_preserves_rest(self):
        items,_=h.collect_news(self.prior,self.now,{},self.fetch)
        queued=[a for a in items if a.get('_translate')]
        self.assertEqual([a['_translate'] for a in queued],[[a['title'],None] for a in self.bad])
        translate,calls=self.translator([[a['headlineKo'] for a in self.bad],
                                        [self.GOOD[a['sourceHash']] for a in self.bad]])
        h.translate_news(items,Path('/unused'),translate)
        self.assertEqual(calls,[[a['title'] for a in self.bad],
                               [h.simpler_headline_input(a['title'],a['sourceExcerpt']) for a in self.bad]])
        for before,after in zip(self.prior['news'],items):
            self.assert_preserved(before,after)
            self.assertEqual(after['translationStatus'],'ready')
            self.assertEqual(after['headlineKo'],self.GOOD.get(before['sourceHash'],before['headlineKo']))
        self.assert_display_order(items)
        again,_=h.collect_news({'news':items},self.now,{},self.fetch)
        self.assertTrue(all('_translate' not in a for a in again))

    def test_repeated_semantic_errors_use_exact_source_fallback_and_keep_summaries(self):
        items,_=h.collect_news(self.prior,self.now,{},self.fetch)
        wrong=[a['headlineKo'] for a in self.bad]
        translate,calls=self.translator([wrong,wrong])
        h.translate_news(items,Path('/unused'),translate)
        self.assertEqual(len(calls),2)
        for before,after in zip(self.prior['news'],items):
            self.assert_preserved(before,after)
            if before['sourceHash'] in self.GOOD:
                self.assertEqual(after['headlineKo'],before['title'])
                self.assertEqual(after['translationStatus'],'headline-fallback')
                self.assertEqual(after['headlineFallbackVersion'],h.HEADLINE_QUALITY_VERSION)
            else:self.assertEqual(after,before)
        self.assert_display_order(items)
        again,_=h.collect_news({'news':items},self.now,{},self.fetch)
        self.assertTrue(all('_translate' not in a for a in again))

    def test_post_normalization_semantic_errors_retry_and_fallback_without_changing_metadata(self):
        items,_=h.collect_news(self.prior,self.now,{},self.fetch)
        fomc='미국 정부 채권 금리율은 투자자들이 연방준비은행의 통화정책 회의에 대한 기록적인 기록을 예상하기 때문에 대체로 일정합니다.'
        quant="수학 및 통계적 거래 전략을 이용한 투자펀드가 '초기, 역동적이고 올바른'로 시장을 이길 수 있는 방법"
        translate,calls=self.translator([[fomc,quant,*[self.GOOD[a['sourceHash']] for a in self.bad[2:]]],[fomc,quant]])
        h.translate_news(items,Path('/unused'),translate)
        self.assertEqual(len(calls),2)
        self.assertEqual(len(calls[1]),2)
        for before,after in zip(self.prior['news'],items):
            self.assert_preserved(before,after)
            if before['sourceHash'] in [a['sourceHash'] for a in self.bad[:2]]:
                self.assertEqual(after['headlineKo'],before['title'])
                self.assertEqual(after['translationStatus'],'headline-fallback')
        self.assert_display_order(items)

    def test_fresh_mixed_batch_has_no_summary_or_retry_index_shift(self):
        items=deepcopy(self.prior['news']);outputs=[]
        for item in items:
            for key in h.TRANSLATION_FIELDS:item.pop(key,None)
            item['_translate']=[item['title'],item['sourceExcerpt']]
        for item in self.prior['news']:outputs.extend([item['headlineKo'],item['summaryKo']])
        translate,calls=self.translator([outputs,[self.GOOD[a['sourceHash']] for a in self.bad]])
        h.translate_news(items,Path('/unused'),translate)
        self.assertEqual(calls[0],[text for a in self.prior['news'] for text in [a['title'],a['sourceExcerpt']]])
        self.assertEqual(len(calls[1]),4)
        for before,after in zip(self.prior['news'],items):self.assert_preserved(before,after)
        self.assert_display_order(items)

    def test_semantic_retry_failure_keeps_summary_and_remains_retryable(self):
        for failed in [TimeoutError(),[],['해상 노동자 파업']*5]:
            with self.subTest(failed=failed),patch('sys.stdout',io.StringIO()):
                items,_=h.collect_news(self.prior,self.now,{},self.fetch)
                translate,_=self.translator([[a['headlineKo'] for a in self.bad],failed])
                h.translate_news(items,Path('/unused'),translate)
                again,_=h.collect_news({'news':items},self.now,{},self.fetch)
                for before,after in zip(self.prior['news'],items):
                    self.assert_preserved(before,after)
                    if before['sourceHash'] in self.GOOD:
                        self.assertEqual(after['headlineKo'],before['title'])
                        self.assertEqual(after['translationStatus'],'headline-fallback')
                        self.assertNotIn('headlineFallbackVersion',after)
                self.assertEqual([a['_translate'] for a in again if a.get('_translate')],[[a['title'],None] for a in self.bad])

    def test_failed_feeds_and_disabled_model_guard_semantics_and_recover(self):
        def fail(_):raise TimeoutError()
        with TemporaryDirectory() as folder,patch('sys.stdout',io.StringIO()):
            root=Path(folder);h.atomic(root/'market/home-cache.json',self.prior)
            quotes={s:{'symbol':s,'name':name,'status':'unavailable'} for s,name,_ in h.INDICES+h.SECTORS}
            with patch.object(h,'home_rankings',return_value={'buy':[],'sell':[]}),patch.object(h,'prices',return_value=(quotes,{})):
                public=h.build(root,self.now,fail,translate_enabled=False)
                for item in public['news']:
                    if item['sourceHash'] in self.GOOD:
                        self.assertEqual(item['headlineKo'],item['title'])
                        self.assertEqual(item['translationStatus'],'headline-fallback')
                self.assertEqual([a['summaryKo'] for a in public['news']],[a['summaryKo'] for a in self.prior['news']])
                translate,calls=self.translator([[self.GOOD[a['sourceHash']] for a in self.bad]])
                recovered=h.build(root,self.now,self.fetch,translate)
                self.assertEqual(calls,[[a['title'] for a in self.bad]])
                self.assertTrue(all(a['translationStatus']=='ready' for a in recovered['news']))
                self.assertEqual([a['summaryKo'] for a in recovered['news']],[a['summaryKo'] for a in self.prior['news']])

    def test_source_changes_retranslate_both_fields_and_old_quality_fallback_retries(self):
        old=deepcopy(self.prior)
        for item in old['news']:
            if item['sourceHash'] in self.GOOD:
                item.update(headlineKo=item['title'],translationStatus='headline-fallback',
                            headlineFallbackVersion='home-headline-quality-v1')
        items,_=h.collect_news(old,self.now,{},self.fetch)
        self.assertEqual([a['_translate'] for a in items if a.get('_translate')],[[a['title'],None] for a in self.bad])
        old['news'][0]['sourceHash']='changed-source'
        changed,_=h.collect_news(old,self.now,{},self.fetch)
        self.assertEqual(changed[0]['_translate'],[self.bad[0]['title'],self.bad[0]['sourceExcerpt']])
        self.assertNotIn('summaryKo',changed[0])
        self.assertEqual(h.HOME_TRANSLATION_VERSION,'home-news-ko-v2')

    def test_assembly_cannot_display_legacy_ready_semantic_errors(self):
        for item in self.bad:self.assertFalse(h.usable_translation(item))
        self.assertTrue(all(h.usable_translation(a) for a in self.prior['news'] if a not in self.bad))

    def test_excerpt_only_terms_do_not_force_title_to_repeat_summary(self):
        item=deepcopy(self.bad[0])
        item.update(title='Treasury yields are flat',headlineKo='국채 금리 보합',
                    sourceExcerpt='Investors await FOMC minutes.',summaryKo='투자자들은 연준 의사록 공개를 기다립니다.')
        before=deepcopy(item)
        translate,calls=self.translator([])
        h.translate_news([item],Path('/unused'),translate)
        self.assertEqual(calls,[])
        self.assertEqual(item,before)


class HeadlineFirst(unittest.TestCase):
    """Exact retained BBC regression between two healthy production headlines."""
    GOOD='포트 후드 총격범 총살형 집행 예정, 미군에서 2차 세계대전 이후 처음'
    RETRY=('Fort Hood gunman will be executed by firing squad. '
           'This will be the first such event for US military since World War Two.')

    def setUp(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/market-headline-first.json').read_text())
        self.now=h.stamp(fixture['observedAt'])
        self.prior={'news':fixture['news']}
        self.bbc=self.prior['news'][1]
        self.assertEqual(self.bbc['headlineKo'],'포트 후드 총기 사격단은 2차 세계대전 이후 처음으로')
        self.assertEqual(h.sha256((self.bbc['title']+'\n'+self.bbc['sourceExcerpt']).encode()).hexdigest(),
                         self.bbc['sourceHash'])

    def fetch(self,url):
        source=next(source for source,feed in h.FEEDS if feed==url)
        rows=[a for a in self.prior['news'] if a['source']==source]
        return '<rss><channel>'+''.join(
            rss(escape(a['title']),escape(a['url']),h.stamp(a['publishedAt']).strftime('%a, %d %b %Y %H:%M:%S GMT'),
                escape(a['sourceExcerpt'])).split('<channel>')[1].split('</channel>')[0] for a in rows)+'</channel></rss>'

    def assert_preserved_and_ordered(self,items):
        changed={'headlineKo','translationStatus','headlineFallbackVersion'}
        for before,after in zip(self.prior['news'],items):
            self.assertEqual({k:v for k,v in before.items() if k not in changed},
                             {k:v for k,v in after.items() if k not in changed})
        quotes={s:{'symbol':s,'name':name,'status':'unavailable'} for s,name,_ in h.INDICES+h.SECTORS}
        public=h.assemble(quotes,items,[],{'buy':[],'sell':[]},self.now)['news']
        self.assertEqual([a['url'] for a in public],[a['url'] for a in self.prior['news']])
        self.assertEqual([a['summaryKo'] for a in public],[a['summaryKo'] for a in self.prior['news']])

    def test_current_cache_retries_only_bbc_title_and_checks_retry_before_ready(self):
        for retried in [self.GOOD,self.bbc['headlineKo'],'미군, 2차 세계대전 이후 최초로.']:
            with self.subTest(retried=retried):
                items,_=h.collect_news(self.prior,self.now,{},self.fetch)
                self.assertEqual([a['_translate'] for a in items if a.get('_translate')],[[self.bbc['title'],None]])
                calls=[]
                def translate(texts):
                    calls.append(texts)
                    return [self.bbc['headlineKo']] if len(calls)==1 else [retried]
                h.translate_news(items,Path('/unused'),translate)
                self.assertEqual(calls,[[self.bbc['title']],[self.RETRY]])
                safe=retried==self.GOOD
                self.assertEqual(items[1]['headlineKo'],self.GOOD if safe else self.bbc['title'])
                self.assertEqual(items[1]['translationStatus'],'ready' if safe else 'headline-fallback')
                self.assert_preserved_and_ordered(items)
                again,_=h.collect_news({'news':items},self.now,{},self.fetch)
                self.assertTrue(all('_translate' not in a for a in again))
        self.assertEqual(h.HOME_TRANSLATION_VERSION,'home-news-ko-v2')

    def test_fresh_mixed_batch_retains_summaries_and_retries_the_correct_title(self):
        items=deepcopy(self.prior['news'])
        for item in items:
            for key in h.TRANSLATION_FIELDS:item.pop(key,None)
            item['_translate']=[item['title'],item['sourceExcerpt']]
        calls=[]
        def translate(texts):
            calls.append(texts)
            return ([text for a in self.prior['news'] for text in [a['headlineKo'],a['summaryKo']]]
                    if len(calls)==1 else [self.GOOD])
        h.translate_news(items,Path('/unused'),translate)
        self.assertEqual(calls,[[text for a in self.prior['news'] for text in [a['title'],a['sourceExcerpt']]],[self.RETRY]])
        self.assertEqual(items[1]['headlineKo'],self.GOOD)
        self.assert_preserved_and_ordered(items)

    def test_failed_feed_and_disabled_translator_still_use_source_fallback(self):
        def fail(_):raise TimeoutError()
        items,_=h.collect_news(self.prior,self.now,{},fail)
        self.assertEqual(items[1]['headlineKo'],self.bbc['title'])
        self.assertEqual(items[1]['translationStatus'],'headline-fallback')
        self.assertEqual(items[1]['_translate'],[self.bbc['title'],None])
        with TemporaryDirectory() as folder,patch('sys.stdout',io.StringIO()):
            root=Path(folder);h.atomic(root/'market/home-cache.json',self.prior)
            quotes={s:{'symbol':s,'name':name,'status':'unavailable'} for s,name,_ in h.INDICES+h.SECTORS}
            with patch.object(h,'home_rankings',return_value={'buy':[],'sell':[]}),patch.object(h,'prices',return_value=(quotes,{})):
                public=h.build(root,self.now,self.fetch,translate_enabled=False)['news']
        self.assertEqual(public[1]['headlineKo'],self.bbc['title'])
        self.assertEqual(public[1]['translationStatus'],'headline-fallback')
        self.assertEqual([a['summaryKo'] for a in public],[a['summaryKo'] for a in self.prior['news']])
        for before,after in zip(self.prior['news'],public):
            for key in ['url','title','sourceHash','importance','importanceReason','publishedAt','firstPublishedAt']:
                self.assertEqual(before[key],after[key])


class PriceCache(unittest.TestCase):
    def test_failure_preserves_success_time_recalculates_week_and_then_expires(self):
        rows=[{'date':'2026-09-25','close':100},{'date':'2026-10-01','close':105},{'date':'2026-10-02','close':110}]
        prior={'quotes':{s:{'rows':rows,'lastSuccessAt':'2026-10-02T22:00:00+00:00'} for s,_,_ in h.INDICES+h.SECTORS}}
        def fail(_):raise TimeoutError()
        quotes,_=h.prices(prior,NOW,fail)
        self.assertTrue(all(q['fromCache'] and q['status']=='unavailable' for q in quotes.values()))
        self.assertEqual(quotes['XLK']['lastSuccessAt'],'2026-10-02T22:00:00+00:00')
        monday,_=h.prices(prior,datetime(2026,10,5,13,tzinfo=timezone.utc),fail)
        self.assertIsNone(monday['XLK']['week'])
        expired,_=h.prices(prior,NOW+timedelta(days=7),fail)
        self.assertFalse(expired['XLK']['fromCache']);self.assertNotIn('day',expired['XLK'])

    def test_both_feeds_recover_to_new_results(self):
        def fetch(url):
            if url==h.FEEDS[0][1]:return rss(url='https://www.federalreserve.gov/newsevents/pressreleases/new.htm')
            if url==h.FEEDS[1][1]:return rss(url='https://www.federalreserve.gov/newsevents/speech/new.htm')
            if url in [f[1] for f in h.FEEDS]:return '<rss><channel/></rss>'
            return '<p>The economy expanded while inflation remained above target.</p>'
        items,feeds=h.collect_news({},NOW,{},fetch)
        self.assertEqual(len(items),2);self.assertTrue(all(not a['fromCache'] for a in items))
        self.assertTrue(all(f['status']=='ready' for f in feeds))


class RankingPublication(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        (self.root/'market').mkdir()
        self.path=self.root/'market/home.json'
        self.cache=self.root/'market/home-cache.json'
        self.previous={'schemaVersion':1,'generatedAt':'2026-10-03T22:00:00Z','rankings':{'buy':[],'sell':[]},
                       'news':[{'headlineKo':'기존 뉴스'}],'recap':{'asOf':'2026-10-02'},'brief':'기존 요약'}
        h.atomic(self.path,self.previous)
        self.cache.write_bytes(b'{"sentinel": "preserve cache bytes"}\n')
        self.ranks={'buy':[{'symbol':'AAPL','asOf':'2026-10-02','code':'breakout'}],
                    'sell':[{'symbol':'APP','asOf':'2026-10-02','holdingCode':'reduce'}],
                    'asOf':'2026-10-02','evaluatedAt':'2026-10-04T09:00:00Z'}

    def run_refresh(self, ranks, now=NOW):
        with patch.object(h,'home_rankings',return_value=ranks), patch.object(h,'get',side_effect=AssertionError('No network')), patch('sys.stdout',io.StringIO()):
            return h.refresh_rankings(self.root,now)

    def test_rankings_publish_before_news_without_changing_other_data_or_cache(self):
        original_cache=self.cache.read_bytes()
        result=self.run_refresh(self.ranks)
        self.assertEqual(result['rankings'],self.ranks)
        for key in ('schemaVersion','news','recap','brief'):self.assertEqual(result[key],self.previous[key])
        self.assertEqual(result['generatedAt'],NOW.isoformat())
        self.assertEqual(self.cache.read_bytes(),original_cache)
        self.assertEqual(json.loads(self.path.read_text()),result)

    def test_ranking_only_clock_changes_do_not_write(self):
        saved=self.run_refresh(self.ranks)
        original=self.path.read_bytes()
        with patch.object(h,'atomic') as atomic:
            result=self.run_refresh({**self.ranks,'evaluatedAt':'2026-10-04T10:00:00Z'},NOW+timedelta(hours=1))
        atomic.assert_not_called()
        self.assertEqual(result,saved)
        self.assertEqual(self.path.read_bytes(),original)

    def test_failed_rankings_preserve_saved_snapshot(self):
        original=self.path.read_bytes()
        with patch.object(h,'home_rankings',side_effect=RuntimeError('Invalid input')):
            with self.assertRaises(RuntimeError):h.refresh_rankings(self.root,NOW)
        self.assertEqual(self.path.read_bytes(),original)


class SemanticPublication(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.now=datetime(2026,10,4,9,34,tzinfo=timezone.utc) # Sunday, same Friday closes
        self.failed=set()
        self.title='U.S. economy outlook'
        self.headline='미국 경제 전망 발표'
        self.summary='경제는 성장했고 물가는 목표 위에 머물렀다.'
        self.url='https://www.federalreserve.gov/newsevents/speech/test.htm'
        self.rows=[{'date':d,'close':v} for d,v in [('2026-09-25',100),('2026-09-28',105),('2026-10-01',110),('2026-10-02',120)]]
        self.rankings={'buy':[],'sell':[{'symbol':s,'name':s,'asOf':'2026-10-02'} for s in ['AON','APP','CCI']],
                       'priceGeneratedAt':'2026-10-04T01:27:08+00:00','marketGeneratedAt':'2026-10-04T09:15:59+00:00',
                       'basis':'technical-rules','priceMaxAgeDays':5,'marketMaxAgeDays':3}

    def fetch(self, url):
        if url in self.failed or any('/chart/'+s+'?' in url for s in self.failed):raise TimeoutError()
        if '/v8/finance/chart/' in url:
            timestamps=[int(datetime.fromisoformat(r['date']+'T13:30:00+00:00').timestamp()) for r in self.rows]
            return json.dumps({'chart':{'result':[{'timestamp':timestamps,'indicators':{'quote':[{'close':[r['close'] for r in self.rows]}]}}]}})
        if url==h.FEEDS[0][1]:return rss(self.title,self.url)
        if url in [f[1] for f in h.FEEDS]:return '<rss><channel/></rss>'
        if url==self.url:return '<p>The economy expanded while inflation remained above target.</p>'
        raise AssertionError('Unexpected fixture URL: '+url)

    def build(self, now):
        h.atomic(self.root/'market/home-reviewed-news.json',{
            self.url:{'title':self.title,'evidence':['inflation remained above target'],
                      'headline':self.headline,'summary':self.summary}})
        rankings={**self.rankings,'evaluatedAt':now.isoformat()}
        output=io.StringIO()
        with patch.object(h.subprocess,'check_output',return_value=json.dumps(rankings)), patch('sys.stdout',output):
            snapshot=h.build(self.root,now,self.fetch,translate_enabled=False)
        return snapshot,json.loads(output.getvalue())

    def files(self):
        return tuple((p.read_bytes(),p.stat().st_mtime_ns) for p in [self.root/'market/home.json',self.root/'market/home-cache.json'])

    def cache(self):
        return json.loads((self.root/'market/home-cache.json').read_text())

    def test_complete_no_op_keeps_both_files_bytes_and_mtimes_and_logs_attempt(self):
        first,log=self.build(self.now)
        self.assertTrue(log['changed'])
        before=self.files()
        later=self.now+timedelta(hours=1)
        with patch.object(h,'atomic',wraps=h.atomic) as write:
            second,log=self.build(later)
        # Only the test's review fixture is written; neither generated file is.
        self.assertEqual([c.args[0].name for c in write.call_args_list],['home-reviewed-news.json'])
        self.assertFalse(log['changed']);self.assertEqual(log['attemptedAt'],later.isoformat())
        self.assertEqual(log['generatedAt'],first['generatedAt'])
        self.assertEqual(first,second);self.assertEqual(before,self.files())

    def test_weekend_news_change_publishes_and_identical_next_poll_does_not(self):
        first,_=self.build(self.now)
        self.title='U.S. economy and inflation outlook'
        self.headline='미국 경제·물가 전망 갱신'
        self.summary='갱신된 경제 전망은 물가가 목표를 넘고 있다고 설명했다.'
        later=self.now+timedelta(hours=1)
        second,log=self.build(later)
        self.assertTrue(log['changed']);self.assertEqual(second['generatedAt'],later.isoformat())
        self.assertEqual(second['news'][0]['headlineKo'],self.headline)
        self.assertNotEqual(first['news'][0]['sourceHash'],second['news'][0]['sourceHash'])
        self.assertEqual(self.cache()['news'][0]['summaryKo'],self.summary)
        before=self.files()
        _,log=self.build(later+timedelta(hours=1))
        self.assertFalse(log['changed']);self.assertEqual(before,self.files())

    def test_news_only_change_keeps_quote_cache_order_despite_completion_order(self):
        symbols=[s for s,_,_ in h.INDICES+h.SECTORS]
        with patch.object(h,'as_completed',side_effect=lambda futures:iter(futures)):
            first,_=self.build(self.now)
        original=self.cache()['quotes']
        self.assertEqual(list(original),symbols)
        self.title='U.S. economy and inflation outlook'
        self.headline='미국 경제·물가 전망 갱신'
        later=self.now+timedelta(hours=1)
        with patch.object(h,'as_completed',side_effect=lambda futures:reversed(futures)):
            second,log=self.build(later)
        updated=self.cache()['quotes']
        self.assertTrue(log['changed'])
        self.assertNotEqual(first['news'][0]['sourceHash'],second['news'][0]['sourceHash'])
        self.assertEqual(second['news'][0]['headlineKo'],self.headline)
        self.assertEqual(list(updated),symbols)
        self.assertEqual(h.semantic_content(original),h.semantic_content(updated))
        self.assertEqual(h.semantic_content(first['recap']),h.semantic_content(second['recap']))
        for key,specs in [('indices',h.INDICES),('sectors',h.SECTORS)]:
            self.assertEqual([q['symbol'] for q in second['recap'][key]],[s for s,_,_ in specs])
        before=self.files()
        with patch.object(h,'as_completed',side_effect=lambda futures:iter(futures[::2]+futures[1::2])):
            _,log=self.build(later+timedelta(hours=1))
        self.assertFalse(log['changed']);self.assertEqual(before,self.files())

    def test_legacy_quote_key_order_is_preserved_on_no_op_until_news_changes(self):
        first,_=self.build(self.now)
        cache=self.cache()
        cache['quotes']=dict(reversed(list(cache['quotes'].items())))
        h.atomic(self.root/'market/home-cache.json',cache)
        before=self.files()
        saved,log=self.build(self.now+timedelta(hours=1))
        self.assertFalse(log['changed']);self.assertEqual(before,self.files())
        self.assertEqual(saved,first)
        self.title='U.S. economy and inflation outlook'
        self.headline='미국 경제·물가 전망 갱신'
        with patch.object(h,'as_completed',side_effect=lambda futures:reversed(futures)):
            _,log=self.build(self.now+timedelta(hours=2))
        self.assertTrue(log['changed'])
        self.assertEqual(list(self.cache()['quotes']),[s for s,_,_ in h.INDICES+h.SECTORS])
        self.assertEqual(h.semantic_content(cache['quotes']),h.semantic_content(self.cache()['quotes']))

    def test_feed_failure_repeated_failure_and_recovery_publish_only_transitions(self):
        first,_=self.build(self.now)
        self.failed.add(h.FEEDS[0][1])
        failed,log=self.build(self.now+timedelta(hours=1))
        self.assertTrue(log['changed'])
        self.assertEqual([f['status'] for f in failed['feeds']],['unavailable']+['ready']*(len(h.FEEDS)-1))
        self.assertEqual(failed['feeds'][0]['lastSuccessAt'],first['feeds'][0]['lastSuccessAt'])
        self.assertTrue(failed['news'][0]['fromCache'])
        self.assertEqual(failed['news'][0]['sourceStatus'],'unavailable')
        self.assertEqual(failed['news'][0]['summaryKo'],first['news'][0]['summaryKo'])
        self.assertEqual(failed['news'][0]['firstPublishedAt'],first['news'][0]['firstPublishedAt'])
        before=self.files()
        _,log=self.build(self.now+timedelta(hours=2))
        self.assertFalse(log['changed']);self.assertEqual(before,self.files())
        self.failed.clear()
        recovery=self.now+timedelta(hours=3)
        recovered,log=self.build(recovery)
        self.assertTrue(log['changed']);self.assertTrue(all(f['status']=='ready' for f in recovered['feeds']))
        self.assertFalse(recovered['news'][0]['fromCache']);self.assertEqual(recovered['news'][0]['sourceStatus'],'ready')
        self.assertEqual(self.cache()['feeds'][0]['lastSuccessAt'],recovery.isoformat())
        before=self.files()
        _,log=self.build(recovery+timedelta(hours=1))
        self.assertFalse(log['changed']);self.assertEqual(before,self.files())
        self.failed.add(h.FEEDS[0][1])
        failed,log=self.build(recovery+timedelta(hours=2))
        self.assertTrue(log['changed']);self.assertEqual(failed['feeds'][0]['lastSuccessAt'],recovery.isoformat())

    def test_quote_failure_and_recovery_keep_fallback_and_new_success_time(self):
        first,_=self.build(self.now)
        self.failed.add('XLK')
        failed,log=self.build(self.now+timedelta(hours=1))
        quote=failed['recap']['sectors'][0]
        self.assertTrue(log['changed']);self.assertEqual(quote['status'],'unavailable');self.assertTrue(quote['fromCache'])
        self.assertEqual(quote['day'],first['recap']['sectors'][0]['day'])
        self.assertEqual(quote['lastSuccessAt'],self.now.isoformat())
        before=self.files()
        _,log=self.build(self.now+timedelta(hours=2))
        self.assertFalse(log['changed']);self.assertEqual(before,self.files())
        self.failed.clear()
        recovery=self.now+timedelta(hours=3)
        recovered,log=self.build(recovery)
        self.assertTrue(log['changed']);self.assertEqual(recovered['recap']['sectors'][0]['status'],'ready')
        self.assertFalse(recovered['recap']['sectors'][0]['fromCache'])
        self.assertEqual(self.cache()['quotes']['XLK']['lastSuccessAt'],recovery.isoformat())
        before=self.files()
        _,log=self.build(recovery+timedelta(hours=1))
        self.assertFalse(log['changed']);self.assertEqual(before,self.files())
        self.failed.add('XLK')
        failed,log=self.build(recovery+timedelta(hours=2))
        self.assertTrue(log['changed']);self.assertEqual(failed['recap']['sectors'][0]['lastSuccessAt'],recovery.isoformat())

    def test_meaningful_fields_and_array_order_are_not_ignored(self):
        snapshot,_=self.build(self.now)
        cache=self.cache()
        changes=[
            ('rankings','buy',[{'symbol':'AAPL','name':'애플','asOf':'2026-10-02'}]),
            ('rankings','sell',list(reversed(snapshot['rankings']['sell']))),
            ('rankings','marketGeneratedAt','2026-10-04T10:15:59+00:00'),
            ('rankings','priceGeneratedAt','2026-10-04T02:27:08+00:00'),
            ('recap','asOf','2026-10-01'),('recap','weekStart','2026-10-05'),
            ('recap','weekComplete',False),('newsPolicy','breakingMaxAgeHours',1),('newsPolicy','displayOrder','importance-first'),
        ]
        changes += [('recap','sectors', [{**snapshot['recap']['sectors'][0],key:value}]+snapshot['recap']['sectors'][1:])
                    for key,value in [('close',121),('day',10),('week',21),('asOf','2026-10-01'),
                                      ('dayBaseDate','2026-09-30'),('weekBaseDate','2026-09-24'),
                                      ('status','unavailable'),('fromCache',True)]]
        changes += [('news',0,{**snapshot['news'][0],key:value}) for key,value in [
            ('publishedAt','2026-10-02T17:00:00+00:00'),('firstPublishedAt','2026-10-01T17:00:00+00:00'),
            ('url','https://www.bbc.com/news/articles/new'),('headlineKo','새로운 한국어 제목'),
            ('summaryKo','갱신된 요약 내용'),('importance','important'),('translationStatus','unavailable'),
            ('sourceStatus','unavailable'),('fromCache',True),('sourceHash','revised-source')]]
        changes += [('feeds',0,{**snapshot['feeds'][0],key:value}) for key,value in [
            ('status','unavailable'),('fromCache',True),('error','TimeoutError')]]
        for section,key,value in changes:
            with self.subTest(section=section,key=key,value=value):
                altered=deepcopy(snapshot);altered[section][key]=value
                self.assertNotEqual(h.semantic_content(altered),h.semantic_content(snapshot))
                _,changed=h.publish_if_changed(self.root,altered,cache)
                self.assertTrue(changed)
                h.publish_if_changed(self.root,snapshot,cache)
        for key,value in [('brief','섹터 혼조'),('schemaVersion',2),('newField','new-value')]:
            with self.subTest(key=key):
                altered={**snapshot,key:value}
                self.assertTrue(h.publish_if_changed(self.root,altered,cache)[1])
                h.publish_if_changed(self.root,snapshot,cache)

    def test_only_polling_timestamps_and_object_key_order_are_ignored(self):
        snapshot,_=self.build(self.now)
        cache=self.cache()
        def change_clocks(value):
            if isinstance(value,dict):
                return {k:('2030-01-01T00:00:00+00:00' if k in h.POLLING_TIMESTAMPS else change_clocks(v))
                        for k,v in reversed(list(value.items()))}
            if isinstance(value,list):return [change_clocks(v) for v in value]
            return value
        before=self.files()
        with patch.object(h,'atomic',wraps=h.atomic) as write:
            saved,changed=h.publish_if_changed(self.root,change_clocks(snapshot),change_clocks(cache))
        self.assertFalse(changed);write.assert_not_called()
        self.assertEqual(saved,snapshot);self.assertEqual(before,self.files())

    def test_cache_only_news_and_price_history_changes_are_persisted(self):
        snapshot,_=self.build(self.now)
        original=self.cache()
        for kind in ['news','quotes']:
            with self.subTest(kind=kind):
                cache=deepcopy(original)
                if kind=='news':cache['news'].append({**cache['news'][0],'url':'https://www.bbc.com/news/articles/cached-only'})
                else:cache['quotes']['XLK']['rows'][1]['close']=106
                _,changed=h.publish_if_changed(self.root,snapshot,cache)
                self.assertTrue(changed);self.assertEqual(self.cache(),cache)
                h.publish_if_changed(self.root,snapshot,original)

    def test_missing_file_or_invalid_public_json_cannot_be_a_no_op(self):
        snapshot,_=self.build(self.now)
        cache=self.cache()
        for name in ['home.json','home-cache.json']:
            with self.subTest(name=name):
                (self.root/'market'/name).unlink()
                self.assertTrue(h.publish_if_changed(self.root,snapshot,cache)[1])
                self.assertEqual(json.loads((self.root/'market/home.json').read_text()),snapshot)
                self.assertEqual(self.cache(),cache)
        (self.root/'market/home.json').write_text('{invalid')
        self.assertTrue(h.publish_if_changed(self.root,snapshot,cache)[1])

    def test_new_week_and_expired_fallback_still_publish(self):
        self.build(self.now)
        monday=datetime(2026,10,5,13,tzinfo=timezone.utc)
        snapshot,log=self.build(monday)
        self.assertTrue(log['changed']);self.assertEqual(snapshot['recap']['weekStart'],'2026-10-05')
        self.assertIsNone(snapshot['recap']['sectors'][0]['week'])
        self.failed.add('XLK')
        self.build(monday+timedelta(hours=1))
        snapshot,log=self.build(datetime(2026,10,8,13,tzinfo=timezone.utc))
        quote=snapshot['recap']['sectors'][0]
        self.assertTrue(log['changed']);self.assertFalse(quote['fromCache']);self.assertNotIn('day',quote)


if __name__=='__main__':unittest.main()
