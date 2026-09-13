import unittest
import numpy as np
from run_stock_quarterly_experiment import timeline_value,source_eligibility
from audit_stock_quarterly_experiment import FIELDS

class IncrementTests(unittest.TestCase):
    def test_only_available_and_fresh_quarters_enter_features(self):
        r=dict(periodEnd='2020-03-31',availableThrough='2020-05-01',**{k:1. for k in FIELDS})
        series=(['2020-05-02'],[r])
        self.assertTrue(np.isnan(timeline_value(series,'2020-05-01')).all())
        self.assertEqual(timeline_value(series,'2020-05-02'),[1.]*6)
        self.assertTrue(np.isnan(timeline_value(series,'2021-01-01')).all())

    def test_failed_or_missing_source_controls_block_fit(self):
        data=dict(e1SelectionEligible=True,errors=[],releaseControls=[dict(symbol=s,status='matched') for s in ('NVDA','MSFT') for _ in range(20)])
        self.assertTrue(all(source_eligibility(data).values()))
        data['releaseControls'].append(dict(symbol='NVDA',status='mismatch'))
        self.assertFalse(all(source_eligibility(data).values()))
        data['releaseControls']=[]
        self.assertFalse(all(source_eligibility(data).values()))

if __name__=='__main__':unittest.main()
