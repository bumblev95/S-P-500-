from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import io
import itertools
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape

import build_market_home as h
import market_news_events as events

FIXTURE = Path(__file__).parent/'fixtures/market-news-events-20261017.json'
NOW = h.stamp('2026-10-17T19:51:02.240595+00:00')


def article(title, index=0, **extra):
    return dict(title=title, sourceExcerpt='The source describes the economic policy decision.',
                url=f'https://www.cnbc.com/2026/10/17/event-{index}.html',
                publishedAt='2026-10-17T18:00:00+00:00',
                firstPublishedAt='2026-10-17T10:00:00+00:00',
                category='국제경제', translationStatus='ready', sourceStatus='ready',
                fromCache=False, importance='normal', **extra)


class ActualOctober17Events(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text())
        self.news = deepcopy(self.fixture['news'])
        self.cnbc, self.bbc = self.news[:2]
        self.quotes = {s: dict(symbol=s, name=name, status='unavailable') for s, name, _ in h.INDICES+h.SECTORS}
        self.ranks = {'buy': [{'symbol': 'ILMN', 'asOf': '2026-10-16'}],
                      'sell': [{'symbol': 'APP', 'asOf': '2026-10-16'}], 'asOf': '2026-10-16'}

    def assemble(self, items=None):
        return h.assemble(self.quotes, self.news if items is None else items, [], self.ranks, NOW)

    def feed(self, rows):
        return '<rss><channel>'+''.join('<item>'+''.join('<'+k+'>'+escape(v)+'</'+k+'>' for k,v in {
            'title': a['title'], 'link': a['url'], 'description': a.get('sourceExcerpt', ''),
            'pubDate': h.stamp(a['publishedAt']).strftime('%a, %d %b %Y %H:%M:%S GMT')}.items())+'</item>' for a in rows)+'</channel></rss>'

    def test_fixture_is_the_exact_1951_snapshot_and_retains_source_hashes(self):
        self.assertEqual(self.fixture['sourceCommit'], 'caf1745ce14a278e85ee0d714b88565f637ebd23')
        self.assertEqual(self.fixture['observedAt'], NOW.isoformat())
        self.assertEqual(self.cnbc['category'], '전쟁·국제')
        self.assertEqual(self.bbc['category'], '국제경제')
        self.assertTrue(all(a['url'] in self.fixture['originalHomeNews'] for a in [self.cnbc, self.bbc]))
        self.assertNotEqual(self.cnbc['headlineKo'], self.bbc['headlineKo'])
        for a in self.news:
            self.assertEqual(sha256((a['title']+'\n'+a['sourceExcerpt']).encode()).hexdigest(), a['sourceHash'])

    def test_actual_paraphrases_become_one_event_and_the_next_distinct_story_fills_five(self):
        before = deepcopy(self.news)
        public = self.assemble()['news']
        self.assertEqual(len(public), 5)
        policy = [a for a in public if a['url'] in {self.cnbc['url'], self.bbc['url']}]
        self.assertEqual(len(policy), 1)
        self.assertEqual(policy[0]['url'], self.bbc['url'], 'A direct policy lead outranks historical background')
        self.assertEqual(policy[0]['category'], '국제경제')
        related = policy[0]['relatedCoverage']
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]['url'], self.cnbc['url'])
        self.assertTrue(related[0]['additionalContext'])
        for key in ['title', 'headlineKo', 'summaryKo', 'sourceHash', 'sourceExcerpt', 'publishedAt', 'firstPublishedAt']:
            self.assertEqual(related[0][key], self.cnbc[key])
        for key in ['title', 'headlineKo', 'summaryKo', 'sourceHash', 'publishedAt', 'firstPublishedAt', 'importance']:
            self.assertEqual(policy[0][key], self.bbc[key])
        self.assertIn(self.news[5]['url'], [a['url'] for a in public])
        self.assertEqual(self.news, before)

    def test_headline_sanctions_override_historical_war_background_everywhere(self):
        for a in [self.cnbc, self.bbc]:
            self.assertEqual(h.category(a['title'], a['sourceExcerpt']), '국제경제')
            self.assertEqual(h.parse_feed(self.feed([a]), a['source'], NOW)[0]['category'], '국제경제')
            self.assertEqual(h.retain_news([a], a['source'], NOW)[0]['category'], '국제경제')
        self.assertEqual(h.category('Missile attacks hit oil facilities', 'New sanctions were also announced on Russia.'), '전쟁·국제')
        self.assertEqual(h.category('Stocks rise after Russia sanctions waiver', self.cnbc['sourceExcerpt']), '주식시장')

    def test_source_economics_and_completeness_choose_the_representative_not_publisher(self):
        rows = [dict(a, category='국제경제') for a in [self.cnbc, self.bbc]]
        result = events.group_coverage(rows, h.usable_translation)
        self.assertEqual(result[0]['url'], self.bbc['url'])
        for a in rows:
            a['source'] = 'CNBC 주요' if a['source'].startswith('BBC') else 'BBC 국제'
        self.assertEqual(events.group_coverage(rows, h.usable_translation)[0]['url'], self.bbc['url'])
        # With a fuller direct lead the other source can win. No fixed priority.
        rows[0]['sourceExcerpt'] = 'Trump waives Russia sanctions on banks, oil exports and trade temporarily, according to a detailed policy statement.'
        self.assertEqual(events.group_coverage(rows, lambda _: True)[0]['url'], self.cnbc['url'])

    def test_unusable_sibling_cannot_displace_valid_translation_or_leak_bad_korean(self):
        rows = [dict(a, category='국제경제') for a in [self.cnbc, self.bbc]]
        rows[1].update(translationStatus='unavailable', summaryKo='끊긴 번역', headlineKo='오류')
        result = events.group_coverage(rows, h.usable_translation)
        self.assertEqual(result[0]['url'], self.cnbc['url'])
        sibling = result[0]['relatedCoverage'][0]
        self.assertEqual(sibling['sourceExcerpt'], self.bbc['sourceExcerpt'])
        self.assertNotIn('headlineKo', sibling)
        self.assertNotIn('summaryKo', sibling)

    def test_latest_first_uses_representative_time_and_original_importance(self):
        public = self.assemble()['news']
        self.assertEqual([h.stamp(a['publishedAt']) for a in public], sorted([h.stamp(a['publishedAt']) for a in public], reverse=True))
        self.assertEqual(public[0]['publishedAt'], self.bbc['publishedAt'])
        self.assertEqual(public[0]['firstPublishedAt'], self.bbc['firstPublishedAt'])
        self.assertEqual(public[0]['importance'], self.bbc['importance'])
        self.assertFalse(h.stamp(public[0]['publishedAt']) == h.stamp(self.cnbc['publishedAt']))

    def test_feed_cache_and_translation_reuse_preserve_both_sources(self):
        def fetch(url):
            source = next(name for name, feed in h.FEEDS if feed == url)
            return self.feed([a for a in self.news if a['source'] == source])
        before = deepcopy(self.news)
        collected, _ = h.collect_news({'news': self.news}, NOW, {}, fetch)
        translator = Mock(side_effect=AssertionError('Healthy cached translations require no model'))
        h.translate_news(collected, Path('/unused'), translator)
        translator.assert_not_called()
        self.assertEqual({a['url'] for a in collected}, {a['url'] for a in self.news})
        self.assertEqual(len(self.assemble(collected)['news']), 5)
        self.assertEqual(self.news, before)

    def test_failed_feeds_and_disabled_model_still_group_and_keep_the_cache(self):
        for enabled in [False, True]:
            with self.subTest(enabled=enabled), TemporaryDirectory() as folder, patch('sys.stdout', io.StringIO()):
                root = Path(folder)
                h.atomic(root/'market/home-cache.json', {'news': self.news})
                with patch.object(h, 'prices', return_value=(self.quotes, {})), patch.object(h, 'home_rankings', return_value=self.ranks):
                    snapshot = h.build(root, NOW, Mock(side_effect=ValueError('offline')), Mock(side_effect=TimeoutError('offline')), translate_enabled=enabled)
                saved = json.loads((root/'market/home-cache.json').read_text())
                self.assertEqual(len(saved['news']), len(self.news))
                self.assertEqual(snapshot['rankings'], self.ranks)
                self.assertEqual(len(snapshot['news']), 5)
                self.assertEqual(snapshot['news'][0]['url'], self.bbc['url'])
                self.assertTrue(snapshot['news'][0]['fromCache'])
                self.assertEqual(snapshot['news'][0]['lastSuccessAt'], self.bbc['lastSuccessAt'])
                for old in self.news:
                    new = next(a for a in saved['news'] if a['url'] == old['url'])
                    for key in ['title', 'sourceExcerpt', 'sourceHash', 'headlineKo', 'summaryKo']:
                        self.assertEqual(new[key], old[key])

    def test_quotes_rankings_and_recap_are_unchanged_by_event_selection(self):
        before = deepcopy((self.quotes, self.ranks))
        with patch.object(h, 'group_coverage', side_effect=lambda rows, usable: [events.public_article(a) for a in rows if usable(a)][:5]):
            legacy = self.assemble()
        updated = self.assemble()
        for key in ['rankings', 'recap', 'brief', 'feeds', 'generatedAt']:
            self.assertEqual(updated[key], legacy[key])
        self.assertEqual((self.quotes, self.ranks), before)

    def test_input_permutations_produce_identical_cards_and_related_order(self):
        expected = self.assemble()['news']
        for first in itertools.permutations(self.news[:3]):
            self.assertEqual(self.assemble(list(first)+self.news[3:])['news'], expected)


class ConservativeEventIdentity(unittest.TestCase):
    def same(self, left, right):
        return events.same_event(article(left), article(right, 1))

    def test_explicit_subject_action_and_target_aliases(self):
        pairs = [('Trump waives broad new Russia sanctions', 'President Donald Trump waived several Russian sanctions'),
                 ('US imposes sanctions on Russia', 'United States imposed Russian sanctions'),
                 ('Fed cuts interest rates by 25 basis points', 'Federal Reserve lowers rates by 25 basis points'),
                 ('Bank of Canada raises interest rates', 'Bank of Canada hikes policy rates'),
                 ('Nvidia acquires Acme', 'Nvidia buys Acme'),
                 ('Nvidia reports Q3 earnings', 'Nvidia posts Q3 earnings')]
        for a, b in pairs:
            with self.subTest(left=a, right=b):
                self.assertTrue(self.same(a, b))

    def test_shared_actor_or_subject_without_same_decision_is_insufficient(self):
        cases = [('Trump waives Russia sanctions', 'Trump imposes Russia sanctions'),
                 ('Trump waives Russia sanctions', 'Trump lifts Russia sanctions'),
                 ('Trump waives Russia sanctions', 'Trump suspends Russia sanctions'),
                 ('Trump waives Russia sanctions', 'Trump waives Iran sanctions'),
                 ('Trump waives Russia sanctions', 'EU waives Russia sanctions'),
                 ('Trump waives Russia sanctions', 'Trump announces Russia sanctions'),
                 ('Trump waives Russia sanctions', 'Trump may waive Russia sanctions'),
                 ('Trump waives Russia sanctions', 'Trump does not waive Russia sanctions'),
                 ('Trump waives Russia sanctions', 'Trump waives all Russia sanctions'),
                 ('Trump waives Russia bank sanctions', 'Trump waives Russia oil sanctions'),
                 ('Trump waives Russia sanctions for 30 days', 'Trump waives Russia sanctions for 60 days'),
                 ('Trump waives Russia sanctions on October 16', 'Trump waives Russia sanctions on October 17'),
                 ('US raises China tariffs to 25%', 'US raises China tariffs to 50%'),
                 ('US raises tariffs on Chinese steel', 'US raises tariffs on Chinese cars'),
                 ('Fed cuts rates by 25 basis points', 'Fed cuts rates by 50 basis points'),
                 ('Fed cuts rates', 'ECB cuts rates'),
                 ('Nvidia posts Q3 earnings', 'Nvidia reports Q2 earnings'),
                 ('Nvidia buys Acme', 'Nvidia buys OtherCo'),
                 ('Trump waives Russia sanctions', 'Trump waives Russia sanctions as oil prices plunge'),
                 ('Trump waives Russia sanctions', 'Trump waives Russia sanctions but Congress imposes new tariffs')]
        for a, b in cases:
            with self.subTest(left=a, right=b):
                self.assertFalse(self.same(a, b))

    def test_unknown_headlines_and_identical_korean_wording_do_not_create_events(self):
        rows = [article('Investors see opportunities in AI stocks'), article('Investors find bargains in AI shares', 1)]
        for a in rows:
            a['headlineKo'] = '인공지능 주식 투자 기회'
        self.assertFalse(events.same_event(*rows))
        self.assertEqual(len(events.group_coverage(rows, lambda _: True)), 2)
        self.assertFalse(self.same('Trump waives sanctions', 'Trump waives several sanctions'))

    def test_exact_syndication_requires_identical_substantive_original_excerpt(self):
        a = article('Officials publish detailed annual economic outlook and investment report')
        b = {**a, 'url': article('', 1)['url']}
        a['sourceExcerpt'] = b['sourceExcerpt'] = 'The annual economic outlook sets out specific investment estimates for next year.'
        self.assertTrue(events.same_event(a, b))
        b['sourceExcerpt'] = 'A different report looks at regional investment conditions.'
        self.assertFalse(events.same_event(a, b))

    def test_conflicting_source_amounts_or_durations_remain_separate(self):
        a, b = article('Trump waives Russia sanctions'), article('Trump waives Russia sanctions', 1)
        a['sourceExcerpt'] = 'Trump waives sanctions on Russia for 30 days.'
        b['sourceExcerpt'] = 'Trump waives sanctions on Russia for 60 days.'
        self.assertFalse(events.same_event(a, b))
        b['sourceExcerpt'] = 'Trump waives sanctions on Russia temporarily.'
        self.assertTrue(events.same_event(a, b), 'An omitted detail stays available as related context')

    def test_first_publication_and_update_windows_are_both_required(self):
        a, b = article('Trump waives Russia sanctions'), article('Trump waives Russia sanctions', 1)
        b['firstPublishedAt'] = (h.stamp(a['firstPublishedAt'])-timedelta(hours=18)).isoformat()
        self.assertTrue(events.same_event(a, b))
        b['firstPublishedAt'] = (h.stamp(b['firstPublishedAt'])-timedelta(seconds=1)).isoformat()
        self.assertFalse(events.same_event(a, b))
        b = {**a, 'publishedAt': (h.stamp(a['publishedAt'])+timedelta(hours=24)).isoformat()}
        self.assertTrue(events.same_event(a, b))
        b['publishedAt'] = (h.stamp(b['publishedAt'])+timedelta(seconds=1)).isoformat()
        self.assertFalse(events.same_event(a, b))

    def test_source_rate_amount_units_are_compared_without_rounding_or_percent_loss(self):
        a, b = article('Fed cuts rates'), article('Fed lowers rates', 1)
        a['sourceExcerpt'] = 'The Fed cuts interest rates by 25 basis points.'
        b['sourceExcerpt'] = 'The Fed cuts interest rates by 0.50 percentage points.'
        self.assertFalse(events.same_event(a, b))
        b['sourceExcerpt'] = 'The Fed cuts interest rates by 0.25 percentage points.'
        self.assertTrue(events.same_event(a, b))
        a['sourceExcerpt'] = 'The Fed holds interest rates at 5%.'
        b['sourceExcerpt'] = 'The Fed holds interest rates at 6%.'
        self.assertFalse(events.same_event(a, b))

    def test_bad_missing_or_reversed_dates_fail_closed(self):
        a = article('Trump waives Russia sanctions')
        for changes in [dict(publishedAt=None), dict(publishedAt='invalid'),
                        dict(firstPublishedAt='invalid'), dict(firstPublishedAt='2026-10-18T18:00:00Z')]:
            self.assertFalse(events.same_event(a, {**a, **changes}))
        # Different timezone representations of the same instant are equivalent.
        b = {**a, 'publishedAt': '2026-10-17T12:00:00-06:00'}
        self.assertTrue(events.same_event(a, b))

    def test_trailing_clauses_cannot_hide_conflicting_dates_or_deal_values(self):
        for left, right in [
            ('Trump waives Russia sanctions, effective October 18', 'Trump waives Russia sanctions, effective October 19'),
            ('Trump waives Russia sanctions, effective Monday', 'Trump waives Russia sanctions, effective Tuesday'),
            ('Nvidia acquires Acme as part of a $5 billion deal', 'Nvidia acquires Acme as part of a $50 billion deal'),
            ('Nvidia acquires Acme as part of a $5 deal', 'Nvidia acquires Acme as part of a $6 deal'),
            ('Nvidia acquires Acme as part of a $5 billion deal', 'Nvidia acquires Acme as part of a €5 billion deal'),
            ('Trump waives Russia sanctions, lasting 30 days', 'Trump waives Russia sanctions, lasting 3 months'),
            ('Fed holds rates at -1%', 'Fed holds rates at 1%'),
        ]:
            with self.subTest(left=left, right=right):
                self.assertFalse(self.same(left, right))

    def test_complete_link_matching_prevents_transitive_multi_day_collapse(self):
        rows = []
        for index, hour in enumerate([0, 12, 24]):
            when = (h.stamp('2026-10-16T10:00:00Z')+timedelta(hours=hour)).isoformat()
            rows.append({**article('Trump waives Russia sanctions', index), 'publishedAt': when, 'firstPublishedAt': when})
        cards = events.group_coverage(rows, lambda _: True)
        self.assertEqual(len(cards), 2)
        self.assertEqual(sum(1+len(a.get('relatedCoverage', [])) for a in cards), 3)

    def test_eligibility_topic_and_valid_translation_are_required(self):
        a = article('Trump waives Russia sanctions')
        self.assertFalse(events.same_event(a, {**a, 'category': '주식시장'}))
        self.assertFalse(events.same_event({**a,'category':None}, {**a,'category':None}))
        b = {**a, 'url': article('', 1)['url']}
        self.assertEqual(events.group_coverage([a, b], lambda _: False), [])


if __name__ == '__main__':
    unittest.main()
