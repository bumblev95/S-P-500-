import unittest
from audit_stock_quarterly_experiment import facts_from,quarters_before,snapshot

def row(metric,start,end,value,filed,tag=None,accession='a'):
    return dict(metric=metric,tag=tag or metric,rank=0,start=start,end=end,value=value,filed=filed,accession=accession)

class QuarterlyTests(unittest.TestCase):
    def test_future_restatement_and_same_day_filing_do_not_change_snapshot(self):
        original=row('revenue','2020-01-01','2020-03-31',100,'2020-05-01')
        corrected=original|dict(value=180,filed='2020-08-01',accession='b')
        self.assertEqual(snapshot([original],'2020-06-01'),snapshot([original,corrected],'2020-06-01'))
        self.assertEqual(snapshot([original,corrected],'2020-08-01')['revenue'],100)
        self.assertEqual(snapshot([original,corrected],'2020-08-02')['revenue'],180)
        self.assertIsNone(snapshot([original],'2020-05-01'))

    def test_cumulative_cashflow_is_differenced_not_read_as_quarter(self):
        data=[row('cashflow','2020-01-01','2020-03-31',10,'2020-05-01'),
              row('cashflow','2020-01-01','2020-06-30',35,'2020-08-01'),
              row('revenue','2020-04-01','2020-06-30',100,'2020-08-01')]
        q=snapshot(data,'2020-08-02')
        self.assertEqual(q['cashflowMargin'],.25)
        self.assertEqual(q['derivedValues'],1)
        self.assertEqual(q['availableThrough'],'2020-08-01')

    def test_q4_annual_minus_nine_months_and_tag_identity(self):
        data=[row('revenue','2020-01-01','2020-09-30',90,'2020-11-01'),
              row('revenue','2020-01-01','2020-12-31',140,'2021-02-01')]
        q=quarters_before(data,'2021-02-02')
        self.assertEqual([(r['start'],r['value']) for r in q],[('2020-10-01',50)])
        data[0]['tag']='other'
        self.assertEqual(quarters_before(data,'2021-02-02'),[])

    def test_period_mismatch_remains_missing_and_standalone_wins(self):
        data=[row('revenue','2020-01-01','2020-03-31',80,'2020-05-01'),
              row('revenue','2020-01-01','2020-06-30',210,'2020-08-01'),
              row('revenue','2020-04-01','2020-06-30',125,'2020-08-01'),
              row('income','2020-01-01','2020-06-30',40,'2020-08-01')]
        q=snapshot(data,'2020-08-02')
        self.assertEqual(q['revenue'],125)
        self.assertIsNone(q['netMargin'])

if __name__=='__main__':unittest.main()
