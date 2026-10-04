from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

import build_market_home as h

NOW=datetime(2026,10,3,23,tzinfo=timezone.utc)


def rss(title='U.S. economy outlook', url='https://www.federalreserve.gov/newsevents/speech/test.htm', published='Fri, 02 Oct 2026 16:00:00 GMT'):
    return '<rss><channel><item><title>'+title+'</title><link>'+url+'</link><pubDate>'+published+'</pubDate><description>The economy grew while inflation remained above target.</description></item></channel></rss>'


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
        self.old=h.parse_feed(rss(),'Fed 발표',NOW-timedelta(hours=1))[0]
        self.old.update(headlineKo='이전 경제 전망',summaryKo='확인한 발표 요약',translationStatus='ready',translationMethod='reviewed-summary',importance='important',importanceReason='검토한 정책 발언')
        self.prior={'news':[self.old], 'feeds':[{'name':'Fed 발표','lastSuccessAt':self.old['lastSuccessAt']}]}

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
        self.assertEqual([f['status'] for f in feeds],['unavailable','ready','ready','ready'])
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
            if url in [f[1] for f in h.FEEDS[:2]]:return rss(url='https://www.federalreserve.gov/newsevents/speech/new.htm')
            if url in [f[1] for f in h.FEEDS]:return '<rss><channel/></rss>'
            return '<p>The economy expanded while inflation remained above target.</p>'
        items,feeds=h.collect_news({},NOW,{},fetch)
        self.assertEqual(len(items),2);self.assertTrue(all(not a['fromCache'] for a in items))
        self.assertTrue(all(f['status']=='ready' for f in feeds))


if __name__=='__main__':unittest.main()
