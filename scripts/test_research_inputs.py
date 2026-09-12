import unittest
from datetime import datetime, timezone
import math
import build_research_inputs as m

class PublicationDates(unittest.TestCase):
    def payload(self):
        def row(start,end,filed,val):
            return dict(start=start,end=end,filed=filed,val=val,form='10-K',accn=filed)
        return {'facts':{'us-gaap':{'Revenues':{'units':{'USD':[
            row('2021-01-01','2021-12-31','2022-02-01',100),
            row('2022-01-01','2022-12-31','2023-02-01',120),
            row('2022-01-01','2022-12-31','2024-02-01',900),
            row('2023-01-01','2023-03-31','2023-05-01',5000)]}}}}}
    def test_restated_and_quarterly_values_cannot_leak(self):
        history=m.financial_history(self.payload())
        x,day=m.stock_before(history,'2023-02-02')
        self.assertAlmostEqual(x[0],.2);self.assertEqual(day,'2023-02-01')
        self.assertTrue(math.isnan(m.stock_before(history,'2023-02-01')[0][0]))
        self.assertTrue(math.isnan(m.stock_before(history,'2026-01-01')[0][0]))
        self.assertEqual(history[1]['evidence'][-1]['filed'],'2022-02-01')
    def test_future_filing_does_not_change_old_features(self):
        payload=self.payload();before=m.financial_history(payload)
        payload['facts']['us-gaap']['Revenues']['units']['USD'][2]['val']=1e12
        self.assertEqual(m.stock_before(before,'2023-02-02')[0][0],m.stock_before(m.financial_history(payload),'2023-02-02')[0][0])
    def test_missing_funding_hours_are_not_zero(self):
        stamp=int(datetime(2024,1,1,tzinfo=timezone.utc).timestamp()*1000)
        rows=[dict(time=stamp+3600000*i,fundingRate='0.001') for i in range(24)]
        self.assertEqual(m.daily_funding(rows[:-1]),[])
        self.assertAlmostEqual(m.daily_funding(rows+rows)[0]['rate'],.024)
    def test_snapshots_cannot_be_backfilled(self):
        funding=[dict(date=f'2024-01-{i:02}',rate=.001) for i in range(1,8)]
        snapshots=[dict(date='2024-01-01',openInterest=100,circulating=10),dict(date='2024-01-08',openInterest=200,circulating=20)]
        x,through=m.crypto_before(funding,snapshots,'2024-01-08')
        self.assertAlmostEqual(x[0],.007);self.assertTrue(math.isnan(x[1]));self.assertTrue(math.isnan(x[2]))
        self.assertLess(through,'2024-01-08')
        self.assertAlmostEqual(m.crypto_before(funding,snapshots,'2024-01-09')[0][2],1.)

if __name__=='__main__':unittest.main()
