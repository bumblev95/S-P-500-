import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import build_company_news as m

NOW = datetime(2026, 10, 3, 3, tzinfo=timezone.utc)
OBSERVED = NOW.isoformat()


def rss(title='Nvidia raises revenue outlook', description='Company update', link='https://finance.yahoo.com/news/nvidia-update.html', date='Fri, 02 Oct 2026 20:00:00 GMT'):
    from xml.sax.saxutils import escape
    return '<rss><channel><item>'+''.join('<'+k+'>'+escape(v)+'</'+k+'>' for k, v in {
        'title': title, 'description': description, 'link': link, 'pubDate': date}.items())+'</item></channel></rss>'


class NewsTests(unittest.TestCase):
    def label(self, title, ticker='NVDA', name='Nvidia'):
        return m.classify(title, [ticker], m.aliases([ticker], name))['status']

    def test_concrete_positive_negative_mixed_and_neutral(self):
        examples = {'Nvidia raises revenue outlook': 'positive',
                    'Nvidia beats estimates but cuts guidance': 'mixed',
                    'Nvidia misses earnings estimates': 'negative',
                    'Nvidia cuts dividend': 'negative',
                    'Nvidia faces antitrust investigation': 'negative',
                    'Nvidia announces date for earnings call': 'neutral',
                    'Nvidia declares quarterly dividend': 'neutral',
                    'Nvidia announces a $150 billion share repurchase': 'positive',
                    'Nvidia wins new supply contract': 'positive',
                    'Nvidia: Wells Fargo downgrades the stock': 'negative',
                    'Nvidia revenue is 41% higher': 'positive',
                    'Nvidia launches a new chip platform': 'positive',
                    'Nvidia stock is back at its May record. Revenue is 41% higher.': 'positive',
                    'Nvidia’s revenue rises 41%': 'positive',
                    'Nvidia raises outlook, cuts dividend': 'mixed'}
        for title, expected in examples.items():
            with self.subTest(title=title): self.assertEqual(self.label(title), expected)

    def test_uncertainty_negation_price_move_and_competitor_are_deferred(self):
        for title in ['Nvidia could raise guidance', 'Nvidia may raise guidance', 'Nvidia denies data breach',
                      'Nvidia does not cut dividend', 'Will Nvidia beat earnings estimates?',
                      'Nvidia lawsuit dismissed', 'Nvidia wins a lawsuit',
                      'Nvidia hits record high', 'Nvidia vs Microsoft: earnings beat estimates',
                      'Microsoft cuts outlook as Nvidia expands']:
            with self.subTest(title=title): self.assertEqual(self.label(title), 'unclear')
        self.assertEqual(self.label('Apple sued while Nvidia unveils a product'), 'positive')

    def test_short_ticker_does_not_match_articles(self):
        self.assertFalse(m.mentions('A new thing is ON the way', ['A', 'ON'], ['agilent']))
        self.assertTrue(m.mentions('Agilent (NYSE: A) reports results', ['A'], ['agilent']))
        self.assertTrue(m.mentions('AT&T reports results', ['T'], m.aliases(['T'], 'AT&T')))

    def test_brand_names_technical_upgrade_and_buyer_or_plaintiff_roles(self):
        self.assertEqual(self.label('Agilent introduces a new sample preparation system', 'A', 'Agilent Technologies'), 'positive')
        label=m.classify('NetApp unveils Novus, AI data engine upgrades to power AI', ['NTAP'], ['netapp'])
        self.assertNotIn('분석가 상향', label['topics'])
        self.assertEqual(self.label('Harbinger lands $300M FedEx order', 'FDX', 'FedEx'), 'unclear')
        self.assertEqual(self.label('Exxon Mobil downgraded, BP upgraded: analyst calls', 'XOM', 'Exxon Mobil'), 'negative')
        self.assertEqual(self.label('First Solar files patent infringement lawsuit against JA Solar', 'FSLR', 'First Solar'), 'unclear')
        self.assertEqual(self.label('Moody’s cuts Dave & Buster’s outlook to negative', 'MCO', "Moody's"), 'unclear')
        self.assertEqual(self.label('Moody’s cuts its 2026 revenue outlook', 'MCO', "Moody's"), 'negative')

    def test_actual_headline_role_and_event_counterexamples(self):
        examples = [
            ('SKIP AND DOMINO\'S TEAM UP TO GIVE PIZZA NIGHT AN UPGRADE', 'DPZ', "Domino's", 'unclear'),
            ('Cushman & Wakefield Earns Upgrade to Ba3 Rating from Moody’s Ratings', 'MCO', "Moody's", 'unclear'),
            ('Harmonic Launches Recon Product Family Developed in Partnership with Comcast', 'CMCSA', 'Comcast', 'unclear'),
            ('Texas Instruments Upgrades to Platinum Membership', 'TXN', 'Texas Instruments', 'unclear'),
            ('Why Coca-Cola (KO) is Poised to Beat Earnings Estimates Again', 'KO', 'Coca-Cola', 'unclear'),
            ('AutoZone shares safety warning for drivers', 'AZO', 'AutoZone', 'unclear'),
            ('ADP September 2026 private payrolls beat expectations', 'ADP', 'Automatic Data Processing', 'neutral'),
            ('Eaton Analyst Sees Strong Orders, Raises 2027 EPS Forecast', 'ETN', 'Eaton', 'unclear'),
            ('Dominion Energy Halted Dividend Growth', 'D', 'Dominion Energy', 'unclear'),
            ('Paychex Beats EPS Estimates, But Slow Growth Weighs on Shares', 'PAYX', 'Paychex', 'mixed'),
            ('General Mills Beats Estimates, But Its Growth Problem Remains', 'GIS', 'General Mills', 'mixed'),
            ('Tesla Rises on Q3 Delivery Beat', 'TSLA', 'Tesla', 'positive'),
            ('Tesla Deliveries Fell 10%', 'TSLA', 'Tesla', 'negative'),
        ]
        for title, ticker, name, expected in examples:
            with self.subTest(title=title): self.assertEqual(self.label(title, ticker, name), expected)

    def test_html_excerpt_dedup_and_bounded_summary(self):
        raw = rss(description='<p>Nvidia update</p><script>alert(1)</script>'+'x'*800)
        rows, rejected = m.parse_feed(raw, ['NVDA'], 'Nvidia', OBSERVED, NOW)
        self.assertEqual(rejected, 0)
        self.assertLessEqual(len(rows[0]['summary']), 300)
        self.assertNotIn('alert', rows[0]['summary'])
        double = raw.replace('</channel>', raw[raw.index('<item>'):raw.index('</item>')+7]+'</channel>')
        self.assertEqual(len(m.parse_feed(double, ['NVDA'], 'Nvidia', OBSERVED, NOW)[0]), 1)

    def test_excerpt_recovers_events_without_borrowing_rivals_or_speculation(self):
        examples = [
            ('Why Tesla Stock Is Up Today', 'Tesla reported vehicle deliveries above analyst estimates.', 'TSLA', 'Tesla', 'positive'),
            ('Can General Dynamics Keep Growing?', 'General Dynamics received a new Army contract extending through 2028.', 'GD', 'General Dynamics', 'positive'),
            ('Nvidia stock rises', 'Microsoft raises revenue outlook.', 'NVDA', 'Nvidia', 'unclear'),
            ('Nvidia stock rises', 'Nvidia could raise revenue outlook.', 'NVDA', 'Nvidia', 'unclear'),
            ('Nvidia stock rises', 'Nvidia raises revenue outlook but', 'NVDA', 'Nvidia', 'unclear'),
            ('What Does Valero Face?', 'Valero Energy is under pressure as officials discuss a possible diesel export ban.', 'VLO', 'Valero Energy', 'unclear'),
            ('Ahead of EQT Earnings', 'EQT heads into its upcoming report with analysts expecting a profit decline.', 'EQT', 'EQT', 'unclear'),
            ('Moody’s cuts Botswana credit rating', 'Investing.com -- Moody’s Ratings has downgraded Botswana’s rating.', 'MCO', "Moody's", 'unclear'),
            ('Wells Fargo downgrades tech', 'Investing.com -- Wells Fargo downgraded its guidance on the technology sector.', 'WFC', 'Wells Fargo', 'unclear'),
            ('Apple Says Some AT&T iPhone Users Must Replace Phones After Service-Loss Bug', '', 'AAPL', 'Apple', 'negative'),
            ('Tesla Deliveries Clear The Street, Rivian Holds Forecast, Ford And GM EV Sales Fall Hard', '', 'TSLA', 'Tesla', 'positive'),
            ('Tesla, Rivian Deliveries Beat Estimates', '', 'TSLA', 'Tesla', 'positive'),
            ('Microsoft Entered the Smart Home Through Your Washing Machine, Not Your Phone', '', 'MSFT', 'Microsoft', 'positive'),
        ]
        for title, summary, ticker, name, expected in examples:
            with self.subTest(title=title, ticker=ticker):
                self.assertEqual(m.classify(title, [ticker], m.aliases([ticker], name), summary=summary)['status'], expected)
        self.assertFalse(m.mentions('Super Group Ltd (JSE:SPG) Earnings Growth', ['SPG'], m.aliases(['SPG'], 'Simon Property Group')))
        self.assertFalse(m.mentions('ARES CAPITAL CORPORATION SCHEDULES EARNINGS', ['ARES'], m.aliases(['ARES'], 'Ares Management')))

    def test_future_stale_invalid_urls_and_unrelated_articles_are_rejected(self):
        bad = [rss(date='Sun, 04 Oct 2026 00:00:00 GMT'), rss(date='Mon, 01 Jun 2026 00:00:00 GMT'),
               rss(link='javascript:alert(1)'), rss(link='https://user@finance.yahoo.com/news/a'),
               rss(link='https://127.0.0.1/private'), rss(title='Apple cuts guidance', description='Apple update'),
               rss(title='Give Nvidia stock to your dying father to inherit it back')]
        for raw in bad:
            self.assertEqual(m.parse_feed(raw, ['NVDA'], 'Nvidia', OBSERVED, NOW)[0], [])
        for raw in ['<rss/>', '<!DOCTYPE rss [<!ENTITY a "b">]><rss/>']:
            with self.assertRaises(ValueError): m.parse_feed(raw, ['NVDA'], 'Nvidia', OBSERVED, NOW)

    def test_summary_only_company_mention_does_not_occupy_the_feed(self):
        rows, _ = m.parse_feed(rss(title='Apple raises guidance', description='Nvidia competes with Apple'), ['NVDA'], 'Nvidia', OBSERVED, NOW)
        self.assertEqual(rows, [])

    def prepare(self, root, second=False):
        members = {'NVDA': {'cik': 1045810, 'name': 'Nvidia'}, 'NVDA.B': {'cik': 1045810, 'name': 'Nvidia'}}
        if second: members['MSFT'] = {'cik': 789019, 'name': 'Microsoft'}
        (root/'research').mkdir()
        (root/'research/universe.json').write_text(json.dumps({'members': members}))
        (root/'research/inputs.json').write_text('{"unchanged":true}')

    def test_share_classes_collect_once_and_other_data_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.prepare(root)
            with patch.object(m, 'fetch', return_value=rss()) as fetcher:
                result = m.build(root, now=NOW, fetcher=fetcher, interval=0)
            self.assertEqual(fetcher.call_count, 1)
            self.assertEqual(result['symbols']['NVDA'], result['symbols']['NVDA-B'])
            self.assertEqual((root/'research/inputs.json').read_text(), '{"unchanged":true}')
            self.assertEqual(result['collection']['freshIssuers'], 1)

    def test_failure_preserves_source_clock_and_stops_on_access_denial(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.prepare(root, second=True)
            first = m.build(root, now=NOW, fetcher=lambda _: rss(), interval=0)
            failed = patch.object(m, 'fetch', side_effect=HTTPError('feed', 429, 'rate limit', {}, None))
            with failed as fetcher:
                later = m.build(root, now=NOW+timedelta(hours=1), fetcher=fetcher, interval=0)
            self.assertEqual(fetcher.call_count, 1)
            for cik in first['issuers']:
                self.assertEqual(later['issuers'][cik]['feed']['lastSuccessAt'], OBSERVED)
                self.assertEqual(later['issuers'][cik]['articles'], first['issuers'][cik]['articles'])
            with patch.object(m, 'fetch') as fetcher:
                again = m.build(root, now=NOW+timedelta(hours=2), fetcher=fetcher, interval=0)
            self.assertEqual(fetcher.call_count, 0)
            self.assertEqual(again['collection']['freshIssuers'], 0)

    def test_offline_replay_and_invalid_refresh_keep_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.prepare(root)
            first = m.build(root, now=NOW, fetcher=lambda _: rss(), interval=0)
            again = m.build(root, download=False, now=NOW+timedelta(hours=1))
            self.assertEqual(again['issuers']['1045810']['articles'][0]['observedAt'], OBSERVED)
            self.assertEqual(again['collection']['freshIssuers'], 0)
            bad = m.build(root, now=NOW+timedelta(hours=2), fetcher=lambda _: '<rss/>', interval=0)
            self.assertEqual(bad['issuers']['1045810']['articles'], first['issuers']['1045810']['articles'])
            self.assertEqual(bad['issuers']['1045810']['feed']['status'], 'invalid_response')

    def test_successful_empty_feed_is_distinct_from_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); self.prepare(root)
            result = m.build(root, now=NOW, fetcher=lambda _: '<rss><channel/></rss>', interval=0)
            self.assertEqual(result['issuers']['1045810']['articles'], [])
            self.assertEqual(result['issuers']['1045810']['feed']['status'], 'ready')


if __name__ == '__main__': unittest.main()
