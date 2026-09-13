import copy
import json
import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import build_earnings_inputs as m


def nvidia_html():
    return '''<h1>NVIDIA Announces Financial Results for Fourth Quarter and Fiscal 2025</h1>
    <div>February 26, 2025</div><p>quarter ended January 26, 2025</p>
    <table><tr><td>GAAP</td></tr><tr><td>millions</td><td>Q4 FY25</td><td>Q3 FY25</td><td>Q4 FY24</td></tr>
    <tr><td>Revenue</td><td>$400</td><td>$300</td><td>$200</td></tr>
    <tr><td>Net income</td><td>80</td><td>70</td><td>60</td></tr>
    <tr><td>Diluted earnings per share*</td><td>0.8</td><td>0.7</td><td>0.4</td></tr></table>
    <table><tr><td>Non-GAAP</td></tr><tr><td>Revenue</td><td>99999</td></tr></table>
    <p>Outlook for next quarter: Revenue is expected to be $0.5 billion, plus or minus 2%.</p>'''


class EarningsInputs(unittest.TestCase):
    def row(self):
        return m.parse_release('NVDA',2025,4,nvidia_html(),m.release_url('NVDA',2025,4))

    def test_prior_year_column_gaap_and_guidance_units(self):
        row=self.row()
        self.assertEqual(row['quarterRevenueGrowth'],1.)
        self.assertEqual(row['quarterNetMargin'],.2)
        self.assertEqual(row['quarterEpsChange'],1.)
        self.assertEqual(row['nextQuarterRevenueGrowth'],.25)
        self.assertEqual(row['periodEnd'],'2025-01-26')

    def test_microsoft_uses_quarter_not_ytd_and_loss_sign(self):
        html='''<h1>Earnings Release FY25 Q2</h1><p>REDMOND, Wash. January 30, 2025.
        quarter ended December 31, 2024</p><table><tr><td>Three Months Ended December 31</td></tr>
        <tr><td>Year</td><td>2024</td><td>2023</td><td>2024 YTD</td><td>2023 YTD</td></tr>
        <tr><td>Total revenue</td><td>100</td><td>80</td><td>190</td><td>140</td></tr>
        <tr><td>Net income</td><td>$(10)</td><td>30</td><td>15</td><td>90</td></tr>
        <tr><td>Diluted</td><td>$(0.10)</td><td>0.30</td><td>0.15</td><td>0.90</td></tr></table>'''
        row=m.parse_release('MSFT',2025,2,html,m.release_url('MSFT',2025,2))
        self.assertAlmostEqual(row['quarterRevenueGrowth'],.25)
        self.assertAlmostEqual(row['quarterNetMargin'],-.1)
        self.assertIsNone(row['nextQuarterRevenueGrowth'])

    def test_publication_same_day_future_and_stale_excluded(self):
        row=self.row()
        self.assertTrue(all(math.isnan(v) for v in m.earnings_before([row],'2025-02-26')[0]))
        values,through=m.earnings_before([row],'2025-02-27')
        self.assertEqual(through,'2025-02-26'); self.assertEqual(values[0],1.)
        future=copy.deepcopy(row);future['availableDate']='2025-03-10';future['quarterRevenueGrowth']=999
        self.assertEqual(values,m.earnings_before([future,row],'2025-02-27')[0])
        self.assertTrue(all(math.isnan(v) for v in m.earnings_before([row],'2026-01-01')[0]))

    def test_quarter_identity_and_columns_fail_closed(self):
        for html in [nvidia_html().replace('Q4 FY24','Q3 FY24'), nvidia_html().replace('Fiscal 2025','Fiscal 2024')]:
            with self.assertRaises(ValueError): m.parse_release('NVDA',2025,4,html,'https://example.invalid')

    def test_abbreviated_dates_and_split_header_digits(self):
        html=nvidia_html().replace('January 26, 2025','Jan. 26, 2025').replace('Q4 FY25','Q 4 FY2 5')
        row=m.parse_release('NVDA',2025,4,html,'https://example.invalid')
        self.assertEqual(row['periodEnd'],'2025-01-26');self.assertEqual(row['quarterRevenueGrowth'],1.)

    def test_existing_release_is_not_downloaded_or_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'research').mkdir();row=self.row()
            (root/'research/earnings.json').write_text(json.dumps({'issuers':{'NVDA':[row]}}))
            with patch.object(m,'urlopen',side_effect=AssertionError('network forbidden')):
                result=m.build(root,download=False,now=datetime(2025,3,1,tzinfo=timezone.utc))
            self.assertEqual(result['issuers']['NVDA'],[row])

    def test_provider_backoff_stops_requests_and_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);now=datetime(2026,9,13,tzinfo=timezone.utc)
            with patch.object(m,'urlopen',side_effect=HTTPError('https://example.invalid',403,'Denied',{},None)) as request:
                m.build(root,now=now)
            self.assertEqual(request.call_count,2)  # one call per independent company host
            with patch.object(m,'urlopen',side_effect=AssertionError('backoff ignored')):
                result=m.build(root,now=now)
            self.assertTrue(all(s['blockedUntil']>now.isoformat() for s in result['requestState'].values()))

    def test_yahoo_snapshot_first_observation_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'fundamentals').mkdir();(root/'research').mkdir()
            source=root/'fundamentals/latest_fundamentals.csv'
            source.write_text('symbol,updatedAt,trailingEps\nDE,2026-09-12T00:00:00Z,10\n')
            m.snapshot_observations(root)
            source.write_text('symbol,updatedAt,trailingEps\nDE,2026-09-12T00:00:00Z,999\n')
            m.snapshot_observations(root)
            rows=json.loads((root/'research/fundamental-observations.json').read_text())['observations']
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['trailingEps'],10.)


if __name__=='__main__':unittest.main()
