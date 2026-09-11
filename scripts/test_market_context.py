import unittest
from datetime import date, datetime, timezone
from build_market_context import parse_csv, summarize, funding, credit_state, parse_news

class Tests(unittest.TestCase):
    def test_bad_rows(self):
        self.assertEqual(parse_csv('DATE,NFCI\n2026-09-01,.\n2026-09-02,nan\n2026-09-03,0.4\n2027-01-01,2','NFCI',date(2026,9,11)), [('2026-09-03',0.4)])
    def test_stale(self):
        self.assertEqual(summarize('NFCI',[('2026-01-01',-1)],date(2026,9,11))['status'],'stale')
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

if __name__=='__main__':unittest.main()
