from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
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
        self.assertEqual([f['status'] for f in failed['feeds']],['unavailable','ready','ready','ready'])
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
            ('recap','weekComplete',False),('newsPolicy','breakingMaxAgeHours',1),
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
