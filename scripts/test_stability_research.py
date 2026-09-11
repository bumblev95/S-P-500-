import unittest
import numpy as np
import pandas as pd
from build_stability_research import compare,stats,fit_relative,FEATURES

class StabilityTests(unittest.TestCase):
    def rows(self):
        return [dict(symbol='TEST',origin=f'{2010+i}-01-01',targetDate=f'{2010+i}-06-01',actual=1.2,
                     noChange=1.,trend=1.05,original=1.1,relativeMAE=1.2,halfBlend=1.1) for i in range(8)]
    def test_relative_price_metric(self):
        rows=self.rows();rows[0].update(actual=1.5,relativeMAE=1.25)
        self.assertAlmostEqual(stats(rows[:1],'relativeMAE')['mape'],1/6)
    def test_later_outcomes_cannot_select_model(self):
        rows=self.rows();first=compare(rows)
        self.assertEqual(first['chosen'],'relativeMAE')
        for r in rows[4:]:r.update(actual=.5,relativeMAE=3)
        second=compare(rows)
        self.assertEqual(first['chosen'],second['chosen'])
        self.assertFalse(second['passed'])
        self.assertFalse(second['liveForecastChanged'])
        self.assertLess(second['selectionTargetThrough'],second['evaluationStart'])
    def test_unmatured_selection_outcome_is_excluded(self):
        rows=self.rows();rows[3]['targetDate']='2015-01-01'
        result=compare(rows)
        self.assertNotIn('2013-01-01',result['selectionDates'])
    def test_weighted_model_accepts_actual_features(self):
        f=pd.DataFrame({k:np.linspace(.1,.2,200) for k in FEATURES})
        f['y']=np.log(np.linspace(.8,1.2,200))
        prediction=fit_relative(f).predict(f[FEATURES])
        self.assertTrue((prediction>0).all())

if __name__=='__main__':unittest.main()
